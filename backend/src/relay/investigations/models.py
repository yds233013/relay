"""Investigations, their transcript steps and findings (data-model.md §13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class InvestigationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class StepType(StrEnum):
    MODEL_MESSAGE = "model_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        check_in("status", "status", InvestigationStatus),
        Index("ix_investigations_migration", "migration_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    started_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Which tools were called with which arguments; the log of what was sent to the provider.
    sent_fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    finished_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()


class InvestigationStep(Base):
    __tablename__ = "investigation_steps"
    __table_args__ = (
        check_in("type", "type", StepType),
        UniqueConstraint("investigation_id", "seq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigations.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(Text)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Canonical JSON as sent to the model: redacted and bounded.
    result: Mapped[str | None] = mapped_column(Text)
    result_sha256: Mapped[str | None] = mapped_column(Text)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        check_in("verification_status", "verification_status", VerificationStatus),
        check_in("review_status", "review_status", ReviewStatus),
        Index("ix_findings_investigation", "investigation_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    investigation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("investigations.id"), nullable=False
    )
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    issue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("issues.id"))
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    affected_record_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    open_questions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)
    verification_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    review_status: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    review_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at()
