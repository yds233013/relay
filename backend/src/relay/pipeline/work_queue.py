"""The work an implementation still needs from a person, composed from what the engine found.

Relay's deterministic controls produce findings, reconciliation differences, entity candidates and
gate results. Those are precise, and they are also the wrong unit of work: sixty-five findings are
not sixty-five decisions. This module groups them into the decisions an operator actually makes,
each one carrying what happened, why it matters, how much money it concerns, and where to act.

Everything here is derived from stored run output. It knows nothing about any particular company:
the mapping item exists because a reconciliation attributed a difference to a legacy account whose
mapping the engine flagged, not because a demo has such an account.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.changes.models import Approval, ChangeRequest, ChangeRequestStatus
from relay.changes.read_model import active_entity_decisions
from relay.core.currency import Currency
from relay.issues.models import Issue
from relay.mapping_sets import accounts
from relay.pipeline import read_model
from relay.pipeline.models import GateResultRow, PipelineRun
from relay.workspace.models import Migration

_OPEN: Final = ("open", "in_progress", "awaiting_verification")

#: Classification the engine attaches when a difference equals one legacy account's balance.
_ACCOUNT_CONTRIBUTION: Final = "single_account_contribution"


@dataclass(frozen=True, slots=True)
class WorkItem:
    """One decision, with the evidence behind it."""

    key: str
    kind: str
    title: str
    """Plain English: what a person is being asked to do."""
    summary: str
    """What happened and why it matters, without engine vocabulary."""
    judgement: str | None
    """What the person must decide that Relay deliberately will not decide for them."""
    amount: Decimal | None
    count: int
    action_label: str
    target_kind: str
    """Where acting happens: mappings, reconciliation_line, issue, entities, change_request,
    import."""
    target_id: str | None
    issue_id: uuid.UUID | None = None
    """The finding an investigation would be about, when one exists.

    The investigation *itself* is attached by the API layer: this module sits below the AI layer
    and may not import it, which the import contracts enforce.
    """
    issue_key: str | None = None
    evidence: tuple[str, ...] = ()
    """Issue fingerprints, reconciliation line keys or candidate keys, as gates record them."""
    blocks: tuple[str, ...] = ()
    """Failing gates whose evidence this item covers, computed by intersection."""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def sort_key(self) -> tuple[int, Decimal, int]:
        return (0 if self.blocks else 1, -(self.amount or Decimal(0)), -self.count)


def _abs(value: Decimal | None) -> Decimal:
    return abs(value) if value is not None else Decimal(0)


def _money(value: Decimal | None, currency: Currency) -> str:
    """A figure fit for a sentence: grouped, and rounded for display only (FC-04)."""
    if value is None:
        return "—"
    places = Decimal(1).scaleb(-currency.minor_units)
    return f"{value.quantize(places, rounding=ROUND_HALF_UP):,}"


def _canonical(reference: str) -> str:
    """Compare evidence by meaning, not by how a dict happened to be printed.

    Gate evidence and reconciliation lines both name a line by its reconciliation id and grain,
    printed as a mapping, but the key order of that mapping is not guaranteed to match on both
    sides, so each reference is reduced to a sorted, order-independent form before comparing.
    """
    recon, _, grain = reference.partition(":")
    if not grain.startswith("{"):
        return reference
    try:
        parsed = ast.literal_eval(grain)
    except (ValueError, SyntaxError):
        return reference
    if not isinstance(parsed, dict):
        return reference
    return recon + ":" + ",".join(f"{k}={parsed[k]}" for k in sorted(parsed))


def _blocked_by(evidence: Sequence[str], gates: Sequence[GateResultRow]) -> tuple[str, ...]:
    """Which failing gates name this evidence. Derived, never assumed from the kind of work."""
    wanted = {_canonical(e) for e in evidence}
    return tuple(
        gate.gate_id
        for gate in gates
        if gate.status == "fail" and wanted and wanted & {_canonical(e) for e in gate.evidence}
    )


def _mapping_problems(session: Session, migration_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Legacy accounts whose mapping the engine doubts, by account code."""
    problems: dict[str, dict[str, Any]] = {}
    for row in accounts.suggestions(session, migration_id):
        signals = row.get("signals") or {}
        target = row.get("target_account_code")
        unmapped = target is None
        incompatible = (
            not signals.get("target_exists", True)
            or signals.get("type_compatible") is False
            or signals.get("subtype_compatible") is False
        )
        if unmapped or incompatible:
            problems[str(row["legacy_account_code"])] = {
                "legacy_name": row.get("legacy_name"),
                "legacy_subtype": row.get("legacy_subtype"),
                "target": target,
                "target_name": row.get("target_name"),
                "target_subtype": row.get("target_subtype"),
                "unmapped": unmapped,
                "signals": signals,
                "proposal": (row.get("proposal") or {}).get("target"),
            }
    return problems


