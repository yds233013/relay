"""Readiness gates G1-G12 evaluated on one engine result (docs/governance.md §4).

Pure: the caller supplies the governance facts the engine cannot know (dataset requirements,
approval state of mapping sets, pending change requests, whether the result is current).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final

from relay.engine.exceptions import RuleException, Severity
from relay.engine.overlays import Overlays
from relay.engine.pipeline import EngineResult
from relay.engine.policy import Policy

GATE_SET_VERSION: Final = 1
MAX_EVIDENCE: Final = 1000
"""Evidence references stored per gate; the count of findings is always in ``observed``."""
WAIVABLE: Final = frozenset({"G6", "G7", "G8", "G9"})


class GateStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - not a password
    FAIL = "fail"
    WAIVED = "waived"


@dataclass(frozen=True, slots=True)
class GovernanceFacts:
    required_datasets: frozenset[str]
    column_mapping_sets_approved: bool = True
    account_mapping_set_approved: bool = True
    current_fingerprint: str | None = None
    """``None`` means the evaluated result is the current run."""
    pending_change_requests: int = 0
    errored_stages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    title: str
    status: GateStatus
    observed: str
    threshold: str
    summary: str
    evidence: tuple[str, ...] = ()
    waiver_id: str | None = None


@dataclass(frozen=True, slots=True)
class Readiness:
    run_fingerprint: str
    gates: tuple[GateResult, ...]
    unresolved_exposure: Decimal
    issue_status: dict[str, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(g.status is not GateStatus.FAIL for g in self.gates)

    def failing(self) -> list[str]:
        return [g.gate_id for g in self.gates if g.status is GateStatus.FAIL]

    def gate(self, gate_id: str) -> GateResult:
        return next(g for g in self.gates if g.gate_id == gate_id)


def issue_statuses(result: EngineResult, overlays: Overlays) -> dict[str, str]:
    """Each finding's status in this run: ``open`` or ``dispositioned`` (resolved = absent)."""
    dispositioned = {d.fingerprint for d in overlays.dispositions}
    return {
        e.fingerprint: ("dispositioned" if e.fingerprint in dispositioned else "open")
        for e in result.exceptions
    }


def unresolved_exposure(exceptions: Iterable[RuleException]) -> Decimal:
    """Σ amount at risk of unresolved findings.

    Findings connected through a shared subject record count once, at their maximum.
    """
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        while parent.setdefault(key, key) != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    amounts: list[tuple[str, Decimal]] = []
    for exception in exceptions:
        if not exception.amount_at_risk or not exception.subjects:
            continue
        root = find(exception.subjects[0])
        for subject in exception.subjects[1:]:
            parent[find(subject)] = root
        amounts.append((exception.subjects[0], exception.amount_at_risk))
    maxima: dict[str, Decimal] = {}
    for subject, amount in amounts:
        root = find(subject)
        maxima[root] = max(maxima.get(root, Decimal(0)), amount)
    return sum(maxima.values(), Decimal(0))


def _gate(  # noqa: PLR0917 - gate rows read like the governance table
    gate_id: str,
    title: str,
    ok: bool,
    observed: object,
    threshold: str,
    summary: str,
    evidence: Iterable[str] = (),
) -> GateResult:
    return GateResult(
        gate_id,
        title,
        GateStatus.PASS if ok else GateStatus.FAIL,
        str(observed),
        threshold,
        summary,
        tuple(sorted(evidence))[:MAX_EVIDENCE],
    )


