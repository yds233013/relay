"""Creating a migration: company, conversion plan, source systems and datasets."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from relay.api.deps import ReaderDep, SessionDep, require
from relay.api.routers.workspace import migration_out
from relay.api.schemas import (
    DatasetIn,
    DatasetOut,
    MigrationIn,
    MigrationOut,
    SourceSystemIn,
    SourceSystemOut,
)
from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.errors import InvalidInputError
from relay.identity.permissions import Permission
from relay.workspace import service as workspace
from relay.workspace.models import DatasetType, SourceSystem, SourceSystemKind

router = APIRouter(prefix="/api/v1", tags=["setup"])

ManagerDep = Annotated[Actor, Depends(require(Permission.MANAGE_WORKSPACE))]


@router.post("/migrations", status_code=status.HTTP_201_CREATED)
def create_migration(body: MigrationIn, actor: ManagerDep, session: SessionDep) -> MigrationOut:
    try:
        currency = Currency.of(body.company.functional_currency)
    except (InvalidInputError, ValueError) as exc:
        raise InvalidInputError("unknown functional currency") from exc
    company = workspace.create_company(
        session,
        actor=actor,
        name=body.company.name.strip(),
        legal_name=body.company.legal_name.strip(),
        country=body.company.country,
        functional_currency=currency,
        fiscal_year_start_month=body.company.fiscal_year_start_month,
    )
    migration = workspace.create_migration(
        session,
        actor=actor,
        company=company,
        name=body.name.strip(),
        plan=workspace.ConversionPlanInput(
            opening_balance_date=body.opening_balance_date,
            history_start_date=body.history_start_date,
            cutover_date=body.cutover_date,
            go_live_date=body.go_live_date,
            bank_clearing_window_days=body.bank_clearing_window_days,
        ),
        issue_key_prefix=body.issue_key_prefix,
        lead_user_id=actor.user_id,
    )
    return migration_out(migration, company.name)


def _system_out(system: SourceSystem) -> SourceSystemOut:
    return SourceSystemOut(
        id=system.id, name=system.name, kind=system.kind, description=system.description
    )


@router.get("/migrations/{migration_id}/source-systems")
def list_source_systems(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[SourceSystemOut]:
    workspace.get_migration(session, migration_id)
    return [_system_out(s) for s in workspace.source_systems_for(session, migration_id)]


@router.post("/migrations/{migration_id}/source-systems", status_code=status.HTTP_201_CREATED)
def create_source_system(
    migration_id: uuid.UUID, body: SourceSystemIn, actor: ManagerDep, session: SessionDep
) -> SourceSystemOut:
    migration = workspace.get_migration(session, migration_id)
    system = workspace.create_source_system(
        session,
        actor=actor,
        migration=migration,
        name=body.name.strip(),
        kind=SourceSystemKind(body.kind),
        description=body.description,
    )
    return _system_out(system)


@router.post("/migrations/{migration_id}/datasets", status_code=status.HTTP_201_CREATED)
def create_dataset(
    migration_id: uuid.UUID, body: DatasetIn, actor: ManagerDep, session: SessionDep
) -> DatasetOut:
    workspace.get_migration(session, migration_id)
    system = session.get(SourceSystem, body.source_system_id)
    if system is None or system.migration_id != migration_id:
        raise InvalidInputError("source system not found in this migration")
    try:
        dataset_type = DatasetType(body.dataset_type)
    except ValueError as exc:
        raise InvalidInputError(f"unknown dataset type {body.dataset_type}") from exc
    settings = (
        workspace.DatasetSettings(bank_account=body.bank_account, gl_account=body.gl_account)
        if body.bank_account or body.gl_account
        else None
    )
    dataset = workspace.create_dataset(
        session,
        actor=actor,
        source_system=system,
        dataset_type=dataset_type,
        name=body.name.strip(),
        as_of_date=body.as_of_date,
        is_required=body.is_required,
        settings=settings,
    )
    return DatasetOut(
        id=dataset.id,
        dataset_type=dataset.dataset_type,
        name=dataset.name,
        as_of_date=dataset.as_of_date,
        is_required=dataset.is_required,
        active_import_id=dataset.active_import_id,
        version=dataset.version,
    )
