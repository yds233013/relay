"""Imports, pipeline runs, findings, reconciliations, drill-downs and records."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from relay.api.deps import BlobStoreDep, ReaderDep, SessionDep, SettingsDep, require
from relay.api.routers.workspace import exception_out, issue_out
from relay.api.schemas import (
    DocumentComparisonOut,
    DrilldownItemOut,
    DrilldownOut,
    ExceptionOut,
    FindingChangeOut,
    FingerprintOut,
    ImportOut,
    LineageOut,
    OpeningSummaryOut,
    Page,
    QuarantinedRowOut,
    QuarantineRefOut,
    ReconciliationLineOut,
    ReconciliationResultOut,
    ReconcilingItemOut,
    RecordOut,
    RuleCatalogOut,
    RuleRunOut,
    RunDiffOut,
    RunOut,
    SourceRowOut,
    StagedRecordOut,
    StatusChangeOut,
    amount_text,
)
from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.hashing import to_canonical
from relay.engine.rules import REGISTRY
from relay.identity.permissions import Permission
from relay.imports import read_model as imports_read
from relay.imports import service as imports
from relay.imports.blob_store import UploadTooLargeError
from relay.imports.models import Import, SourceRow
from relay.issues import read_model as issues_read
from relay.pipeline import overview as overview_read
from relay.pipeline import read_model as runs_read
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun
from relay.profiling.domain import DatasetProfile
from relay.workspace import service as workspace

router = APIRouter(prefix="/api/v1", tags=["runs"])

UploaderDep = Annotated[Actor, Depends(require(Permission.UPLOAD_IMPORT))]
RunRequesterDep = Annotated[Actor, Depends(require(Permission.REQUEST_PIPELINE_RUN))]


def import_out(record: Import) -> ImportOut:
    return ImportOut(
        id=record.id,
        dataset_id=record.dataset_id,
        sequence=record.sequence,
        original_filename=record.original_filename,
        status=record.status,
        encoding=record.encoding,
        delimiter=record.delimiter,
        header=[str(h) for h in record.header] if record.header is not None else None,
        row_count=record.row_count,
        quarantined_count=record.quarantined_count,
        error=record.error,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


@router.post(
    "/datasets/{dataset_id}/imports",
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": ImportOut, "description": "Identical file already imported"}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload_import(
    dataset_id: uuid.UUID,
    request: Request,
    response: Response,
    actor: UploaderDep,
    session: SessionDep,
    settings: SettingsDep,
    blob_store: BlobStoreDep,
    x_relay_filename: Annotated[str, Header(alias="X-Relay-Filename", max_length=1024)],
) -> ImportOut:
    """Upload a delimited text file as the request body (SEC-01, SEC-02, SEC-03).

    The body is read in chunks and refused as soon as it exceeds the configured limit; the file
    name header is percent-decoded and used for display only.
    """
    limits = imports.ImportLimits(
        settings.max_upload_bytes, settings.max_rows_per_import, settings.max_uploads_per_hour
    )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limits.max_upload_bytes:
        raise UploadTooLargeError(f"uploads are limited to {limits.max_upload_bytes} bytes")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limits.max_upload_bytes:
            raise UploadTooLargeError(f"uploads are limited to {limits.max_upload_bytes} bytes")
        chunks.append(chunk)

    def store() -> imports.UploadOutcome:
        dataset = workspace.get_dataset(session, dataset_id)
        return imports.upload(
            session,
            actor=actor,
            dataset=dataset,
            filename=unquote(x_relay_filename),
            chunks=chunks,
            blob_store=blob_store,
            limits=limits,
        )

    outcome = await run_in_threadpool(store)
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    return import_out(outcome.import_)


@router.get("/datasets/{dataset_id}/imports")
def list_imports(dataset_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> list[ImportOut]:
    workspace.get_dataset(session, dataset_id)
    return [import_out(i) for i in imports_read.imports_for(session, dataset_id)]


@router.get("/imports/{import_id}")
def get_import(import_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> ImportOut:
    return import_out(imports_read.get_import(session, import_id))


def row_out(row: SourceRow) -> SourceRowOut:
    return SourceRowOut(
        row_number=row.row_number,
        line_start=row.line_start,
        line_end=row.line_end,
        values={str(k): str(v) for k, v in row.values.items()},
    )


@router.get("/imports/{import_id}/rows")
def list_rows(
    import_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[SourceRowOut]:
    imports_read.get_import(session, import_id)
    rows = imports_read.rows(session, import_id, after_row=cursor, limit=limit)
    return Page(
        items=[row_out(r) for r in rows],
        next_cursor=str(rows[-1].row_number) if len(rows) == limit else None,
    )


@router.get("/imports/{import_id}/quarantine")
def list_quarantine(
    import_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[QuarantinedRowOut]:
    imports_read.get_import(session, import_id)
    return [
        QuarantinedRowOut(
            id=q.id,
            quarantine_key=q.quarantine_key,
            line_start=q.line_start,
            line_end=q.line_end,
            reason=q.reason,
            field_counts=list(q.field_counts),
            raw_text=q.raw_text,
        )
        for q in imports_read.quarantine(session, import_id)
    ]


@router.get("/imports/{import_id}/profile")
def get_profile(import_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> DatasetProfile:
    imports_read.get_import(session, import_id)
    profile = imports_read.profile(session, import_id)
    if profile is None:
        raise runs_read.ResourceNotFoundError("profile not available")
    return DatasetProfile.model_validate(profile.profile)


def run_out(run: PipelineRun, current_fingerprint: str | None) -> RunOut:
    return RunOut(
        id=run.id,
        sequence=run.sequence,
        status=run.status,
        trigger=run.trigger,
        fingerprint=run.fingerprint,
        result_fingerprint=run.result_fingerprint,
        is_current=None if current_fingerprint is None else run.fingerprint == current_fingerprint,
        error=run.error,
        stage_timings=run.stage_timings,
        counts=run.counts,
        requested_at=run.requested_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post("/migrations/{migration_id}/pipeline-runs", status_code=status.HTTP_202_ACCEPTED)
def request_pipeline_run(
    migration_id: uuid.UUID, response: Response, actor: RunRequesterDep, session: SessionDep
) -> RunOut:
    """Idempotent on the input fingerprint: an equal queued, running or succeeded run is reused."""
    workspace.get_migration(session, migration_id)
    outcome = pipeline.request_run(session, actor=actor, migration_id=migration_id)
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    return run_out(outcome.run, outcome.run.fingerprint)


@router.get("/migrations/{migration_id}/pipeline-runs")
def list_runs(
    migration_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RunOut]:
    workspace.get_migration(session, migration_id)
    current = pipeline.current_fingerprint(session, migration_id).fingerprint
    return [run_out(r, current) for r in runs_read.runs_for(session, migration_id, limit)]


@router.get("/migrations/{migration_id}/fingerprint")
def fingerprint(migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> FingerprintOut:
    workspace.get_migration(session, migration_id)
    configuration = pipeline.current_fingerprint(session, migration_id)
    latest = runs_read.latest_succeeded_run(session, migration_id)
    components = to_canonical(configuration.components)
    return FingerprintOut(
        fingerprint=configuration.fingerprint,
        components=components if isinstance(components, dict) else {},
        latest_run_id=latest.id if latest else None,
        latest_run_is_current=bool(latest and latest.fingerprint == configuration.fingerprint),
    )


def _run_and_currency(session: Session, run_id: uuid.UUID) -> tuple[PipelineRun, Currency]:
    run = runs_read.get_run(session, run_id)
    return run, workspace.get_migration(session, run.migration_id).functional_currency


@router.get("/pipeline-runs/{run_id}")
def get_run(run_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> RunOut:
    run = runs_read.get_run(session, run_id)
    return run_out(run, pipeline.current_fingerprint(session, run.migration_id).fingerprint)


@router.get("/pipeline-runs/{run_id}/rules")
def list_rule_runs(run_id: uuid.UUID, _actor: ReaderDep, session: SessionDep) -> list[RuleRunOut]:
    runs_read.get_run(session, run_id)
    return [
        RuleRunOut(
            rule_id=r.rule_id,
            rule_version=r.rule_version,
            title=r.title,
            status=r.status,
            exception_count=r.exception_count,
            missing_datasets=list(r.missing_datasets),
            error=r.error,
        )
        for r in runs_read.rule_runs(session, run_id)
    ]


@router.get("/pipeline-runs/{run_id}/exceptions")
def list_exceptions(
    run_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    rule_id: Annotated[str | None, Query(max_length=64)] = None,
    severity: Annotated[str | None, Query(max_length=16)] = None,
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[ExceptionOut]:
    _, currency = _run_and_currency(session, run_id)
    rows = runs_read.exceptions(
        session, run_id, rule_id=rule_id, severity=severity, after_id=cursor, limit=limit
    )
    return Page(
        items=[exception_out(r, currency) for r in rows],
        next_cursor=str(rows[-1].id) if len(rows) == limit else None,
    )


@router.get("/pipeline-runs/{run_id}/reconciliations")
def list_reconciliations(
    run_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[ReconciliationResultOut]:
    _, currency = _run_and_currency(session, run_id)
    return [
        ReconciliationResultOut(
            id=r.id,
            recon_id=r.recon_id,
            recon_version=r.recon_version,
            title=r.title,
            purpose=r.purpose,
            status=r.status,
            applicable=r.applicable,
            left_label=r.left_label,
            right_label=r.right_label,
            tolerance=amount_text(r.tolerance, currency) or "0",
            line_count=r.line_count,
            discrepancy_count=r.discrepancy_count,
            note=r.note,
        )
        for r in runs_read.reconciliation_results(session, run_id)
    ]


def _amount(value: Decimal, currency: Currency) -> str:
    return amount_text(value, currency) or "0"


@router.get("/reconciliation-results/{result_id}/lines")
def list_lines(
    result_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    line_status: Annotated[str | None, Query(alias="status", max_length=32)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[ReconciliationLineOut]:
    result = runs_read.get_result(session, result_id)
    _, currency = _run_and_currency(session, result.run_id)
    rows = runs_read.lines(session, result_id, status=line_status, after_key=cursor, limit=limit)
    return Page(
        items=[
            ReconciliationLineOut(
                id=line.id,
                grain_key=line.grain_key,
                grain=line.grain,
                left_amount=_amount(line.left_amount, currency),
                right_amount=_amount(line.right_amount, currency),
                difference=_amount(line.difference, currency),
                explained_amount=_amount(line.explained_amount, currency),
                unexplained_amount=_amount(line.unexplained_amount, currency),
                status=line.status,
                extra=line.extra,
                currency=currency.code,
                items=[
                    ReconcilingItemOut(
                        classification=i.classification,
                        amount=_amount(i.amount, currency),
                        record_keys=list(i.record_keys),
                        message=i.message,
                    )
                    for i in runs_read.items_for(session, line.id)
                ],
            )
            for line in rows
        ],
        next_cursor=rows[-1].grain_key if len(rows) == limit else None,
    )


@router.get("/reconciliation-lines/{line_id}/drilldown")
def drilldown(
    line_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> DrilldownOut:
    """Both sides' contributing records, with lineage to source rows."""
    line = runs_read.get_line(session, line_id)
    run_id = runs_read.get_result(session, line.result_id).run_id
    _, currency = _run_and_currency(session, run_id)
    data = runs_read.drilldown(session, line_id, limit=limit)

    def money(value: Any) -> str:
        return _amount(Decimal(str(value)), currency)

    def record(view: dict[str, Any]) -> StagedRecordOut:
        amount = view.get("functional_amount")
        open_amount = view.get("open_amount")
        return StagedRecordOut(
            natural_key=view["natural_key"],
            record_type=view["record_type"],
            account_code=view.get("account_code"),
            party_code=view.get("party_code"),
            document_number=view.get("document_number"),
            entry_number=view.get("entry_number"),
            record_date=view.get("record_date"),
            posting_period=view.get("posting_period"),
            functional_amount=None if amount is None else money(amount),
            lineage=LineageOut(**view["lineage"]) if view.get("lineage") else None,
            role=view.get("role"),
            counted_by_entry_date=view.get("counted_by_entry_date"),
            counted_by_posting_period=view.get("counted_by_posting_period"),
            open_amount=None if open_amount is None else money(open_amount),
        )

    opening = data.get("opening")
    extra = to_canonical(data.get("extra", {}))
    return DrilldownOut(
        recon_id=data["recon_id"],
        grain=data["grain"],
        left_amount=money(data["left_amount"]),
        right_amount=money(data["right_amount"]),
        difference=money(data["difference"]),
        unexplained_amount=money(data["unexplained_amount"]),
        status=data["status"],
        currency=currency.code,
        run_id=run_id,
        basis=data["basis"],
        limits=data.get("limits"),
        left_label=data.get("left_label"),
        right_label=data.get("right_label"),
        accounts=data.get("accounts", []),
        documents=[
            DocumentComparisonOut(
                document=d["document"],
                status=d["status"],
                left_amount=money(d["left_amount"]),
                right_amount=money(d["right_amount"]),
                difference=money(d["difference"]),
                left_records=[record(r) for r in d["left_records"]],
                right_records=[record(r) for r in d["right_records"]],
            )
            for d in data.get("documents", [])
        ],
        matched_document_count=data.get("matched_document_count"),
        opening=OpeningSummaryOut(**{k: money(v) for k, v in opening.items()}) if opening else None,
        control_balances=[record(r) for r in data.get("control_balances", [])],
        detail_line_count=data.get("detail_line_count"),
        detail_total=money(data["detail_total"]) if "detail_total" in data else None,
        date_period_disagreements=[record(r) for r in data.get("date_period_disagreements", [])],
        quarantined_rows=[QuarantineRefOut(**q) for q in data.get("quarantined_rows", [])],
        items=[
            DrilldownItemOut(
                classification=i["classification"],
                amount=money(i["amount"]),
                message=i["message"],
                records=[record(r) for r in i["records"]],
            )
            for i in data.get("items", [])
        ],
        extra=extra if isinstance(extra, dict) else {},
    )