def evaluate_readiness(
    result: EngineResult, overlays: Overlays, policy: Policy, facts: GovernanceFacts
) -> Readiness:
    snapshot = result.snapshot
    statuses = issue_statuses(result, overlays)
    unresolved = [e for e in result.exceptions if statuses[e.fingerprint] == "open"]
    recon = {r.recon_id: r for r in result.reconciliations}
    gates: list[GateResult] = []

    missing = sorted(facts.required_datasets - snapshot.datasets_present)
    quarantine = [
        e for e in unresolved if e.rule_id in {"NORM.MALFORMED_ROW", "NORM.UNREADABLE_FILE"}
    ]
    gates.append(
        _gate(
            "G1",
            "Required datasets",
            not missing and not quarantine,
            f"{len(missing)} missing, {len(quarantine)} unresolved quarantined records",
            "0 missing, 0 quarantined",
            "Every required dataset is present and fully parsed",
            [*(f"dataset:{d}" for d in missing), *(e.fingerprint for e in quarantine)],
        )
    )
    gates.append(
        _gate(
            "G2",
            "Column mappings approved",
            facts.column_mapping_sets_approved,
            facts.column_mapping_sets_approved,
            "approved",
            "Every imported dataset uses an approved column mapping set",
        )
    )
    mapping_findings = [
        e
        for e in result.exceptions
        if e.rule_id in {"MAP.ACCOUNT_UNMAPPED", "MAP.TARGET_ACCOUNT_EXISTS"}
    ]
    gates.append(
        _gate(
            "G3",
            "Account mapping complete",
            facts.account_mapping_set_approved and not mapping_findings,
            f"{len(mapping_findings)} unmapped or invalid targets",
            "0",
            "Every legacy account maps to an existing target account",
            [e.fingerprint for e in mapping_findings],
        )
    )
    current = (
        facts.current_fingerprint is None or facts.current_fingerprint == result.input_fingerprint
    )
    gates.append(
        _gate(
            "G4",
            "Results current",
            current and not facts.errored_stages,
            "current" if current else "stale",
            "current, no errors",
            "The evaluated run reflects the current inputs and completed without errors",
            facts.errored_stages,
        )
    )
    blocking = [e for e in unresolved if e.severity in {Severity.CRITICAL, Severity.HIGH}]
    gates.append(
        _gate(
            "G5",
            "No blocking exceptions",
            not blocking,
            f"{sum(e.severity is Severity.CRITICAL for e in blocking)} critical, "
            f"{sum(e.severity is Severity.HIGH for e in blocking)} high",
            "0 unresolved critical, 0 undispositioned high",
            "No critical or high findings remain open",
            [e.fingerprint for e in blocking],
        )
    )

    def recon_gate(
        gate_id: str, title: str, recon_ids: tuple[str, ...], summary: str
    ) -> GateResult:
        lines = [
            f"{rid}:{dict(line.grain)}"
            for rid in recon_ids
            if rid in recon
            for line in recon[rid].discrepancies()
        ]
        not_applicable = [rid for rid in recon_ids if rid not in recon or not recon[rid].applicable]
        return _gate(
            gate_id,
            title,
            not lines and not not_applicable,
            f"{len(lines)} discrepancy lines",
            "0",
            summary,
            [*lines, *(f"not_applicable:{rid}" for rid in not_applicable)],
        )

    gates.append(
        recon_gate(
            "G6",
            "Ledger ties",
            ("R1", "R2"),
            "Trial balance, GL detail and staged balances agree for every period",
        )
    )
    gates.append(
        recon_gate(
            "G7",
            "Subledgers tie",
            ("R3", "R3b", "R4", "R4b"),
            "AR and AP open items agree with the GL and the agings",
        )
    )
    r5 = recon.get("R5")
    unexplained = (
        sum((abs(line.unexplained) for line in r5.lines), Decimal(0))
        if r5 and r5.applicable
        else None
    )
    bank_open = [e for e in unresolved if e.rule_id == "BANK.UNRECORDED_ACTIVITY"]
    gates.append(
        _gate(
            "G8",
            "Cash reconciled",
            unexplained is not None
            and unexplained <= policy.cash_unexplained_tolerance
            and not bank_open,
            f"unexplained {unexplained}, {len(bank_open)} unrecorded bank items open",
            f"≤ {policy.cash_unexplained_tolerance}, 0 open",
            "Cash ties to the bank with only documented timing items",
            [e.fingerprint for e in bank_open],
        )
    )
    exposure = unresolved_exposure(unresolved)
    gates.append(
        _gate(
            "G9",
            "Exposure below threshold",
            exposure <= policy.max_unresolved_exposure,
            exposure,
            f"≤ {policy.max_unresolved_exposure}",
            "Unresolved amount at risk is within policy",
        )
    )
    strong = [
        c
        for c in result.candidates
        if c.score >= policy.entity_strong_threshold
        and frozenset(c.members) not in result.clusters[c.party_type].decided_pairs
    ]
    gates.append(
        _gate(
            "G10",
            "Entities decided",
            not strong,
            f"{len(strong)} undecided strong candidates",
            "0",
            "Every strong duplicate candidate has a decision",
            [f"{c.party_type.value}:{c.left}:{c.right}" for c in strong],
        )
    )
    gates.append(
        _gate(
            "G11",
            "No pending changes",
            facts.pending_change_requests == 0,
            facts.pending_change_requests,
            "0",
            "No change requests are waiting for approval",
        )
    )

    waivers = {
        w.gate_id: w
        for w in overlays.gate_waivers
        if w.run_fingerprint == result.input_fingerprint and w.gate_id in WAIVABLE
    }
    gates = [
        GateResult(
            g.gate_id,
            g.title,
            GateStatus.WAIVED,
            g.observed,
            g.threshold,
            g.summary,
            g.evidence,
            waivers[g.gate_id].id,
        )
        if g.status is GateStatus.FAIL and g.gate_id in waivers
        else g
        for g in gates
    ]
    prior_ok = all(g.status is not GateStatus.FAIL for g in gates)
    signed = [s for s in overlays.signoffs if s.run_fingerprint == result.input_fingerprint]
    gates.append(
        _gate(
            "G12",
            "Signed off",
            prior_ok and bool(signed),
            f"{len(signed)} sign-offs for this run",
            "1 applied sign-off",
            "Lead and controller signed off on this exact run",
            [s.id for s in signed],
        )
    )
    return Readiness(
        run_fingerprint=result.input_fingerprint,
        gates=tuple(gates),
        unresolved_exposure=exposure,
        issue_status=statuses,
    )


def gate_set_version() -> list[str]:
    return [f"G{n}@{GATE_SET_VERSION}" for n in range(1, 13)]
