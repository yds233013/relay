"""Users and roles (data-model.md §3). Identity in the MVP is seeded users plus a dev header."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.db import Base
from relay.core.schema import check_in, created_at, uuid_pk


class Role(StrEnum):
    IMPLEMENTATION_SPECIALIST = "implementation_specialist"
    IMPLEMENTATION_LEAD = "implementation_lead"
    CUSTOMER_CONTROLLER = "customer_controller"
    ADMIN = "admin"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        check_in("role", "role", Role),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at()