def _recon_line_key(recon_id: str, grain: dict[str, str]) -> str:
    return f"{recon_id}:{grain}"


def _mapping_items(
    session: Session,
    migration_id: uuid.UUID,
    run: PipelineRun,
    gates: Sequence[GateResultRow],
    currency: Currency,
) -> tuple[list[WorkItem], set[str]]:
    """Mapping decisions, strongest first: those a reconciliation has already put a number on.

    The link is the engine's own explainer — a reconciling item whose classification says the
    difference equals one legacy account's balance — so the money and the mapping are joined by
    evidence rather than by assumption.
    """
    problems = _mapping_problems(session, migration_id)
    items: list[WorkItem] = []
    attributed: set[str] = set()
    explained_lines: set[str] = set()

    for result in read_model.reconciliation_results(session, run.id):
        for line in read_model.lines(
            session, result.id, status="discrepancy", after_key=None, limit=500
        ):
            for item in read_model.items_for(session, line.id):
                if item.classification != _ACCOUNT_CONTRIBUTION:
                    continue
                for record in item.record_keys:
                    code = str(record).rsplit(":", 1)[-1]
                    problem = problems.get(code)
                    if problem is None:
                        continue
                    attributed.add(code)
                    explained_lines.add(_recon_line_key(result.recon_id, dict(line.grain)))
                    evidence = (_recon_line_key(result.recon_id, dict(line.grain)),)
                    target = problem["target"]
                    where = (
                        "is not mapped to any account in the new chart"
                        if problem["unmapped"]
                        else f"is mapped to {target} {problem['target_name'] or ''}".rstrip()
                    )
                    items.append(
                        WorkItem(
                            key=f"mapping:{code}",
                            kind="account_mapping",
                            title=f"Review how legacy account {code} is mapped",
                            summary=(
                                f"{result.title} differs by "
                                f"{_money(_abs(line.difference), currency)}, and Relay "
                                f"attributes the whole difference to legacy account {code} "
                                f"{problem['legacy_name'] or ''}".rstrip()
                                + f". That account {where}, which the compatibility check flags as "
                                "the wrong accounting treatment."
                            ),
                            judgement=(
                                "Relay can tell that the treatment conflicts. Choosing the right "
                                "target account is an accounting decision for the implementation "
                                "team."
                            ),
                            amount=_abs(line.difference),
                            count=1,
                            action_label="Review mapping",
                            target_kind="mappings",
                            target_id=code,
                            evidence=evidence,
                            blocks=_blocked_by(evidence, gates),
                            detail={
                                "legacy_account": code,
                                "legacy_name": problem["legacy_name"],
                                "legacy_subtype": problem["legacy_subtype"],
                                "target_account": target,
                                "target_subtype": problem["target_subtype"],
                                "suggested_target": problem["proposal"],
                                "reconciliation": result.recon_id,
                                "reconciliation_title": result.title,
                                "line_id": str(line.id),
                            },
                        )
                    )

    unattributed = sorted(set(problems) - attributed)
    if unattributed:
        first = problems[unattributed[0]]
        items.append(
            WorkItem(
                key="mapping:incomplete",
                kind="account_mapping",
                title=(
                    f"Map {len(unattributed)} legacy account"
                    f"{'s' if len(unattributed) > 1 else ''} to the new chart"
                ),
                summary=(
                    "These accounts carry a balance or activity but do not map cleanly onto the "
                    "target chart of accounts, so the migrated ledger cannot be trusted to add up."
                ),
                judgement="Which target account each one belongs to.",
                amount=None,
                count=len(unattributed),
                action_label="Review mapping",
                target_kind="mappings",
                target_id=unattributed[0],
                evidence=(),
                blocks=(),
                detail={"accounts": unattributed, "first_name": first["legacy_name"]},
            )
        )
    return items, explained_lines