@router.get("/pipeline-runs/{run_id}/records/{natural_key:path}")
def get_record(
    run_id: uuid.UUID, natural_key: str, _actor: ReaderDep, session: SessionDep
) -> RecordOut:
    run, currency = _run_and_currency(session, run_id)
    record = runs_read.get_record(session, run_id, natural_key)
    source_row = None
    source_header = None
    if record.source_import_id and record.source_row_number:
        source_import = imports_read.get_import(session, record.source_import_id)
        source_header = [str(h) for h in source_import.header] if source_import.header else None
        rows = imports_read.rows(
            session, record.source_import_id, after_row=record.source_row_number - 1, limit=1
        )
        if rows and rows[0].row_number == record.source_row_number:
            source_row = row_out(rows[0])
    view = to_canonical(runs_read.record_view(record))
    return RecordOut(
        run_id=run_id,
        record=view if isinstance(view, dict) else {},
        data=record.data,
        source_row=source_row,
        source_header=source_header,
        related_issues=[
            issue_out(i, currency)
            for i in issues_read.issues_touching(session, run.migration_id, natural_key)
        ],
    )


@router.get("/pipeline-runs/{run_id}/diff/{other_run_id}")
def diff_runs(
    run_id: uuid.UUID, other_run_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> RunDiffOut:
    """Changes from ``run_id`` to ``other_run_id``: inputs, findings, reconciliations, gates."""
    diff = overview_read.run_diff(session, run_id, other_run_id)
    return RunDiffOut(
        base_run_id=diff["base_run_id"],
        other_run_id=diff["other_run_id"],
        changed_fingerprint_components=diff["changed_fingerprint_components"],
        findings_added=[FindingChangeOut(**f) for f in diff["findings_added"]],
        findings_removed=[FindingChangeOut(**f) for f in diff["findings_removed"]],
        reconciliation_changes=[
            StatusChangeOut(key=c["recon_id"], before=c["before"], after=c["after"])
            for c in diff["reconciliation_changes"]
        ],
        gate_changes=[
            StatusChangeOut(key=c["gate_id"], before=c["before"], after=c["after"])
            for c in diff["gate_changes"]
        ],
        entity_candidates_before=diff["entity_candidates"]["before"] or 0,
        entity_candidates_after=diff["entity_candidates"]["after"] or 0,
    )


@router.get("/rules")
def rule_catalog(_actor: ReaderDep) -> list[RuleCatalogOut]:
    return [
        RuleCatalogOut(
            rule_id=spec.id,
            version=spec.version,
            title=spec.title,
            severity=spec.severity.value,
            nature=spec.nature.value,
            category=spec.category.value,
            requires=sorted(spec.requires),
        )
        for spec, _ in sorted(REGISTRY.values(), key=lambda item: item[0].id)
    ]
