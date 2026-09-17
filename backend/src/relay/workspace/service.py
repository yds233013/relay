"""Workspace setup: companies, migrations, source systems, datasets. Every change is audited."""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.errors import InvalidInputError, NotFoundError
from relay.core.hashing import to_canonical
from relay.core.ids import uuid7
from relay.engine.policy import Policy
from relay.workspace.models import (
    AS_OF_DATASETS,
    Company,
    Dataset,
    DatasetType,
    Migration,
    MigrationStatus,
    PolicyVersion,
    SourceSystem,
    SourceSystemKind,
)


class DatasetSettings(BaseModel):
    """Per-dataset configuration that is not part of the column mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bank_account: str | None = Field(default=None, min_length=1, max_length=64)
    """Bank statement datasets: the bank account the statement belongs to."""
    gl_account: str | None = Field(default=None, min_length=1, max_length=64)
    """Bank statement datasets: the legacy GL cash account that records this bank account."""


class ConversionPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    opening_balance_date: date
    history_start_date: date
    cutover_date: date
    go_live_date: date
    bank_clearing_window_days: int = Field(default=15, ge=0, le=90)


def policy_document(policy: Policy) -> dict[str, Any]:
    document = to_canonical(policy.as_dict())
    if not isinstance(document, dict):
        raise TypeError("policy document must be an object")
    return document


def policy_from_document(document: dict[str, Any]) -> Policy:
    """Rebuild engine policy from a stored document; unknown or missing keys are errors."""
    defaults = Policy()
    values: dict[str, Any] = {}
    for spec in fields(Policy):
        if spec.name not in document:
            raise InvalidInputError(f"policy document is missing {spec.name}")
        raw = document[spec.name]
        current = getattr(defaults, spec.name)
        if isinstance(current, bool | int):
            values[spec.name] = int(raw)
        elif isinstance(current, Decimal):
            values[spec.name] = Decimal(str(raw))
        else:
            values[spec.name] = dict(raw)
    unknown = set(document) - {spec.name for spec in fields(Policy)}
    if unknown:
        raise InvalidInputError(f"policy document has unknown keys {sorted(unknown)}")
    return Policy(**values)


def create_company(
    session: Session,
    *,
    actor: Actor,
    name: str,
    legal_name: str,
    country: str,
    functional_currency: Currency,
    fiscal_year_start_month: int,
) -> Company:
    company = Company(
        id=uuid7(),
        name=name,
        legal_name=legal_name,
        country=country,
        functional_currency=functional_currency,
        fiscal_year_start_month=fiscal_year_start_month,
        created_by=actor.user_id,
    )
    session.add(company)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="company.created",
        entity_type="company",
        entity_id=company.id,
        migration_id=None,
        after={"name": name, "functional_currency": functional_currency.code},
    )
    return company


def create_migration(
    session: Session,
    *,
    actor: Actor,
    company: Company,
    name: str,
    plan: ConversionPlanInput,
    issue_key_prefix: str,
    lead_user_id: uuid.UUID | None,
) -> Migration:
    if not (
        plan.opening_balance_date < plan.history_start_date <= plan.cutover_date < plan.go_live_date
    ):
        raise InvalidInputError(
            "conversion plan dates must satisfy opening < history start <= cutover < go-live"
        )
    migration = Migration(
        id=uuid7(),
        company_id=company.id,
        name=name,
        status=MigrationStatus.IN_PROGRESS.value,
        functional_currency=company.functional_currency,
        fiscal_year_start_month=company.fiscal_year_start_month,
        opening_balance_date=plan.opening_balance_date,
        history_start_date=plan.history_start_date,
        cutover_date=plan.cutover_date,
        go_live_date=plan.go_live_date,
        bank_clearing_window_days=plan.bank_clearing_window_days,
        issue_key_prefix=issue_key_prefix,
        next_issue_number=1,
        next_change_request_number=1,
        lead_user_id=lead_user_id,
        ai_enabled=False,
        version=1,
        created_by=actor.user_id,
    )
    session.add(migration)
    session.flush()
    policy = PolicyVersion(
        id=uuid7(),
        migration_id=migration.id,
        version=1,
        policy=policy_document(Policy()),
        created_by=actor.user_id,
    )
    session.add(policy)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="migration.created",
        entity_type="migration",
        entity_id=migration.id,
        migration_id=migration.id,
        after={"name": name, "conversion_plan": plan.model_dump(mode="json"), "policy_version": 1},
    )
    return migration


def create_source_system(
    session: Session,
    *,
    actor: Actor,
    migration: Migration,
    name: str,
    kind: SourceSystemKind,
    description: str = "",
) -> SourceSystem:
    system = SourceSystem(
        id=uuid7(),
        migration_id=migration.id,
        name=name,
        kind=kind.value,
        description=description,
        created_by=actor.user_id,
    )
    session.add(system)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="source_system.created",
        entity_type="source_system",
        entity_id=system.id,
        migration_id=migration.id,
        after={"name": name, "kind": kind.value},
    )
    return system


def create_dataset(
    session: Session,
    *,
    actor: Actor,
    source_system: SourceSystem,
    dataset_type: DatasetType,
    name: str,
    as_of_date: date | None = None,
    is_required: bool = True,
    settings: DatasetSettings | None = None,
) -> Dataset:
    if (dataset_type in AS_OF_DATASETS) != (as_of_date is not None):
        raise InvalidInputError(
            "aging datasets need an as-of date; other datasets must not have one"
        )
    resolved = settings or DatasetSettings()
    if dataset_type is DatasetType.BANK_TRANSACTIONS and not (
        resolved.bank_account and resolved.gl_account
    ):
        raise InvalidInputError("bank statement datasets need a bank account and a GL account")
    dataset = Dataset(
        id=uuid7(),
        migration_id=source_system.migration_id,
        source_system_id=source_system.id,
        dataset_type=dataset_type.value,
        name=name,
        as_of_date=as_of_date,
        is_required=is_required,
        settings=resolved.model_dump(exclude_none=True),
        version=1,
        created_by=actor.user_id,
    )
    session.add(dataset)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="dataset.created",
        entity_type="dataset",
        entity_id=dataset.id,
        migration_id=source_system.migration_id,
        after={"name": name, "dataset_type": dataset_type.value, "as_of_date": as_of_date},
    )
    return dataset


def get_migration(session: Session, migration_id: uuid.UUID) -> Migration:
    migration = session.get(Migration, migration_id)
    if migration is None:
        raise NotFoundError("migration not found")
    return migration


def get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError("dataset not found")
    return dataset


def datasets_for(session: Session, migration_id: uuid.UUID) -> list[Dataset]:
    return list(
        session.scalars(
            select(Dataset)
            .where(Dataset.migration_id == migration_id)
            .order_by(Dataset.dataset_type, Dataset.as_of_date, Dataset.name)
        )
    )


def current_policy(session: Session, migration_id: uuid.UUID) -> PolicyVersion:
    policy = session.scalars(
        select(PolicyVersion)
        .where(PolicyVersion.migration_id == migration_id)
        .order_by(PolicyVersion.version.desc())
        .limit(1)
    ).first()
    if policy is None:
        raise NotFoundError("migration has no policy version")
    return policy
