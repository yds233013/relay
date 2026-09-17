"""Resolve gate waiver and sign-off requests against the current run's readiness evaluation.

A waiver covers exactly the scope a failing waivable gate reports on the current run. A sign-off
may be requested only when G1-G11 pass or are waived on the current run and nothing else is
pending. The client names the gate or asks to sign off; the server supplies run, fingerprint,
evaluation and scope.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.changes import service as changes
from relay.changes.kinds import ChangeRequestPreconditionError
from relay.changes.models import ChangeRequest, ChangeRequestKind, ChangeRequestStatus
from relay.core.actor import Actor
from relay.core.clock import Clock
from relay.core.errors import RelayError
from relay.pipeline.inputs import load_configuration
from relay.pipeline.models import GateResultRow, PipelineRun, ReadinessEvaluationRow, RunStatus

SIGNOFF_PREREQUISITES: Final = tuple(f"G{n}" for n in range(1, 12))


class ReadinessNotCurrentError(RelayError):
    code: ClassVar[str] = "readiness.not_current"
    title: ClassVar[str] = "Readiness has not been evaluated on the current inputs"
    http_status: ClassVar[int] = 409


def current_evaluation(
    session: Session, migration_id: uuid.UUID
) -> tuple[PipelineRun, ReadinessEvaluationRow, dict[str, GateResultRow]]:
    fingerprint = load_configuration(session, migration_id).fingerprint
    run = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.migration_id == migration_id,
            PipelineRun.fingerprint == fingerprint,
            PipelineRun.status == RunStatus.SUCCEEDED.value,
        )
        .order_by(PipelineRun.sequence.desc())
    ).first()
    if run is None:
        raise ReadinessNotCurrentError("run the pipeline on the current inputs first")
    evaluation = session.scalars(
        select(ReadinessEvaluationRow)
        .where(ReadinessEvaluationRow.run_id == run.id)
        .order_by(ReadinessEvaluationRow.sequence.desc())
    ).first()
    if evaluation is None:
        raise ReadinessNotCurrentError("the current run has no readiness evaluation")
    gates = {
        g.gate_id: g
        for g in session.scalars(
            select(GateResultRow).where(GateResultRow.evaluation_id == evaluation.id)
        )
    }
    return run, evaluation, gates


def waiver_payload(session: Session, *, migration_id: uuid.UUID, gate_id: str) -> dict[str, Any]:
    run, evaluation, gates = current_evaluation(session, migration_id)
    gate = gates.get(gate_id)
    if gate is None or gate.status != "fail" or not gate.scope:
        raise ChangeRequestPreconditionError(f"{gate_id} is not failing on the current run")
    return {
        "gate_id": gate_id,
        "run_id": str(run.id),
        "run_fingerprint": run.fingerprint,
        "evaluation_id": str(evaluation.id),
        "scope": {str(k): str(v) for k, v in gate.scope.items()},
    }


def signoff_payload(
    session: Session, *, migration_id: uuid.UUID, exclude_change_id: uuid.UUID | None = None
) -> dict[str, Any]:
    run, evaluation, gates = current_evaluation(session, migration_id)
    failing = [
        gate_id
        for gate_id in SIGNOFF_PREREQUISITES
        if gate_id != "G11" and (gates.get(gate_id) is None or gates[gate_id].status == "fail")
    ]
    if failing:
        raise ChangeRequestPreconditionError(
            f"sign-off needs G1-G11 to pass or be waived; failing: {', '.join(failing)}"
        )
    pending = [
        c.key
        for c in changes.change_requests_for(session, migration_id, limit=500)
        if c.status in {ChangeRequestStatus.SUBMITTED.value, ChangeRequestStatus.STALE.value}
        and c.id != exclude_change_id
    ]
    if pending:
        raise ChangeRequestPreconditionError(
            f"sign-off needs no other pending change requests; pending: {', '.join(pending)}"
        )
    return {
        "run_id": str(run.id),
        "run_fingerprint": run.fingerprint,
        "evaluation_id": str(evaluation.id),
    }


def ensure_current(
    session: Session, *, actor: Actor, change: ChangeRequest, clock: Clock | None = None
) -> bool:
    """Mark a waiver or sign-off request stale when the current run no longer matches it.

    Returns False (and records staleness) when the request is no longer valid.
    """
    if change.status != ChangeRequestStatus.SUBMITTED.value:
        return True
    kind = ChangeRequestKind(change.kind)
    try:
        if kind is ChangeRequestKind.GATE_WAIVER:
            current = waiver_payload(
                session, migration_id=change.migration_id, gate_id=change.payload["gate_id"]
            )
            valid = current["scope"] == change.payload["scope"]
        elif kind is ChangeRequestKind.READINESS_SIGNOFF:
            current = signoff_payload(
                session, migration_id=change.migration_id, exclude_change_id=change.id
            )
            valid = current["run_fingerprint"] == change.payload["run_fingerprint"]
        else:
            return True
    except (ChangeRequestPreconditionError, ReadinessNotCurrentError) as exc:
        current = {"reason": exc.detail}
        valid = False
    if valid:
        return True
    changes.mark_stale(session, actor=actor, change=change, current=current, clock=clock)
    return False
