"""EVALUATION ONLY: check the engine's Kestrel results against the hand-authored expectations.

The expectations live in ``evaluation/kestrel/expected.toml`` and are never read by runtime code.
This module runs the unchanged engine over the generated fixtures and compares: the exact set of
findings (rule and subjects), the reconciliation figures the manifest names, and that the clean
books produce nothing at all.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from relay.engine.inputs import build_inputs
from relay.engine.pipeline import EngineResult, run_engine
from relay_evaluation.paths import REPO_ROOT
from relay_scenarios.kestrel.scenario import build_scenario

EXPECTED = REPO_ROOT / "evaluation" / "kestrel" / "expected.toml"
MAPPING_SET = REPO_ROOT / "fixtures" / "demo" / "kestrel_config" / "column_mapping_set_v1.json"


@dataclass(frozen=True, slots=True)
class Report:
    checks: tuple[tuple[str, bool, str], ...]

    @property
    def failures(self) -> list[tuple[str, bool, str]]:
        return [check for check in self.checks if not check[1]]


def expectations() -> dict[str, Any]:
    return tomllib.loads(EXPECTED.read_text(encoding="utf-8"))


def run_kestrel(*, defects: tuple[str, ...] | None = None) -> EngineResult:
    scenario = build_scenario() if defects is None else build_scenario(defects=defects)
    mapping = json.loads(MAPPING_SET.read_text(encoding="utf-8"))
    descriptor = json.loads(scenario.files["migration.json"])
    return run_engine(build_inputs(descriptor, scenario.files, mapping))


def _line(result: EngineResult, recon_id: str, **grain: str) -> Any:
    recon = next((r for r in result.reconciliations if r.recon_id == recon_id), None)
    if recon is None:
        return None
    return next((line for line in recon.lines if dict(line.grain) == grain), None)


def _discrepancies(result: EngineResult, recon_id: str) -> list[Any]:
    recon = next((r for r in result.reconciliations if r.recon_id == recon_id), None)
    return list(recon.discrepancies()) if recon else []


def verify() -> Report:
    """One check per expectation, in the order the manifest states them."""
    expected = expectations()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    clean = run_kestrel(defects=())
    clean_discrepancies = sum(len(r.discrepancies()) for r in clean.reconciliations)
    check(
        "clean books produce no findings",
        not clean.exceptions,
        ", ".join(sorted({e.rule_id for e in clean.exceptions})),
    )
    check("clean books reconcile", clean_discrepancies == 0, str(clean_discrepancies))
    check("clean books have no errored stage", not clean.errored_stages,
          ", ".join(e.stage for e in clean.errored_stages))  # fmt: skip

    result = run_kestrel()
    check(
        "no reconciliation errored",
        not result.errored_stages,
        ", ".join(f"{e.stage}: {e.error}" for e in result.errored_stages),
    )

    seen: dict[tuple[str, tuple[str, ...]], Any] = {
        (e.rule_id, tuple(e.subjects)): e for e in result.exceptions
    }
    counted: dict[str, int] = {}
    for finding in expected["findings"]:
        rule_id = finding["rule_id"]
        counted[rule_id] = counted.get(rule_id, 0) + finding.get("count", 1)
        if "subjects" in finding:
            key = (rule_id, tuple(finding["subjects"]))
            match = seen.get(key)
            check(
                f"{finding['defect']} {rule_id} {finding['subjects']}",
                match is not None and match.severity.value == finding["severity"],
                "missing" if match is None else f"severity {match.severity.value}",
            )
        else:
            found = [e for e in result.exceptions if e.rule_id == rule_id]
            check(
                f"{finding['defect']} {rule_id} x{finding.get('count', 1)}",
                len(found) == finding.get("count", 1),
                f"found {len(found)}",
            )

    rule_counts: dict[str, int] = {}
    for exception in result.exceptions:
        if not exception.rule_id.startswith("RECON."):
            rule_counts[exception.rule_id] = rule_counts.get(exception.rule_id, 0) + 1
    check(
        "no findings beyond the manifest",
        rule_counts == counted,
        f"engine {sorted(rule_counts.items())} vs manifest {sorted(counted.items())}",
    )

    r1 = expected["reconciliations"]["R1"]
    january = _line(result, "R1", account=r1["account"], period_end="2026-01-31")
    february = _line(result, "R1", account=r1["account"], period_end="2026-02-28")
    check(
        "R1 January difference",
        january is not None and january.difference == Decimal(r1["difference_january"]),
        "missing" if january is None else str(january.difference),
    )
    check(
        "R1 difference from February",
        february is not None and february.difference == Decimal(r1["difference_from_february"]),
        "missing" if february is None else str(february.difference),
    )
    check(
        "R1 differs on the named account only",
        {dict(line.grain)["account"] for line in _discrepancies(result, "R1")} == {r1["account"]},
        str(sorted({dict(line.grain)["account"] for line in _discrepancies(result, "R1")})),
    )

    r2 = expected["reconciliations"]["R2"]
    inherited = _line(result, "R2", target_account=r2["target_account"], period_end="2026-02-28")
    check(
        "R2 inherits the R1 difference",
        inherited is not None and inherited.difference == Decimal(r2["difference_from_february"]),
        "missing" if inherited is None else str(inherited.difference),
    )

    r3 = expected["reconciliations"]["R3"]
    party_line = _line(result, "R3", party=r3["party"])
    check(
        "R3 customer difference",
        party_line is not None and party_line.difference == Decimal(r3["difference"]),
        "missing" if party_line is None else str(party_line.difference),
    )
    unassigned = expected["reconciliations"]["R3_unassigned"]
    unassigned_line = _line(result, "R3", party=unassigned["party"])
    check(
        "R3 unassigned difference",
        unassigned_line is not None
        and unassigned_line.difference == Decimal(unassigned["difference"]),
        "missing" if unassigned_line is None else str(unassigned_line.difference),
    )

    r3b = expected["reconciliations"]["R3b"]
    document_line = _line(result, "R3b", document=r3b["document"])
    check(
        "R3b document difference",
        document_line is not None and document_line.difference == Decimal(r3b["difference"]),
        "missing" if document_line is None else str(document_line.difference),
    )

    r5 = expected["reconciliations"]["R5"]
    cash = next((r for r in result.reconciliations if r.recon_id == "R5"), None)
    cash_line = cash.lines[0] if cash and cash.lines else None
    classifications = [item.classification for item in cash_line.items] if cash_line else []
    check(
        "R5 difference",
        cash_line is not None and cash_line.difference == Decimal(r5["difference"]),
        "missing" if cash_line is None else str(cash_line.difference),
    )
    check(
        "R5 unexplained",
        cash_line is not None and cash_line.unexplained == Decimal(r5["unexplained"]),
        "missing" if cash_line is None else str(cash_line.unexplained),
    )
    check(
        "R5 items",
        classifications.count("bank_only_activity") == r5["bank_only_activity"]
        and classifications.count("ledger_only_movement") == r5["ledger_only_movement"],
        str(sorted(classifications)),
    )

    r6 = expected["reconciliations"]["R6"]
    unreadable = _line(result, "R6", period=r6["period"])
    check(
        "R6 unreadable row",
        unreadable is not None
        and int(str(unreadable.extra["count_difference"])) == r6["count_difference"],
        "missing" if unreadable is None else str(dict(unreadable.extra)),
    )
    check(
        "R6 reports nothing else",
        len(_discrepancies(result, "R6")) == 1,
        str(len(_discrepancies(result, "R6"))),
    )

    for recon_id in expected["reconciliations"]["tied"]["recon_ids"]:
        check(f"{recon_id} ties", not _discrepancies(result, recon_id))

    # A defect need not raise a rule finding to be caught: KS-04 (an invoice missing from the sales
    # export) only ever shows up as a subledger difference. The manifest therefore names the defect
    # each reconciliation block belongs to, and coverage is the union of both.
    covered = {finding["defect"] for finding in expected["findings"]}
    for block in expected["reconciliations"].values():
        covered |= set(block.get("defects", ()))
    check(
        "every planted defect is expected",
        covered == set(build_scenario().planted),
        f"covered {sorted(covered)}",
    )
    return Report(tuple(checks))


def format_report(report: Report) -> str:
    lines = [
        f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else "")
        for name, ok, detail in report.checks
    ]
    passed = len(report.checks) - len(report.failures)
    lines.append(f"{passed}/{len(report.checks)} Kestrel expectations met")
    return "\n".join(lines)


def fixtures_root() -> Path:
    return REPO_ROOT / "fixtures" / "demo" / "kestrel"