def _reconciliation_items(
    session: Session,
    run: PipelineRun,
    gates: Sequence[GateResultRow],
    explained: set[str],
    currency: Currency,
) -> list[WorkItem]:
    """One item per control that does not tie, excluding differences a mapping item already owns."""
    items: list[WorkItem] = []
    for result in read_model.reconciliation_results(session, run.id):
        if result.status != "discrepancy":
            continue
        lines = [
            line
            for line in read_model.lines(
                session, result.id, status="discrepancy", after_key=None, limit=500
            )
            if _recon_line_key(result.recon_id, dict(line.grain)) not in explained
        ]
        if not lines:
            continue
        largest = max(lines, key=lambda line: _abs(line.unexplained_amount))
        evidence = tuple(_recon_line_key(result.recon_id, dict(line.grain)) for line in lines)
        items.append(
            WorkItem(
                key=f"recon:{result.recon_id}",
                kind="reconciliation",
                title=(
                    f"Resolve {len(lines)} difference{'s' if len(lines) != 1 else ''} in "
                    f"{result.title}"
                ),
                summary=(
                    f"{result.left_label} and {result.right_label} disagree on "
                    f"{len(lines)} line{'s' if len(lines) != 1 else ''}. The largest single "
                    f"difference is {_money(_abs(largest.unexplained_amount), currency)}."
                ),
                judgement=(
                    "Relay can show which records make up the difference; whether it is a bad "
                    "import or a real misstatement is a person's call."
                ),
                amount=_abs(largest.unexplained_amount),
                count=len(lines),
                action_label="Investigate difference",
                target_kind="reconciliation_line",
                target_id=str(largest.id),
                evidence=evidence,
                blocks=_blocked_by(evidence, gates),
                detail={
                    "reconciliation": result.recon_id,
                    "left_label": result.left_label,
                    "right_label": result.right_label,
                    "result_id": str(result.id),
                },
            )
        )
    return items


_NATURE_FRAMING: Final = {
    "source_anomaly": (
        "The legacy books really are wrong here. Migrating the numbers as they stand is usually "
        "right; the correction belongs in the new system.",
        "Whether to carry this forward as an adjustment, accept it, or rule it out.",
        "Decide how to handle",
    ),
    "migration_defect": (
        "Relay or the export is wrong here, not the customer's books. This should be fixed before "
        "go-live.",
        "What the correct value is, and whether it needs a re-export or an override.",
        "Review finding",
    ),
}


def _issue_items(
    session: Session,
    migration_id: uuid.UUID,
    run: PipelineRun,
    gates: Sequence[GateResultRow],
    covered_rules: set[str],
) -> list[WorkItem]:
    """Open findings grouped by the control that raised them: one cause makes many findings.

    Rules whose work is already represented by a more useful item — the mapping decision, the
    duplicate-party decision, the unreadable rows — are left out rather than listed twice.
    """
    issues = list(
        session.scalars(
            select(Issue)
            .where(Issue.migration_id == migration_id, Issue.status.in_(_OPEN))
            .order_by(Issue.key)
        )
    )
    titles = {r.rule_id: r.title for r in read_model.rule_runs(session, run.id)}
    grouped: dict[tuple[str, str], list[Issue]] = {}
    for issue in issues:
        rule = issue.rule_or_recon_id or "other"
        if rule.startswith("RECON.") or rule in covered_rules:
            continue  # reconciliation differences and covered causes have their own items
        grouped.setdefault((issue.nature, rule), []).append(issue)

    items: list[WorkItem] = []
    for (nature, rule), group in grouped.items():
        why, judgement, verb = _NATURE_FRAMING.get(
            nature, ("This needs a person to look at it.", None, "Review finding")
        )
        total = sum((i.amount_at_risk or Decimal(0) for i in group), Decimal(0))
        evidence = tuple(i.fingerprint for i in group if i.fingerprint)
        head = group[0]
        items.append(
            WorkItem(
                key=f"issues:{nature}:{rule}",
                kind=nature,
                title=f"{verb}: {(titles.get(rule) or head.title.split(':')[0]).strip().lower()}",
                summary=(
                    f"{len(group)} finding{'s' if len(group) != 1 else ''} of the same kind. {why}"
                ),
                judgement=judgement,
                amount=total or None,
                count=len(group),
                action_label="Review evidence",
                target_kind="issue",
                target_id=str(head.id),
                evidence=evidence,
                blocks=_blocked_by(evidence, gates),
                detail={"rule": rule, "nature": nature, "issue_keys": [i.key for i in group[:10]]},
            )
        )
    return items


