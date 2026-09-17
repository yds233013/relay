"""Measure the persisted pipeline on a synthetic clean migration (not a demo, not evaluation truth).

The synthetic files are loaded through the same services as the Brightwater seed (uploads, parse
jobs, approved column and account mappings, a pipeline run), then a governed policy change produces
a second run, readiness is re-evaluated, and the main read endpoints are timed in process. Every
number printed is measured on this machine in this invocation; nothing is extrapolated.
"""

from __future__ import annotations

import statistics
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from relay.changes.models import ApprovalDecision, ChangeRequest, ChangeRequestKind
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.identity import service as identity
from relay.imports.blob_store import BlobStore
from relay.imports.models import Import
from relay.imports.service import ImportLimits
from relay.pipeline import approvals
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun, ReadinessEvaluationRow, StagedRecord
from relay.worker import WorkerContext, drain
from relay.workspace.models import Dataset
from relay_scenarios.brightwater.seed import PEOPLE, seed
from relay_scenarios.volume import build_volume_migration, export_volume_migration

READ_REPEATS = 5


@dataclass(frozen=True, slots=True)
class Timing:
    label: str
    median_ms: float
    max_ms: float
    detail: str = ""


def _time(call: Callable[[], Any], repeats: int = READ_REPEATS) -> tuple[float, float, Any]:
    samples = []
    result: Any = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = call()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples), max(samples), result


def _user_actor(session: Session, email: str) -> Any:
    user = identity.find_active_user_by_email(session, email)
    if user is None:
        raise RuntimeError(f"seed user {email} is missing")
    return identity.actor_for(user)


def _second_run(
    factory: sessionmaker[Session],
    context: WorkerContext,
    migration_id: uuid.UUID,
    after_run: uuid.UUID,
) -> tuple[float, uuid.UUID]:
    """A governed policy change (as the seeded people) changing the fingerprint, then its run."""
    maya, daniel, priya = PEOPLE[0][0], PEOPLE[1][0], PEOPLE[2][0]
    started = time.perf_counter()
    with session_scope(factory) as session:
        actor = _user_actor(session, maya)
        change = approvals.create(
            session, actor=actor, migration_id=migration_id, kind=ChangeRequestKind.POLICY_CHANGE,
            title="Widen the duplicate window", payload={"changes": {"duplicate_window_days": 10}},
        )  # fmt: skip
        approvals.submit(session, actor=actor, change=change, justification="Measurement.")
        change_id = change.id
    for email in (daniel, priya):
        with session_scope(factory) as session:
            current = session.get_one(ChangeRequest, change_id)
            if current.status != "submitted":
                break
            approvals.review(
                session, actor=_user_actor(session, email), change=current,
                decision=ApprovalDecision.APPROVE, comment="Measurement.",
            )  # fmt: skip
    drain(context)
    elapsed = time.perf_counter() - started
    with session_scope(factory) as session:
        run = session.scalars(
            select(PipelineRun)
            .where(PipelineRun.migration_id == migration_id)
            .order_by(PipelineRun.sequence.desc())
        ).first()
        if run is None or run.id == after_run or run.status != "succeeded":
            raise RuntimeError(
                "the policy change did not produce a new succeeded run: "
                f"{run.sequence if run else None} {run.status if run else None}"
            )
        return elapsed, run.id


