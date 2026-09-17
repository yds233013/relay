"""Migration overview, portfolio summary, evidence links and run diffs (product-spec.md §8.2).

Every figure is computed here on the server from persisted records, and every summary carries the
references a client needs to link to its evidence. Clients never add or compare amounts.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.audit.models import AuditEvent
from relay.changes.models import Approval, ChangeRequest, ChangeRequestStatus
from relay.imports.models import Import, ImportStatus
from relay.issues.models import OPEN_STATUSES, Issue
from relay.mapping_sets.models import ColumnMappingSet, MappingSetStatus
from relay.pipeline import read_model
from relay.pipeline.inputs import load_configuration
from relay.pipeline.models import (
    EntityCandidateRow,
    PipelineRun,
    ReconciliationLineRow,
    ReconciliationResultRow,
    RuleExceptionRow,
)
from relay.workspace.models import Dataset, Migration

_FINGERPRINT: Final = re.compile(r"[0-9a-f]{64}")
_OPEN: Final = [status.value for status in OPEN_STATUSES]


def resolve_evidence(
    session: Session, migration_id: uuid.UUID, run_id: uuid.UUID, evidence: list[str]
) -> list[dict[str, Any]]:
    """Turn gate evidence strings into typed links (issues, reconciliation lines, candidates)."""
    fingerprints = [e for e in evidence if _FINGERPRINT.fullmatch(e)]
    issues = (
        {
            issue.fingerprint: issue
            for issue in session.scalars(
                select(Issue).where(
                    Issue.migration_id == migration_id, Issue.fingerprint.in_(fingerprints)
                )
            )
        }
        if fingerprints
        else {}
    )
    # Only the cited lines: a gate's evidence names a handful, and a run can hold hundreds of
    # thousands of them.
    wanted = {item: _line_key(item) for item in evidence}
    keys = {key for key in wanted.values() if key}
    lines = (
        {
            line.grain_key: line
            for line in session.scalars(
                select(ReconciliationLineRow)
                .join(
                    ReconciliationResultRow,
                    ReconciliationLineRow.result_id == ReconciliationResultRow.id,
                )
                .where(
                    ReconciliationResultRow.run_id == run_id,
                    ReconciliationLineRow.grain_key.in_(keys),
                )
            )
        }
        if keys
        else {}
    )
    links: list[dict[str, Any]] = []
    for item in evidence:
        if item in issues:
            issue = issues[item]
            links.append(
                {"kind": "issue", "label": f"{issue.key} {issue.title}", "issue_id": issue.id}
            )
            continue
        key = wanted[item]
        if key:
            line = lines.get(key)
            links.append(
                {
                    "kind": "reconciliation_line" if line else "text",
                    "label": key.removeprefix("recon:"),
                    "line_id": line.id if line else None,
                }
            )
            continue
        candidate = re.fullmatch(r"(customer|vendor):([^:]+):([^:]+)", item)
        if candidate:
            links.append({"kind": "entity_candidate", "label": item})
            continue
        links.append({"kind": "text", "label": item})
    return links


def _line_key(item: str) -> str | None:
    """The reconciliation line an evidence string names, if it names one."""
    recon = re.fullmatch(r"(R\d[a-z]?):(\{.*\})", item)
    if recon is None:
        return None
    grain = _grain_from_repr(recon.group(2))
    return "recon:" + recon.group(1) + ":" + ",".join(f"{k}={v}" for k, v in grain.items())


def _grain_from_repr(text: str) -> dict[str, str]:
    """Parse the ``{'account': '1200', ...}`` form gate evidence uses for reconciliation lines."""
    return dict(re.findall(r"'([^']*)': '([^']*)'", text))


def open_issue_totals(session: Session, migration_id: uuid.UUID) -> dict[str, Decimal]:
    rows = session.execute(
        select(Issue.nature, func.coalesce(func.sum(Issue.amount_at_risk), 0))
        .where(Issue.migration_id == migration_id, Issue.status.in_(_OPEN))
        .group_by(Issue.nature)
    ).all()
    return {nature: Decimal(total) for nature, total in rows}


def top_open_issues(session: Session, migration_id: uuid.UUID, limit: int = 5) -> list[Issue]:
    return list(
        session.scalars(
            select(Issue)
            .where(
                Issue.migration_id == migration_id,
                Issue.status.in_(_OPEN),
                Issue.amount_at_risk.is_not(None),
            )
            .order_by(Issue.amount_at_risk.desc(), Issue.key)
            .limit(limit)
        )
    )


def _stages(
    session: Session, migration: Migration, run: PipelineRun | None
) -> list[dict[str, Any]]:
    datasets = list(session.scalars(select(Dataset).where(Dataset.migration_id == migration.id)))
    active_ids = [d.active_import_id for d in datasets if d.active_import_id]
    imports = (
        list(session.scalars(select(Import).where(Import.id.in_(active_ids)))) if active_ids else []
    )
    parsed = [i for i in imports if i.status == ImportStatus.PARSED.value]
    approved = session.scalar(
        select(func.count())
        .select_from(ColumnMappingSet)
        .where(
            ColumnMappingSet.dataset_id.in_([d.id for d in datasets]),
            ColumnMappingSet.status == MappingSetStatus.APPROVED.value,
        )
    )
    stages: list[dict[str, Any]] = [
        {
            "stage": "import",
            "status": "complete" if len(parsed) == len(datasets) and datasets else "incomplete",
            "detail": f"{len(parsed)} of {len(datasets)} datasets imported",
        },
        {
            "stage": "profile",
            "status": "complete" if parsed else "incomplete",
            "detail": (
                f"{sum(i.row_count or 0 for i in parsed)} rows, "
                f"{sum(i.quarantined_count or 0 for i in parsed)} quarantined"
            ),
        },
        {
            "stage": "map",
            "status": "complete" if approved == len(datasets) and datasets else "incomplete",
            "detail": f"{approved} of {len(datasets)} column mappings approved",
        },
    ]
    if run is None:
        stages.extend(
            {"stage": name, "status": "not_run", "detail": "no successful run"}
            for name in ("normalize", "validate", "reconcile")
        )
        return stages
    counts = run.counts
    by_severity = counts.get("findings_by_severity", {})
    normalization = session.scalar(
        select(func.count())
        .select_from(RuleExceptionRow)
        .where(RuleExceptionRow.run_id == run.id, RuleExceptionRow.rule_id.like("NORM.%"))
    )
    results = read_model.reconciliation_results(session, run.id)
    stages.extend(
        [
            {
                "stage": "normalize",
                "status": "complete",
                "detail": (
                    f"{counts.get('staged_records', 0)} staged records, "
                    f"{normalization} normalization findings"
                ),
            },
            {
                "stage": "validate",
                "status": "complete",
                "detail": ", ".join(
                    f"{by_severity.get(s, 0)} {s}" for s in ("critical", "high", "medium", "low")
                ),
            },
            {
                "stage": "reconcile",
                "status": "complete",
                "detail": (
                    f"{sum(1 for r in results if r.status == 'discrepancy')} of {len(results)} "
                    "reconciliations with discrepancies"
                ),
            },
        ]
    )
    return stages


def _queue(
    session: Session, migration_id: uuid.UUID, user_id: uuid.UUID | None, role: str | None
) -> dict[str, Any]:
    if user_id is None:
        return {"issues": [], "approvals": []}
    owned = list(
        session.scalars(
            select(Issue)
            .where(
                Issue.migration_id == migration_id,
                Issue.owner_user_id == user_id,
                Issue.status.in_(_OPEN),
            )
            .order_by(Issue.key)
            .limit(20)
        )
    )
    waiting = []
    for change in session.scalars(
        select(ChangeRequest).where(
            ChangeRequest.migration_id == migration_id,
            ChangeRequest.status == ChangeRequestStatus.SUBMITTED.value,
            ChangeRequest.requested_by != user_id,
        )
    ):
        decided = session.scalars(
            select(Approval).where(Approval.change_request_id == change.id)
        ).all()
        if any(a.reviewer_user_id == user_id for a in decided):
            continue
        satisfied = {a.satisfies_requirement_index for a in decided if a.decision == "approve"}
        if any(
            i not in satisfied and r.get("role") == role
            for i, r in enumerate(change.required_approvals)
        ):
            waiting.append(change)
    return {"issues": owned, "approvals": waiting}


def overview(
    session: Session, migration: Migration, *, user_id: uuid.UUID | None, role: str | None
) -> dict[str, Any]:
    run = read_model.latest_succeeded_run(session, migration.id)
    stored = read_model.readiness_for_run(session, run.id) if run else None
    current = bool(run and load_configuration(session, migration.id).fingerprint == run.fingerprint)
    gates = stored[1] if stored else []
    evaluation = stored[0] if stored else None
    failing = [g for g in gates if g.status == "fail"]
    blockers = [
        {
            "gate_id": gate.gate_id,
            "title": gate.title,
            "summary": gate.summary,
            "observed": gate.observed,
            "evidence_count": len(gate.evidence),
            "evidence": resolve_evidence(session, migration.id, run.id, list(gate.evidence)[:5])
            if run
            else [],
        }
        for gate in failing
    ]
    recent = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.migration_id == migration.id)
            .order_by(AuditEvent.migration_seq.desc())
            .limit(10)
        )
    )
    if evaluation is None or not current:
        overall = "stale"
    else:
        overall = "ready" if evaluation.overall == "ready" else "not_ready"
    return {
        "run": run,
        "run_is_current": current,
        "overall": overall,
        "gate_count": len(gates),
        "failing_gate_count": len(failing),
        "blockers": blockers,
        "unresolved_exposure": evaluation.unresolved_exposure if evaluation is not None else None,
        "open_issue_amounts_by_nature": open_issue_totals(session, migration.id),
        "open_issue_count": session.scalar(
            select(func.count())
            .select_from(Issue)
            .where(Issue.migration_id == migration.id, Issue.status.in_(_OPEN))
        ),
        "top_issues": top_open_issues(session, migration.id),
        "queue": _queue(session, migration.id, user_id, role),
        "stages": _stages(session, migration, run),
        "recent_activity": recent,
    }


def portfolio_row(session: Session, migration: Migration, today: date) -> dict[str, Any]:
    run = read_model.latest_succeeded_run(session, migration.id)
    stored = read_model.readiness_for_run(session, run.id) if run else None
    current = bool(run and load_configuration(session, migration.id).fingerprint == run.fingerprint)
    failing = [g for g in stored[1] if g.status == "fail"] if stored else []
    return {
        "overall": (stored[0].overall if stored and current else "stale"),
        "failing_gate_count": len(failing) if stored else None,
        "gate_count": len(stored[1]) if stored else None,
        "unresolved_exposure": stored[0].unresolved_exposure if stored else None,
        "days_to_go_live": (migration.go_live_date - today).days,
    }


def run_diff(session: Session, base_id: uuid.UUID, other_id: uuid.UUID) -> dict[str, Any]:
    base = read_model.get_run(session, base_id)
    other = read_model.get_run(session, other_id)
    if base.migration_id != other.migration_id:
        raise read_model.ResourceNotFoundError("runs belong to different migrations")
    keys = sorted(set(base.fingerprint_components) | set(other.fingerprint_components))
    changed_components = [
        k for k in keys if base.fingerprint_components.get(k) != other.fingerprint_components.get(k)
    ]

    def findings(run_id: uuid.UUID) -> dict[str, tuple[str, str]]:
        return {
            fp: (rule, message)
            for fp, rule, message in session.execute(
                select(
                    RuleExceptionRow.fingerprint, RuleExceptionRow.rule_id, RuleExceptionRow.message
                ).where(RuleExceptionRow.run_id == run_id)
            ).tuples()
        }

    def statuses(run_id: uuid.UUID) -> dict[str, str]:
        return {r.recon_id: r.status for r in read_model.reconciliation_results(session, run_id)}

    def gate_statuses(run_id: uuid.UUID) -> dict[str, str]:
        stored = read_model.readiness_for_run(session, run_id)
        return {g.gate_id: g.status for g in stored[1]} if stored else {}

    before, after = findings(base.id), findings(other.id)
    recon_before, recon_after = statuses(base.id), statuses(other.id)
    gates_before, gates_after = gate_statuses(base.id), gate_statuses(other.id)
    candidates_before = session.scalar(
        select(func.count())
        .select_from(EntityCandidateRow)
        .where(EntityCandidateRow.run_id == base.id)
    )
    candidates_after = session.scalar(
        select(func.count())
        .select_from(EntityCandidateRow)
        .where(EntityCandidateRow.run_id == other.id)
    )
    return {
        "base_run_id": base.id,
        "other_run_id": other.id,
        "changed_fingerprint_components": changed_components,
        "findings_added": [
            {"fingerprint": fp, "rule_id": after[fp][0], "message": after[fp][1]}
            for fp in sorted(set(after) - set(before))
        ],
        "findings_removed": [
            {"fingerprint": fp, "rule_id": before[fp][0], "message": before[fp][1]}
            for fp in sorted(set(before) - set(after))
        ],
        "reconciliation_changes": [
            {"recon_id": k, "before": recon_before.get(k), "after": recon_after.get(k)}
            for k in sorted(set(recon_before) | set(recon_after))
            if recon_before.get(k) != recon_after.get(k)
        ],
        "gate_changes": [
            {"gate_id": k, "before": gates_before.get(k), "after": gates_after.get(k)}
            for k in sorted(set(gates_before) | set(gates_after), key=lambda g: int(g[1:]))
            if gates_before.get(k) != gates_after.get(k)
        ],
        "entity_candidates": {"before": candidates_before, "after": candidates_after},
    }
