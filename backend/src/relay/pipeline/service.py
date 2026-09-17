"""Pipeline runs: request (idempotent on fingerprint), execute, persist (architecture.md §4).

Execution happens in one transaction: staged records, findings, reconciliations, candidates, issue
synchronization, readiness and the run's final status become visible together or not at all.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, ClassVar

from psycopg.types.json import Jsonb
from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.changes import service as changes
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.db import copy_rows
from relay.core.db_types import AmountType
from relay.core.errors import RelayError
from relay.core.hashing import to_canonical
from relay.core.ids import uuid7
from relay.core.money import validate_amount
from relay.engine.exceptions import RuleException
from relay.engine.pipeline import EngineResult, run_engine
from relay.engine.policy import Policy
from relay.engine.readiness import GATE_SET_VERSION, GovernanceFacts, Readiness, evaluate_readiness
from relay.engine.reconciliation import RECONCILIATION_VERSION, ReconResult, grain_key
from relay.engine.rules import REGISTRY
from relay.imports.blob_store import BlobStore
from relay.issues.service import IssueSeed, synchronize_issues
from relay.jobs import service as jobs
from relay.jobs.models import JobKind
from relay.pipeline.inputs import RunConfiguration, load_configuration, load_engine_inputs
from relay.pipeline.models import (
    CandidateStatus,
    EntityCandidateRow,
    GateResultRow,
    PipelineRun,
    ReadinessEvaluationRow,
    ReconciliationLineRow,
    ReconciliationResultRow,
    ReconcilingItemRow,
    RuleExceptionRow,
    RuleRun,
    RuleRunStatus,
    RunStatus,
    RunTrigger,
    StagedRecord,
)
from relay.pipeline.staging import staged_rows
from relay.workspace.models import Migration


class PipelineRunNotFoundError(RelayError):
    code: ClassVar[str] = "pipeline_run.not_found"
    title: ClassVar[str] = "Pipeline run not found"
    http_status: ClassVar[int] = 404


@dataclass(frozen=True, slots=True)
class RunRequest:
    run: PipelineRun
    created: bool


def lock_migration(session: Session, migration_id: uuid.UUID) -> None:
    """Serialize run requests and executions per migration.

    Lock order: take this lock before any audit write in the same transaction (the worker takes
    it first and then writes audit events), or the two can deadlock.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": audit.advisory_lock_key("pipeline", migration_id)},
    )


def request_run(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    trigger: RunTrigger = RunTrigger.MANUAL,
    change_request_id: uuid.UUID | None = None,
    clock: Clock | None = None,
) -> RunRequest:
    lock_migration(session, migration_id)
    configuration = load_configuration(session, migration_id)
    existing = session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.migration_id == migration_id,
            PipelineRun.fingerprint == configuration.fingerprint,
            PipelineRun.status.in_(
                [RunStatus.SUCCEEDED.value, RunStatus.QUEUED.value, RunStatus.RUNNING.value]
            ),
        )
        .order_by(PipelineRun.sequence.desc())
    ).first()
    if existing is not None:
        return RunRequest(existing, created=False)
    sequence = (
        session.scalar(
            select(func.max(PipelineRun.sequence)).where(PipelineRun.migration_id == migration_id)
        )
        or 0
    ) + 1
    run = PipelineRun(
        id=uuid7(clock),
        migration_id=migration_id,
        sequence=sequence,
        fingerprint=configuration.fingerprint,
        fingerprint_components=to_canonical(configuration.components),
        status=RunStatus.QUEUED.value,
        trigger=trigger.value,
        triggered_by_user_id=actor.user_id,
        change_request_id=change_request_id,
        stage_timings={},
        counts={},
    )
    session.add(run)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="pipeline_run.requested",
        entity_type="pipeline_run",
        entity_id=run.id,
        migration_id=migration_id,
        change_request_id=change_request_id,
        after={"sequence": sequence, "fingerprint": run.fingerprint, "trigger": trigger.value},
        clock=clock,
    )
    jobs.enqueue(
        session,
        JobKind.RUN_PIPELINE,
        {"run_id": str(run.id)},
        dedupe_key=f"run_pipeline:{run.id}",
        clock=clock,
    )
    return RunRequest(run, created=True)


def current_fingerprint(session: Session, migration_id: uuid.UUID) -> RunConfiguration:
    return load_configuration(session, migration_id)