#: Rules whose findings are the symptom of a decision that already has its own work item.
COVERED_BY_ENTITY_ITEM: Final = frozenset({"PARTY.UNRESOLVED_DUPLICATE_CANDIDATE"})
COVERED_BY_DATA_ITEM: Final = frozenset({"NORM.MALFORMED_ROW"})
COVERED_BY_MAPPING_ITEM: Final = frozenset(
    {"MAP.SUBTYPE_COMPATIBLE", "MAP.TYPE_COMPATIBLE", "MAP.TARGET_EXISTS"}
)


def _entity_items(
    session: Session, migration_id: uuid.UUID, run: PipelineRun, gates: Sequence[GateResultRow]
) -> list[WorkItem]:
    decided = {tuple(sorted(d.members)) for d in active_entity_decisions(session, migration_id)}
    undecided = [
        c
        for c in read_model.candidates(session, run.id)
        if c.strong and tuple(sorted([c.left_code, c.right_code])) not in decided
    ]
    if not undecided:
        return []
    evidence = tuple(f"{c.party_type}:{c.left_code}:{c.right_code}" for c in undecided)
    first = undecided[0]
    return [
        WorkItem(
            key="entities:duplicates",
            kind="entity_decision",
            title=(
                f"Decide {len(undecided)} possible duplicate "
                f"part{'ies' if len(undecided) != 1 else 'y'}"
            ),
            summary=(
                "Relay found records that look like the same customer or vendor recorded twice. "
                "Merging changes which balances belong together, so it never merges on its own."
            ),
            judgement="Whether each pair is genuinely one party, or two that merely look alike.",
            amount=None,
            count=len(undecided),
            action_label="Review duplicates",
            target_kind="entities",
            target_id=str(first.id),
            evidence=evidence,
            blocks=_blocked_by(evidence, gates),
            detail={
                "pairs": [f"{c.left_code} / {c.right_code}" for c in undecided[:10]],
            },
        )
    ]


def _approval_items(
    session: Session, migration_id: uuid.UUID, user_id: uuid.UUID | None, role: str | None
) -> list[WorkItem]:
    waiting = list(
        session.scalars(
            select(ChangeRequest).where(
                ChangeRequest.migration_id == migration_id,
                ChangeRequest.status == ChangeRequestStatus.SUBMITTED.value,
            )
        )
    )
    items: list[WorkItem] = []
    for change in waiting:
        decided = list(
            session.scalars(select(Approval).where(Approval.change_request_id == change.id))
        )
        satisfied = {a.satisfies_requirement_index for a in decided if a.decision == "approve"}
        outstanding = [r for i, r in enumerate(change.required_approvals) if i not in satisfied]
        yours = (
            user_id is not None
            and change.requested_by != user_id
            and not any(a.reviewer_user_id == user_id for a in decided)
            and any(r.get("role") == role for r in outstanding)
        )
        items.append(
            WorkItem(
                key=f"approval:{change.id}",
                kind="approval",
                title=(
                    "Approve a proposed correction"
                    if yours
                    else "A correction is waiting for approval"
                ),
                summary=(
                    f"{change.title}. "
                    f"{len(outstanding)} approval"
                    f"{'s' if len(outstanding) != 1 else ''} outstanding. "
                    "Nothing changes in the migration until it is approved."
                ),
                judgement="Whether the evidence supports the change.",
                amount=None,
                count=1,
                action_label="Review change" if yours else "Open change request",
                target_kind="change_request",
                target_id=str(change.id),
                evidence=(),
                blocks=(),
                detail={"yours": yours, "key": change.key, "kind": change.kind},
            )
        )
    return items


