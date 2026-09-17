"""Issue workflow, comments, links and history; entity decisions and dispositions."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.api.deps import ClockDep, ReaderDep, SessionDep, require
from relay.api.routers.workspace import audit_event_out, issue_out
from relay.api.schemas import (
    AuditEventOut,
    CandidateDetailOut,
    CandidateOut,
    CommentIn,
    CommentOut,
    DispositionOut,
    EntityDecisionOut,
    IssueLinkOut,
    IssueOut,
    IssueUpdateIn,
    ManualIssueIn,
    PartyOut,
    amount_text,
)
from relay.audit.models import AuditEvent
from relay.changes.models import Disposition, EntityDecision
from relay.core.actor import Actor
from relay.identity import service as identity
from relay.identity.permissions import Permission
from relay.issues import read_model as issues_read
from relay.issues import workflow
from relay.issues.models import Issue
from relay.pipeline import overrides as run_evidence
from relay.pipeline.models import EntityCandidateRow, PipelineRun
from relay.pipeline.read_model import ResourceNotFoundError
from relay.workspace import service as workspace

router = APIRouter(prefix="/api/v1", tags=["issues"])

IssueManagerDep = Annotated[Actor, Depends(require(Permission.MANAGE_ISSUES))]


def _name(session: Session, user_id: uuid.UUID) -> str:
    user = identity.get_user(session, user_id)
    return user.display_name if user else "Unknown user"


@router.patch("/issues/{issue_id}")
def update_issue(
    issue_id: uuid.UUID,
    body: IssueUpdateIn,
    actor: IssueManagerDep,
    session: SessionDep,
    clock: ClockDep,
) -> IssueOut:
    """Owner and workflow status. ``resolved`` is refused: only a current run resolves issues."""
    issue = workflow.get_issue(session, issue_id, for_update=True)
    owner: uuid.UUID | object | None = workflow.UNCHANGED
    if body.clear_owner:
        owner = None
    elif body.owner_user_id is not None:
        owner = body.owner_user_id
    workflow.update_issue(
        session,
        actor=actor,
        issue=issue,
        expected_version=body.version,
        owner_user_id=owner,
        status=body.status,
        note=body.note,
        clock=clock,
    )
    currency = workspace.get_migration(session, issue.migration_id).functional_currency
    return issue_out(issue, currency)


@router.post("/migrations/{migration_id}/issues", status_code=status.HTTP_201_CREATED)
def create_manual_issue(
    migration_id: uuid.UUID,
    body: ManualIssueIn,
    actor: IssueManagerDep,
    session: SessionDep,
    clock: ClockDep,
) -> IssueOut:
    migration = workspace.get_migration(session, migration_id)
    issue = workflow.create_manual_issue(
        session,
        actor=actor,
        migration=migration,
        title=body.title,
        severity=body.severity,
        category=body.category,
        nature=body.nature,
        description=body.description,
        clock=clock,
    )
    return issue_out(issue, migration.functional_currency)


@router.get("/issues/{issue_id}/comments")
def list_comments(issue_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> list[CommentOut]:
    workflow.get_issue(session, issue_id)
    return [
        CommentOut(
            id=c.id,
            author_user_id=c.author_user_id,
            author_name=_name(session, c.author_user_id),
            body=c.body,
            created_at=c.created_at,
        )
        for c in workflow.comments_for(session, issue_id)
    ]


@router.post("/issues/{issue_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    issue_id: uuid.UUID,
    body: CommentIn,
    actor: IssueManagerDep,
    session: SessionDep,
    clock: ClockDep,
) -> CommentOut:
    issue = workflow.get_issue(session, issue_id)
    comment = workflow.add_comment(session, actor=actor, issue=issue, body=body.body, clock=clock)
    return CommentOut(
        id=comment.id,
        author_user_id=comment.author_user_id,
        author_name=_name(session, comment.author_user_id),
        body=comment.body,
        created_at=comment.created_at,
    )


@router.get("/issues/{issue_id}/links")
def list_links(issue_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> list[IssueLinkOut]:
    workflow.get_issue(session, issue_id)
    links = []
    for link, other in issues_read.links_for(session, issue_id):
        links.append(
            IssueLinkOut(
                id=link.id,
                link_type=link.link_type,
                other_issue_id=other.id,
                other_issue_key=other.key,
                other_issue_title=other.title,
                other_issue_status=other.status,
                created_by_actor_type=link.created_by_actor_type,
                reason=link.reason,
            )
        )
    return links


@router.get("/issues/{issue_id}/history")
def issue_history(
    issue_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[AuditEventOut]:
    issue = workflow.get_issue(session, issue_id)
    events = session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.migration_id == issue.migration_id,
            AuditEvent.entity_type == "issue",
            AuditEvent.entity_id == issue.id,
        )
        .order_by(AuditEvent.migration_seq)
        .limit(500)
    )
    return [audit_event_out(e) for e in events]


def decision_out(row: EntityDecision) -> EntityDecisionOut:
    return EntityDecisionOut(
        id=row.id,
        party_type=row.party_type,
        decision=row.decision,
        members=list(row.members),
        survivor=row.survivor,
        reason=row.reason,
        status=row.status,
        change_request_id=row.change_request_id,
        reverted_by_cr_id=row.reverted_by_cr_id,
        created_at=row.created_at,
    )


@router.get("/migrations/{migration_id}/entity-decisions")
def list_entity_decisions(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[EntityDecisionOut]:
    workspace.get_migration(session, migration_id)
    rows = session.scalars(
        select(EntityDecision)
        .where(EntityDecision.migration_id == migration_id)
        .order_by(EntityDecision.created_at.desc(), EntityDecision.id)
    )
    return [decision_out(r) for r in rows]


@router.get("/entity-candidates/{candidate_id}")
def get_candidate(
    candidate_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> CandidateDetailOut:
    candidate = session.get(EntityCandidateRow, candidate_id)
    if candidate is None:
        raise ResourceNotFoundError("entity candidate not found")
    run = session.get_one(PipelineRun, candidate.run_id)
    codes = [candidate.left_code, candidate.right_code]
    decisions = session.scalars(
        select(EntityDecision)
        .where(
            EntityDecision.migration_id == run.migration_id,
            EntityDecision.party_type == candidate.party_type,
            EntityDecision.members.overlap(codes),
        )
        .order_by(EntityDecision.created_at.desc())
    )
    return CandidateDetailOut(
        candidate=CandidateOut(
            id=candidate.id,
            party_type=candidate.party_type,
            left_code=candidate.left_code,
            right_code=candidate.right_code,
            score=str(candidate.score),
            strong=candidate.strong,
            status=candidate.status,
            features=candidate.features,
        ),
        run_id=run.id,
        parties=[
            PartyOut(
                natural_key=record.natural_key,
                code=str(record.party_code),
                data=record.data,
                open_documents=documents,
            )
            for record, documents in run_evidence.parties(
                session, run.id, candidate.party_type, codes
            )
        ],
        decisions=[decision_out(d) for d in decisions],
    )


@router.get("/migrations/{migration_id}/dispositions")
def list_dispositions(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[DispositionOut]:
    migration = workspace.get_migration(session, migration_id)
    rows = session.execute(
        select(Disposition, Issue.key)
        .join(Issue, Issue.id == Disposition.issue_id)
        .where(Disposition.migration_id == migration_id)
        .order_by(Disposition.created_at.desc(), Disposition.id)
    ).tuples()
    return [
        DispositionOut(
            id=d.id,
            issue_id=d.issue_id,
            issue_key=key,
            kind=d.kind,
            amount=amount_text(d.amount, migration.functional_currency),
            currency=d.currency.code if d.currency else None,
            follow_up=d.follow_up,
            follow_up_owner_id=d.follow_up_owner_id,
            reason=d.reason,
            status=d.status,
            change_request_id=d.change_request_id,
            reverted_by_cr_id=d.reverted_by_cr_id,
            created_at=d.created_at,
        )
        for d, key in rows
    ]
