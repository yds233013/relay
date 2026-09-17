"""CSV reading with lineage and quarantine; declarative column mapping transforms."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from relay.core.currency import Currency
from relay.ingestion.csv_reader import (
    MAX_RECORD_LINES,
    SourceFileError,
    read_csv,
    reconstruct_quarantined,
    repair_quarantined,
)
from relay.mapping.transforms import (
    DatasetMapping,
    FieldMapping,
    MappingConfigError,
    TransformError,
)


# ------------------------------------------------------------------------------------ reader
def test_rows_keep_physical_line_lineage() -> None:
    table = read_csv("f.csv", b"a,b\r\n1,2\r\n3,4\r\n", encoding="utf-8")
    assert table.header == ("a", "b")
    assert [(r.row_number, r.line_start, r.line_end, r.values) for r in table.rows] == [
        (1, 2, 2, {"a": "1", "b": "2"}),
        (2, 3, 3, {"a": "3", "b": "4"}),
    ]
    assert table.quarantined == ()


def test_quoted_field_may_span_lines() -> None:
    table = read_csv("f.csv", b'a,b\n1,"two\nlines"\n3,4\n', encoding="utf-8")
    assert [(r.line_start, r.line_end, r.values["b"]) for r in table.rows] == [
        (2, 3, "two\nlines"),
        (4, 4, "4"),
    ]


def test_unquoted_line_break_is_quarantined_as_one_record_and_can_be_repaired() -> None:
    table = read_csv("f.csv", b"a,b,c\n1,memo\nsplit,3\n4,5,6\n", encoding="utf-8")
    [row] = table.quarantined
    assert (row.line_start, row.line_end, row.field_counts) == (2, 3, (2, 2))
    assert [r.values["a"] for r in table.rows] == ["4"]
    # Provisional reconstruction joins the physical lines (used only for control totals).
    assert reconstruct_quarantined(table, row) == {"a": "1", "b": "memo split", "c": "3"}
    assert repair_quarantined(table, '1,"memo split",3') == {"a": "1", "b": "memo split", "c": "3"}
    with pytest.raises(SourceFileError):
        repair_quarantined(table, "1,2")


def test_quarantine_key_depends_on_content_not_position() -> None:
    first = read_csv("f.csv", b"a,b\n1\n2,3\n", encoding="utf-8")
    second = read_csv("f.csv", b"a,b\n2,3\n4,5\n1\n", encoding="utf-8")
    assert first.quarantined[0].key == second.quarantined[0].key


def test_a_stray_quote_cannot_swallow_the_rest_of_the_file() -> None:
    body = "".join(f"{n},x\n" for n in range(MAX_RECORD_LINES + 10))
    table = read_csv("f.csv", ('a,b\n1,"oops\n' + body).encode(), encoding="utf-8")
    assert len(table.rows) >= MAX_RECORD_LINES + 9
    assert len(table.quarantined) == 1
    assert table.quarantined[0].line_start == 2


def test_unreadable_files_are_rejected() -> None:
    with pytest.raises(SourceFileError):
        read_csv("f.csv", b"", encoding="utf-8")
    with pytest.raises(SourceFileError):
        read_csv("f.csv", b"a,a\n1,2\n", encoding="utf-8")
    with pytest.raises(SourceFileError):
        read_csv("f.csv", b"a,b\n\xff\xfe,1\n", encoding="utf-8")
    with pytest.raises(SourceFileError):
        read_csv("f.csv", b"a,b\n1\x00,2\n", encoding="utf-8")


def test_windows_1252_text_is_decoded_exactly() -> None:
    table = read_csv("f.csv", "name\nCaf\u00e9 \u2013 Nord\n".encode("cp1252"), encoding="cp1252")
    assert table.rows[0].values["name"] == "Caf\u00e9 \u2013 Nord"


# ---------------------------------------------------------------------------------- transforms
def _field(target: str, spec: dict[str, object]) -> FieldMapping:
    return FieldMapping.parse(target, spec)


def test_amounts_dates_periods_and_currencies_parse_explicitly() -> None:
    amount = _field(
        "amount",
        {"source": "Amt", "steps": [{"step": "parse_decimal", "thousands_separator": ","}]},
    )
    assert amount.apply({"Amt": "1,234.50"}) == Decimal("1234.50")
    with pytest.raises(Exception, match="format"):
        amount.apply({"Amt": "1.234,50"})
    day = _field("day", {"source": "D", "steps": [{"step": "parse_date", "format": "MM/DD/YYYY"}]})
    assert day.apply({"D": "03/14/2026"}) == date(2026, 3, 14)
    period = _field("p", {"source": "P", "steps": [{"step": "parse_period", "format": "MM/YYYY"}]})
    assert period.apply({"P": "03/2026"}) == "2026-03"
    with pytest.raises(TransformError):
        period.apply({"P": "13/2026"})
    currency = _field("c", {"source": "C", "steps": [{"step": "currency"}]})
    assert currency.apply({"C": "EUR"}) == Currency.of("EUR")


def test_debit_and_credit_columns_become_one_signed_amount() -> None:
    signed = _field(
        "amount", {"debit_credit": {"debit": "Dr", "credit": "Cr", "thousands_separator": ","}}
    )
    assert signed.apply({"Dr": "1,000.00", "Cr": ""}) == Decimal("1000.00")
    assert signed.apply({"Dr": "", "Cr": "250.00"}) == Decimal("-250.00")
    with pytest.raises(Exception):  # noqa: B017, PT011 - both sides populated is invalid input
        signed.apply({"Dr": "1.00", "Cr": "1.00"})


def test_value_maps_never_guess() -> None:
    strict = _field(
        "kind", {"source": "K", "steps": [{"step": "value_map", "mapping": {"Bill": "document"}}]}
    )
    assert strict.apply({"K": "Bill"}) == "document"
    with pytest.raises(TransformError):
        strict.apply({"K": "Invoice"})
    passthrough = _field(
        "terms",
        {
            "source": "T",
            "steps": [
                {"step": "value_map", "mapping": {"Due on receipt": "Net 0"}, "passthrough": True}
            ],
        },
    )
    assert passthrough.apply({"T": "Net 30"}) == "Net 30"
    boolean = _field(
        "active",
        {"source": "A", "steps": [{"step": "parse_boolean", "true": ["Yes"], "false": ["No"]}]},
    )
    with pytest.raises(TransformError):
        boolean.apply({"A": "Y"})


def test_blank_values_become_missing_and_required_fields_are_marked() -> None:
    field = _field("email", {"source": "E", "steps": [{"step": "trim"}], "required": False})
    assert field.apply({"E": "   "}) is None
    assert not field.required
    assert _field("code", {"source": "C"}).required


def test_invalid_mapping_configuration_is_rejected_up_front() -> None:
    bad_specs: list[dict[str, object]] = [
        {"source": "X", "steps": [{"step": "eval"}]},
        {"source": "X", "steps": [{"step": "parse_date"}]},
        {"source": "X", "steps": [{"step": "parse_date", "format": "whatever"}]},
        {"source": "X", "steps": [{"step": "regex_extract", "pattern": "("}]},
        {"source": "X", "steps": [{"step": "trim", "extra": 1}]},
        {"steps": [{"step": "trim"}]},
        {"source": "X", "unknown": True},
        {"debit_credit": {"debit": "D"}},
    ]
    for spec in bad_specs:
        with pytest.raises(MappingConfigError):
            FieldMapping.parse("f", spec)
    with pytest.raises(MappingConfigError):
        DatasetMapping.parse(
            "gl_detail", {"fields": {"a": {"source": "Missing"}}}, header=["Present"]
        )


def test_rows_can_be_excluded_by_blank_key_columns() -> None:
    mapping = DatasetMapping.parse("ar_aging", {"fields": {}, "exclude_rows_where_blank": ["ID"]})
    assert mapping.excludes({"ID": "", "Name": "TOTAL"})
    assert not mapping.excludes({"ID": "C-1", "Name": "x"})
