"""Append-only, hash-chained audit events (data-model.md §12, governance.md §3).

A trigger rejects UPDATE, DELETE and TRUNCATE. ``migration_seq`` is gapless per migration and is
assigned under a per-migration advisory lock. Platform events (no migration) form their own chain.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import UtcTimestampType
from relay.core.schema import check_in


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    AI = "ai"


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        check_in("actor_type", "actor_type", ActorType),
        UniqueConstraint("migration_id", "migration_seq", postgresql_nulls_not_distinct=True),
        Index("ix_audit_events_entity", "migration_id", "entity_type", "entity_id"),
        Index("ix_audit_events_occurred", "migration_id", "occurred_at"),
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    migration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    migration_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcTimestampType(), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Minimal typed diffs; never raw source row values.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hash: Mapped[str] = mapped_column(Text, nullable=False)
