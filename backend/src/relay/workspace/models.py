"""Companies, migrations (with conversion plans), source systems and datasets (data-model.md §4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from relay.core.currency import Currency
from relay.core.db import Base
from relay.core.db_types import BusinessDateType, CurrencyCodeType, UtcTimestampType
from relay.core.schema import check_in, created_at, uuid_pk


class MigrationStatus(StrEnum):
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    SIGNED_OFF = "signed_off"
    LAUNCHED = "launched"
    ARCHIVED = "archived"


class SourceSystemKind(StrEnum):
    LEGACY_ERP = "legacy_erp"
    SPREADSHEET = "spreadsheet"
    BANK = "bank"
    BILLING = "billing"
    CRM = "crm"
    OTHER = "other"


class DatasetType(StrEnum):
    LEGACY_COA = "legacy_coa"
    TARGET_COA = "target_coa"
    ACCOUNT_MAPPING = "account_mapping"
    GL_DETAIL = "gl_detail"
    TRIAL_BALANCE = "trial_balance"
    CUSTOMERS = "customers"
    VENDORS = "vendors"
    INVOICES = "invoices"
    BILLS = "bills"
    PAYMENTS = "payments"
    AR_AGING = "ar_aging"
    AP_AGING = "ap_aging"
    BANK_TRANSACTIONS = "bank_transactions"
    FX_RATES = "fx_rates"


AS_OF_DATASETS = frozenset({DatasetType.AR_AGING, DatasetType.AP_AGING})


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_year_start_month"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    functional_currency: Mapped[Currency] = mapped_column(CurrencyCodeType(), nullable=False)
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Migration(Base):
    __tablename__ = "migrations"
    __table_args__ = (
        check_in("status", "status", MigrationStatus),
        CheckConstraint(
            "opening_balance_date < history_start_date AND history_start_date <= cutover_date "
            "AND cutover_date < go_live_date",
            name="conversion_plan_order",
        ),
        CheckConstraint("bank_clearing_window_days BETWEEN 0 AND 90", name="clearing_window"),
        CheckConstraint("issue_key_prefix ~ '^[A-Z]{2,6}$'", name="issue_key_prefix"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    functional_currency: Mapped[Currency] = mapped_column(CurrencyCodeType(), nullable=False)
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opening_balance_date: Mapped[date] = mapped_column(BusinessDateType(), nullable=False)
    history_start_date: Mapped[date] = mapped_column(BusinessDateType(), nullable=False)
    cutover_date: Mapped[date] = mapped_column(BusinessDateType(), nullable=False)
    go_live_date: Mapped[date] = mapped_column(BusinessDateType(), nullable=False)
    bank_clearing_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    next_issue_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_change_request_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lead_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())


class SourceSystem(Base):
    __tablename__ = "source_systems"
    __table_args__ = (
        check_in("kind", "kind", SourceSystemKind),
        UniqueConstraint("migration_id", "name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        check_in("dataset_type", "dataset_type", DatasetType),
        UniqueConstraint(
            "migration_id",
            "source_system_id",
            "dataset_type",
            "as_of_date",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "(dataset_type IN ('ar_aging', 'ap_aging')) = (as_of_date IS NOT NULL)",
            name="as_of_date_for_agings",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    source_system_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_systems.id"), nullable=False
    )
    dataset_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    as_of_date: Mapped[date | None] = mapped_column(BusinessDateType())
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Validated by relay.workspace.schemas.DatasetSettings (for example a bank account link).
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active_import_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("imports.id", use_alter=True, name="fk_datasets_active_import_id_imports")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(UtcTimestampType())


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("migration_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    migration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("migrations.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Engine policy parameters (relay.engine.policy.Policy.as_dict), as strings for decimals.
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("change_requests.id", use_alter=True, name="fk_policy_versions_cr")
    )
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
