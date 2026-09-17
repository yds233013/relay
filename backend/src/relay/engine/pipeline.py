"""Engine pipeline: inputs + overlays + policy → a deterministic, fingerprinted run result.

The pipeline is pure: no database, no clock, no network. The same inputs, overlays, policy and
engine versions always yield the same result and the same fingerprints.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import combinations
from typing import Final

from relay.canonical.enums import PartyType
from relay.core.hashing import fingerprint as content_fingerprint
from relay.engine.entities import (
    SCORING_VERSION,
    Candidate,
    Clusters,
    build_clusters,
    find_candidates,
)
from relay.engine.exceptions import SEVERITY_RANK, RuleException, Severity
from relay.engine.inputs import MigrationInputs
from relay.engine.overlays import Overlays
from relay.engine.policy import Policy
from relay.engine.reconciliation import (
    ReconResult,
    grain_key,
    reconcile,
    reconciliation_set_version,
)
from relay.engine.rules import REGISTRY, RuleContext, ruleset_version
from relay.engine.snapshot import NORM_VERSION, RunSnapshot, normalize

ENGINE_VERSION: Final = "relay-engine/1"


@dataclass(frozen=True, slots=True)
class SkippedRule:
    rule_id: str
    missing_datasets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ErroredStage:
    """A rule or reconciliation that raised: its findings are unknown, so G4 fails (FC-10)."""

    stage: str
    error: str


@dataclass(frozen=True, slots=True)
class EngineResult:
    input_fingerprint: str
    snapshot: RunSnapshot
    candidates: tuple[Candidate, ...]
    clusters: dict[PartyType, Clusters]
    exceptions: tuple[RuleException, ...]
    reconciliations: tuple[ReconResult, ...]
    skipped_rules: tuple[SkippedRule, ...]
    errored_stages: tuple[ErroredStage, ...] = ()

    @property
    def result_fingerprint(self) -> str:
        """Identity of the findings (not of timing or ordering)."""
        return content_fingerprint(
            {
                "exceptions": sorted(
                    f"{e.fingerprint}:{e.severity}:{e.amount_at_risk}" for e in self.exceptions
                ),
                "reconciliations": sorted(
                    f"{grain_key(r.recon_id, line.grain)}:{line.left}:{line.right}:{line.explained}"
                    for r in self.reconciliations
                    for line in r.lines
                    if line.difference != 0 or line.other_differences()
                ),
                "candidates": sorted(
                    f"{c.party_type}:{c.left}:{c.right}:{c.score}" for c in self.candidates
                ),
                # Only for a run that errored, so an error-free result keeps the identity it had.
                **(
                    {"errored": sorted(e.stage for e in self.errored_stages)}
                    if self.errored_stages
                    else {}
                ),
            }
        )


def engine_versions() -> dict[str, object]:
    return {
        "engine": ENGINE_VERSION,
        "normalization": NORM_VERSION,
        "entity_scoring": SCORING_VERSION,
        "rules": ruleset_version(),
        "reconciliations": reconciliation_set_version(),
    }


def input_fingerprint(inputs: MigrationInputs, overlays: Overlays, policy: Policy) -> str:
    components: dict[str, object] = {
        "files": dict(sorted(inputs.file_hashes.items())),
        "mapping_set": inputs.mapping_set,
        "plan": {
            "opening_balance_date": inputs.plan.opening_balance_date.isoformat(),
            "history_start_date": inputs.plan.history_start_date.isoformat(),
            "cutover_date": inputs.plan.cutover_date.isoformat(),
            "go_live_date": inputs.plan.go_live_date.isoformat(),
            "bank_clearing_window_days": inputs.plan.bank_clearing_window_days,
        },
        "overlays": overlays.identity(),
        "policy": {k: str(v) for k, v in policy.as_dict().items()},
        "versions": engine_versions(),
    }
    if inputs.governed_account_mapping is not None:
        # Added only when present, so fingerprints of ungoverned inputs are unchanged.
        components["governed_account_mapping"] = dict(
            sorted(inputs.governed_account_mapping.items())
        )
    return content_fingerprint(components)


def _shared_references(snapshot: RunSnapshot) -> dict[frozenset[str], int]:
    """Vendor pairs whose bills carry the same vendor invoice reference."""
    by_reference: dict[str, set[str]] = defaultdict(set)
    for od in snapshot.bills.values():
        reference = re.sub(r"[^0-9a-z]", "", (od.document.party_reference or "").casefold())
        if reference:
            by_reference[reference].add(od.document.party_code)
    shared: dict[frozenset[str], int] = defaultdict(int)
    for parties in by_reference.values():
        for a, b in combinations(sorted(parties), 2):
            shared[frozenset((a, b))] += 1
    return dict(shared)


def _severity(policy: Policy, exception: RuleException) -> RuleException:
    override = policy.severity_overrides.get(exception.rule_id)
    if override is None:
        return exception
    return replace(exception, severity=Severity(override))


def _error_text(error: Exception) -> str:
    """Type and message only: an engine result must never carry a traceback or row values."""
    return f"{type(error).__name__}: {error}"[:200]


def run_engine(
    inputs: MigrationInputs, overlays: Overlays | None = None, policy: Policy | None = None
) -> EngineResult:
    overlays = overlays or Overlays()
    policy = policy or Policy()
    snapshot = normalize(inputs, overlays)
    clusters = {
        party_type: build_clusters(list(overlays.entity_decisions), party_type)
        for party_type in PartyType
    }
    shared = _shared_references(snapshot)
    candidates = [
        *find_candidates(
            snapshot.customers, PartyType.CUSTOMER, {}, policy.entity_candidate_threshold
        ),
        *find_candidates(
            snapshot.vendors, PartyType.VENDOR, shared, policy.entity_candidate_threshold
        ),
    ]
    context = RuleContext(
        snapshot=snapshot, policy=policy, clusters=clusters, candidates=candidates
    )
    found: list[RuleException] = list(snapshot.exceptions)
    skipped: list[SkippedRule] = []
    errored: list[ErroredStage] = []
    for rule_id in sorted(REGISTRY):
        spec, function = REGISTRY[rule_id]
        missing = tuple(sorted(spec.requires - snapshot.datasets_present))
        if missing:
            skipped.append(SkippedRule(rule_id, missing))
            continue
        try:
            found.extend(function(context, spec))
        except Exception as error:  # noqa: BLE001 - one broken rule must not hide the others
            # FC-10: the rule's findings are unknown. Keep the rest of the evidence and fail G4.
            errored.append(ErroredStage(f"rule:{rule_id}", _error_text(error)))
    reconciliations, recon_exceptions, recon_errors = reconcile(snapshot, policy)
    found.extend(recon_exceptions)
    errored.extend(ErroredStage(stage, _error_text(error)) for stage, error in recon_errors)

    unique: dict[str, RuleException] = {}
    for raw in found:
        exception = _severity(policy, raw)
        current = unique.get(exception.fingerprint)
        if current is None or SEVERITY_RANK[exception.severity] < SEVERITY_RANK[current.severity]:
            unique[exception.fingerprint] = exception
    ordered = sorted(
        unique.values(),
        key=lambda e: (SEVERITY_RANK[e.severity], e.rule_id, e.subjects, e.discriminator),
    )
    return EngineResult(
        input_fingerprint=input_fingerprint(inputs, overlays, policy),
        snapshot=snapshot,
        candidates=tuple(candidates),
        clusters=clusters,
        exceptions=tuple(ordered),
        reconciliations=tuple(reconciliations),
        skipped_rules=tuple(skipped),
        errored_stages=tuple(sorted(errored, key=lambda e: e.stage)),
    )


def total_exposure(exceptions: tuple[RuleException, ...]) -> Decimal:
    return sum((e.amount_at_risk or Decimal(0) for e in exceptions), Decimal(0))
