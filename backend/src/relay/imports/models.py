"""Stored files, imports, immutable source rows and quarantined rows (data-model.md §5).

``source_rows`` and ``quarantined_rows`` are append-only: a database trigger rejects UPDATE and
DELETE (FC-08). Rows keep raw string values exactly as read.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class ImportStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class QuarantineReason(StrEnum):
    FIELD_COUNT_MISMATCH = "field_count_mismatch"
    UNTERMINATED_QUOTE = "unterminated_quote"
    FIELD_TOO_LONG = "field_too_long"


class StoredFile(Base):
    __tablename__ = "stored_files"
    __table_args__ = (CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    first_uploaded_at: Mapped[datetime] = created_at()
    first_uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Import(Base):
    __tablename__ = "imports"
    __table_args__ = (
        check_in("status", "status", ImportStatus),
        UniqueConstraint("dataset_id", "stored_file_id"),
        UniqueConstraint("dataset_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    stored_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stored_files.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    encoding: Mapped[str | None] = mapped_column(Text)
    delimiter: Mapped[str | None] = mapped_column(Text)
    # List of header strings as read.
    header: Mapped[list[Any] | None] = mapped_column(JSONB)
    row_count: Mapped[int | None] = mapped_column(Integer)
    quarantined_count: Mapped[int | None] = mapped_column(Integer)
    # Structured failure: {"code": ..., "detail": ...}; never raw row values.
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    completed_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class SourceRow(Base):
    __tablename__ = "source_rows"
    __table_args__ = (UniqueConstraint("import_id", "row_number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    # {header: raw string} exactly as read.
    values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    row_hash: Mapped[str] = mapped_column(Text, nullable=False)


class QuarantinedRow(Base):
    __tablename__ = "quarantined_rows"
    __table_args__ = (
        check_in("reason", "reason", QuarantineReason),
        UniqueConstraint("import_id", "line_start"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"), nullable=False)
    quarantine_key: Mapped[str] = mapped_column(Text, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    field_counts: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("imports.id"), nullable=False, unique=True
    )
    profiler_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Validated by relay.profiling.domain.DatasetProfile.
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = created_at()
