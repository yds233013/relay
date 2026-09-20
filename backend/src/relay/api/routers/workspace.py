"""Identity, migrations, datasets, readiness, issues, audit and entity candidates."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.api.deps import ActorDep, ClockDep, ReaderDep, SessionDep, SettingsDep
from relay.api.schemas import (
    AmountByNatureOut,
    AuditEventOut,
    AutomationSummaryOut,
    BlockerOut,
    CandidateOut,
    ChainVerificationOut,
    ChangeRequestSummaryOut,
    DatasetOut,
    EvidenceLinkOut,
    ExceptionOut,
    GateOut,
    IssueDetailOut,
    IssueOut,
    LineageOut,
    MigrationOut,
    MigrationSummaryOut,
    OverviewOut,
    Page,
    PolicyOut,
    ReadinessOut,
    SignoffOut,
    StageOut,
    UserOut,
    WaiverOut,
    WorkItemOut,
    WorkQueueOut,
    amount_text,
)
from relay.audit import read_model as audit_read
from relay.audit import service as audit
from relay.audit.models import AuditEvent
from relay.changes import kinds as governance_read
from relay.core.currency import Currency
from relay.engine.readiness import WAIVABLE
from relay.identity import service as identity
from relay.investigations.models import Finding as AIFinding
from relay.investigations.models import Investigation
from relay.issues import read_model as issues_read
from relay.issues.models import Issue
from relay.pipeline import overview as overview_read
from relay.pipeline import read_model as runs_read
from relay.pipeline import service as pipeline
from relay.pipeline import work_queue
from relay.pipeline.models import RuleExceptionRow
from relay.pipeline.read_model import ResourceNotFoundError
from relay.workspace import read_model as workspace_read
from relay.workspace import service as workspace
from relay.workspace.models import Migration

router = APIRouter(prefix="/api/v1", tags=["workspace"])


@router.get("/me")
def me(actor: ActorDep, session: SessionDep) -> UserOut:
    user = identity.get_user(session, actor.user_id) if actor.user_id else None
    if user is None:
        raise identity.AuthenticationRequiredError("sign-in is required")
    return UserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)


@router.get("/dev/users")
def dev_users(session: SessionDep, settings: SettingsDep) -> list[UserOut]:
    """Local and test only: the seeded users a developer can act as."""
    if not settings.dev_identity_active:
        raise ResourceNotFoundError("not available")
    return [
        UserOut(id=u.id, email=u.email, display_name=u.display_name, role=u.role)
        for u in identity.list_active_users(session)
    ]


def migration_out(migration: Migration, company_name: str) -> MigrationOut:
    return MigrationOut(
        id=migration.id,
        name=migration.name,
        company_name=company_name,
        status=migration.status,
        functional_currency=migration.functional_currency.code,
        opening_balance_date=migration.opening_balance_date,
        history_start_date=migration.history_start_date,
        cutover_date=migration.cutover_date,
        go_live_date=migration.go_live_date,
        bank_clearing_window_days=migration.bank_clearing_window_days,
    )


@router.get("/migrations")
def list_migrations(
    _actor: ReaderDep, session: SessionDep, clock: ClockDep
) -> list[MigrationSummaryOut]:
    """Portfolio: each migration's readiness on its latest run (stale when inputs changed)."""
    today = clock.now().date()
    rows = []
    for migration, company in workspace_read.migrations(session):
        summary = overview_read.portfolio_row(session, migration, today)
        rows.append(
            MigrationSummaryOut(
                **migration_out(migration, company.name).model_dump(),
                overall=summary["overall"],
                failing_gate_count=summary["failing_gate_count"],
                gate_count=summary["gate_count"],
                unresolved_exposure=amount_text(
                    summary["unresolved_exposure"], migration.functional_currency
                ),
                days_to_go_live=summary["days_to_go_live"],
            )
        )
    return rows


