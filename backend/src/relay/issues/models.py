"""Issues: cross-run, fingerprinted problems with a lifecycle (data-model.md §10).

Lifecycle rules: governance.md §1.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import AmountType, UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class IssueStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    RESOLVED = "resolved"
    DISPOSITIONED = "dispositioned"
    CLOSED = "closed"


OPEN_STATUSES = frozenset(
    {IssueStatus.OPEN, IssueStatus.IN_PROGRESS, IssueStatus.AWAITING_VERIFICATION}
)


class IssueSource(StrEnum):
    RULE = "rule"
    RECONCILIATION = "reconciliation"
    NORMALIZATION = "normalization"
    MANUAL = "manual"


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        check_in("status", "status", IssueStatus),
        check_in("source", "source", IssueSource),
        UniqueConstraint("migration_id", "key"),
        UniqueConstraint("migration_id", "fingerprint"),
        Index("ix_issues_status_severity", "migration_id", "status", "severity"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    rule_or_recon_id: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    nature: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subjects: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    amount_at_risk: Mapped[Decimal | None] = mapped_column(AmountType())
    first_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    last_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    verified_absent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())


class IssueOccurrence(Base):
    __tablename__ = "issue_occurrences"

    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"), primary_key=True)
    rule_exception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rule_exceptions.id"), primary_key=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
