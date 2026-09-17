"""Job worker: claim a job, run its handler in its own transaction, record the outcome.

The handler's writes and the job's ``succeeded`` status commit together. On failure the handler's
transaction rolls back and the failure is recorded in a new transaction; transient database errors
are retried with backoff, domain errors are not.
"""

from __future__ import annotations

import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from relay.ai.investigator import Budgets
from relay.ai.providers.base import LLMProvider
from relay.ai.providers.factory import provider_from_settings
from relay.core.clock import Clock
from relay.core.config import get_settings
from relay.core.db import session_scope
from relay.core.errors import RelayError
from relay.core.logging import get_logger
from relay.imports import service as imports
from relay.imports.blob_store import BlobStore
from relay.investigations import service as investigations
from relay.jobs import service as jobs
from relay.jobs.models import Job, JobKind
from relay.pipeline import service as pipeline

_log = get_logger("relay.worker")


@dataclass(frozen=True, slots=True)
class WorkerContext:
    session_factory: sessionmaker[Session]
    blob_store: BlobStore
    limits: imports.ImportLimits
    clock: Clock | None = None
    name: str = f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
    ai_provider: LLMProvider | None = None
    """The provider investigations use; built from settings when None."""
    ai_budgets: Budgets = field(default_factory=Budgets)


Handler = Callable[[Session, WorkerContext, dict[str, Any]], None]


def _parse_import(session: Session, context: WorkerContext, payload: dict[str, Any]) -> None:
    imports.parse(
        session,
        import_id=uuid.UUID(payload["import_id"]),
        blob_store=context.blob_store,
        limits=context.limits,
        clock=context.clock,
    )


def _run_pipeline(session: Session, context: WorkerContext, payload: dict[str, Any]) -> None:
    pipeline.execute_run(
        session,
        run_id=uuid.UUID(payload["run_id"]),
        blob_store=context.blob_store,
        clock=context.clock,
    )


def _evaluate_readiness(session: Session, context: WorkerContext, payload: dict[str, Any]) -> None:
    pipeline.reevaluate_readiness(
        session,
        migration_id=uuid.UUID(payload["migration_id"]),
        blob_store=context.blob_store,
        clock=context.clock,
    )


def _run_investigation(_session: Session, context: WorkerContext, payload: dict[str, Any]) -> None:
    if context.ai_provider is not None:
        provider, budgets = context.ai_provider, context.ai_budgets
    else:
        settings = get_settings()
        provider = provider_from_settings(settings)
        budgets = Budgets(
            max_tool_calls=settings.ai_max_tool_calls,
            max_seconds=float(settings.ai_max_seconds),
            max_total_tokens=settings.ai_max_total_tokens,
        )
    investigations.execute(
        context.session_factory,
        investigation_id=uuid.UUID(payload["investigation_id"]),
        provider=provider,
        budgets=budgets,
        clock=context.clock,
    )


HANDLERS: dict[JobKind, Handler] = {
    JobKind.PARSE_IMPORT: _parse_import,
    JobKind.RUN_PIPELINE: _run_pipeline,
    JobKind.EVALUATE_READINESS: _evaluate_readiness,
    JobKind.RUN_INVESTIGATION: _run_investigation,
}


def _payload_id(payload: dict[str, Any], key: str) -> uuid.UUID | None:
    """A malformed payload must not stop the worker from recording the failure."""
    try:
        return uuid.UUID(str(payload[key]))
    except (KeyError, ValueError):
        return None


def run_once(context: WorkerContext) -> bool:
    """Process at most one job. Returns False when the queue had nothing due."""
    with session_scope(context.session_factory) as session:
        jobs.requeue_stale(session, clock=context.clock)
        claimed = jobs.claim(session, context.name, clock=context.clock)
        if claimed is None:
            return False
        job_id, kind, payload = claimed.id, JobKind(claimed.kind), dict(claimed.payload)
    started = time.perf_counter()
    try:
        with session_scope(context.session_factory) as session:
            HANDLERS[kind](session, context, payload)
            job = session.get(Job, job_id, with_for_update=True)
            if job is not None:
                jobs.succeed(session, job, clock=context.clock)
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded on the job
        transient = isinstance(exc, OperationalError)
        error = {
            "code": exc.code if isinstance(exc, RelayError) else "job.unexpected_error",
            "detail": exc.detail if isinstance(exc, RelayError) else type(exc).__name__,
        }
        _log.warning("job_failed", job_id=str(job_id), kind=kind.value, error_code=error["code"])
        with session_scope(context.session_factory) as session:
            job = session.get(Job, job_id, with_for_update=True)
            final = not transient or (job is not None and job.attempts >= job.max_attempts)
            run_id = _payload_id(payload, "run_id")
            import_id = _payload_id(payload, "import_id")
            if final and kind is JobKind.RUN_PIPELINE and run_id is not None:
                pipeline.mark_failed(session, run_id=run_id, error=error, clock=context.clock)
            investigation_id = _payload_id(payload, "investigation_id")
            if final and kind is JobKind.RUN_INVESTIGATION and investigation_id is not None:
                investigations.mark_failed(
                    session, investigation_id=investigation_id, error=error, clock=context.clock
                )
            if final and kind is JobKind.PARSE_IMPORT and import_id is not None:
                imports.mark_failed(session, import_id=import_id, error=error, clock=context.clock)
            if job is not None:
                jobs.fail(session, job, error, retry=transient, clock=context.clock)
        return True
    _log.info(
        "job_succeeded",
        job_id=str(job_id),
        kind=kind.value,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return True


def drain(context: WorkerContext, max_jobs: int = 10_000) -> int:
    """Run jobs until the queue has nothing due (used by seeding and tests)."""
    processed = 0
    while processed < max_jobs and run_once(context):
        processed += 1
    return processed


def run_forever(
    context: WorkerContext, poll_seconds: int = 1, heartbeat_file: Path | None = None
) -> None:
    """Poll forever. ``heartbeat_file`` is touched every loop iteration for liveness checks."""
    _log.info("worker_started", worker=context.name)
    while True:
        if heartbeat_file is not None:
            heartbeat_file.touch()
        if not run_once(context):
            time.sleep(poll_seconds)
