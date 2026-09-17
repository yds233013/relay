"""The deterministic engine against the independently authored Brightwater golden manifest (M2).

The engine is general: nothing here configures it for Brightwater beyond the approved column mapping
set a customer implementation would have. Expected answers come only from the manifest and from
the documented resolutions in ``relay_evaluation.brightwater.resolution``.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from relay.engine.exceptions import Severity
from relay.engine.overlays import GateWaiver, Overlays, Signoff
from relay.engine.pipeline import EngineResult, run_engine
from relay.engine.policy import Policy
from relay.engine.readiness import GateStatus, GovernanceFacts, evaluate_readiness
from relay_evaluation.brightwater import resolution
from relay_evaluation.brightwater.engine_compare import (
    check_issues_present,
    compare_run1,
    expected_after_resolution,
)
from relay_evaluation.brightwater.manifest import Manifest
from relay_evaluation.brightwater.verify import VerificationReport
from relay_scenarios.brightwater.scenario import Scenario

FACTS = GovernanceFacts(required_datasets=resolution.REQUIRED_DATASETS)


@pytest.fixture(scope="module")
def run1(run1_scenario: Scenario) -> EngineResult:
    return run_engine(resolution.inputs_for(run1_scenario.files))


@pytest.fixture(scope="module")
def reexported(run1_scenario: Scenario) -> dict[str, bytes]:
    return resolution.reexported_files(run1_scenario)


def _failures(report: VerificationReport) -> list[str]:
    return [f"{name}: {detail}" for name, ok, detail in report.results if not ok]


# ------------------------------------------------------------------------------------ Run #1
def test_run1_matches_the_golden_manifest_exactly(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    report = compare_run1(run1, run1_scenario.files, manifest)
    assert _failures(report) == []
    # The comparison covers every expected issue, reconciliation line, candidate and trap.
    expected_issues = sum(len(d.expected_issues) for d in manifest.defects)
    assert len(report.results) >= expected_issues + len(manifest.reconciliation_lines)


def test_run1_failing_gates_match_the_manifest(run1: EngineResult, manifest: Manifest) -> None:
    readiness = evaluate_readiness(run1, Overlays(), Policy(), FACTS)
    assert readiness.failing() == list(manifest.failing_gates)
    assert not readiness.ready


def test_committed_fixtures_give_the_same_result_as_generation(run1: EngineResult) -> None:
    from relay_evaluation.cli import _read_fixtures  # noqa: PLC0415 - test-only helper
    from relay_evaluation.paths import BRIGHTWATER_FIXTURES  # noqa: PLC0415

    committed = run_engine(resolution.inputs_for(_read_fixtures(BRIGHTWATER_FIXTURES)))
    assert committed.input_fingerprint == run1.input_fingerprint
    assert committed.result_fingerprint == run1.result_fingerprint


def test_engine_is_deterministic(run1: EngineResult, run1_scenario: Scenario) -> None:
    again = run_engine(resolution.inputs_for(run1_scenario.files))
    assert again.input_fingerprint == run1.input_fingerprint
    assert again.result_fingerprint == run1.result_fingerprint
    assert [e.fingerprint for e in again.exceptions] == [e.fingerprint for e in run1.exceptions]


# ------------------------------------------------------------------ the comparison is not vacuous
def test_comparison_detects_a_missing_issue(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    dropped = next(e for e in run1.exceptions if e.rule_id == "GL.JE_BALANCED")
    mutated = replace(run1, exceptions=tuple(e for e in run1.exceptions if e is not dropped))
    assert _failures(compare_run1(mutated, run1_scenario.files, manifest))


def test_comparison_detects_an_extra_issue(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    extra = replace(run1.exceptions[0], subjects=("je:NOT-A-REAL-ENTRY",))
    mutated = replace(run1, exceptions=(*run1.exceptions, extra))
    assert _failures(compare_run1(mutated, run1_scenario.files, manifest))


def test_comparison_detects_a_wrong_severity_or_amount(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    target = next(e for e in run1.exceptions if e.rule_id == "GL.DATE_IN_WINDOW")
    for changed in (
        replace(target, severity=Severity.HIGH),
        replace(target, amount_at_risk=Decimal("1184.63")),
    ):
        exceptions = tuple(changed if e is target else e for e in run1.exceptions)
        assert _failures(
            compare_run1(replace(run1, exceptions=exceptions), run1_scenario.files, manifest)
        )


def test_comparison_detects_a_missing_reconciliation_line(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    reconciliations = tuple(r for r in run1.reconciliations if r.recon_id != "R6")
    mutated = replace(run1, reconciliations=reconciliations)
    assert _failures(compare_run1(mutated, run1_scenario.files, manifest))
    r6 = next(r for r in run1.reconciliations if r.recon_id == "R6")
    emptied = replace(r6, lines=())
    mutated = replace(run1, reconciliations=(*reconciliations, emptied))
    assert _failures(compare_run1(mutated, run1_scenario.files, manifest))


# ------------------------------------------------------------------------ resolution sequence
def test_merging_ds01_reveals_ds02(
    run1: EngineResult, run1_scenario: Scenario, manifest: Manifest
) -> None:
    for rule_id in ("AP.DUPLICATE_BILL", "PAY.DUPLICATE_PAYMENT"):
        assert not [e for e in run1.exceptions if e.rule_id == rule_id]
    overlays = Overlays(entity_decisions=(resolution.DS01_MERGE,))
    merged = run_engine(resolution.inputs_for(run1_scenario.files), overlays)
    report = VerificationReport()
    check_issues_present(
        report, merged, run1_scenario.files, expected_after_resolution(manifest), "after DS-01"
    )
    assert _failures(report) == []
    duplicates = [
        e for e in merged.exceptions if e.rule_id in {"AP.DUPLICATE_BILL", "PAY.DUPLICATE_PAYMENT"}
    ]
    assert len(duplicates) == len(expected_after_resolution(manifest))
    ds01_pair = ("party:vendor:V-1042", "party:vendor:V-1187")
    assert not [e for e in merged.exceptions if e.subjects == ds01_pair]
    assert merged.input_fingerprint != run1.input_fingerprint


def test_documented_resolutions_reach_ready_with_signoff(
    run1: EngineResult, reexported: dict[str, bytes], manifest: Manifest
) -> None:
    policy = Policy()
    inputs = resolution.inputs_for(reexported)
    corrected = resolution.corrections(run1)
    before_dispositions = run_engine(inputs, corrected)
    # Every remaining blocking finding is a documented source anomaly that needs a disposition.
    blocking = {
        e.rule_id
        for e in before_dispositions.exceptions
        if e.severity in {Severity.CRITICAL, Severity.HIGH}
    }
    assert blocking == {"AP.DUPLICATE_BILL", "PAY.DUPLICATE_PAYMENT", "CUR.PARTY_CURRENCY_MISMATCH"}
    # No normalization findings and no stale overrides.
    assert not before_dispositions.snapshot.exceptions
    assert sorted(before_dispositions.snapshot.applied_overrides) == sorted(
        [o.id for o in corrected.record_overrides]
        + [r.id for r in corrected.quarantine_repairs]
        + [c.id for c in corrected.account_mapping_changes]
    )

    final_overlays = resolution.with_dispositions(corrected, before_dispositions)
    final = run_engine(inputs, final_overlays)
    readiness = evaluate_readiness(final, final_overlays, policy, FACTS)
    assert readiness.failing() == ["G12"]
    assert readiness.unresolved_exposure == 0
    assert all(r.status in {"tied", "tied_with_explained_items"} for r in final.reconciliations)

    signed = replace(final_overlays, signoffs=(Signoff("SIGN-1", final.input_fingerprint),))
    signed_result = run_engine(inputs, signed)
    assert signed_result.input_fingerprint == final.input_fingerprint
    signed_readiness = evaluate_readiness(signed_result, signed, policy, FACTS)
    assert signed_readiness.ready
    assert signed_readiness.failing() == []
    # DS-02, DS-07, DS-10 and DS-13 remain visible as dispositioned findings.
    assert sorted(set(signed_readiness.issue_status.values())) == ["dispositioned", "open"]
    assert manifest.defect("DS-02").amount_at_risk == "14862.50"


def test_signoff_for_another_fingerprint_does_not_count(
    run1: EngineResult, reexported: dict[str, bytes]
) -> None:
    corrected = resolution.corrections(run1)
    inputs = resolution.inputs_for(reexported)
    final_overlays = resolution.with_dispositions(corrected, run_engine(inputs, corrected))
    stale = replace(final_overlays, signoffs=(Signoff("SIGN-OLD", run1.input_fingerprint),))
    result = run_engine(inputs, stale)
    readiness = evaluate_readiness(result, stale, Policy(), FACTS)
    assert readiness.failing() == ["G12"]


def test_waivers_cover_waivable_gates_while_their_scope_is_unchanged(
    run1: EngineResult, run1_scenario: Scenario
) -> None:
    """governance.md §4.3: bound to the gate's scope, not to one fingerprint; lapse on change."""
    before = evaluate_readiness(run1, Overlays(), Policy(), FACTS)
    g6_scope = before.gate("G6").scope
    g7_scope = before.gate("G7").scope
    assert g6_scope
    assert g7_scope
    changed = {**g7_scope, next(iter(g7_scope)): "0.01"}
    waivers = (
        GateWaiver("W-G6", "G6", run1.input_fingerprint, "reviewed", g6_scope),
        GateWaiver("W-G5", "G5", run1.input_fingerprint, "not waivable", {"x": "1"}),
        GateWaiver("W-G7-CHANGED", "G7", run1.input_fingerprint, "amount changed", changed),
    )
    readiness = evaluate_readiness(run1, Overlays(gate_waivers=waivers), Policy(), FACTS)
    assert readiness.gate("G6").status is GateStatus.WAIVED
    assert readiness.gate("G6").waiver_id == "W-G6"
    assert readiness.gate("G5").status is GateStatus.FAIL
    assert readiness.gate("G7").status is GateStatus.FAIL
    assert readiness.gate("G12").status is GateStatus.FAIL

    inputs = resolution.inputs_for(run1_scenario.files)
    # A change that does not touch the ledger reconciliations keeps the G6 waiver valid.
    merged_overlays = Overlays(entity_decisions=(resolution.DS01_MERGE,), gate_waivers=waivers)
    merged = run_engine(inputs, merged_overlays)
    assert merged.input_fingerprint != run1.input_fingerprint
    assert (
        evaluate_readiness(merged, merged_overlays, Policy(), FACTS).gate("G6").status
        is GateStatus.WAIVED
    )
    # Correcting a backdated entry changes waived R1 and R2 amounts: the waiver lapses.
    ds08 = next(o for o in resolution.corrections(run1).record_overrides if o.id == "RO-DS08")
    corrected_overlays = Overlays(record_overrides=(ds08,), gate_waivers=waivers)
    corrected = run_engine(inputs, corrected_overlays)
    assert (
        evaluate_readiness(corrected, corrected_overlays, Policy(), FACTS).gate("G6").status
        is GateStatus.FAIL
    )


def test_a_wrong_merge_of_the_distinct_store_is_visible(run1_scenario: Scenario) -> None:
    """TN-02: merging all three Green Valley records is wrong; the choice must stay explicit."""
    from relay.canonical.enums import PartyType  # noqa: PLC0415
    from relay.engine.overlays import EntityDecision  # noqa: PLC0415

    wrong = EntityDecision(
        "ED-WRONG",
        PartyType.CUSTOMER,
        "same_entity",
        ("C-0107", "C-0154", "C-0198"),
        "C-0107",
        "naive",
    )
    result = run_engine(
        resolution.inputs_for(run1_scenario.files), Overlays(entity_decisions=(wrong,))
    )
    clusters = result.clusters[PartyType.CUSTOMER]
    assert clusters.cluster("C-0198") == clusters.cluster("C-0107")
    # The decision is an explicit overlay in the input fingerprint, never an automatic merge.
    baseline = run_engine(resolution.inputs_for(run1_scenario.files))
    assert baseline.clusters[PartyType.CUSTOMER].cluster("C-0198") == "C-0198"
    assert result.input_fingerprint != baseline.input_fingerprint
