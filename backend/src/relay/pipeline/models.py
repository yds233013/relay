"""Pipeline runs and their persisted results (data-model.md §8 and §9).

Staged records use one semi-typed table (``staged_records``) instead of one table per record type:
the columns needed for filtering and drill-down are typed and indexed, and the full canonical
record is kept as validated JSON (docs/decisions/0004-persistence-and-pipeline.md).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import AmountType, BusinessDateType, UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunTrigger(StrEnum):
    MANUAL = "manual"
    CHANGE_REQUEST_APPLIED = "change_request_applied"
    IMPORT_ACTIVATED = "import_activated"


class RuleRunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class LineStatus(StrEnum):
    TIED = "tied"
    WITHIN_TOLERANCE = "within_tolerance"
    EXPLAINED = "explained"
    DISCREPANCY = "discrepancy"


class CandidateStatus(StrEnum):
    OPEN = "open"
    DECIDED_SAME = "decided_same"
    DECIDED_DISTINCT = "decided_distinct"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        check_in("status", "status", RunStatus),
        check_in("trigger", "trigger", RunTrigger),
        UniqueConstraint("migration_id", "sequence"),
        Index(
            "uq_pipeline_runs_succeeded_fingerprint",
            "migration_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
        ),
        Index(
            "uq_pipeline_runs_active_fingerprint",
            "migration_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_fingerprint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("change_requests.id"))
    stage_timings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    requested_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    finished_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())


class StagedRecord(Base):
    __tablename__ = "staged_records"
    __table_args__ = (
        UniqueConstraint("run_id", "natural_key"),
        Index("ix_staged_records_type_account", "run_id", "record_type", "account_code"),
        Index("ix_staged_records_party", "run_id", "party_code"),
        Index("ix_staged_records_document", "run_id", "document_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    record_type: Mapped[str] = mapped_column(Text, nullable=False)
    natural_key: Mapped[str] = mapped_column(Text, nullable=False)
    account_code: Mapped[str | None] = mapped_column(Text)
    party_code: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(Text)
    entry_number: Mapped[str | None] = mapped_column(Text)
    record_date: Mapped[date | None] = mapped_column(BusinessDateType())
    posting_period: Mapped[str | None] = mapped_column(Text)
    functional_amount: Mapped[Decimal | None] = mapped_column(AmountType())
    source_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("imports.id"))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    # Canonical record fields (amounts as strings, dates ISO) from relay.pipeline.staging.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RuleRun(Base):
    __tablename__ = "rule_runs"
    __table_args__ = (
        check_in("status", "status", RuleRunStatus),
        UniqueConstraint("run_id", "rule_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    exception_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_datasets: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)


class RuleExceptionRow(Base):
    __tablename__ = "rule_exceptions"
    __table_args__ = (
        UniqueConstraint("run_id", "fingerprint"),
        Index("ix_rule_exceptions_rule", "run_id", "rule_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    nature: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    subjects: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    discriminator: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[Any] = mapped_column(JSONB, nullable=True)
    observed: Mapped[Any] = mapped_column(JSONB, nullable=True)
    amount_at_risk: Mapped[Decimal | None] = mapped_column(AmountType())
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Source locations as {"import_id", "row_number", "line_start", "line_end"}.
    lineage: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)


class ReconciliationResultRow(Base):
    __tablename__ = "reconciliation_results"
    __table_args__ = (UniqueConstraint("run_id", "recon_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    recon_id: Mapped[str] = mapped_column(Text, nullable=False)
    recon_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    left_label: Mapped[str] = mapped_column(Text, nullable=False)
    right_label: Mapped[str] = mapped_column(Text, nullable=False)
    tolerance: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ReconciliationLineRow(Base):
    __tablename__ = "reconciliation_lines"
    __table_args__ = (
        check_in("status", "status", LineStatus),
        UniqueConstraint("result_id", "grain_key"),
        Index("ix_reconciliation_lines_status", "result_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_results.id"), nullable=False
    )
    grain_key: Mapped[str] = mapped_column(Text, nullable=False)
    grain: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    left_amount: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    right_amount: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    difference: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    explained_amount: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    unexplained_amount: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    # Secondary measures (for example R6 debit/credit differences), decimals as strings.
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ReconcilingItemRow(Base):
    __tablename__ = "reconciling_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reconciliation_lines.id"), nullable=False
    )
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    record_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class EntityCandidateRow(Base):
    __tablename__ = "entity_candidates"
    __table_args__ = (
        check_in("status", "status", CandidateStatus),
        UniqueConstraint("run_id", "party_type", "left_code", "right_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    party_type: Mapped[str] = mapped_column(Text, nullable=False)
    left_code: Mapped[str] = mapped_column(Text, nullable=False)
    right_code: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    strong: Mapped[bool] = mapped_column(Boolean, nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class ReadinessEvaluationRow(Base):
    __tablename__ = "readiness_evaluations"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=False, unique=True
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    overall: Mapped[str] = mapped_column(Text, nullable=False)
    unresolved_exposure: Mapped[Decimal] = mapped_column(AmountType(), nullable=False)
    # Governance facts supplied to the evaluation (required datasets, pending change requests).
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = created_at()


class GateResultRow(Base):
    __tablename__ = "gate_results"
    __table_args__ = (UniqueConstraint("evaluation_id", "gate_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("readiness_evaluations.id"), nullable=False
    )
    gate_id: Mapped[str] = mapped_column(Text, nullable=False)
    gate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observed: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    waiver_id: Mapped[str | None] = mapped_column(Text)
