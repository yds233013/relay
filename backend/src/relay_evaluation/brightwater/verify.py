"""Verification of generated Brightwater fixtures against the golden manifest."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise
from typing import Any

from relay.core.dates import parse_iso_business_date
from relay_evaluation.brightwater.fixtures import (
    Table,
    amount,
    normalize,
    normalize_expected,
    read_table,
)
from relay_evaluation.brightwater.manifest import DefectSpec, Manifest, TrapSpec
from relay_evaluation.brightwater.oracle import Line, Oracle, reconstruct_quarantined


@dataclass
class VerificationReport:
    results: list[tuple[str, bool, str]] = field(default_factory=list)

    def record(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))

    @property
    def failures(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.results if not r[1]]

    @property
    def ok(self) -> bool:
        return not self.failures


def _matches(row: dict[str, str], where: dict[str, Any]) -> bool:
    return all(
        normalize(row.get(column, "")) == normalize_expected(value)
        for column, value in where.items()
    )


def check_fact(fact: dict[str, Any], tables: dict[str, Table], oracle: Oracle) -> tuple[bool, str]:
    kind = fact["check"]
    if kind == "csv_rows":
        table = tables[fact["file"]]
        rows = [row for row in table.rows if _matches(row, fact.get("where", {}))]
        if "count" in fact and len(rows) != fact["count"]:
            return (
                False,
                f"expected {fact['count']} rows matching {fact.get('where')}, found {len(rows)}",
            )
        for row in rows:
            for column, expected in fact.get("expect", {}).items():
                if normalize(row[column]) != normalize_expected(expected):
                    return False, f"{column}: expected {expected!r}, found {row[column]!r}"
        for column in fact.get("distinct", []):
            values = [row[column] for row in rows]
            if len(set(values)) != len(values):
                return False, f"{column} values are not distinct: {values}"
        for column in fact.get("same", []):
            if len({row[column] for row in rows}) > 1:
                return False, f"{column} values differ"
        return True, f"{len(rows)} rows"
    if kind == "csv_sum":
        table = tables[fact["file"]]
        total = sum(
            (amount(row[fact["column"]]) for row in table.rows if _matches(row, fact["where"])),
            Decimal(0),
        )
        return total == Decimal(fact["total"]), f"sum {total}"
    if kind == "malformed_rows":
        table = tables[fact["file"]]
        malformed = table.malformed
        if len(malformed) != fact["count"]:
            return False, f"expected {fact['count']} malformed rows, found {len(malformed)}"
        if fact.get("consecutive") and any(
            b.line_start != a.line_end + 1 for a, b in pairwise(malformed)
        ):
            return False, "malformed rows are not consecutive"
        if fact.get("first_contains") and fact["first_contains"] not in malformed[0].raw_text:
            return False, "first malformed row does not contain the expected text"
        records = reconstruct_quarantined(table)
        if len(records) != 1:
            return False, f"expected one reconstructed record, found {len(records)}"
        for column, expected in fact.get("reconstructed_fields", {}).items():
            if normalize(records[0][column]) != normalize_expected(expected):
                return (
                    False,
                    f"reconstructed {column}: expected {expected!r}, found {records[0][column]!r}",
                )
        return True, "malformed rows as expected"
    if kind == "balance":
        as_of = parse_iso_business_date(fact["as_of"])
        expected = Decimal(fact["value"])
        actual: object
        if fact["measure"] == "tb_closing":
            actual = oracle.tb()[(fact["account"], as_of)]
        elif fact["measure"] == "gl_by_date":
            actual = (
                oracle.r5()["gl_balance"]
                if fact["account"] == "1010" and as_of.isoformat() == "2026-06-30"
                else None
            )
        elif fact["measure"] == "bank":
            actual = oracle.r5()["bank_balance"]
        else:
            return False, f"unknown measure {fact['measure']}"
        return actual == expected, f"actual {actual}"
    return False, f"unknown check {kind}"


def _line_key(
    recon: str, grain: Iterable[tuple[str, str]]
) -> tuple[str, tuple[tuple[str, str], ...]]:
    return recon, tuple(sorted(grain))


def verify_scenario(files: dict[str, bytes], manifest: Manifest) -> VerificationReport:
    report = VerificationReport()
    tables = {
        path: read_table(path, content) for path, content in files.items() if path.endswith(".csv")
    }
    oracle = Oracle(files)

    specs: list[DefectSpec | TrapSpec] = [*manifest.defects, *manifest.traps]
    for spec in specs:
        for index, fact in enumerate(spec.facts):
            ok, detail = check_fact(fact, tables, oracle)
            report.record(f"{spec.id}.fact[{index}] {fact['check']}", ok, detail)

    r5 = oracle.r5()
    report.record(
        "controls.gl_cash_1010_at_cutover",
        r5["gl_balance"] == Decimal(manifest.controls["gl_cash_1010_at_cutover"]),
        str(r5["gl_balance"]),
    )
    report.record(
        "controls.bank_balance_at_cutover",
        r5["bank_balance"] == Decimal(manifest.controls["bank_balance_at_cutover"]),
        str(r5["bank_balance"]),
    )
    report.record(
        "controls.legacy_1205_balance_at_cutover",
        oracle.tb()[("1205", parse_iso_business_date("2026-06-30"))]
        == Decimal(manifest.controls["legacy_1205_balance_at_cutover"]),
    )
    for measure in ("gl_balance", "bank_balance", "difference", "unexplained"):
        report.record(
            f"R5.{measure}",
            r5[measure] == Decimal(manifest.r5[measure]),
            f"actual {r5[measure]}",
        )
    for item in ("outstanding_checks", "deposits_in_transit", "bank_only_activity"):
        actual_item = r5[item]
        expected_item = manifest.r5[item]
        if not isinstance(actual_item, dict):
            raise TypeError(f"R5 {item} must be a mapping")
        report.record(
            f"R5.{item}",
            actual_item["count"] == expected_item["count"]
            and actual_item["total"] == Decimal(expected_item["total"]),
            f"actual {actual_item}",
        )
    report.record(
        "R5.no_unmatched_ledger_cash",
        r5["unexplained_gl_movements"] == 0,
        f"{r5['unexplained_gl_movements']}",
    )

    actual_lines: dict[tuple[str, tuple[tuple[str, str], ...]], Line] = {}
    for line in oracle.all_lines():
        actual_lines[_line_key(line.recon, line.grain)] = line
    expected_keys = set()
    for line_spec in manifest.reconciliation_lines:
        key = _line_key(line_spec.recon, line_spec.grain.items())
        expected_keys.add(key)
        actual_line = actual_lines.get(key)
        if actual_line is None:
            report.record(f"reconciliation {key}", False, "expected discrepancy not present")
            continue
        mismatches = []
        for name, expected_value in line_spec.values.items():
            actual_value = actual_line.values.get(name)
            expected_cmp = (
                expected_value if isinstance(expected_value, int) else Decimal(str(expected_value))
            )
            if actual_value != expected_cmp:
                mismatches.append(f"{name}: expected {expected_value}, actual {actual_value}")
        report.record(f"reconciliation {key}", not mismatches, "; ".join(mismatches))
    if manifest.reconciliation_exact:
        unexpected = sorted(set(actual_lines) - expected_keys)
        report.record(
            "reconciliation.exact_set",
            not unexpected,
            f"unexpected discrepancies: {unexpected[:10]}",
        )

    r3_total = Decimal(0)
    for line in actual_lines.values():
        if line.recon == "R3":
            difference = line.values["difference"]
            if not isinstance(difference, Decimal):
                raise TypeError("R3 difference must be a Decimal")
            r3_total += difference
    report.record(
        "reconciliation.R3_total",
        r3_total == Decimal(manifest.reconciliation_totals["R3_total_difference"]),
        f"actual {r3_total}",
    )
    return report
