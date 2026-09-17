"""Change requests: draft, submit, review, withdraw and apply (governance.md §2).

Approval and application happen in the same transaction (GV-04): when the last required approval is
recorded, the kind's applier runs immediately; if it raises, the whole transaction rolls back. After
an application, other submitted requests of the migration whose base objects changed become stale.
Every transition writes an audit event with its before and after state.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.changes.domain import RecordedApproval, eligibility, fully_approved
from relay.changes.kinds import KINDS, ChangeRequestPreconditionError, parse_payload
from relay.changes.models import (
    Approval,
    ApprovalDecision,
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestOrigin,
    ChangeRequestStatus,
)
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.errors import InvalidInputError, NotFoundError, RelayError
from relay.core.ids import uuid7
from relay.issues import workflow as issue_workflow
from relay.workspace.models import Migration

MAX_TITLE_LENGTH: Final = 200
MAX_TEXT_LENGTH: Final = 4000
OPEN_STATUSES: Final = frozenset(
    {ChangeRequestStatus.DRAFT.value, ChangeRequestStatus.SUBMITTED.value}
)
WITHDRAWABLE_STATUSES: Final = frozenset({*OPEN_STATUSES, ChangeRequestStatus.STALE.value})

__all__ = [
    "ChangeRequestPreconditionError",
    "ChangeRequestStateError",
    "SegregationOfDutiesError",
    "create_draft",
    "get_change_request",
    "pending_count",
    "review",
    "submit",
    "update_draft",
    "withdraw",
]


class ChangeRequestStateError(RelayError):
    code: ClassVar[str] = "change_request.invalid_state"
    title: ClassVar[str] = "Change request is not in a state that allows this"
    http_status: ClassVar[int] = 409


class SegregationOfDutiesError(RelayError):
    code: ClassVar[str] = "approval.segregation_of_duties"
    title: ClassVar[str] = "Reviewer is not eligible"
    http_status: ClassVar[int] = 403


def get_change_request(session: Session, change_id: uuid.UUID) -> ChangeRequest:
    change = session.get(ChangeRequest, change_id)
    if change is None:
        raise NotFoundError("change request not found")
    return change


def _text(value: str, label: str, limit: int, *, required: bool) -> str:
    text = value.strip()
    if required and not text:
        raise InvalidInputError(f"{label} is required")
    if len(text) > limit:
        raise InvalidInputError(f"{label} is too long")
    return text


def _require_person(actor: Actor) -> uuid.UUID:
    if actor.kind != "user" or actor.user_id is None:
        raise ChangeRequestStateError("change requests are requested by a person")  # GV-07
    return actor.user_id


def create_draft(
    session: Session,
    *,
    actor: Actor,
    migration: Migration,
    kind: ChangeRequestKind,
    title: str,
    payload: dict[str, Any],
    evidence_refs: list[Any] | None = None,
    origin: ChangeRequestOrigin = ChangeRequestOrigin.OPERATOR,
    origin_finding_id: uuid.UUID | None = None,
    clock: Clock | None = None,
) -> ChangeRequest:
    requester = _require_person(actor)
    if (origin is ChangeRequestOrigin.AI_FINDING) != (origin_finding_id is not None):
        raise InvalidInputError("a change drafted from a finding names that finding")
    title = _text(title, "title", MAX_TITLE_LENGTH, required=True)
    parsed = parse_payload(kind, payload)
    KINDS[kind].check_draft(session, migration.id, parsed)
    locked = session.get(Migration, migration.id, with_for_update=True)
    if locked is None:
        raise InvalidInputError("migration does not exist")
    number = locked.next_change_request_number
    locked.next_change_request_number += 1
    stored = parsed.model_dump(mode="json")
    change = ChangeRequest(
        id=uuid7(clock),
        migration_id=migration.id,
        key=f"CR-{number}",
        kind=kind.value,
        status=ChangeRequestStatus.DRAFT.value,
        title=title,
        payload=stored,
        evidence_refs=evidence_refs or [],
        origin=origin.value,
        origin_finding_id=origin_finding_id,
        requested_by=requester,
        required_approvals=[],
        base_entity_versions={},
        version=1,
    )
    session.add(change)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="change_request.drafted",
        entity_type="change_request",
        entity_id=change.id,
        migration_id=migration.id,
        change_request_id=change.id,
        before={"status": None},
        after={
            "status": change.status,
            "key": change.key,
            "kind": kind.value,
            "title": title,
            "payload": stored,
            "origin": origin.value,
            "origin_finding_id": origin_finding_id,
        },
        evidence_refs=change.evidence_refs,
        clock=clock,
    )
    return change


def update_draft(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    title: str | None,
    payload: dict[str, Any] | None,
    expected_version: int,
    clock: Clock | None = None,
) -> ChangeRequest:
    if change.status != ChangeRequestStatus.DRAFT.value:
        raise ChangeRequestStateError("only drafts can be edited")
    if actor.user_id != change.requested_by:
        raise ChangeRequestStateError("only the requester can edit a draft")
    if change.version != expected_version:
        raise ChangeRequestStateError("the draft changed since it was loaded; reload it")
    kind = ChangeRequestKind(change.kind)
    before = {"title": change.title, "payload": change.payload}
    if title is not None:
        change.title = _text(title, "title", MAX_TITLE_LENGTH, required=True)
    if payload is not None:
        parsed = parse_payload(kind, payload)
        KINDS[kind].check_draft(session, change.migration_id, parsed)
        change.payload = parsed.model_dump(mode="json")
    change.version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="change_request.draft_updated",
        entity_type="change_request",
        entity_id=change.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before=before,
        after={"title": change.title, "payload": change.payload},
        clock=clock,
    )
    return change


def submit(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    justification: str,
    clock: Clock | None = None,
) -> ChangeRequest:
    if change.status != ChangeRequestStatus.DRAFT.value:
        raise ChangeRequestStateError("only drafts can be submitted")
    if actor.user_id != change.requested_by:
        raise ChangeRequestStateError("only the requester can submit a draft")
    change.justification = _text(justification, "a justification", MAX_TEXT_LENGTH, required=True)
    kind = ChangeRequestKind(change.kind)
    handler = KINDS[kind]
    payload = parse_payload(kind, change.payload)
    prepared = handler.prepare(session, change, payload)
    session.flush()
    change.before = prepared.before
    change.after = prepared.after
    change.impact = prepared.impact
    change.required_approvals = prepared.required_approvals
    change.base_entity_versions = handler.versions(session, change, payload)
    change.status = ChangeRequestStatus.SUBMITTED.value
    change.submitted_at = (clock or SystemClock()).now()
    change.version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="change_request.submitted",
        entity_type="change_request",
        entity_id=change.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        reason=change.justification,
        before={"status": ChangeRequestStatus.DRAFT.value, "state": change.before},
        after={
            "status": change.status,
            "state": change.after,
            "impact": change.impact,
            "required_approvals": change.required_approvals,
            "base_entity_versions": change.base_entity_versions,
        },
        clock=clock,
    )
    return change


def _approvals(session: Session, change: ChangeRequest) -> list[RecordedApproval]:
    return [
        RecordedApproval(a.reviewer_user_id, a.satisfies_requirement_index, a.decision)
        for a in session.scalars(select(Approval).where(Approval.change_request_id == change.id))
    ]


def _transition(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    status: ChangeRequestStatus,
    action: str,
    reason: str | None = None,
    extra_before: dict[str, Any] | None = None,
    extra_after: dict[str, Any] | None = None,
    clock: Clock | None = None,
) -> None:
    previous = change.status
    change.status = status.value
    change.version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action=action,
        entity_type="change_request",
        entity_id=change.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        reason=reason,
        before={"status": previous, **(extra_before or {})},
        after={"status": status.value, **(extra_after or {})},
        clock=clock,
    )


def _release(session: Session, change: ChangeRequest, outcome: ChangeRequestStatus) -> None:
    kind = ChangeRequestKind(change.kind)
    KINDS[kind].release(session, change, parse_payload(kind, change.payload), outcome)


def _mark_if_stale(
    session: Session, change: ChangeRequest, actor: Actor, clock: Clock | None
) -> bool:
    """Mark a submitted request stale (audited) when its base objects changed.

    Staleness is recorded and returned, not raised: raising would roll the marking back.
    """
    kind = ChangeRequestKind(change.kind)
    current = KINDS[kind].versions(session, change, parse_payload(kind, change.payload))
    if current == change.base_entity_versions:
        return False
    _transition(
        session,
        actor=actor,
        change=change,
        status=ChangeRequestStatus.STALE,
        action="change_request.stale",
        extra_before={"base_entity_versions": change.base_entity_versions},
        extra_after={"current_entity_versions": current},
        clock=clock,
    )
    _release(session, change, ChangeRequestStatus.STALE)
    session.flush()
    return True


def mark_stale(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    current: dict[str, Any],
    clock: Clock | None = None,
) -> None:
    """Record that a submitted request no longer matches state checked outside this module."""
    if change.status != ChangeRequestStatus.SUBMITTED.value:
        raise ChangeRequestStateError("only submitted change requests become stale")
    _transition(
        session,
        actor=actor,
        change=change,
        status=ChangeRequestStatus.STALE,
        action="change_request.stale",
        extra_before={"payload": change.payload},
        extra_after={"current": current},
        clock=clock,
    )
    _release(session, change, ChangeRequestStatus.STALE)
    session.flush()


def sweep_stale(
    session: Session, *, actor: Actor, migration_id: uuid.UUID, clock: Clock | None = None
) -> list[ChangeRequest]:
    """Mark every submitted request of the migration whose base changed as stale."""
    submitted = session.scalars(
        select(ChangeRequest)
        .where(
            ChangeRequest.migration_id == migration_id,
            ChangeRequest.status == ChangeRequestStatus.SUBMITTED.value,
        )
        .order_by(ChangeRequest.created_at, ChangeRequest.id)
        .with_for_update()
    )
    return [change for change in list(submitted) if _mark_if_stale(session, change, actor, clock)]


def review(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    decision: ApprovalDecision,
    comment: str,
    clock: Clock | None = None,
) -> ChangeRequest:
    """Record one review. A returned status of ``stale`` means the review was not recorded."""
    if change.status != ChangeRequestStatus.SUBMITTED.value:
        raise ChangeRequestStateError("only submitted change requests can be reviewed")
    if actor.kind != "user" or actor.user_id is None or actor.role is None:
        raise SegregationOfDutiesError("reviews are made by people")  # GV-07
    comment = _text(comment, "comment", MAX_TEXT_LENGTH, required=False)
    if _mark_if_stale(session, change, actor, clock):
        return change
    approvals = _approvals(session, change)
    check = eligibility(
        requirements=change.required_approvals,
        approvals=approvals,
        requested_by=change.requested_by,
        reviewer_id=actor.user_id,
        reviewer_role=actor.role,
    )
    if not check.allowed:
        raise SegregationOfDutiesError(check.reason)
    if decision is ApprovalDecision.REJECT and not comment:
        raise InvalidInputError("a comment is required to reject")
    approval = Approval(
        id=uuid7(clock),
        change_request_id=change.id,
        reviewer_user_id=actor.user_id,
        reviewer_role_at_decision=actor.role,
        decision=decision.value,
        comment=comment,
        satisfies_requirement_index=check.requirement_index,
    )
    session.add(approval)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="change_request.approval_recorded",
        entity_type="change_request",
        entity_id=change.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        reason=comment or None,
        before={"approvals": len(approvals), "required": len(change.required_approvals)},
        after={
            "decision": decision.value,
            "role": actor.role,
            "requirement_index": check.requirement_index,
            "approvals": len(approvals) + 1,
        },
        clock=clock,
    )
    now = (clock or SystemClock()).now()
    if decision is ApprovalDecision.REJECT:
        change.decided_at = now
        _transition(
            session,
            actor=actor,
            change=change,
            status=ChangeRequestStatus.REJECTED,
            action="change_request.rejected",
            reason=comment,
            clock=clock,
        )
        _release(session, change, ChangeRequestStatus.REJECTED)
        session.flush()
        return change
    recorded = [
        *approvals,
        RecordedApproval(actor.user_id, check.requirement_index, decision.value),
    ]
    if not fully_approved(change.required_approvals, recorded):
        return change
    change.decided_at = now
    _transition(
        session,
        actor=actor,
        change=change,
        status=ChangeRequestStatus.APPROVED,
        action="change_request.approved",
        clock=clock,
    )
    kind = ChangeRequestKind(change.kind)
    KINDS[kind].apply(session, actor, change, parse_payload(kind, change.payload), clock)
    change.applied_at = now
    _transition(
        session,
        actor=actor,
        change=change,
        status=ChangeRequestStatus.APPLIED,
        action="change_request.applied",
        clock=clock,
    )
    if kind is not ChangeRequestKind.DISPOSITION:
        issue_workflow.await_verification(
            session,
            actor=actor,
            issue_ids=evidence_issue_ids(change.evidence_refs),
            change_request_id=change.id,
            clock=clock,
        )
    sweep_stale(session, actor=actor, migration_id=change.migration_id, clock=clock)
    return change


def evidence_issue_ids(evidence_refs: list[Any]) -> list[uuid.UUID]:
    """Issues a change request names as its evidence (``{"kind": "issue", "issue_id": ...}``)."""
    ids = []
    for ref in evidence_refs:
        if isinstance(ref, dict) and ref.get("kind") == "issue":
            try:
                ids.append(uuid.UUID(str(ref.get("issue_id"))))
            except ValueError:
                continue
    return ids


def withdraw(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    reason: str,
    clock: Clock | None = None,
) -> ChangeRequest:
    if change.status not in WITHDRAWABLE_STATUSES:
        raise ChangeRequestStateError(
            "only draft, submitted or stale change requests can be withdrawn"
        )
    if actor.user_id != change.requested_by:
        raise ChangeRequestStateError("only the requester can withdraw a change request")
    _transition(
        session,
        actor=actor,
        change=change,
        status=ChangeRequestStatus.WITHDRAWN,
        action="change_request.withdrawn",
        reason=_text(reason, "reason", MAX_TEXT_LENGTH, required=False) or None,
        clock=clock,
    )
    _release(session, change, ChangeRequestStatus.WITHDRAWN)
    session.flush()
    return change


def pending_count(session: Session, migration_id: uuid.UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(ChangeRequest)
            .where(
                ChangeRequest.migration_id == migration_id,
                # governance.md G11: stale requests stay pending until withdrawn.
                ChangeRequest.status.in_(
                    [ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.STALE.value]
                ),
            )
        )
        or 0
    )


def approvals_for(session: Session, change_id: uuid.UUID) -> list[Approval]:
    return list(
        session.scalars(
            select(Approval)
            .where(Approval.change_request_id == change_id)
            .order_by(Approval.decided_at, Approval.id)
        )
    )


def change_requests_for(
    session: Session,
    migration_id: uuid.UUID,
    *,
    status: str | None = None,
    kind: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[ChangeRequest]:
    query = select(ChangeRequest).where(ChangeRequest.migration_id == migration_id)
    if status:
        query = query.where(ChangeRequest.status == status)
    if kind:
        query = query.where(ChangeRequest.kind == kind)
    return list(
        session.scalars(
            query.order_by(ChangeRequest.created_at.desc(), ChangeRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
