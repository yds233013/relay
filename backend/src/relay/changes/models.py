"""Change requests and approvals (data-model.md §11, governance.md §2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.db_types import UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class ChangeRequestKind(StrEnum):
    COLUMN_MAPPING_SET = "column_mapping_set"
    ACCOUNT_MAPPING_SET = "account_mapping_set"
    RECORD_OVERRIDE = "record_override"
    ENTITY_DECISION = "entity_decision"
    DISPOSITION = "disposition"
    POLICY_CHANGE = "policy_change"
    GATE_WAIVER = "gate_waiver"
    READINESS_SIGNOFF = "readiness_signoff"


class ChangeRequestStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    APPLIED = "applied"
    STALE = "stale"
    FAILED_TO_APPLY = "failed_to_apply"


class ChangeRequestOrigin(StrEnum):
    OPERATOR = "operator"
    AI_FINDING = "ai_finding"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    __table_args__ = (
        check_in("kind", "kind", ChangeRequestKind),
        check_in("status", "status", ChangeRequestStatus),
        check_in("origin", "origin", ChangeRequestOrigin),
        UniqueConstraint("migration_id", "key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Typed per kind by relay.changes.schemas; before/after/impact are computed server-side.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    impact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    base_fingerprint: Mapped[str | None] = mapped_column(Text)
    base_entity_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    required_approvals: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    submitted_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    decided_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    applied_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at()


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        check_in("decision", "decision", ApprovalDecision),
        UniqueConstraint("change_request_id", "reviewer_user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("change_requests.id"), nullable=False
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewer_role_at_decision: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    satisfies_requirement_index: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = created_at()
