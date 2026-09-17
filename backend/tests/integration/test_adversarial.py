"""Review pass 2: attempts to break Relay, kept as regressions.

Each test is an attack or an accident that a real migration could produce: work belonging to another
migration, actions repeated or replayed, amounts at the edge of what the schema can hold, a worker
that dies mid-job, and references to records that do not exist. They run against real PostgreSQL
because most of the protections are transactions, constraints and locks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from relay.changes import service as changes
from relay.changes.models import ChangeRequest, ChangeRequestKind, ChangeRequestStatus
from relay.core.db import create_session_factory, session_scope
from relay.core.errors import RelayError
from relay.core.money import Money, validate_amount
from relay.imports import service as imports
from relay.imports.blob_store import LocalBlobStore
from relay.jobs import service as jobs
from relay.jobs.models import Job, JobKind, JobStatus
from relay.mapping_sets import service as mapping_sets
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun
from relay.workspace import service as workspace
from tests.integration.support import LIMITS, Workspace, ensure_head, make_workspace, worker_context

CSV = b"Customer ID,Customer Name\r\nC-1,Alpha Foods\r\nC-2,Beta Market\r\n"
MAPPING = {
    "fields": {
        "party_code": {"source": "Customer ID", "steps": [{"step": "trim"}]},
        "name": {"source": "Customer Name", "steps": [{"step": "trim"}]},
    }
}


@pytest.fixture
def factory(migrated: str, engine: Engine) -> sessionmaker[Session]:
    ensure_head(migrated)
    return create_session_factory(engine)


@pytest.fixture
def space(factory: sessionmaker[Session]) -> Workspace:
    return make_workspace(factory)


@pytest.fixture
def other(factory: sessionmaker[Session]) -> Workspace:
    """A second migration, with its own people, that must stay completely separate."""
    return make_workspace(factory)


@pytest.fixture
def blob_root(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


def _upload_and_parse(factory: sessionmaker[Session], space: Workspace, root: Path) -> None:
    from relay.worker import drain  # noqa: PLC0415

    with session_scope(factory) as session:
        imports.upload(
            session,
            actor=space.specialist,
            dataset=workspace.get_dataset(session, space.dataset_id),
            filename="customers.csv",
            chunks=[CSV],
            blob_store=LocalBlobStore(root),
            limits=LIMITS,
        )
    drain(worker_context(factory, root))


def _draft_mapping_set(factory: sessionmaker[Session], space: Workspace, root: Path) -> uuid.UUID:
    _upload_and_parse(factory, space, root)
    with session_scope(factory) as session:
        dataset = workspace.get_dataset(session, space.dataset_id)
        draft = mapping_sets.create_draft(
            session, actor=space.specialist, dataset=dataset, config=MAPPING
        )
        return draft.id


# ------------------------------------------------------------------ work of another migration


def test_a_change_request_cannot_adopt_another_migrations_mapping_set(
    factory: sessionmaker[Session], space: Workspace, other: Workspace, blob_root: Path
) -> None:
    """Payload ids are checked against the change request's migration, not only for existence."""
    theirs = _draft_mapping_set(factory, other, blob_root)
    with session_scope(factory) as session, pytest.raises(RelayError, match="another migration"):
        changes.create_draft(
            session,
            actor=space.specialist,
            migration=workspace.get_migration(session, space.migration_id),
            kind=ChangeRequestKind.COLUMN_MAPPING_SET,
            title="Borrowed mapping set",
            payload={"mapping_set_id": str(theirs)},
        )


def test_a_disposition_cannot_reach_an_issue_in_another_migration(
    factory: sessionmaker[Session], space: Workspace, other: Workspace
) -> None:
    with session_scope(factory) as session:
        stranger = _manual_issue(session, other)
    with session_scope(factory) as session, pytest.raises(RelayError):
        changes.create_draft(
            session,
            actor=space.specialist,
            migration=workspace.get_migration(session, space.migration_id),
            kind=ChangeRequestKind.DISPOSITION,
            title="Disposition of someone else's issue",
            payload={
                "issue_ids": [str(stranger)],
                "kind": "carry_forward_adjustment",
                "amount": "1.00",
            },
        )


def _manual_issue(session: Session, space: Workspace) -> uuid.UUID:
    from relay.issues import workflow  # noqa: PLC0415 - avoids importing the workflow everywhere

    issue = workflow.create_manual_issue(
        session,
        actor=space.specialist,
        migration=workspace.get_migration(session, space.migration_id),
        title="Manual issue",
        severity="medium",
        category="other",
        nature="migration_defect",
        description="Raised by hand.",
    )
    return issue.id


# ------------------------------------------------------------------------- repeated actions


