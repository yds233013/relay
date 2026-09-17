"""Helpers for persistence tests: unique users and a small workspace per test."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from alembic import command
from sqlalchemy.orm import Session, sessionmaker

from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.db import alembic_config, session_scope
from relay.identity import service as identity
from relay.identity.models import Role
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay.worker import WorkerContext
from relay.workspace import service as workspace
from relay.workspace.models import DatasetType, SourceSystemKind

LIMITS = ImportLimits(max_upload_bytes=1_000_000, max_rows=10_000)


def ensure_head(database_url: str) -> None:
    config = alembic_config(database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


@dataclass(frozen=True, slots=True)
class Workspace:
    migration_id: uuid.UUID
    dataset_id: uuid.UUID
    specialist: Actor
    lead: Actor
    controller: Actor
    viewer_email: str
    specialist_email: str


def make_workspace(
    factory: sessionmaker[Session], dataset_type: DatasetType = DatasetType.CUSTOMERS
) -> Workspace:
    tag = uuid.uuid4().hex[:10]
    with session_scope(factory) as session:
        system = Actor.system()
        users = {
            role: identity.create_user(
                session,
                email=f"{role.value}.{tag}@test.example",
                display_name=role.value,
                role=role,
                actor=system,
            )
            for role in (
                Role.IMPLEMENTATION_SPECIALIST,
                Role.IMPLEMENTATION_LEAD,
                Role.CUSTOMER_CONTROLLER,
                Role.VIEWER,
            )
        }
        lead = identity.actor_for(users[Role.IMPLEMENTATION_LEAD])
        company = workspace.create_company(
            session,
            actor=lead,
            name=f"Test Co {tag}",
            legal_name="Test Co",
            country="US",
            functional_currency=Currency.of("USD"),
            fiscal_year_start_month=1,
        )
        migration = workspace.create_migration(
            session,
            actor=lead,
            company=company,
            name="test",
            plan=workspace.ConversionPlanInput(
                opening_balance_date=date(2025, 12, 31),
                history_start_date=date(2026, 1, 1),
                cutover_date=date(2026, 6, 30),
                go_live_date=date(2026, 7, 1),
            ),
            issue_key_prefix="TST",
            lead_user_id=lead.user_id,
        )
        source = workspace.create_source_system(
            session,
            actor=lead,
            migration=migration,
            name="Legacy",
            kind=SourceSystemKind.LEGACY_ERP,
        )
        dataset = workspace.create_dataset(
            session, actor=lead, source_system=source, dataset_type=dataset_type, name="data.csv"
        )
        return Workspace(
            migration_id=migration.id,
            dataset_id=dataset.id,
            specialist=identity.actor_for(users[Role.IMPLEMENTATION_SPECIALIST]),
            lead=lead,
            controller=identity.actor_for(users[Role.CUSTOMER_CONTROLLER]),
            viewer_email=users[Role.VIEWER].email,
            specialist_email=users[Role.IMPLEMENTATION_SPECIALIST].email,
        )  # fmt: skip


def worker_context(factory: sessionmaker[Session], root: Path) -> WorkerContext:
    return WorkerContext(session_factory=factory, blob_store=LocalBlobStore(root), limits=LIMITS)
