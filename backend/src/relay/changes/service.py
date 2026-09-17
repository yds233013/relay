"""Change requests: draft, submit, review and apply (governance.md §2).

Approval and application happen in the same transaction (GV-04): when the last required approval is
recorded, the applier runs immediately; if it raises, the whole transaction rolls back.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.changes.domain import RecordedApproval, eligibility, fully_approved, required_approvals
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
from relay.core.errors import InvalidInputError, RelayError
from relay.core.ids import uuid7
from relay.mapping_sets import service as mapping_sets
from relay.mapping_sets.models import ColumnMappingSet
from relay.workspace.models import Dataset, Migration


class ChangeRequestStateError(RelayError):
    code: ClassVar[str] = "change_request.invalid_state"
    title: ClassVar[str] = "Change request is not in a state that allows this"
    http_status: ClassVar[int] = 409


class SegregationOfDutiesError(RelayError):
    code: ClassVar[str] = "approval.segregation_of_duties"
    title: ClassVar[str] = "Reviewer is not eligible"
    http_status: ClassVar[int] = 403


class ColumnMappingSetPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_set_id: uuid.UUID


def _entity_versions(
    session: Session, kind: ChangeRequestKind, payload: dict[str, Any]
) -> dict[str, int]:
    if kind is ChangeRequestKind.COLUMN_MAPPING_SET:
        mapping_set = session.get(ColumnMappingSet, uuid.UUID(payload["mapping_set_id"]))
        if mapping_set is None:
            raise InvalidInputError("mapping set does not exist")
        return {f"column_mapping_set:{mapping_set.id}": mapping_set.lock_version}
    raise NotImplementedError(f"{kind.value} change requests are not implemented yet")


def _validate_payload(kind: ChangeRequestKind, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind is ChangeRequestKind.COLUMN_MAPPING_SET:
            return ColumnMappingSetPayload.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise InvalidInputError(f"invalid payload for {kind.value}") from exc
    raise NotImplementedError(f"{kind.value} change requests are not implemented yet")


def create_draft(
    session: Session,
    *,
    actor: Actor,
    migration: Migration,
    kind: ChangeRequestKind,
    title: str,
    payload: dict[str, Any],
    evidence_refs: list[Any] | None = None,
    clock: Clock | None = None,
) -> ChangeRequest:
    if actor.kind != "user" or actor.user_id is None:
        raise ChangeRequestStateError("change requests are requested by a person")  # GV-07
    validated = _validate_payload(kind, payload)
    locked = session.get(Migration, migration.id, with_for_update=True)
    if locked is None:
        raise InvalidInputError("migration does not exist")
    number = locked.next_change_request_number
    locked.next_change_request_number += 1
    change = ChangeRequest(
        id=uuid7(clock),
        migration_id=migration.id,
        key=f"CR-{number}",
        kind=kind.value,
        status=ChangeRequestStatus.DRAFT.value,
        title=title,
        payload=validated,
        evidence_refs=evidence_refs or [],
        origin=ChangeRequestOrigin.OPERATOR.value,
        requested_by=actor.user_id,
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
        after={"key": change.key, "kind": kind.value, "title": title, "payload": validated},
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
    if not justification.strip():
        raise InvalidInputError("a justification is required")
    kind = ChangeRequestKind(change.kind)
    change.required_approvals = required_approvals(kind)
    change.base_entity_versions = _entity_versions(session, kind, change.payload)
    if kind is ChangeRequestKind.COLUMN_MAPPING_SET:
        mapping_set = session.get(ColumnMappingSet, uuid.UUID(change.payload["mapping_set_id"]))
        if mapping_set is None:
            raise InvalidInputError("mapping set does not exist")
        mapping_sets.mark_pending(mapping_set)
        dataset = session.get(Dataset, mapping_set.dataset_id)
        change.before = {"approved_version": None}
        current = mapping_sets.approved_set(session, mapping_set.dataset_id)
        if current is not None:
            change.before = {"approved_version": current.version}
        change.after = {"approved_version": mapping_set.version}
        change.impact = {
            "dataset_id": str(mapping_set.dataset_id),
            "dataset_type": dataset.dataset_type if dataset else None,
        }
        session.flush()
        change.base_entity_versions = _entity_versions(session, kind, change.payload)
    change.justification = justification
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
        reason=justification,
        after={"required_approvals": change.required_approvals},
        clock=clock,
    )
    return change


def _approvals(session: Session, change: ChangeRequest) -> list[RecordedApproval]:
    return [
        RecordedApproval(a.reviewer_user_id, a.satisfies_requirement_index, a.decision)
        for a in session.scalars(select(Approval).where(Approval.change_request_id == change.id))
    ]


def _mark_if_stale(
    session: Session, change: ChangeRequest, actor: Actor, clock: Clock | None
) -> bool:
    """Mark the change request stale (and audit it) when its base objects changed.

    Staleness is recorded and returned, not raised: raising would roll the marking back.
    """
    current = _entity_versions(session, ChangeRequestKind(change.kind), change.payload)
    if current != change.base_entity_versions:
        change.status = ChangeRequestStatus.STALE.value
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="change_request.stale",
            entity_type="change_request",
            entity_id=change.id,
            migration_id=change.migration_id,
            change_request_id=change.id,
            before={"base_entity_versions": change.base_entity_versions},
            after={"current_entity_versions": current},
            clock=clock,
        )
        return True
    return False


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
    if decision is ApprovalDecision.REJECT and not comment.strip():
        raise InvalidInputError("a comment is required to reject")
    if not check.allowed:
        raise SegregationOfDutiesError(check.reason)
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
        after={"decision": decision.value, "requirement_index": check.requirement_index},
        clock=clock,
    )
    now = (clock or SystemClock()).now()
    if decision is ApprovalDecision.REJECT:
        change.status = ChangeRequestStatus.REJECTED.value
        change.decided_at = now
        change.version += 1
        _on_rejected(session, change)
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="change_request.rejected",
            entity_type="change_request",
            entity_id=change.id,
            migration_id=change.migration_id,
            change_request_id=change.id,
            reason=comment,
            clock=clock,
        )
        return change
    if fully_approved(
        change.required_approvals,
        [*approvals, RecordedApproval(actor.user_id, check.requirement_index, decision.value)],
    ):
        change.status = ChangeRequestStatus.APPROVED.value
        change.decided_at = now
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="change_request.approved",
            entity_type="change_request",
            entity_id=change.id,
            migration_id=change.migration_id,
            change_request_id=change.id,
            clock=clock,
        )
        _apply(session, actor, change)
        change.status = ChangeRequestStatus.APPLIED.value
        change.applied_at = now
        change.version += 1
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="change_request.applied",
            entity_type="change_request",
            entity_id=change.id,
            migration_id=change.migration_id,
            change_request_id=change.id,
            clock=clock,
        )
    return change


def _apply(session: Session, actor: Actor, change: ChangeRequest) -> None:
    kind = ChangeRequestKind(change.kind)
    if kind is ChangeRequestKind.COLUMN_MAPPING_SET:
        mapping_set = session.get(
            ColumnMappingSet, uuid.UUID(change.payload["mapping_set_id"]), with_for_update=True
        )
        if mapping_set is None:
            raise ChangeRequestStateError("mapping set disappeared")
        mapping_sets.approve(
            session,
            actor=actor,
            mapping_set=mapping_set,
            change_request_id=change.id,
            migration_id=change.migration_id,
        )
        return
    raise NotImplementedError(f"{kind.value} appliers are not implemented yet")


def _on_rejected(session: Session, change: ChangeRequest) -> None:
    if ChangeRequestKind(change.kind) is ChangeRequestKind.COLUMN_MAPPING_SET:
        mapping_set = session.get(ColumnMappingSet, uuid.UUID(change.payload["mapping_set_id"]))
        if mapping_set is not None:
            mapping_sets.reject(mapping_set)


def pending_count(session: Session, migration_id: uuid.UUID) -> int:
    return len(
        list(
            session.scalars(
                select(ChangeRequest.id).where(
                    ChangeRequest.migration_id == migration_id,
                    ChangeRequest.status.in_(
                        [ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.STALE.value]
                    ),
                )
            )
        )
    )