def execute_run(
    session: Session, *, run_id: uuid.UUID, blob_store: BlobStore, clock: Clock | None = None
) -> PipelineRun:
    """Job handler. Idempotent: a run that is no longer queued is returned unchanged."""
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise PipelineRunNotFoundError(f"pipeline run {run_id} does not exist")
    lock_migration(session, run.migration_id)
    session.refresh(run, with_for_update=True)
    if run.status != RunStatus.QUEUED.value:
        return run
    timings: dict[str, int] = {}
    started = time.perf_counter_ns()
    now = (clock or SystemClock()).now()
    run.started_at = now
    configuration = load_configuration(session, run.migration_id)
    if configuration.fingerprint != run.fingerprint:
        _finish_failed(
            session,
            run,
            {
                "code": "pipeline.inputs_changed",
                "detail": "configuration changed after the request",
            },
            clock,
        )
        return run
    inputs = load_engine_inputs(configuration, blob_store)
    timings["load_ms"] = (time.perf_counter_ns() - started) // 1_000_000
    mark = time.perf_counter_ns()
    result = run_engine(inputs, configuration.overlays, configuration.policy)
    timings["engine_ms"] = (time.perf_counter_ns() - mark) // 1_000_000
    mark = time.perf_counter_ns()
    exception_ids = _persist_results(session, run, result, configuration.policy)
    timings["persist_ms"] = (time.perf_counter_ns() - mark) // 1_000_000
    mark = time.perf_counter_ns()
    migration = session.get(Migration, run.migration_id, with_for_update=True)
    if migration is None:
        raise PipelineRunNotFoundError("migration disappeared")
    summary = synchronize_issues(
        session,
        migration=migration,
        run_id=run.id,
        seeds=_issue_seeds(result, exception_ids),
        clock=clock,
    )
    timings["issues_ms"] = (time.perf_counter_ns() - mark) // 1_000_000
    facts = GovernanceFacts(
        required_datasets=configuration.required_dataset_types,
        column_mapping_sets_approved=configuration.all_mapped,
        account_mapping_set_approved=configuration.account_mapping_set_id is not None,
        current_fingerprint=None,
        pending_change_requests=changes.pending_count(session, run.migration_id),
    )
    readiness = evaluate_readiness(result, configuration.overlays, configuration.policy, facts)
    _persist_readiness(session, run, configuration, readiness, facts)
    run.status = RunStatus.SUCCEEDED.value
    run.result_fingerprint = result.result_fingerprint
    run.finished_at = (clock or SystemClock()).now()
    timings["total_ms"] = (time.perf_counter_ns() - started) // 1_000_000
    run.stage_timings = timings
    run.counts = {
        "findings": len(result.exceptions),
        "findings_by_severity": dict(Counter(e.severity.value for e in result.exceptions)),
        "staged_records": session.scalar(
            select(func.count()).select_from(StagedRecord).where(StagedRecord.run_id == run.id)
        ),
        "reconciliation_discrepancies": sum(len(r.discrepancies()) for r in result.reconciliations),
        "entity_candidates": len(result.candidates),
        "issues_created": summary.created,
        "issues_reopened": summary.reopened,
        "issues_verified_resolved": summary.verified_resolved,
    }
    session.flush()
    audit.record(
        session,
        actor=Actor.system(),
        action="pipeline_run.succeeded",
        entity_type="pipeline_run",
        entity_id=run.id,
        migration_id=run.migration_id,
        after={
            "sequence": run.sequence,
            "result_fingerprint": run.result_fingerprint,
            "counts": run.counts,
        },
        clock=clock,
    )
    audit.record(
        session,
        actor=Actor.system(),
        action="readiness.evaluated",
        entity_type="pipeline_run",
        entity_id=run.id,
        migration_id=run.migration_id,
        after={"ready": readiness.ready, "failing_gates": readiness.failing()},
        clock=clock,
    )
    return run


def mark_failed(
    session: Session, *, run_id: uuid.UUID, error: dict[str, Any], clock: Clock | None = None
) -> None:
    """Record a failure after the execution transaction rolled back."""
    run = session.get(PipelineRun, run_id, with_for_update=True)
    if run is None or run.status not in {RunStatus.QUEUED.value, RunStatus.RUNNING.value}:
        return
    _finish_failed(session, run, error, clock)


def _finish_failed(
    session: Session, run: PipelineRun, error: dict[str, Any], clock: Clock | None
) -> None:
    run.status = RunStatus.FAILED.value
    run.error = error
    run.finished_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=Actor.system(),
        action="pipeline_run.failed",
        entity_type="pipeline_run",
        entity_id=run.id,
        migration_id=run.migration_id,
        after={"sequence": run.sequence, "error": error},
        clock=clock,
    )