def test_submitting_and_withdrawing_the_same_draft_twice_is_refused(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    mapping_set = _draft_mapping_set(factory, space, blob_root)
    with session_scope(factory) as session:
        change = changes.create_draft(
            session,
            actor=space.specialist,
            migration=workspace.get_migration(session, space.migration_id),
            kind=ChangeRequestKind.COLUMN_MAPPING_SET,
            title="Mapping",
            payload={"mapping_set_id": str(mapping_set)},
        )
        change_id = change.id
    with session_scope(factory) as session:
        changes.submit(
            session,
            actor=space.specialist,
            change=session.get_one(ChangeRequest, change_id),
            justification="Reviewed against the header.",
        )
    with session_scope(factory) as session, pytest.raises(RelayError):
        changes.submit(
            session,
            actor=space.specialist,
            change=session.get_one(ChangeRequest, change_id),
            justification="Again.",
        )
    with session_scope(factory) as session:
        changes.withdraw(
            session,
            actor=space.specialist,
            change=session.get_one(ChangeRequest, change_id),
            reason="Probe",
        )
    with session_scope(factory) as session, pytest.raises(RelayError):
        changes.withdraw(
            session,
            actor=space.specialist,
            change=session.get_one(ChangeRequest, change_id),
            reason="Probe",
        )
    with session_scope(factory) as session:
        assert (
            session.get_one(ChangeRequest, change_id).status == ChangeRequestStatus.WITHDRAWN.value
        )


def test_requesting_the_same_run_repeatedly_creates_one_run(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    _upload_and_parse(factory, space, blob_root)
    context = worker_context(factory, blob_root)
    from relay.worker import drain  # noqa: PLC0415

    requested = []
    for _ in range(5):
        with session_scope(factory) as session:
            requested.append(
                pipeline.request_run(
                    session, actor=space.specialist, migration_id=space.migration_id
                ).run.id
            )
    assert len(set(requested)) == 1
    drain(context)
    with session_scope(factory) as session:
        runs = session.scalar(
            select(func.count())
            .select_from(PipelineRun)
            .where(PipelineRun.migration_id == space.migration_id)
        )
    assert runs == 1


# ------------------------------------------------------------------------- extreme amounts


@pytest.mark.parametrize(
    "value",
    [
        "1e30",  # beyond NUMERIC(20,4)
        "99999999999999999.0000",  # 17 integer digits
        "1.00005",  # more precision than the column holds
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_amounts_the_database_cannot_hold_exactly_are_refused_in_python(value: str) -> None:
    """FC-01 and FC-02: refuse rather than round, and long before PostgreSQL sees it."""
    with pytest.raises((ValueError, ArithmeticError)):
        validate_amount(Decimal(value))


def test_an_amount_at_the_edge_of_the_column_survives_a_round_trip(
    factory: sessionmaker[Session],
) -> None:
    edge = Decimal("9999999999999999.9999")  # 16 integer digits, 4 decimals
    assert validate_amount(edge) == edge
    with session_scope(factory) as session:
        stored = session.scalar(text("SELECT CAST(:v AS NUMERIC(20,4))"), {"v": str(edge)})
    assert Decimal(str(stored)) == edge
    assert Money(edge, "USD").amount_str == "9999999999999999.9999"


def test_postgres_refuses_an_over_scale_amount_rather_than_rounding_it(
    factory: sessionmaker[Session],
) -> None:
    with session_scope(factory) as session, pytest.raises(DBAPIError):
        session.execute(text("SELECT CAST('1e30' AS NUMERIC(20,4))"))


# --------------------------------------------------------------------------- broken workers


def test_a_job_locked_by_a_dead_worker_is_reclaimed(factory: sessionmaker[Session]) -> None:
    """An interrupted worker must not strand its job: the lock expires and another claims it."""
    with session_scope(factory) as session:
        job_id = jobs.enqueue(session, JobKind.RUN_PIPELINE, {"run_id": str(uuid.uuid4())})
    stale = datetime.now(UTC) - timedelta(hours=1)
    with session_scope(factory) as session:
        row = session.get_one(Job, job_id)
        row.status = JobStatus.RUNNING.value
        row.locked_by = "worker-that-died"
        row.locked_at = stale
        row.heartbeat_at = stale
    with session_scope(factory) as session:
        assert jobs.claim(session, worker="worker-alive") is None  # still held by the dead worker
        assert jobs.requeue_stale(session) == 1
    with session_scope(factory) as session:
        claimed = jobs.claim(session, worker="worker-alive")
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.locked_by == "worker-alive"


def test_an_unknown_job_kind_in_the_queue_cannot_be_enqueued(
    factory: sessionmaker[Session],
) -> None:
    with session_scope(factory) as session, pytest.raises(DBAPIError):
        session.execute(
            text(
                "INSERT INTO jobs (id, kind, payload, status, attempts, max_attempts, run_after)"
                " VALUES (:id, 'delete_everything', '{}', 'queued', 0, 3, now())"
            ),
            {"id": uuid.uuid4()},
        )


# ------------------------------------------------------------------------ missing references


def test_an_override_for_a_record_that_does_not_exist_is_refused(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    with session_scope(factory) as session, pytest.raises(RelayError):
        changes.create_draft(
            session,
            actor=space.specialist,
            migration=workspace.get_migration(session, space.migration_id),
            kind=ChangeRequestKind.RECORD_OVERRIDE,
            title="Override of nothing",
            payload={
                "natural_key": "je:JE-DOES-NOT-EXIST",
                "field": "entry_date",
                "new_value": "2026-03-31",
                "rationale": "Probe",
            },
        )


def test_a_change_request_for_a_migration_that_does_not_exist_is_refused(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    with session_scope(factory) as session, pytest.raises(RelayError):
        changes.create_draft(
            session,
            actor=space.specialist,
            migration=workspace.get_migration(session, uuid.uuid4()),
            kind=ChangeRequestKind.POLICY_CHANGE,
            title="Ghost migration",
            payload={"changes": {"duplicate_window_days": 8}},
        )
