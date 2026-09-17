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
class EngineResult:
    input_fingerprint: str
    snapshot: RunSnapshot
    candidates: tuple[Candidate, ...]
    clusters: dict[PartyType, Clusters]
    exceptions: tuple[RuleException, ...]
    reconciliations: tuple[ReconResult, ...]
    skipped_rules: tuple[SkippedRule, ...]

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
    return content_fingerprint(
        {
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
    )


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
    for rule_id in sorted(REGISTRY):
        spec, function = REGISTRY[rule_id]
        missing = tuple(sorted(spec.requires - snapshot.datasets_present))
        if missing:
            skipped.append(SkippedRule(rule_id, missing))
            continue
        found.extend(function(context, spec))
    reconciliations, recon_exceptions = reconcile(snapshot, policy)
    found.extend(recon_exceptions)

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
    )


def total_exposure(exceptions: tuple[RuleException, ...]) -> Decimal:
    return sum((e.amount_at_risk or Decimal(0) for e in exceptions), Decimal(0))
