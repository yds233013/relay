"""Defect injectors DS-01 to DS-13 (M1 acceptance criterion 2).

Each injector is applied to the clean books on its own (plus declared dependencies). Its manifest
facts must hold, its reconciliation effects must be exactly the manifest lines attributed to it, and
it must not touch unrelated records.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from relay_evaluation.brightwater.fixtures import read_table
from relay_evaluation.brightwater.manifest import Manifest
from relay_evaluation.brightwater.oracle import Oracle
from relay_evaluation.brightwater.verify import check_fact
from relay_scenarios.brightwater import controls
from relay_scenarios.brightwater.exports import export_all
from relay_scenarios.brightwater.injectors import ALL_DEFECTS, INJECTORS_BY_ID, apply_defects
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.errors import ScenarioConsistencyError

# Records each injector is allowed to change: collection -> keys (callables receive the universe).
ALLOWED_CHANGES: dict[str, set[str]] = {
    "DS-01": {"vendors", "vendor_info", "bills", "payments", "journals"},
    "DS-02": {"bills", "bill_info", "payments", "journals", "journal_info", "bank_lines"},
    "DS-03": {"account_mapping"},
    "DS-04": {"invoice_info"},
    "DS-05": {"journals"},
    "DS-06": {"customers", "customer_info", "invoices", "payments", "journals"},
    "DS-07": {"invoices", "payments", "journals"},
    "DS-08": {"journals"},
    "DS-09": {"customers", "customer_info"},
    "DS-10": {"bank_lines"},
    "DS-11": {"journals"},
    "DS-12": {"accounts"},
    "DS-13": {"vendors"},
}
COLLECTIONS = (
    "accounts",
    "target_accounts",
    "account_mapping",
    "customers",
    "customer_info",
    "vendors",
    "vendor_info",
    "invoices",
    "invoice_info",
    "bills",
    "bill_info",
    "payments",
    "journals",
    "journal_info",
    "bank_lines",
    "fx_rates",
    "opening_balances",
)


def _with_dependencies(defect_id: str) -> list[str]:
    order: list[str] = []

    def visit(current: str) -> None:
        for dependency in INJECTORS_BY_ID[current].depends_on:
            visit(dependency)
        if current not in order:
            order.append(current)

    visit(defect_id)
    return order


def _changed(before: LegacyUniverse, after: LegacyUniverse) -> dict[str, set[Any]]:
    changes: dict[str, set[Any]] = {}
    for name in COLLECTIONS:
        old, new = getattr(before, name), getattr(after, name)
        if isinstance(old, list):
            if old != new:
                changes[name] = {"<list>"}
            continue
        keys = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
        if keys:
            changes[name] = keys
    return changes


@pytest.fixture(scope="module")
def isolated(
    clean_universe: LegacyUniverse,
) -> Callable[[str], tuple[LegacyUniverse, dict[str, bytes]]]:
    cache: dict[str, tuple[LegacyUniverse, dict[str, bytes]]] = {}

    def build(defect_id: str) -> tuple[LegacyUniverse, dict[str, bytes]]:
        if defect_id not in cache:
            universe = apply_defects(copy.deepcopy(clean_universe), _with_dependencies(defect_id))
            cache[defect_id] = (universe, export_all(universe))
        return cache[defect_id]

    return build


@pytest.mark.parametrize("defect_id", ALL_DEFECTS)
def test_injector_facts_hold_in_isolation(
    defect_id: str,
    isolated: Callable[[str], tuple[LegacyUniverse, dict[str, bytes]]],
    manifest: Manifest,
) -> None:
    _, files = isolated(defect_id)
    tables = {
        path: read_table(path, content) for path, content in files.items() if path.endswith(".csv")
    }
    oracle = Oracle(files)
    failures = []
    applied = set(_with_dependencies(defect_id))
    for fact in manifest.defect(defect_id).facts:
        if not set(fact.get("requires", [])) <= applied:
            continue
        ok, detail = check_fact(fact, tables, oracle)
        if not ok:
            failures.append((fact, detail))
    assert failures == []


@pytest.mark.parametrize("defect_id", ALL_DEFECTS)
def test_injector_reconciliation_effects_are_exactly_its_manifest_lines(
    defect_id: str,
    isolated: Callable[[str], tuple[LegacyUniverse, dict[str, bytes]]],
    manifest: Manifest,
) -> None:
    _, files = isolated(defect_id)
    applied = set(_with_dependencies(defect_id))
    expected = {
        (line.recon, tuple(sorted(line.grain.items())))
        for line in manifest.reconciliation_lines
        if set(line.defects) & applied
    }
    actual = {(line.recon, tuple(sorted(line.grain))) for line in Oracle(files).all_lines()}
    assert actual == expected


@pytest.mark.parametrize("defect_id", ALL_DEFECTS)
def test_injector_changes_only_its_records(defect_id: str, clean_universe: LegacyUniverse) -> None:
    before = copy.deepcopy(clean_universe)
    for dependency in _with_dependencies(defect_id)[:-1]:
        apply_defects(before, [dependency])
    after = apply_defects(copy.deepcopy(before), [defect_id])
    changed = _changed(before, after)
    assert set(changed) <= ALLOWED_CHANGES[defect_id]
    assert changed, "an injector must change something"


def test_injector_record_scopes_are_bounded(clean_universe: LegacyUniverse) -> None:
    after = apply_defects(copy.deepcopy(clean_universe), ["DS-05", "DS-08", "DS-11"])
    changed = _changed(clean_universe, after)
    assert changed == {"journals": {"JE-2026-0412", "JE-2026-0388", "JE-AP-20455"}}
    ds01 = _changed(clean_universe, apply_defects(copy.deepcopy(clean_universe), ["DS-01"]))
    assert len(ds01["bills"]) == 3
    assert ds01["vendors"] == {"V-1187"}


def test_cash_effects_of_injectors(clean_universe: LegacyUniverse) -> None:
    cutover = clean_universe.plan.cutover_date
    both = apply_defects(copy.deepcopy(clean_universe), ["DS-01", "DS-02", "DS-10"])
    assert controls.gl_balance(both, "1010", cutover) == Decimal("412906.18")
    assert controls.bank_balance(both, cutover) == Decimal("427101.93")


def test_dependencies_are_enforced(clean_universe: LegacyUniverse) -> None:
    with pytest.raises(ScenarioConsistencyError, match="requires"):
        apply_defects(copy.deepcopy(clean_universe), ["DS-02"])


def test_injectors_cannot_be_applied_twice(clean_universe: LegacyUniverse) -> None:
    with pytest.raises(ScenarioConsistencyError):
        apply_defects(copy.deepcopy(clean_universe), ["DS-04", "DS-04"])


def test_unknown_defect_rejected(clean_universe: LegacyUniverse) -> None:
    with pytest.raises(ScenarioConsistencyError, match="unknown defect"):
        apply_defects(copy.deepcopy(clean_universe), ["DS-99"])


@pytest.mark.parametrize("defect_id", ["DS-03", "DS-05", "DS-08", "DS-11", "DS-12", "DS-13"])
def test_injector_preconditions_fail_loudly(defect_id: str, clean_universe: LegacyUniverse) -> None:
    universe = apply_defects(copy.deepcopy(clean_universe), [defect_id])
    universe.applied_injectors.clear()
    with pytest.raises(ScenarioConsistencyError):
        INJECTORS_BY_ID[defect_id].apply(universe)


def test_combined_scenario_applies_all_defects_in_order(run1_scenario: Any) -> None:
    assert run1_scenario.universe.applied_injectors == list(ALL_DEFECTS)
