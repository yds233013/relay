"""Typed loader for the Brightwater golden manifest (TOML)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from relay_evaluation.paths import BRIGHTWATER_MANIFEST


class ManifestError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ExpectedIssue:
    rule: str
    subjects: tuple[Any, ...]
    severity: str
    amount_at_risk: str | None = None
    after: str | None = None


@dataclass(frozen=True, slots=True)
class DefectSpec:
    id: str
    title: str
    category: str
    nature: str
    depends_on: tuple[str, ...]
    visible_in_run1: bool
    condition: str
    facts: tuple[dict[str, Any], ...]
    expected_issues: tuple[ExpectedIssue, ...]
    expected_issues_after_resolution: tuple[ExpectedIssue, ...]
    expected_candidates: tuple[dict[str, Any], ...]
    amount_at_risk: str | None


@dataclass(frozen=True, slots=True)
class TrapSpec:
    id: str
    title: str
    silent_rules: tuple[str, ...]
    facts: tuple[dict[str, Any], ...]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconciliationLineSpec:
    recon: str
    defects: tuple[str, ...]
    grain: dict[str, str]
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Manifest:
    raw: dict[str, Any]
    seed: int
    controls: dict[str, str]
    clean_controls: dict[str, str]
    failing_gates: tuple[str, ...]
    defects: tuple[DefectSpec, ...]
    traps: tuple[TrapSpec, ...]
    reconciliation_lines: tuple[ReconciliationLineSpec, ...]
    reconciliation_exact: bool
    reconciliation_totals: dict[str, str]
    r5: dict[str, Any]

    def defect(self, defect_id: str) -> DefectSpec:
        for defect in self.defects:
            if defect.id == defect_id:
                return defect
        raise ManifestError(f"unknown defect {defect_id}")

    def trap(self, trap_id: str) -> TrapSpec:
        for trap in self.traps:
            if trap.id == trap_id:
                return trap
        raise ManifestError(f"unknown trap {trap_id}")


def _issues(items: list[dict[str, Any]]) -> tuple[ExpectedIssue, ...]:
    return tuple(
        ExpectedIssue(
            rule=item["rule"],
            subjects=tuple(item["subjects"]),
            severity=item["severity"],
            amount_at_risk=item.get("amount_at_risk"),
            after=item.get("after"),
        )
        for item in items
    )


def load_manifest(path: Path = BRIGHTWATER_MANIFEST) -> Manifest:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    if raw.get("schema_version") != 1:
        raise ManifestError("unsupported manifest schema version")
    defects = tuple(
        DefectSpec(
            id=d["id"],
            title=d["title"],
            category=d["category"],
            nature=d["nature"],
            depends_on=tuple(d["depends_on"]),
            visible_in_run1=d["visible_in_run1"],
            condition=d["condition"],
            facts=tuple(d.get("facts", [])),
            expected_issues=_issues(d.get("expected_issues", [])),
            expected_issues_after_resolution=_issues(d.get("expected_issues_after_resolution", [])),
            expected_candidates=tuple(d.get("expected_candidates", [])),
            amount_at_risk=d.get("amount_at_risk"),
        )
        for d in raw["defects"]
    )
    ids = [d.id for d in defects]
    if ids != [f"DS-{n:02d}" for n in range(1, 14)]:
        raise ManifestError(f"manifest must define DS-01..DS-13 in order, found {ids}")
    traps = tuple(
        TrapSpec(
            id=t["id"],
            title=t["title"],
            silent_rules=tuple(t.get("silent_rules", [])),
            facts=tuple(t.get("facts", [])),
            extra={
                key: value
                for key, value in t.items()
                if key not in {"id", "title", "silent_rules", "facts"}
            },
        )
        for t in raw["traps"]
    )
    if [t.id for t in traps] != [f"TN-{n:02d}" for n in range(1, 6)]:
        raise ManifestError("manifest must define TN-01..TN-05 in order")
    recon = raw["reconciliations"]
    lines = tuple(
        ReconciliationLineSpec(
            recon=line["recon"],
            defects=tuple(line["defects"]),
            grain=dict(line["grain"]),
            values={
                key: value
                for key, value in line.items()
                if key not in {"recon", "defects", "grain"}
            },
        )
        for line in recon["lines"]
    )
    return Manifest(
        raw=raw,
        seed=raw["seed"],
        controls=dict(raw["controls"]),
        clean_controls=dict(raw["clean_controls"]),
        failing_gates=tuple(raw["run1_gates"]["failing"]),
        defects=defects,
        traps=traps,
        reconciliation_lines=lines,
        reconciliation_exact=bool(recon.get("exact", False)),
        reconciliation_totals=dict(recon.get("totals", {})),
        r5=dict(recon["R5"]),
    )