@router.get("/migrations/{migration_id}")
def get_migration(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> MigrationOut:
    found = workspace_read.migration_with_company(session, migration_id)
    if found is None:
        raise ResourceNotFoundError("migration not found")
    migration, company = found
    return migration_out(migration, company.name)


@router.get("/migrations/{migration_id}/overview")
def get_overview(migration_id: uuid.UUID, actor: ReaderDep, session: SessionDep) -> OverviewOut:
    """What is blocking this migration from going live, with links to the evidence."""
    migration = workspace.get_migration(session, migration_id)
    found = workspace_read.migration_with_company(session, migration_id)
    company_name = found[1].name if found else ""
    currency = migration.functional_currency
    data = overview_read.overview(session, migration, user_id=actor.user_id, role=actor.role)
    queue = work_queue.work_items(session, migration, user_id=actor.user_id, role=actor.role)
    run = data["run"]
    names = identity.display_names(
        session,
        {
            issue.owner_user_id
            for issue in [*data["top_issues"], *data["queue"]["issues"]]
            if issue.owner_user_id
        },
    )
    return OverviewOut(
        migration=migration_out(migration, company_name),
        run_id=run.id if run else None,
        run_sequence=run.sequence if run else None,
        run_is_current=data["run_is_current"],
        overall=data["overall"],
        gate_count=data["gate_count"],
        failing_gate_count=data["failing_gate_count"],
        blockers=[
            BlockerOut(
                gate_id=b["gate_id"],
                title=b["title"],
                summary=b["summary"],
                observed=b["observed"],
                evidence_count=b["evidence_count"],
                evidence=[EvidenceLinkOut(**link) for link in b["evidence"]],
            )
            for b in data["blockers"]
        ],
        unresolved_exposure=amount_text(data["unresolved_exposure"], currency),
        open_issue_count=data["open_issue_count"] or 0,
        open_issue_amounts_by_nature=[
            AmountByNatureOut(nature=nature, amount=amount_text(amount, currency) or "0")
            for nature, amount in sorted(data["open_issue_amounts_by_nature"].items())
        ],
        top_issues=[issue_out(i, currency, names) for i in data["top_issues"]],
        my_issues=[issue_out(i, currency, names) for i in data["queue"]["issues"]],
        my_approvals=[
            ChangeRequestSummaryOut(id=c.id, key=c.key, kind=c.kind, title=c.title, status=c.status)
            for c in data["queue"]["approvals"]
        ],
        stages=[StageOut(**stage) for stage in data["stages"]],
        recent_activity=[audit_event_out(e) for e in data["recent_activity"]],
        currency=currency.code,
        work_items=[
            work_item_out(i, currency, _latest_investigations(session, queue)) for i in queue
        ],
        automation=AutomationSummaryOut(**work_queue.automation_summary(session, run)),
    )


def _latest_investigations(
    session: Session, items: Sequence[work_queue.WorkItem]
) -> dict[uuid.UUID, dict[str, Any]]:
    """The latest investigation of each work item's finding.

    Composed here rather than in the work queue itself: `relay.pipeline` sits below the AI layer
    and must not import it (enforced by the import contracts). The API is the one place that may
    see both.
    """
    issue_ids = {item.issue_id for item in items if item.issue_id is not None}
    if not issue_ids:
        return {}
    latest: dict[uuid.UUID, Investigation] = {}
    for row in session.scalars(
        select(Investigation)
        .where(Investigation.issue_id.in_(issue_ids))
        .order_by(Investigation.created_at)
    ):
        if row.issue_id is not None:
            latest[row.issue_id] = row  # ascending, so the last one written wins
    counts: dict[uuid.UUID, int] = {}
    for investigation_id, count in session.execute(
        select(AIFinding.investigation_id, func.count())
        .where(AIFinding.investigation_id.in_([row.id for row in latest.values()]))
        .group_by(AIFinding.investigation_id)
    ):
        counts[investigation_id] = int(count)
    return {
        issue_id: {
            "id": str(row.id),
            "status": row.status,
            "finding_count": counts.get(row.id, 0),
        }
        for issue_id, row in latest.items()
    }


def work_item_out(
    item: work_queue.WorkItem,
    currency: Currency,
    investigations_by_issue: Mapping[uuid.UUID, dict[str, Any]] | None = None,
) -> WorkItemOut:
    return WorkItemOut(
        key=item.key,
        kind=item.kind,
        title=item.title,
        summary=item.summary,
        judgement=item.judgement,
        amount=amount_text(item.amount, currency),
        currency=currency.code,
        count=item.count,
        action_label=item.action_label,
        target_kind=item.target_kind,
        target_id=item.target_id,
        issue_id=item.issue_id,
        issue_key=item.issue_key,
        investigation=(investigations_by_issue or {}).get(item.issue_id)
        if item.issue_id is not None
        else None,
        blocks=list(item.blocks),
        detail=item.detail,
    )


@router.get("/migrations/{migration_id}/work-queue")
def get_work_queue(migration_id: uuid.UUID, actor: ReaderDep, session: SessionDep) -> WorkQueueOut:
    """Everything still waiting on a person, grouped into decisions rather than findings."""
    migration = workspace.get_migration(session, migration_id)
    currency = migration.functional_currency
    items = work_queue.work_items(session, migration, user_id=actor.user_id, role=actor.role)
    found = _latest_investigations(session, items)
    run = runs_read.latest_succeeded_run(session, migration_id)
    return WorkQueueOut(
        items=[work_item_out(i, currency, found) for i in items],
        automation=AutomationSummaryOut(**work_queue.automation_summary(session, run)),
    )


@router.get("/migrations/{migration_id}/datasets")
def list_datasets(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[DatasetOut]:
    workspace.get_migration(session, migration_id)
    return [
        DatasetOut(
            id=d.id,
            dataset_type=d.dataset_type,
            name=d.name,
            as_of_date=d.as_of_date,
            is_required=d.is_required,
            active_import_id=d.active_import_id,
            version=d.version,
        )
        for d in workspace.datasets_for(session, migration_id)
    ]


@router.get("/migrations/{migration_id}/policy")
def current_policy(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> PolicyOut:
    """The policy in effect; changing it is a ``policy_change`` change request."""
    workspace.get_migration(session, migration_id)
    row = workspace.current_policy(session, migration_id)
    return PolicyOut(
        version=row.version,
        policy=row.policy,
        change_request_id=row.change_request_id,
        created_at=row.created_at,
    )


@router.get("/migrations/{migration_id}/readiness")
def readiness(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> ReadinessOut:
    """Readiness of the latest successful run, marked stale when inputs have changed since."""
    migration = workspace.get_migration(session, migration_id)
    currency = migration.functional_currency
    run = runs_read.latest_succeeded_run(session, migration_id)
    stored = runs_read.readiness_for_run(session, run.id) if run else None
    current_fingerprint = pipeline.current_fingerprint(session, migration_id).fingerprint
    waivers = [
        WaiverOut(
            id=w.id,
            gate_id=w.gate_id,
            status=w.status,
            reason=w.reason,
            scope={str(k): str(v) for k, v in w.scope.items()},
            run_id=w.run_id,
            change_request_id=w.change_request_id,
            created_at=w.created_at,
        )
        for w in governance_read.waivers(session, migration_id)
    ]
    signoffs = [
        SignoffOut(
            id=s.id,
            run_id=s.run_id,
            run_fingerprint=s.run_fingerprint,
            status=s.status,
            change_request_id=s.change_request_id,
            invalidated_by_fingerprint=s.invalidated_by_fingerprint,
            created_at=s.created_at,
        )
        for s in governance_read.signoffs(session, migration_id)
    ]
    if run is None or stored is None:
        return ReadinessOut(
            run_id=None,
            current_fingerprint=current_fingerprint,
            run_is_current=False,
            overall="stale",
            unresolved_exposure=None,
            currency=currency.code,
            gates=[],
            migration_status=migration.status,
            waivers=waivers,
            signoffs=signoffs,
        )
    evaluation, gates = stored
    current = current_fingerprint == run.fingerprint
    return ReadinessOut(
        run_id=run.id,
        run_sequence=run.sequence,
        run_fingerprint=run.fingerprint,
        current_fingerprint=current_fingerprint,
        run_is_current=current,
        overall=evaluation.overall if current else "stale",
        unresolved_exposure=amount_text(evaluation.unresolved_exposure, currency),
        currency=currency.code,
        migration_status=migration.status,
        evaluation_sequence=evaluation.sequence,
        evaluated_at=evaluation.evaluated_at,
        waivers=waivers,
        signoffs=signoffs,
        gates=[
            GateOut(
                gate_id=g.gate_id,
                title=g.title,
                status=g.status,
                observed=g.observed,
                threshold=g.threshold,
                summary=g.summary,
                evidence=list(g.evidence),
                evidence_links=[
                    EvidenceLinkOut(**link)
                    for link in overview_read.resolve_evidence(
                        session, migration_id, run.id, list(g.evidence)
                    )
                ],
                waiver_id=g.waiver_id,
                waivable=g.gate_id in WAIVABLE,
                scope={str(k): str(v) for k, v in g.scope.items()} if g.scope else None,
            )
            for g in gates
        ],
    )


def audit_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        migration_seq=event.migration_seq,
        occurred_at=event.occurred_at,
        actor_type=event.actor_type,
        actor_user_id=event.actor_user_id,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        before=event.before,
        after=event.after,
        reason=event.reason,
        change_request_id=event.change_request_id,
        request_id=event.request_id,
        hash=event.hash,
    )


def issue_out(
    issue: Issue, currency: Currency, names: dict[uuid.UUID, str] | None = None
) -> IssueOut:
    return IssueOut(
        id=issue.id,
        key=issue.key,
        fingerprint=issue.fingerprint,
        source=issue.source,
        rule_or_recon_id=issue.rule_or_recon_id,
        category=issue.category,
        nature=issue.nature,
        severity=issue.severity,
        title=issue.title,
        subjects=list(issue.subjects),
        status=issue.status,
        owner_user_id=issue.owner_user_id,
        owner_name=(names or {}).get(issue.owner_user_id) if issue.owner_user_id else None,
        amount_at_risk=amount_text(issue.amount_at_risk, currency),
        currency=currency.code,
        first_seen_run_id=issue.first_seen_run_id,
        last_seen_run_id=issue.last_seen_run_id,
        verified_absent_run_id=issue.verified_absent_run_id,
        version=issue.version,
    )


def exception_out(row: RuleExceptionRow, currency: Currency) -> ExceptionOut:
    return ExceptionOut(
        id=row.id,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        fingerprint=row.fingerprint,
        severity=row.severity,
        nature=row.nature,
        category=row.category,
        subjects=list(row.subjects),
        message=row.message,
        expected=row.expected,
        observed=row.observed,
        amount_at_risk=amount_text(row.amount_at_risk, currency),
        currency=currency.code,
        details=row.details,
        lineage=[LineageOut(**item) for item in row.lineage],
    )


@router.get("/migrations/{migration_id}/issues")
def list_issues(
    migration_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    status: Annotated[str | None, Query(max_length=32)] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
    nature: Annotated[str | None, Query(max_length=32)] = None,
    fingerprint: Annotated[str | None, Query(max_length=64)] = None,
    owner: Annotated[uuid.UUID | None, Query()] = None,
    rule: Annotated[str | None, Query(max_length=64)] = None,
    order: Annotated[Literal["key", "amount"], Query()] = "key",
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[IssueOut]:
    migration = workspace.get_migration(session, migration_id)
    items = issues_read.issues_for(
        session,
        migration_id,
        status=status,
        severity=severity,
        nature=nature,
        fingerprint=fingerprint,
        owner=owner,
        rule=rule,
        order=order,
        offset=cursor,
        limit=limit,
    )
    names = identity.display_names(session, {i.owner_user_id for i in items if i.owner_user_id})
    return Page(
        items=[issue_out(i, migration.functional_currency, names) for i in items],
        next_cursor=str(cursor + limit) if len(items) == limit else None,
    )


@router.get("/issues/{issue_id}")
def get_issue(issue_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> IssueDetailOut:
    issue = issues_read.get_issue(session, issue_id)
    currency = workspace.get_migration(session, issue.migration_id).functional_currency
    latest = runs_read.latest_exception(session, issue)
    return IssueDetailOut(
        **issue_out(issue, currency).model_dump(),
        latest_exception=exception_out(latest, currency) if latest else None,
    )


@router.get("/migrations/{migration_id}/audit-events")
def list_audit_events(
    migration_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[uuid.UUID | None, Query()] = None,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[AuditEventOut]:
    workspace.get_migration(session, migration_id)
    events = audit_read.events(
        session,
        migration_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        after_seq=cursor,
        limit=limit,
    )
    return Page(
        items=[audit_event_out(e) for e in events],
        next_cursor=str(events[-1].migration_seq) if len(events) == limit else None,
    )


@router.get("/migrations/{migration_id}/audit-events/verify")
def verify_audit(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> ChainVerificationOut:
    workspace.get_migration(session, migration_id)
    result = audit.verify_chain(session, migration_id)
    return ChainVerificationOut(
        valid=result.valid,
        events_checked=result.events_checked,
        first_broken_seq=result.first_broken_seq,
        problem=result.problem,
    )


@router.get("/migrations/{migration_id}/entity-candidates")
def list_candidates(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[CandidateOut]:
    workspace.get_migration(session, migration_id)
    run = runs_read.latest_succeeded_run(session, migration_id)
    if run is None:
        return []
    return [
        CandidateOut(
            id=c.id,
            party_type=c.party_type,
            left_code=c.left_code,
            right_code=c.right_code,
            score=str(c.score),
            strong=c.strong,
            status=c.status,
            features=c.features,
        )
        for c in runs_read.candidates(session, run.id)
    ]
