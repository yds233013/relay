"""The documented correct resolution of every Brightwater defect (docs/demo-scenario.md §4).

EVALUATION ONLY: this encodes the answers. It builds the overlays a well-run implementation team
would approve and the re-exported source files, so tests can check that the engine reaches the
documented final state. Overlays that need engine-assigned identifiers (quarantine keys, finding
fingerprints) take them from a prior engine result, exactly as a person would from the UI.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from relay.canonical.enums import PartyType
from relay.engine.inputs import MigrationInputs, build_inputs
from relay.engine.overlays import (
    AccountMappingChange,
    Disposition,
    EntityDecision,
    Overlays,
    QuarantineRepair,
    RecordOverride,
)
from relay.engine.pipeline import EngineResult
from relay_evaluation.paths import FIXTURES_DIR
from relay_scenarios.brightwater.exports import ExportFilters, export_all
from relay_scenarios.brightwater.scenario import Scenario

MAPPING_SET = FIXTURES_DIR / "demo" / "brightwater_config" / "column_mapping_set_v1.json"
REQUIRED_DATASETS = frozenset(
    {
        "legacy_coa", "target_coa", "account_mapping", "trial_balance", "gl_detail", "customers",
        "vendors", "invoices", "bills", "payments", "ar_aging", "ap_aging", "bank_transactions",
    }
)  # fmt: skip
REEXPORT_FILTERS = ExportFilters(
    include_inactive_accounts=True,  # DS-12
    include_inactive_customers=True,  # DS-09
    include_unprinted_invoices=True,  # DS-04
)

DS01_MERGE = EntityDecision(
    "ED-DS01", PartyType.VENDOR, "same_entity", ("V-1042", "V-1187"), "V-1042",
    "Same legal entity: identical tax id, address and vendor invoice reference",
)  # fmt: skip
_STORE = "Separate store location with its own billing"
DS06_DECISIONS = (
    EntityDecision(
        "ED-DS06-MERGE", PartyType.CUSTOMER, "same_entity", ("C-0107", "C-0154"), "C-0107",
        "Same billing entity and AP contact",
    ),
    EntityDecision("ED-DS06-A", PartyType.CUSTOMER, "distinct", ("C-0107", "C-0198"), None, _STORE),
    EntityDecision("ED-DS06-B", PartyType.CUSTOMER, "distinct", ("C-0154", "C-0198"), None, _STORE),
)  # fmt: skip


def mapping_set() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(Path(MAPPING_SET).read_text(encoding="utf-8"))
    return loaded


def inputs_for(files: dict[str, bytes]) -> MigrationInputs:
    return build_inputs(json.loads(files["migration.json"]), files, mapping_set())


def reexported_files(scenario: Scenario) -> dict[str, bytes]:
    """Import #2: the same legacy books exported with the corrected LedgerPro filters."""
    return export_all(scenario.universe, REEXPORT_FILTERS)


def quarantine_repair(result: EngineResult) -> QuarantineRepair:
    """DS-05: quote the memo that contained an unquoted line break, as an operator would."""
    finding = next(e for e in result.exceptions if e.rule_id == "NORM.MALFORMED_ROW")
    joined = str(finding.details["raw_text"]).replace("\r\n", " ").replace("\n", " ").rstrip()
    row = next(csv.reader(io.StringIO(joined)))
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(row)
    key = finding.subjects[0].rsplit(":", 1)[1]
    return QuarantineRepair(
        "QR-DS05",
        str(finding.details["file"]),
        key,
        buffer.getvalue(),
        "Memo contained a line break",
    )


def corrections(run1: EngineResult) -> Overlays:
    """Every resolution except dispositions: decisions, mapping changes, overrides, repairs."""
    return Overlays(
        entity_decisions=(DS01_MERGE, *DS06_DECISIONS),
        account_mapping_changes=(
            AccountMappingChange("AM-DS03", "1205", "1210", "Allowance is a contra account"),
            AccountMappingChange("AM-DS12", "6999", "1999", "Suspense maps to target suspense"),
        ),
        quarantine_repairs=(quarantine_repair(run1),),
        record_overrides=(
            RecordOverride("RO-DS08", "je:JE-2026-0388", "entry_date", "2026-04-02", "2026-03-31",
                           "Adjustment belongs to the March close"),
            RecordOverride("RO-DS11", "je:JE-AP-20455", "entry_date", "2062-03-14", "2026-03-14",
                           "Keying error; bill date and posting period are March 2026"),
        ),
    )  # fmt: skip


_DISPOSITIONS = {
    "AP.DUPLICATE_BILL": "carry_forward_adjustment",  # DS-02
    "PAY.DUPLICATE_PAYMENT": "carry_forward_adjustment",  # DS-02
    "CUR.PARTY_CURRENCY_MISMATCH": "carry_forward_adjustment",  # DS-07
    "BANK.UNRECORDED_ACTIVITY": "carry_forward_adjustment",  # DS-10
    "DATA.INSTRUCTION_LIKE_TEXT": "not_applicable",  # DS-13
}


def with_dispositions(overlays: Overlays, result: EngineResult) -> Overlays:
    dispositions = tuple(
        Disposition(
            f"DISP-{index:02d}", finding.fingerprint, _DISPOSITIONS[finding.rule_id], "Documented"
        )
        for index, finding in enumerate(e for e in result.exceptions if e.rule_id in _DISPOSITIONS)
    )
    return replace(overlays, dispositions=dispositions)