def _lineage(finding: RuleException) -> list[dict[str, Any]]:
    lineage = []
    for location in finding.lineage:
        try:
            import_id = str(uuid.UUID(location.file_name))
        except ValueError:
            continue
        lineage.append(
            {
                "import_id": import_id,
                "row_number": location.row_number,
                "line_start": location.line_start,
                "line_end": location.line_end,
            }
        )
    return lineage


def _insert(session: Session, model: type[Any], rows: list[dict[str, Any]]) -> None:
    """COPY rows into the model's table. Amounts are validated; JSON values are wrapped."""
    if not rows:
        return
    table = model.__table__
    columns = list(rows[0])
    json_columns = {c.name for c in table.columns if isinstance(c.type, JSONB)}
    amount_columns = {c.name for c in table.columns if isinstance(c.type, AmountType)}

    def values(row: dict[str, Any]) -> list[object]:
        converted: list[object] = []
        for column in columns:
            value = row[column]
            if value is not None and column in json_columns:
                value = Jsonb(value)
            elif value is not None and column in amount_columns:
                value = validate_amount(value)
            converted.append(value)
        return converted

    copy_rows(session, table.name, columns, (values(row) for row in rows))


def _persist_results(
    session: Session, run: PipelineRun, result: EngineResult, policy: Policy
) -> dict[str, uuid.UUID]:
    staged = [{"id": uuid7(), **row} for row in staged_rows(result.snapshot, run.id)]
    _insert(session, StagedRecord, staged)

    counts = Counter(e.rule_id for e in result.exceptions)
    skipped = {s.rule_id: s.missing_datasets for s in result.skipped_rules}
    rule_rows = []
    for rule_id, (spec, _) in sorted(REGISTRY.items()):
        status = (
            RuleRunStatus.NOT_APPLICABLE
            if rule_id in skipped
            else RuleRunStatus.FAILED
            if counts[rule_id]
            else RuleRunStatus.PASSED
        )
        rule_rows.append(
            {
                "id": uuid7(),
                "run_id": run.id,
                "rule_id": rule_id,
                "rule_version": spec.version,
                "title": spec.title,
                "status": status.value,
                "exception_count": counts[rule_id],
                "missing_datasets": list(skipped.get(rule_id, ())),
            }
        )
    _insert(session, RuleRun, rule_rows)

    exception_ids: dict[str, uuid.UUID] = {}
    exception_rows = []
    for finding in result.exceptions:
        exception_id = uuid7()
        exception_ids[finding.fingerprint] = exception_id
        exception_rows.append(
            {
                "id": exception_id,
                "run_id": run.id,
                "rule_id": finding.rule_id,
                "rule_version": finding.rule_version,
                "fingerprint": finding.fingerprint,
                "severity": finding.severity.value,
                "nature": finding.nature.value,
                "category": finding.category.value,
                "subjects": list(finding.subjects),
                "discriminator": finding.discriminator,
                "message": finding.message,
                "expected": to_canonical(finding.expected),
                "observed": to_canonical(finding.observed),
                "amount_at_risk": finding.amount_at_risk,
                "details": to_canonical(finding.details),
                "lineage": _lineage(finding),
            }
        )
    _insert(session, RuleExceptionRow, exception_rows)

    by_recon: dict[str, list[ReconResult]] = {}
    for recon in result.reconciliations:
        by_recon.setdefault(recon.recon_id, []).append(recon)
    for recon_id, parts in by_recon.items():
        first = parts[0]
        lines = [line for part in parts for line in part.lines]
        applicable = any(part.applicable for part in parts)
        statuses = [part.status for part in parts]
        recon_status = next(
            (s for s in ("discrepancy", "tied_with_explained_items", "tied") if s in statuses),
            "not_applicable",
        )
        result_row = ReconciliationResultRow(
            id=uuid7(),
            run_id=run.id,
            recon_id=recon_id,
            recon_version=RECONCILIATION_VERSION,
            title=first.title,
            purpose=first.purpose,
            status=recon_status if applicable else "not_applicable",
            applicable=applicable,
            left_label=first.left_label,
            right_label=first.right_label,
            tolerance=first.tolerance,
            line_count=len(lines),
            discrepancy_count=sum(len(part.discrepancies()) for part in parts),
            note="; ".join(part.note for part in parts if part.note),
        )
        session.add(result_row)
        session.flush()
        line_rows: list[dict[str, Any]] = []
        item_rows: list[dict[str, Any]] = []
        for part in parts:
            for line in part.lines:
                line_id = uuid7()
                line_rows.append(
                    {
                        "id": line_id,
                        "result_id": result_row.id,
                        "grain_key": grain_key(recon_id, line.grain),
                        "grain": dict(line.grain),
                        "left_amount": line.left,
                        "right_amount": line.right,
                        "difference": line.difference,
                        "explained_amount": line.explained,
                        "unexplained_amount": line.unexplained,
                        "status": line.status(part.tolerance).value,
                        "extra": to_canonical(line.extra),
                    }
                )
                item_rows.extend(
                    {
                        "id": uuid7(),
                        "line_id": line_id,
                        "classification": item.classification,
                        "amount": item.amount,
                        "record_keys": list(item.record_keys),
                        "message": item.message,
                    }
                    for item in line.items
                )
        _insert(session, ReconciliationLineRow, line_rows)
        _insert(session, ReconcilingItemRow, item_rows)

    candidate_rows = []
    for candidate in result.candidates:
        decided = (
            frozenset(candidate.members) in result.clusters[candidate.party_type].decided_pairs
        )
        same = decided and result.clusters[candidate.party_type].cluster(
            candidate.left
        ) == result.clusters[candidate.party_type].cluster(candidate.right)
        candidate_rows.append(
            {
                "id": uuid7(),
                "run_id": run.id,
                "party_type": candidate.party_type.value,
                "left_code": candidate.left,
                "right_code": candidate.right,
                "score": candidate.score,
                "strong": candidate.score >= policy.entity_strong_threshold,
                "features": to_canonical({k: str(v) for k, v in candidate.features.items()}),
                "status": (
                    CandidateStatus.DECIDED_SAME
                    if same
                    else CandidateStatus.DECIDED_DISTINCT
                    if decided
                    else CandidateStatus.OPEN
                ).value,
            }
        )
    _insert(session, EntityCandidateRow, candidate_rows)
    session.flush()
    return exception_ids