def measure_pipeline(
    factory: sessionmaker[Session],
    settings: Settings,
    blob_store: BlobStore,
    limits: ImportLimits,
    mapping_set_path: Path,
    lines: int,
) -> list[str]:
    from fastapi.testclient import TestClient  # noqa: PLC0415 - measurement-only dependency

    from relay.api.app import create_app  # noqa: PLC0415

    migration = build_volume_migration(lines)
    files = export_volume_migration(migration)
    report = [
        f"GL detail lines      {migration.line_count}",
        f"source bytes         {sum(len(v) for v in files.values())}",
    ]
    context = WorkerContext(session_factory=factory, blob_store=blob_store, limits=limits)
    with tempfile.TemporaryDirectory(prefix="relay-perf-") as directory:
        root = Path(directory)
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(content)
        started = time.perf_counter()
        result = seed(factory, blob_store, limits, root, mapping_set_path)
        report.append(
            f"seed seconds         {time.perf_counter() - started:.1f} (users, uploads, parse jobs,"
            " approved mappings, run #1)"
        )

    migration_id, run_id = result.migration_id, result.run_id
    with session_scope(factory) as session:
        parse = [
            (i.completed_at - i.started_at).total_seconds()
            for i in session.scalars(
                select(Import)
                .join(Dataset, Dataset.id == Import.dataset_id)
                .where(Dataset.migration_id == migration_id)
            )
            if i.started_at and i.completed_at
        ]
        run = session.get_one(PipelineRun, run_id)
        staged = session.scalar(
            select(func.count()).select_from(StagedRecord).where(StagedRecord.run_id == run_id)
        )
        entry_key = session.scalar(
            select(StagedRecord.natural_key)
            .where(StagedRecord.run_id == run_id, StagedRecord.record_type == "journal_entry")
            .order_by(StagedRecord.natural_key)
            .limit(1)
        )
        timings = dict(run.stage_timings)
        counts = dict(run.counts)
    report += [
        f"imports parsed       {len(parse)}, total {sum(parse):.1f} s, slowest {max(parse):.1f} s",
        f"run #1 stage ms      {timings}",
        f"run #1 staged        {staged} records; counts {counts}",
    ]

    second_seconds, second_run = _second_run(factory, context, migration_id, run_id)
    with session_scope(factory) as session:
        second = session.get_one(PipelineRun, second_run)
        report.append(
            f"policy change + rerun seconds {second_seconds:.1f} (run #{second.sequence}); "
            f"stage ms {dict(second.stage_timings)}"
        )

    with session_scope(factory) as session:
        pipeline.request_readiness_evaluation(session, migration_id=migration_id)
    started = time.perf_counter()
    drain(context)
    with session_scope(factory) as session:
        sequence = session.scalar(
            select(func.max(ReadinessEvaluationRow.sequence)).where(
                ReadinessEvaluationRow.run_id == second_run
            )
        )
    report.append(
        f"readiness re-evaluation seconds {time.perf_counter() - started:.1f} "
        f"(evaluation sequence {sequence})"
    )

    reads: list[Timing] = []
    headers = {"X-Relay-User": PEOPLE[0][0]}
    with TestClient(create_app(settings)) as client:

        def get(path: str, **params: Any) -> Any:
            response = client.get(path, params=params, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"{path}: {response.status_code} {response.text[:200]}")
            return response.json()

        def timed(label: str, path: str, **params: Any) -> Any:
            median, worst, body = _time(lambda: get(path, **params))
            size = len(body) if isinstance(body, list) else len(body.get("items", [])) or ""
            reads.append(Timing(label, median, worst, f"{size} items" if size != "" else ""))
            return body

        base = f"/api/v1/migrations/{migration_id}"
        timed("overview", f"{base}/overview")
        timed("readiness", f"{base}/readiness")
        timed("issues (first page)", f"{base}/issues", limit=100)
        timed("datasets", f"{base}/datasets")
        results = timed("reconciliations", f"/api/v1/pipeline-runs/{second_run}/reconciliations")
        timed("rule runs", f"/api/v1/pipeline-runs/{second_run}/rules")
        timed("run diff (previous → latest)", f"/api/v1/pipeline-runs/{run_id}/diff/{second_run}")
        timed("audit events (first page)", f"{base}/audit-events", limit=100)
        timed("audit chain verify", f"{base}/audit-events/verify")
        largest = max(results, key=lambda r: int(r.get("line_count", 0) or 0))
        page = timed(
            f"recon lines {largest['recon_id']} (first page)",
            f"/api/v1/reconciliation-results/{largest['id']}/lines",
            limit=100,
        )
        if page["items"]:
            timed(
                "recon line drill-down",
                f"/api/v1/reconciliation-lines/{page['items'][0]['id']}/drilldown",
                limit=100,
            )
        if entry_key:
            timed("record inspector", f"/api/v1/pipeline-runs/{second_run}/records/{entry_key}")
        imports = get(f"{base}/datasets")
        gl = next((d for d in imports if d.get("dataset_type") == "gl_detail"), None)
        if gl and gl.get("active_import_id"):
            rows = f"/api/v1/imports/{gl['active_import_id']}/rows"
            first = timed("GL source rows (first page)", rows, limit=200)
            if first.get("next_cursor"):
                timed("GL source rows (next page)", rows, limit=200, cursor=first["next_cursor"])
    report.append(f"read endpoints (in process, {READ_REPEATS} repeats each, median / max ms):")
    report += [f"  {t.label:<34} {t.median_ms:8.1f} {t.max_ms:8.1f}  {t.detail}" for t in reads]
    return report
