"""AI investigations: status, start, transcript, findings, review, draft change request."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.api.deps import ClockDep, ReaderDep, SessionDep, SettingsDep, require
from relay.api.routers.governance import change_request_out
from relay.api.schemas import (
    AIStatusOut,
    ChangeRequestOut,
    FindingOut,
    FindingReviewIn,
    InvestigationDetailOut,
    InvestigationIn,
    InvestigationOut,
    InvestigationStepOut,
)
from relay.changes.models import ChangeRequest
from relay.core.actor import Actor
from relay.core.errors import NotFoundError
from relay.identity.permissions import Permission
from relay.investigations import service as investigations
from relay.investigations.models import Finding, Investigation, InvestigationStep
from relay.workspace import service as workspace

router = APIRouter(prefix="/api/v1", tags=["ai"])

InvestigatorDep = Annotated[Actor, Depends(require(Permission.MANAGE_ISSUES))]
DrafterDep = Annotated[Actor, Depends(require(Permission.DRAFT_CHANGE_REQUEST))]


def investigation_out(row: Investigation) -> InvestigationOut:
    return InvestigationOut(
        id=row.id,
        migration_id=row.migration_id,
        issue_id=row.issue_id,
        run_id=row.run_id,
        question=row.question,
        status=row.status,
        provider=row.provider,
        model=row.model,
        prompt_version=row.prompt_version,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        tool_call_count=row.tool_call_count,
        created_at=row.created_at,
        finished_at=row.finished_at,
        error=row.error,
    )


def finding_out(session: Session, row: Finding) -> FindingOut:
    drafted = session.scalars(
        select(ChangeRequest.id).where(ChangeRequest.origin_finding_id == row.id)
    ).first()
    return FindingOut(
        id=row.id,
        hypothesis=row.hypothesis,
        evidence=list(row.evidence),
        affected_record_refs=[str(r) for r in row.affected_record_refs],
        confidence=row.confidence,
        suggested_action=dict(row.suggested_action),
        open_questions=[str(q) for q in row.open_questions],
        requires_approval=row.requires_approval,
        verification_status=row.verification_status,
        verification_report=dict(row.verification_report),
        review_status=row.review_status,
        review_comment=row.review_comment,
        drafted_change_request_id=drafted,
        draftable=drafted is None and investigations.promotion_problem(row) is None,
    )


@router.get("/ai/status")
def ai_status(
    _actor: ReaderDep, session: SessionDep, settings: SettingsDep, migration_id: uuid.UUID
) -> AIStatusOut:
    migration = workspace.get_migration(session, migration_id)
    current = investigations.status(settings, migration.ai_enabled)
    return AIStatusOut(
        provider=current.provider,
        configured=current.configured,
        migration_enabled=current.migration_enabled,
        available=current.available,
    )


@router.post("/migrations/{migration_id}/investigations", status_code=status.HTTP_202_ACCEPTED)
def start_investigation(
    migration_id: uuid.UUID,
    body: InvestigationIn,
    actor: InvestigatorDep,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> InvestigationOut:
    model = settings.ai_model if settings.ai_provider == "anthropic" else settings.ai_provider
    row = investigations.start(
        session,
        actor=actor,
        migration_id=migration_id,
        question=body.question,
        issue_id=body.issue_id,
        settings=settings,
        model=model,
        clock=clock,
    )
    return investigation_out(row)


@router.get("/migrations/{migration_id}/investigations")
def list_investigations(
    migration_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    issue_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[InvestigationOut]:
    workspace.get_migration(session, migration_id)
    query = select(Investigation).where(Investigation.migration_id == migration_id)
    if issue_id:
        query = query.where(Investigation.issue_id == issue_id)
    rows = session.scalars(query.order_by(Investigation.created_at.desc()).limit(limit))
    return [investigation_out(r) for r in rows]


@router.get("/investigations/{investigation_id}")
def get_investigation(
    investigation_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> InvestigationDetailOut:
    row = session.get(Investigation, investigation_id)
    if row is None:
        raise NotFoundError("investigation not found")
    steps = session.scalars(
        select(InvestigationStep)
        .where(InvestigationStep.investigation_id == row.id)
        .order_by(InvestigationStep.seq)
    )
    findings = session.scalars(
        select(Finding).where(Finding.investigation_id == row.id).order_by(Finding.created_at)
    )
    return InvestigationDetailOut(
        investigation=investigation_out(row),
        steps=[
            InvestigationStepOut(
                seq=s.seq,
                type=s.type,
                tool_name=s.tool_name,
                arguments=s.arguments,
                result=s.result,
                truncated=s.truncated,
                is_error=s.is_error,
                text=s.text,
                latency_ms=s.latency_ms,
            )
            for s in steps
        ],
        findings=[finding_out(session, f) for f in findings],
    )


@router.post("/findings/{finding_id}/accept")
def accept_finding(
    finding_id: uuid.UUID,
    body: FindingReviewIn,
    actor: InvestigatorDep,
    session: SessionDep,
    clock: ClockDep,
) -> FindingOut:
    finding = investigations.get_finding(session, finding_id)
    investigations.review_finding(
        session, actor=actor, finding=finding, accept=True, comment=body.comment, clock=clock
    )
    return finding_out(session, finding)


@router.post("/findings/{finding_id}/dismiss")
def dismiss_finding(
    finding_id: uuid.UUID,
    body: FindingReviewIn,
    actor: InvestigatorDep,
    session: SessionDep,
    clock: ClockDep,
) -> FindingOut:
    finding = investigations.get_finding(session, finding_id)
    investigations.review_finding(
        session, actor=actor, finding=finding, accept=False, comment=body.comment, clock=clock
    )
    return finding_out(session, finding)


@router.post("/findings/{finding_id}/draft-change-request", status_code=status.HTTP_201_CREATED)
def draft_from_finding(
    finding_id: uuid.UUID, actor: DrafterDep, session: SessionDep, clock: ClockDep
) -> ChangeRequestOut:
    finding = investigations.get_finding(session, finding_id)
    change = investigations.draft_change_request(session, actor=actor, finding=finding, clock=clock)
    return change_request_out(session, change)