def _issue_title(finding: RuleException, result: EngineResult) -> str:
    if finding.rule_id in REGISTRY:
        title = REGISTRY[finding.rule_id][0].title
    elif finding.rule_id.startswith("RECON."):
        recon_id = finding.rule_id.split(".", 1)[1]
        title = next((r.title for r in result.reconciliations if r.recon_id == recon_id), recon_id)
    else:
        title = finding.rule_id
    subjects = ", ".join(finding.subjects[:2]) + (", ..." if len(finding.subjects) > 2 else "")
    return f"{title}: {subjects}" if subjects else title


def _issue_seeds(result: EngineResult, exception_ids: dict[str, uuid.UUID]) -> dict[str, IssueSeed]:
    return {
        finding.fingerprint: IssueSeed(
            rule_exception_id=exception_ids[finding.fingerprint],
            fingerprint=finding.fingerprint,
            rule_id=finding.rule_id,
            category=finding.category.value,
            nature=finding.nature.value,
            severity=finding.severity.value,
            title=_issue_title(finding, result),
            subjects=finding.subjects,
            amount_at_risk=finding.amount_at_risk,
        )
        for finding in result.exceptions
    }


def _persist_readiness(
    session: Session,
    run: PipelineRun,
    configuration: RunConfiguration,
    readiness: Readiness,
    facts: GovernanceFacts,
) -> None:
    evaluation = ReadinessEvaluationRow(
        id=uuid7(),
        run_id=run.id,
        policy_version=configuration.policy_version,
        overall="ready" if readiness.ready else "not_ready",
        unresolved_exposure=readiness.unresolved_exposure,
        facts={
            "required_datasets": sorted(facts.required_datasets),
            "column_mapping_sets_approved": facts.column_mapping_sets_approved,
            "account_mapping_set_approved": facts.account_mapping_set_approved,
            "pending_change_requests": facts.pending_change_requests,
        },
    )
    session.add(evaluation)
    session.flush()
    session.execute(
        insert(GateResultRow),
        [
            {
                "id": uuid7(),
                "evaluation_id": evaluation.id,
                "gate_id": gate.gate_id,
                "gate_version": GATE_SET_VERSION,
                "title": gate.title,
                "status": gate.status.value,
                "blocking": True,
                "observed": gate.observed,
                "threshold": gate.threshold,
                "summary": gate.summary,
                "evidence": list(gate.evidence),
                "waiver_id": gate.waiver_id,
            }
            for gate in readiness.gates
        ],
    )
