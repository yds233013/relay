"""False-positive traps (criterion 3), golden-manifest agreement (criterion 4)."""

from __future__ import annotations

import copy
import dataclasses
from decimal import Decimal

import pytest

from relay.canonical.enums import PaymentDirection
from relay_evaluation.brightwater.fixtures import read_table
from relay_evaluation.brightwater.manifest import Manifest, load_manifest
from relay_evaluation.brightwater.oracle import Oracle
from relay_evaluation.brightwater.verify import check_fact, verify_scenario
from relay_evaluation.paths import BRIGHTWATER_MANIFEST
from relay_scenarios.brightwater.scenario import Scenario
from relay_scenarios.brightwater.universe import LegacyUniverse

TRAPS = ("TN-01", "TN-02", "TN-03", "TN-04", "TN-05")


@pytest.mark.parametrize("trap_id", TRAPS)
@pytest.mark.parametrize("scenario_name", ["clean_scenario", "run1_scenario"])
def test_trap_facts_hold(
    trap_id: str, scenario_name: str, request: pytest.FixtureRequest, manifest: Manifest
) -> None:
    scenario: Scenario = request.getfixturevalue(scenario_name)
    tables = {p: read_table(p, c) for p, c in scenario.files.items() if p.endswith(".csv")}
    oracle = Oracle(scenario.files)
    failures = [
        (f, d)
        for f in manifest.trap(trap_id).facts
        for ok, d in [check_fact(f, tables, oracle)]
        if not ok
    ]
    assert failures == []


def test_traps_are_legitimate_in_clean_books(clean_universe: LegacyUniverse) -> None:
    # TN-01: each rent bill paid exactly once, by a distinct payment on its own date.
    landlord = next(
        v.code for v in clean_universe.vendors.values() if v.name == "Lombard Street Properties LLC"
    )
    rent_bills = [b for b in clean_universe.bills.values() if b.party_code == landlord]
    assert len(rent_bills) == 6
    for bill in rent_bills:
        payments = [
            p
            for p in clean_universe.payments.values()
            if any(a.document_number == bill.number for a in p.applications)
        ]
        assert len(payments) == 1
        assert payments[0].payment_date == bill.document_date
    # TN-04: the reversal exactly negates the accrual.
    accrual = clean_universe.journals["JE-2026-0455"]
    reversal = clean_universe.journals["JE-2026-0456"]
    assert reversal.reversal_of == accrual.entry_number
    assert [(ln.account_code, -ln.functional_amount.amount) for ln in accrual.lines] == [
        (ln.account_code, ln.functional_amount.amount) for ln in reversal.lines
    ]
    # TN-05: two receipts on the same day, each settling a different 1,250.00 invoice in full.
    receipts = [
        p
        for p in clean_universe.payments.values()
        if p.party_code == "C-0120"
        and p.direction is PaymentDirection.RECEIVED
        and p.amount.amount == Decimal("1250.00")
    ]
    assert len(receipts) == 2
    assert receipts[0].payment_date == receipts[1].payment_date
    assert {r.applications[0].document_number for r in receipts} == {
        d.number
        for d in clean_universe.invoices.values()
        if d.party_code == "C-0120" and d.total.amount == Decimal("1250.00")
    }
    # TN-02 / TN-03: distinct legal entities with distinct tax ids and addresses.
    by_name = {p.name: p for p in clean_universe.customers.values()}
    assert (
        by_name["Mountain Grocers Inc."].tax_id_last4
        != by_name["Mountain Grocers LLC"].tax_id_last4
    )
    assert by_name["Mountain Grocers Inc."].region != by_name["Mountain Grocers LLC"].region
    assert (
        by_name["GREEN VALLEY COOP #2"].address_line1 != by_name["Green Valley Co-op"].address_line1
    )


def test_run1_scenario_agrees_with_golden_manifest(
    run1_scenario: Scenario, manifest: Manifest
) -> None:
    report = verify_scenario(run1_scenario.files, manifest)
    assert report.failures == []
    assert len(report.results) >= 100


def test_manifest_covers_every_defect_and_trap(manifest: Manifest) -> None:
    assert [d.id for d in manifest.defects] == [f"DS-{n:02d}" for n in range(1, 14)]
    assert [t.id for t in manifest.traps] == list(TRAPS)
    for defect in manifest.defects:
        assert defect.facts, defect.id
        has_reconciliation_signal = any(
            defect.id in line.defects for line in manifest.reconciliation_lines
        )
        assert (
            defect.expected_issues
            or defect.expected_issues_after_resolution
            or has_reconciliation_signal
        ), defect.id
    assert manifest.reconciliation_exact
    assert manifest.failing_gates == ("G1", "G3", "G5", "G6", "G7", "G8", "G9", "G10", "G12")


def test_verifier_detects_a_wrong_expected_amount(
    run1_scenario: Scenario, manifest: Manifest
) -> None:
    line = manifest.reconciliation_lines[0]
    altered = dataclasses.replace(line, values={**line.values, "difference": "-449.99"})
    lines = tuple(altered if ln is line else ln for ln in manifest.reconciliation_lines)
    report = verify_scenario(
        run1_scenario.files, dataclasses.replace(manifest, reconciliation_lines=lines)
    )
    assert any("reconciliation" in name for name, _, _ in report.failures)


def test_verifier_detects_a_missing_expected_discrepancy(
    run1_scenario: Scenario, manifest: Manifest
) -> None:
    lines = manifest.reconciliation_lines[1:]
    report = verify_scenario(
        run1_scenario.files, dataclasses.replace(manifest, reconciliation_lines=lines)
    )
    assert [name for name, _, _ in report.failures] == ["reconciliation.exact_set"]


def test_verifier_detects_corrupted_fixtures(run1_scenario: Scenario, manifest: Manifest) -> None:
    files = dict(run1_scenario.files)
    statement = (
        files["firstcascade/firstcascade_4471_statement.csv"]
        .decode("utf-8-sig")
        .splitlines(keepends=True)
    )
    files["firstcascade/firstcascade_4471_statement.csv"] = "".join(
        line
        for line in statement
        if "MONTHLY MAINTENANCE FEE" not in line or "2026-03-31" not in line
    ).encode("utf-8-sig")
    report = verify_scenario(files, manifest)
    assert report.failures


def test_verifier_detects_a_changed_fact(run1_scenario: Scenario) -> None:
    manifest = load_manifest(BRIGHTWATER_MANIFEST)
    defect = manifest.defect("DS-01")
    facts = copy.deepcopy(list(defect.facts))
    facts[2]["count"] = 22
    changed = dataclasses.replace(defect, facts=tuple(facts))
    defects = tuple(changed if d is defect else d for d in manifest.defects)
    report = verify_scenario(run1_scenario.files, dataclasses.replace(manifest, defects=defects))
    assert [name for name, _, _ in report.failures] == ["DS-01.fact[2] csv_rows"]
