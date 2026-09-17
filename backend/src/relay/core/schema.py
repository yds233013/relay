"""Shared helpers for table definitions: enum check constraints and standard columns."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db_types import UtcTimestampType


def enum_values(enum: type[StrEnum] | Iterable[str]) -> list[str]:
    return [str(member) for member in enum]


def check_in(name: str, column: str, values: type[StrEnum] | Iterable[str]) -> CheckConstraint:
    """``CHECK (column IN (...))`` for a ``TEXT`` enum column (data-model.md §1)."""
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in enum_values(values))
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True)


def created_at() -> Mapped[datetime]:
    return mapped_column(UtcTimestampType(), nullable=False, server_default=text("now()"))
