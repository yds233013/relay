"""PostgreSQL-backed job queue (architecture.md §7, decision D-04)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class JobKind(StrEnum):
    PARSE_IMPORT = "parse_import"
    PROFILE_IMPORT = "profile_import"
    RUN_PIPELINE = "run_pipeline"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        check_in("kind", "kind", JobKind),
        check_in("status", "status", JobStatus),
        Index("ix_jobs_queued", "run_after", postgresql_where=text("status = 'queued'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Identifiers only (for example {"import_id": ...}); never data values.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(UtcTimestampType(), nullable=False)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    last_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
