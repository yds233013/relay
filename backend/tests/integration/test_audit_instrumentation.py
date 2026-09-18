"""The GV-05 instrumentation is not vacuous: it fails an unaudited governed mutation.

The autouse fixture in ``conftest.py`` watches every transaction the integration suite commits, so
those ~115 flows are the positive evidence. These tests prove the check can fail at all, that it
leaves operational writes alone, and that a violation takes the change down with it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from relay.audit import instrumentation
from relay.audit.instrumentation import UnauditedMutationError
from relay.core.actor import Actor
from relay.core.currency import Currency
from relay.core.db import create_session_factory, session_scope
from relay.core.ids import uuid7
from relay.jobs import service as jobs
from relay.jobs.models import Job, JobKind
from relay.workspace import service as workspace
from relay.workspace.models import Company, Migration
from tests.integration.support import Workspace, ensure_head, make_workspace


@pytest.fixture
def factory(migrated: str, engine: Engine) -> sessionmaker[Session]:
    ensure_head(migrated)
    return create_session_factory(engine)


@pytest.fixture
def space(factory: sessionmaker[Session]) -> Workspace:
    return make_workspace(factory)


def test_the_instrumentation_is_active_for_the_integration_suite() -> None:
    assert instrumentation.installed()


def test_an_unaudited_governed_mutation_fails_and_rolls_back(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    with pytest.raises(UnauditedMutationError, match="migrations"), session_scope(factory) as s:
        workspace.get_migration(s, space.migration_id).name = "renamed without an event"

    with session_scope(factory) as session:
        assert workspace.get_migration(session, space.migration_id).name == "test"


def test_an_unaudited_governed_insert_fails(factory: sessionmaker[Session]) -> None:
    with pytest.raises(UnauditedMutationError, match="companies"), session_scope(factory) as s:
        s.add(
            Company(
                id=uuid7(),
                name="Unaudited Co",
                legal_name="Unaudited Co",
                country="US",
                functional_currency=Currency.of("USD"),
                fiscal_year_start_month=1,
            )
        )


def test_an_unaudited_bulk_update_of_a_governed_table_fails(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    """ORM-enabled bulk DML bypasses the unit of work; ``do_orm_execute`` still observes it."""
    with pytest.raises(UnauditedMutationError, match="migrations"), session_scope(factory) as s:
        s.execute(update(Migration).where(Migration.id == space.migration_id).values(name="bulk"))


def test_a_governed_mutation_with_its_audit_event_commits(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        company = workspace.create_company(
            session,
            actor=Actor.system(),
            name="Audited Co",
            legal_name="Audited Co",
            country="US",
            functional_currency=Currency.of("USD"),
            fiscal_year_start_month=1,
        )
        company_id = company.id
    with session_scope(factory) as session:
        assert session.get(Company, company_id) is not None


def test_operational_writes_do_not_need_an_audit_event(factory: sessionmaker[Session]) -> None:
    """The job queue is exempt: enqueue, claim and heartbeat are scheduling, not governed state."""
    with session_scope(factory) as session:
        job_id = jobs.enqueue(session, JobKind.EVALUATE_READINESS, {"migration_id": "none"})
    assert job_id is not None

    with session_scope(factory) as session:
        jobs.heartbeat(session, job_id)

    with session_scope(factory) as session:
        assert session.scalar(select(Job.id).where(Job.id == job_id)) == job_id
