"""Column mapping sets (data-model.md §6).

A column mapping set becomes ``approved`` only by applying an approved change request. At most one
set per dataset is approved at a time (partial unique index).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.schema import check_in, created_at, uuid_pk


class MappingSetStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    ABANDONED = "abandoned"
    """Its change request was withdrawn or went stale; draft again from the current state."""


class MappingBasis(StrEnum):
    EXACT = "exact"
    SYNONYM = "synonym"
    OPERATOR = "operator"
    AI_SUGGESTED = "ai_suggested"


class AccountMappingBasis(StrEnum):
    IMPORTED = "imported"
    """Carried from the account mapping file supplied by the project."""
    EXACT = "exact"
    NAME_MATCH = "name_match"
    OPERATOR = "operator"
    AI_SUGGESTED = "ai_suggested"


class ColumnMappingSet(Base):
    __tablename__ = "column_mapping_sets"
    __table_args__ = (
        check_in("status", "status", MappingSetStatus),
        UniqueConstraint("dataset_id", "version"),
        Index(
            "uq_column_mapping_sets_one_approved",
            "dataset_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    based_on_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("imports.id"))
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("change_requests.id", use_alter=True, name="fk_column_mapping_sets_cr")
    )
    exclude_rows_where_blank: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ColumnMapping(Base):
    __tablename__ = "column_mappings"
    __table_args__ = (
        check_in("basis", "basis", MappingBasis),
        UniqueConstraint("mapping_set_id", "target_field"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    mapping_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("column_mapping_sets.id"), nullable=False
    )
    target_field: Mapped[str] = mapped_column(Text, nullable=False)
    # The FieldMapping specification ({"source", "steps", "required"} or {"debit_credit"}),
    # validated by relay.mapping.transforms.FieldMapping.parse before it is stored.
    transform: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class AccountMappingSet(Base):
    """A complete legacy → target account mapping for a migration (data-model.md §6)."""

    __tablename__ = "account_mapping_sets"
    __table_args__ = (
        check_in("status", "status", MappingSetStatus),
        UniqueConstraint("migration_id", "version"),
        Index(
            "uq_account_mapping_sets_one_approved",
            "migration_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    based_on_set_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("account_mapping_sets.id"))
    based_on_import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("imports.id"))
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("change_requests.id", use_alter=True, name="fk_account_mapping_sets_cr")
    )
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AccountMapping(Base):
    __tablename__ = "account_mappings"
    __table_args__ = (
        check_in("basis", "basis", AccountMappingBasis),
        UniqueConstraint("mapping_set_id", "legacy_account_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    mapping_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account_mapping_sets.id"), nullable=False
    )
    legacy_account_code: Mapped[str] = mapped_column(Text, nullable=False)
    target_account_code: Mapped[str] = mapped_column(Text, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
