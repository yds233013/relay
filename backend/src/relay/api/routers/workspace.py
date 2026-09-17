"""Identity, migrations, datasets, readiness, issues, audit and entity candidates."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from relay.api.deps import ActorDep, ReaderDep, SessionDep, SettingsDep
from relay.api.schemas import (
    AuditEventOut,
    CandidateOut,
    ChainVerificationOut,
    DatasetOut,
    ExceptionOut,
    GateOut,
    IssueDetailOut,
    IssueOut,
    LineageOut,
    MigrationOut,
    Page,
    ReadinessOut,
    UserOut,
    amount_text,
)
from relay.audit import read_model as audit_read
from relay.audit import service as audit
from relay.core.currency import Currency
from relay.identity import service as identity
from relay.issues import read_model as issues_read
from relay.issues.models import Issue
from relay.pipeline import read_model as runs_read
from relay.pipeline import service as pipeline
from relay.pipeline.models import RuleExceptionRow
from relay.pipeline.read_model import ResourceNotFoundError
from relay.workspace import read_model as workspace_read
from relay.workspace import service as workspace

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


@router.get("/migrations")
def list_migrations(_actor: ReaderDep, session: SessionDep) -> list[MigrationOut]:
    return [
        MigrationOut(
            id=m.id,
            name=m.name,
            company_name=c.name,
            status=m.status,
            functional_currency=m.functional_currency.code,
            opening_balance_date=m.opening_balance_date,
            history_start_date=m.history_start_date,
            cutover_date=m.cutover_date,
            go_live_date=m.go_live_date,
            bank_clearing_window_days=m.bank_clearing_window_days,
        )
        for m, c in workspace_read.migrations(session)
    ]


@router.get("/migrations/{migration_id}")
def get_migration(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> MigrationOut:
    for m, c in workspace_read.migrations(session):
        if m.id == migration_id:
            return MigrationOut(
                id=m.id,
                name=m.name,
                company_name=c.name,
                status=m.status,
                functional_currency=m.functional_currency.code,
                opening_balance_date=m.opening_balance_date,
                history_start_date=m.history_start_date,
                cutover_date=m.cutover_date,
                go_live_date=m.go_live_date,
                bank_clearing_window_days=m.bank_clearing_window_days,
            )
    raise ResourceNotFoundError("migration not found")


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


@router.get("/migrations/{migration_id}/readiness")
def readiness(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> ReadinessOut:
    """Readiness of the latest successful run, marked stale when inputs have changed since."""
    migration = workspace.get_migration(session, migration_id)
    currency = migration.functional_currency
    run = runs_read.latest_succeeded_run(session, migration_id)
    stored = runs_read.readiness_for_run(session, run.id) if run else None
    if run is None or stored is None:
        return ReadinessOut(
            run_id=None,
            run_is_current=False,
            overall="stale",
            unresolved_exposure=None,
            currency=currency.code,
            gates=[],
        )
    evaluation, gates = stored
    current = pipeline.current_fingerprint(session, migration_id).fingerprint == run.fingerprint
    return ReadinessOut(
        run_id=run.id,
        run_is_current=current,
        overall=evaluation.overall if current else "stale",
        unresolved_exposure=amount_text(evaluation.unresolved_exposure, currency),
        currency=currency.code,
        gates=[
            GateOut(
                gate_id=g.gate_id,
                title=g.title,
                status=g.status,
                observed=g.observed,
                threshold=g.threshold,
                summary=g.summary,
                evidence=list(g.evidence),
                waiver_id=g.waiver_id,
            )
            for g in gates
        ],
    )


def issue_out(issue: Issue, currency: Currency) -> IssueOut:
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
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[IssueOut]:
    migration = workspace.get_migration(session, migration_id)
    items = issues_read.issues_for(
        session, migration_id, status=status, severity=severity, after_id=cursor, limit=limit
    )
    return Page(
        items=[issue_out(i, migration.functional_currency) for i in items],
        next_cursor=str(items[-1].id) if len(items) == limit else None,
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
        items=[
            AuditEventOut(
                id=e.id,
                migration_seq=e.migration_seq,
                occurred_at=e.occurred_at,
                actor_type=e.actor_type,
                actor_user_id=e.actor_user_id,
                action=e.action,
                entity_type=e.entity_type,
                entity_id=e.entity_id,
                before=e.before,
                after=e.after,
                reason=e.reason,
                change_request_id=e.change_request_id,
                request_id=e.request_id,
                hash=e.hash,
            )
            for e in events
        ],
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
