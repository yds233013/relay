"""Pure governance logic: approval policy, mapping suggestions and previews, account signals."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from relay.canonical.enums import AccountSubtype
from relay.changes.domain import record_override_approvals, required_approvals
from relay.changes.kinds import parse_payload
from relay.changes.models import ChangeRequestKind
from relay.core.errors import InvalidInputError
from relay.mapping import registry
from relay.mapping.transforms import MappingConfigError
from relay.mapping_sets.accounts import ChartAccount, _score, _similarity, signals
from relay.mapping_sets.suggest import normalize_header, preview, suggest
from relay.profiling.domain import profile_rows


def _roles(requirements: list[dict[str, str]]) -> list[str]:
    return [r["role"] for r in requirements]


# ----------------------------------------------------------------------------- approval policy
def test_record_override_needs_the_controller_for_accounting_fields_and_large_amounts() -> None:
    lead_only = record_override_approvals(
        field="memo", restores_row=False, impact=Decimal("9999.99")
    )
    assert _roles(lead_only) == ["implementation_lead"]
    for field, impact in (
        ("entry_date", Decimal("1.00")),
        ("posting_period", None),
        ("memo", Decimal("10000.00")),
        ("memo", Decimal("-10000.00")),
    ):
        both = record_override_approvals(field=field, restores_row=False, impact=impact)
        assert _roles(both) == ["implementation_lead", "customer_controller"], (field, impact)
    repair = record_override_approvals(field=None, restores_row=True, impact=Decimal("450.00"))
    assert _roles(repair) == ["implementation_lead", "customer_controller"]


def test_payload_dependent_kinds_have_no_fixed_policy() -> None:
    for kind in (ChangeRequestKind.RECORD_OVERRIDE, ChangeRequestKind.REVERT):
        with pytest.raises(NotImplementedError):
            required_approvals(kind)
    assert _roles(required_approvals(ChangeRequestKind.POLICY_CHANGE)) == [
        "implementation_lead",
        "customer_controller",
    ]


def test_payloads_are_validated_strictly() -> None:
    with pytest.raises(InvalidInputError):
        parse_payload(ChangeRequestKind.ACCOUNT_MAPPING_SET, {"mapping_set_id": "nope"})
    with pytest.raises(InvalidInputError):
        parse_payload(
            ChangeRequestKind.REVERT, {"record_override_id": str(uuid.uuid4()), "extra": 1}
        )
    with pytest.raises(InvalidInputError):
        parse_payload(ChangeRequestKind.POLICY_CHANGE, {"changes": {}})
    with pytest.raises(InvalidInputError):
        # A client cannot smuggle a hand-written expected value past the discriminated union.
        parse_payload(
            ChangeRequestKind.RECORD_OVERRIDE, {"override": {"expected_current": "2026-01-01"}}
        )
    with pytest.raises(InvalidInputError):
        parse_payload(ChangeRequestKind.ENTITY_DECISION, {})


# --------------------------------------------------------------------------- column suggestions
HEADER = [
    "Transaction Date", "GL Account", "Fiscal Period", "Journal Number", "Line", "Debit",
    "Credit", "Currency Code", "Memo", "Source", "Unused Column",
]  # fmt: skip
ROWS = [
    {"Transaction Date": "2025-01-31", "GL Account": "4000", "Fiscal Period": "2025-01",
     "Journal Number": "J1", "Line": "1", "Debit": "", "Credit": "1,250.00",
     "Currency Code": "EUR", "Memo": "Sale", "Source": "AR", "Unused Column": "x"},
    {"Transaction Date": "2025-01-31", "GL Account": "1100", "Fiscal Period": "2025-01",
     "Journal Number": "J1", "Line": "2", "Debit": "1,250.00", "Credit": "",
     "Currency Code": "EUR", "Memo": "Sale", "Source": "AR", "Unused Column": "y"},
]  # fmt: skip


def test_suggestions_for_an_unfamiliar_export() -> None:
    proposal = suggest("gl_detail", HEADER, profile_rows(HEADER, ROWS, 0))
    by_field = {f.field: f for f in proposal.fields}
    assert by_field["account_code"].specification == {
        "source": "GL Account", "steps": [{"step": "trim"}]
    }  # fmt: skip
    assert by_field["account_code"].basis == "synonym"
    assert by_field["entry_date"].specification == {
        "source": "Transaction Date",
        "steps": [{"step": "trim"}, {"step": "parse_date", "format": "YYYY-MM-DD"}],
    }
    assert by_field["functional_amount"].specification == {
        "debit_credit": {"debit": "Debit", "credit": "Credit", "thousands_separator": ","}
    }
    # The period is YYYY-MM, which has no profile pattern: the operator must choose.
    assert by_field["posting_period"].notes == ("choose the period format",)
    assert by_field["source_module"].notes[0].startswith("map the column's values to:")
    assert by_field["line_number"].specification is not None
    assert "Unused Column" in proposal.unmatched_columns
    assert set(proposal.config()["fields"]) <= {f.name for f in registry.fields_for("gl_detail")}


def test_one_column_is_never_suggested_for_two_fields() -> None:
    proposal = suggest("customers", ["Code", "Name"], None)
    sources = [f.specification["source"] for f in proposal.fields if f.specification]
    assert len(sources) == len(set(sources))
    assert normalize_header("  Open Balance (USD) ") == "open balance usd"


def test_preview_reports_field_errors_without_failing() -> None:
    config = {
        "fields": {
            "entry_date": {
                "source": "Transaction Date",
                "steps": [{"step": "parse_date", "format": "MM/DD/YYYY"}],
            },
            "account_code": {"source": "GL Account", "steps": [{"step": "trim"}]},
            "memo": {"source": "Memo", "required": False},
        }
    }
    rows = preview("gl_detail", config, HEADER, list(enumerate(ROWS, start=1)))
    assert [r.row_number for r in rows] == [1, 2]
    assert "entry_date" in rows[0].errors
    assert rows[0].values["account_code"] == "4000"
    with pytest.raises(MappingConfigError):
        preview("gl_detail", {"fields": {"memo": {"source": "Missing"}}}, HEADER, [])


def test_registry_requirements() -> None:
    assert registry.missing_required("account_mapping", {"legacy_account_code"}) == [
        "target_account_code"
    ]
    assert registry.unknown_fields("account_mapping", {"legacy_account_code", "bogus"}) == ["bogus"]


# ----------------------------------------------------------------------------- account signals
def test_signals_and_scores() -> None:
    allowance = ChartAccount(
        "1250", "Allowance for doubtful receivables", AccountSubtype.CONTRA_ASSET
    )
    receivable = ChartAccount("1100", "Trade receivables", AccountSubtype.ACCOUNTS_RECEIVABLE)
    reserve = ChartAccount(
        "1190", "Allowance for expected credit losses", AccountSubtype.CONTRA_ASSET
    )
    revenue = ChartAccount("4000", "Allowance revenue", AccountSubtype.OPERATING_REVENUE)
    assert signals(allowance, receivable) == {
        "target_exists": True, "type_compatible": True, "subtype_compatible": False
    }  # fmt: skip
    assert signals(allowance, None) == {
        "target_exists": False, "type_compatible": None, "subtype_compatible": None
    }  # fmt: skip
    assert _score(allowance, receivable) == Decimal(0)
    assert _score(allowance, revenue) == Decimal(0)
    assert _score(allowance, reserve) > Decimal("0.50")
    assert _similarity("", "Cash") == Decimal(0)