def _data_items(session: Session, run: PipelineRun) -> list[WorkItem]:
    rows = read_model.quarantine_for_run(session, run)
    if not rows:
        return []
    return [
        WorkItem(
            key="data:quarantine",
            kind="data_quality",
            title=f"Recover {len(rows)} row{'s' if len(rows) != 1 else ''} Relay could not read",
            summary=(
                "These lines are in the export but could not be parsed, so whatever they contain "
                "is missing from the migrated books. They are kept exactly as received."
            ),
            judgement="What the row was meant to say, confirmed against the source system.",
            amount=None,
            count=len(rows),
            action_label="Review rows",
            target_kind="import",
            target_id=str(rows[0].import_id),
            evidence=(),
            blocks=(),
            detail={"import_id": str(rows[0].import_id)},
        )
    ]


def _issue_by_subject(session: Session, migration_id: uuid.UUID) -> dict[str, Issue]:
    """Open issues indexed by each subject they name, so an item can find its finding."""
    index: dict[str, Issue] = {}
    for issue in session.scalars(
        select(Issue)
        .where(Issue.migration_id == migration_id, Issue.status.in_(_OPEN))
        .order_by(Issue.key)
    ):
        for subject in issue.subjects:
            index.setdefault(str(subject), issue)
    return index


def work_items(
    session: Session, migration: Migration, *, user_id: uuid.UUID | None, role: str | None
) -> list[WorkItem]:
    """Everything waiting on a person, most consequential first."""
    currency = migration.functional_currency
    run = read_model.latest_succeeded_run(session, migration.id)
    items: list[WorkItem] = _approval_items(session, migration.id, user_id, role)
    if run is not None:
        stored = read_model.readiness_for_run(session, run.id)
        gates: Sequence[GateResultRow] = stored[1] if stored else []
        mapping, explained = _mapping_items(session, migration.id, run, gates, currency)
        entities = _entity_items(session, migration.id, run, gates)
        data = _data_items(session, run)
        covered: set[str] = set()
        if any(item.kind == "account_mapping" for item in mapping):
            covered |= COVERED_BY_MAPPING_ITEM
        if entities:
            covered |= COVERED_BY_ENTITY_ITEM
        if data:
            covered |= COVERED_BY_DATA_ITEM
        items += mapping
        items += _reconciliation_items(session, run, gates, explained, currency)
        items += _issue_items(session, migration.id, run, gates, covered)
        items += entities
        items += data
        by_subject = _issue_by_subject(session, migration.id)
        items = [_with_issue(item, by_subject) for item in items]
    return sorted(items, key=lambda item: item.sort_key)


def _with_issue(item: WorkItem, by_subject: dict[str, Issue]) -> WorkItem:
    """Attach the finding an item is about: its own, or the one naming the record it concerns."""
    if item.issue_id is not None:
        return item
    if item.target_kind == "issue" and item.target_id:
        # The item already points at its finding; name it so an investigation can be run from here.
        issue = next((i for i in by_subject.values() if str(i.id) == item.target_id), None)
        return item if issue is None else replace(item, issue_id=issue.id, issue_key=issue.key)
    subject = None
    if item.kind == "account_mapping" and item.detail.get("legacy_account"):
        subject = f"acct:legacy:{item.detail['legacy_account']}"
    elif item.kind == "reconciliation" and item.detail.get("reconciliation"):
        subject = next(
            (s for s in by_subject if s.startswith(f"recon:{item.detail['reconciliation']}:")), None
        )
    issue = by_subject.get(subject) if subject else None
    return item if issue is None else replace(item, issue_id=issue.id, issue_key=issue.key)


def automation_summary(session: Session, run: PipelineRun | None) -> dict[str, Any]:
    """What the last verification did, counted from what it stored. Nothing here is estimated."""
    if run is None:
        return {}
    counts = dict(run.counts)
    rules = read_model.rule_runs(session, run.id)
    results = read_model.reconciliation_results(session, run.id)
    return {
        "run_sequence": run.sequence,
        "finished_at": run.finished_at,
        "duration_ms": dict(run.stage_timings).get("total_ms"),
        "staged_records": counts.get("staged_records"),
        "controls_evaluated": len(rules),
        "controls_errored": sum(1 for r in rules if r.status == "errored"),
        "reconciliations_performed": len(results),
        "reconciliations_with_differences": sum(1 for r in results if r.status == "discrepancy"),
        "findings": counts.get("findings"),
        "entity_candidates": counts.get("entity_candidates"),
        "issues_created": counts.get("issues_created"),
        "issues_resolved": counts.get("issues_verified_resolved"),
    }
