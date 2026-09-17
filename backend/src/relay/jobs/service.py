"""Job queue operations: enqueue, claim with SKIP LOCKED, heartbeat, finish (architecture.md §7)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from relay.core.clock import Clock, SystemClock
from relay.core.ids import uuid7
from relay.jobs.models import Job, JobKind, JobStatus

STALE_AFTER: Final = timedelta(minutes=10)


def enqueue(
    session: Session,
    kind: JobKind,
    payload: Mapping[str, Any],
    *,
    dedupe_key: str | None = None,
    clock: Clock | None = None,
) -> uuid.UUID | None:
    """Insert a job; with a dedupe key, an existing job with the same key wins (returns None)."""
    now = (clock or SystemClock()).now()
    job_id = uuid7(clock)
    statement = (
        insert(Job)
        .values(
            id=job_id,
            kind=kind.value,
            payload=dict(payload),
            dedupe_key=dedupe_key,
            status=JobStatus.QUEUED.value,
            attempts=0,
            max_attempts=3,
            run_after=now,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Job.id)
    )
    return session.execute(statement).scalar_one_or_none()


def claim(session: Session, worker: str, *, clock: Clock | None = None) -> Job | None:
    """Lock and mark one due job as running. Competing workers never receive the same job."""
    now = (clock or SystemClock()).now()
    job = session.scalars(
        select(Job)
        .where(Job.status == JobStatus.QUEUED.value, Job.run_after <= now)
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING.value
    job.attempts += 1
    job.locked_by = worker
    job.locked_at = now
    job.heartbeat_at = now
    session.flush()
    return job


def heartbeat(session: Session, job_id: uuid.UUID, *, clock: Clock | None = None) -> None:
    session.execute(
        update(Job).where(Job.id == job_id).values(heartbeat_at=(clock or SystemClock()).now())
    )


def succeed(session: Session, job: Job, *, clock: Clock | None = None) -> None:
    job.status = JobStatus.SUCCEEDED.value
    job.finished_at = (clock or SystemClock()).now()
    session.flush()


def fail(
    session: Session, job: Job, error: Mapping[str, Any], *, retry: bool, clock: Clock | None = None
) -> None:
    now = (clock or SystemClock()).now()
    job.last_error = dict(error)
    if retry and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED.value
        job.run_after = now + timedelta(seconds=5 * 2 ** (job.attempts - 1))
        job.locked_by = None
        job.locked_at = None
    else:
        job.status = JobStatus.DEAD.value if retry else JobStatus.FAILED.value
        job.finished_at = now
    session.flush()


def requeue_stale(session: Session, *, clock: Clock | None = None) -> int:
    """Return running jobs whose worker stopped heartbeating to the queue."""
    now = (clock or SystemClock()).now()
    stale = list(
        session.scalars(
            select(Job)
            .where(Job.status == JobStatus.RUNNING.value, Job.heartbeat_at < now - STALE_AFTER)
            .with_for_update(skip_locked=True)
        )
    )
    for job in stale:
        if job.attempts >= job.max_attempts:
            job.status = JobStatus.DEAD.value
            job.finished_at = now
            job.last_error = {"code": "job.stale", "detail": "worker stopped heartbeating"}
        else:
            job.status = JobStatus.QUEUED.value
            job.locked_by = None
    session.flush()
    return len(stale)
