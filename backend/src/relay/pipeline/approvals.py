"""Change request orchestration shared by the API and demo tooling.

These functions add what the ``changes`` module cannot see from its layer: resolving payloads from
run evidence and readiness, holding the pipeline lock in the order the worker uses, requesting a
run when an applied change alters the inputs, and queueing a readiness re-evaluation otherwise.
Anything that proposes or approves a change goes through here, so demo scripts follow exactly the
path people follow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from relay.changes import service as changes
from relay.changes.kinds import ChangeRequestPreconditionError
from relay.changes.models import (
    ApprovalDecision,
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestOrigin,
    ChangeRequestStatus,
)
from relay.core.actor import Actor
from relay.core.clock import Clock
from relay.core.errors import InvalidInputError
from relay.pipeline import overrides as override_resolver
from relay.pipeline import readiness as readiness_resolver
from relay.pipeline import service as pipeline
from relay.pipeline.models import RunTrigger
from relay.workspace import service as workspace


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    change: ChangeRequest
    run_id: uuid.UUID | None


def resolve_payload(
    session: Session,
    *,
    migration_id: uuid.UUID,
    kind: ChangeRequestKind,
    payload: dict[str, Any] | None,
    field_override: dict[str, Any] | None = None,
    quarantine_repair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn what a client may say into a stored payload; the server supplies evidence values."""
    if kind is ChangeRequestKind.RECORD_OVERRIDE:
        if payload is not None or (field_override is None) == (quarantine_repair is None):
            raise InvalidInputError(
                "a record override needs exactly one of field_override or quarantine_repair"
            )
        if field_override is not None:
            return override_resolver.field_override_payload(
                session, migration_id=migration_id, **field_override
            )
        assert quarantine_repair is not None  # noqa: S101 - narrowed by the check above
        return override_resolver.quarantine_repair_payload(
            session, migration_id=migration_id, **quarantine_repair
        )
    if payload is None or field_override or quarantine_repair:
        raise InvalidInputError(f"{kind.value} change requests take a payload")
    if kind is ChangeRequestKind.GATE_WAIVER:
        return readiness_resolver.waiver_payload(
            session, migration_id=migration_id, gate_id=str(payload.get("gate_id", ""))
        )
    if kind is ChangeRequestKind.READINESS_SIGNOFF:
        return readiness_resolver.signoff_payload(session, migration_id=migration_id)
    if kind is ChangeRequestKind.ENTITY_DECISION:
        override_resolver.check_decision_parties(
            session, migration_id=migration_id, payload=payload
        )
    return payload


def create(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    kind: ChangeRequestKind,
    title: str,
    payload: dict[str, Any] | None,
    field_override: dict[str, Any] | None = None,
    quarantine_repair: dict[str, Any] | None = None,
    evidence_refs: list[Any] | None = None,
    origin: ChangeRequestOrigin = ChangeRequestOrigin.OPERATOR,
    origin_finding_id: uuid.UUID | None = None,
    clock: Clock | None = None,
) -> ChangeRequest:
    migration = workspace.get_migration(session, migration_id)
    resolved = resolve_payload(
        session,
        migration_id=migration_id,
        kind=kind,
        payload=payload,
        field_override=field_override,
        quarantine_repair=quarantine_repair,
    )
    return changes.create_draft(
        session,
        actor=actor,
        migration=migration,
        kind=kind,
        title=title,
        payload=resolved,
        evidence_refs=evidence_refs,
        origin=origin,
        origin_finding_id=origin_finding_id,
        clock=clock,
    )


def _require_current_resolution(session: Session, change: ChangeRequest) -> None:
    """A waiver or sign-off draft must still match the current run when it is submitted."""
    kind = ChangeRequestKind(change.kind)
    if kind is ChangeRequestKind.GATE_WAIVER:
        current = readiness_resolver.waiver_payload(
            session, migration_id=change.migration_id, gate_id=change.payload["gate_id"]
        )
    elif kind is ChangeRequestKind.READINESS_SIGNOFF:
        current = readiness_resolver.signoff_payload(
            session, migration_id=change.migration_id, exclude_change_id=change.id
        )
    else:
        return
    if current != change.payload:
        raise ChangeRequestPreconditionError(
            "the current run changed since this request was drafted; draft it again"
        )


def submit(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    justification: str,
    clock: Clock | None = None,
) -> ChangeRequest:
    _require_current_resolution(session, change)
    changes.submit(session, actor=actor, change=change, justification=justification, clock=clock)
    pipeline.request_readiness_evaluation(session, migration_id=change.migration_id, clock=clock)
    return change


def review(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    decision: ApprovalDecision,
    comment: str,
    clock: Clock | None = None,
) -> ReviewOutcome:
    # An approval may apply the change and request a run: take the pipeline lock before any audit
    # write, in the same order as the worker (otherwise the two can deadlock).
    pipeline.lock_migration(session, change.migration_id)
    run_id = None
    new_run = False
    if readiness_resolver.ensure_current(session, actor=actor, change=change, clock=clock):
        changes.review(
            session, actor=actor, change=change, decision=decision, comment=comment, clock=clock
        )
    if change.status == ChangeRequestStatus.APPLIED.value:
        # Applying a change may alter the run inputs; an unchanged fingerprint returns the
        # existing run.
        outcome = pipeline.request_run(
            session,
            actor=actor,
            migration_id=change.migration_id,
            trigger=RunTrigger.CHANGE_REQUEST_APPLIED,
            change_request_id=change.id,
            clock=clock,
        )
        run_id = outcome.run.id
        new_run = outcome.created
    if not new_run:
        # Waivers, sign-offs and pending-request counts change readiness without a new run.
        pipeline.request_readiness_evaluation(
            session, migration_id=change.migration_id, clock=clock
        )
    return ReviewOutcome(change, run_id)


def withdraw(
    session: Session,
    *,
    actor: Actor,
    change: ChangeRequest,
    reason: str,
    clock: Clock | None = None,
) -> ChangeRequest:
    changes.withdraw(session, actor=actor, change=change, reason=reason, clock=clock)
    pipeline.request_readiness_evaluation(session, migration_id=change.migration_id, clock=clock)
    return change
