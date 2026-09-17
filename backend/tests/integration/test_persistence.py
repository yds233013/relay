"""Persistence guarantees against real PostgreSQL (testing.md §2.4).

FC-08 append-only source rows, GV-05 audit atomicity, GV-06 hash chain, GV-02 segregation of duties,
SEC-01..SEC-03 upload limits, idempotent imports, SKIP LOCKED job claiming, run idempotency.
"""

from __future__ import annotations

import uuid
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from relay.audit import service as audit
from relay.audit.models import AuditEvent
from relay.changes.models import Approval, ApprovalDecision, ChangeRequest, ChangeRequestKind
from relay.core.actor import Actor
from relay.core.db import create_session_factory, session_scope
from relay.core.ids import uuid7
from relay.engine.rules import REGISTRY
from relay.imports import service as imports
from relay.imports.blob_store import LocalBlobStore, UploadTooLargeError
from relay.imports.models import Import, ImportStatus, QuarantinedRow, SourceRow, StoredFile
from relay.imports.service import ImportLimits
from relay.jobs import service as jobs
from relay.jobs.models import JobKind
from relay.mapping_sets import service as mapping_sets
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun
from relay.worker import drain
from relay.workspace import service as workspace
from relay.workspace.models import SourceSystemKind
from tests.integration.support import (
    LIMITS,
    Workspace,
    ensure_head,
    make_workspace,
    worker_context,
)

CSV = (
    b"Customer ID,Customer Name\r\nC-1,Alpha Foods\r\nC-2,Beta Market\r\nC-3,broken\r\n"
    b"row,here,x\r\n"
)


@pytest.fixture
def factory(migrated: str, engine: Engine) -> sessionmaker[Session]:
    ensure_head(migrated)
    return create_session_factory(engine)


@pytest.fixture(scope="module")
def blob_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One store for the module: stored files are deduplicated by content across tests."""
    return tmp_path_factory.mktemp("blobs")


@pytest.fixture
def space(factory: sessionmaker[Session]) -> Workspace:
    return make_workspace(factory)


def _upload(
    factory: sessionmaker[Session],
    space: Workspace,
    root: Path,
    content: bytes,
    name: str = "customers.csv",
) -> imports.UploadOutcome:
    with session_scope(factory) as session:
        return imports.upload(
            session,
            actor=space.specialist,
            dataset=workspace.get_dataset(session, space.dataset_id),
            filename=name,
            chunks=[content[:10], content[10:]],
            blob_store=LocalBlobStore(root),
            limits=LIMITS,
        )


# ------------------------------------------------------------------------------ append-only tables
@pytest.mark.parametrize(
    "statement", ["UPDATE {t} SET line_start = line_start", "DELETE FROM {t}", "TRUNCATE {t}"]
)
@pytest.mark.parametrize("table", ["source_rows", "quarantined_rows"])
def test_source_and_quarantined_rows_are_append_only(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path, table: str, statement: str
) -> None:
    _upload(factory, space, blob_root, CSV)
    drain(worker_context(factory, blob_root))
    with pytest.raises(DBAPIError, match="append-only"), session_scope(factory) as session:
        session.execute(text(statement.format(t=table)))


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET reason = 'x'", "DELETE FROM audit_events", "TRUNCATE audit_events"],
)
@pytest.mark.usefixtures("space")
def test_audit_events_are_append_only(factory: sessionmaker[Session], statement: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"), session_scope(factory) as session:
        session.execute(text(statement))


# ------------------------------------------------------------------------------------------ audit
def test_audit_event_and_change_roll_back_together(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    before = _event_count(factory, space.migration_id)

    def write_then_fail() -> None:
        with session_scope(factory) as session:
            migration = workspace.get_migration(session, space.migration_id)
            workspace.create_source_system(
                session,
                actor=space.lead,
                migration=migration,
                name="Rolled back",
                kind=SourceSystemKind.BANK,
            )
            raise RuntimeError("failure after the domain write")

    with pytest.raises(RuntimeError):
        write_then_fail()
    assert _event_count(factory, space.migration_id) == before
    with session_scope(factory) as session:
        names = session.scalars(
            text("SELECT name FROM source_systems WHERE name = 'Rolled back'")
        ).all()
    assert names == []


def _event_count(factory: sessionmaker[Session], migration_id: uuid.UUID) -> int:
    with session_scope(factory) as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.migration_id == migration_id)
            )
            or 0
        )


def test_hash_chain_verifies_and_detects_tampering(
    factory: sessionmaker[Session], space: Workspace, engine: Engine
) -> None:
    with session_scope(factory) as session:
        result = audit.verify_chain(session, space.migration_id)
    assert result.valid
    assert result.events_checked >= 3
    with session_scope(factory) as session:
        target = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.migration_id == space.migration_id)
            .order_by(AuditEvent.migration_seq)
            .offset(1)
            .limit(1)
        ).one()
        seq = target.migration_seq
    # A database owner can bypass the trigger; the chain still exposes the edit (tamper-evident).
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only")
        )
        connection.execute(
            text(
                "UPDATE audit_events SET reason = 'edited' "
                "WHERE migration_id = :m AND migration_seq = :s"
            ),
            {"m": space.migration_id, "s": seq},
        )
        connection.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only"))
    with session_scope(factory) as session:
        broken = audit.verify_chain(session, space.migration_id)
    assert not broken.valid
    assert broken.first_broken_seq == seq
    assert broken.problem == "event content altered"


def test_migration_sequence_is_gapless_and_chained(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    with session_scope(factory) as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.migration_id == space.migration_id)
            .order_by(AuditEvent.migration_seq)
        ).all()
        assert [e.migration_seq for e in events] == list(range(1, len(events) + 1))
        assert all(e.prev_hash == p.hash for p, e in pairwise(events))


# ---------------------------------------------------------------------------- segregation of duties
def test_database_rejects_self_approval(factory: sessionmaker[Session], space: Workspace) -> None:
    with session_scope(factory) as session:
        change = ChangeRequest(
            id=uuid7(), migration_id=space.migration_id, key=f"CR-X-{uuid.uuid4().hex[:6]}",
            kind=ChangeRequestKind.COLUMN_MAPPING_SET.value, status="submitted", title="t",
            payload={}, origin="operator", requested_by=space.specialist.user_id,
        )  # fmt: skip
        session.add(change)
        change_id = change.id
    with pytest.raises(DBAPIError, match="own change request"), session_scope(factory) as session:
        session.add(
            Approval(
                id=uuid7(), change_request_id=change_id, reviewer_user_id=space.specialist.user_id,
                reviewer_role_at_decision="implementation_lead",
                decision=ApprovalDecision.APPROVE.value,
            )
        )  # fmt: skip


# ----------------------------------------------------------------------------------------- imports
def test_identical_upload_is_idempotent_and_parsing_quarantines(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    first = _upload(factory, space, blob_root, CSV)
    second = _upload(factory, space, blob_root, CSV, name="renamed.csv")
    assert first.created
    assert not second.created
    assert second.import_.id == first.import_.id
    drain(worker_context(factory, blob_root))
    with session_scope(factory) as session:
        record = session.get_one(Import, first.import_.id)
        assert record.status == ImportStatus.PARSED.value
        assert (record.row_count, record.quarantined_count) == (3, 1)
        assert workspace.get_dataset(session, space.dataset_id).active_import_id == record.id
        stored = session.get_one(StoredFile, record.stored_file_id)
        assert stored.storage_key == f"{stored.sha256[:2]}/{stored.sha256[2:4]}/{stored.sha256}"
        rows = session.scalars(
            select(SourceRow).where(SourceRow.import_id == record.id).order_by(SourceRow.row_number)
        ).all()
        assert [r.values["Customer ID"] for r in rows] == ["C-1", "C-2", "C-3"]
        quarantined = session.scalars(
            select(QuarantinedRow).where(QuarantinedRow.import_id == record.id)
        ).one()
        assert (quarantined.line_start, quarantined.reason) == (5, "field_count_mismatch")
        actions = session.scalars(
            select(AuditEvent.action).where(AuditEvent.migration_id == space.migration_id)
        ).all()
    assert {
        "import.uploaded",
        "import.duplicate_upload_ignored",
        "import.parsed",
        "import.activated",
    } <= set(actions)


def test_new_file_supersedes_the_active_import(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    context = worker_context(factory, blob_root)
    first = _upload(factory, space, blob_root, CSV)
    drain(context)
    second = _upload(factory, space, blob_root, CSV + b"C-4,Gamma\r\n")
    drain(context)
    with session_scope(factory) as session:
        assert session.get_one(Import, first.import_.id).status == ImportStatus.SUPERSEDED.value
        assert session.get_one(Import, second.import_.id).sequence == 2
        assert (
            workspace.get_dataset(session, space.dataset_id).active_import_id == second.import_.id
        )


def test_upload_limits_and_content_checks(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    with pytest.raises(UploadTooLargeError):
        _upload(factory, space, blob_root, b"a,b\n" + b"1,2\n" * 300_000)
    with pytest.raises(imports.UnsupportedContentError):
        _upload(factory, space, blob_root, b"PK\x03\x04binary", name="book.csv")
    with pytest.raises(imports.UnsupportedContentError):
        _upload(factory, space, blob_root, CSV, name="report.xlsx")
    assert list((blob_root / "tmp").iterdir()) == []  # SEC-06: temporary files are removed


def test_uploads_are_rate_limited_per_person(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    """SEC-17: the limit is checked before any bytes are read, and counts this person's uploads."""
    limited = ImportLimits(max_upload_bytes=1_000_000, max_rows=10_000, max_uploads_per_hour=2)

    def upload(content: bytes) -> None:
        with session_scope(factory) as session:
            imports.upload(
                session,
                actor=space.specialist,
                dataset=workspace.get_dataset(session, space.dataset_id),
                filename="customers.csv",
                chunks=[content],
                blob_store=LocalBlobStore(blob_root),
                limits=limited,
            )

    upload(b"Customer ID,Customer Name\r\nC-9,Nine\r\n")
    upload(b"Customer ID,Customer Name\r\nC-8,Eight\r\n")
    with pytest.raises(imports.UploadRateLimitedError, match="2 uploads per person per hour"):
        upload(b"Customer ID,Customer Name\r\nC-7,Seven\r\n")
    # Someone else is unaffected.
    with session_scope(factory) as session:
        imports.upload(
            session,
            actor=space.lead,
            dataset=workspace.get_dataset(session, space.dataset_id),
            filename="customers.csv",
            chunks=[b"Customer ID,Customer Name\r\nC-6,Six\r\n"],
            blob_store=LocalBlobStore(blob_root),
            limits=limited,
        )


def test_path_traversal_in_file_names_is_inert(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    outcome = _upload(factory, space, blob_root, CSV, name="../../etc/passwd\x00.csv")
    assert outcome.import_.original_filename == "passwd.csv"
    assert not (blob_root.parent / "etc").exists()


def test_too_many_rows_fails_the_import_with_a_problem_code(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    body = b"Customer ID,Customer Name\n" + b"".join(
        b"C-%d,Name\n" % n for n in range(LIMITS.max_rows + 1)
    )
    outcome = _upload(factory, space, blob_root, body)
    drain(worker_context(factory, blob_root))
    with session_scope(factory) as session:
        record = session.get_one(Import, outcome.import_.id)
    assert record.status == ImportStatus.FAILED.value
    assert record.error is not None
    assert record.error["code"] == "import.unreadable"


def test_a_parse_job_that_cannot_read_its_file_fails_the_import(
    factory: sessionmaker[Session], space: Workspace, tmp_path: Path
) -> None:
    body = CSV + b"C-9," + uuid.uuid4().hex.encode() + b"\r\n"  # unique content, stored only in tmp
    outcome = _upload(factory, space, tmp_path / "elsewhere", body)
    drain(worker_context(factory, tmp_path / "empty-store"))
    with session_scope(factory) as session:
        record = session.get_one(Import, outcome.import_.id)
        actions = session.scalars(
            select(AuditEvent.action).where(AuditEvent.entity_id == record.id)
        ).all()
    assert record.status == ImportStatus.FAILED.value
    assert record.error == {"code": "storage.integrity_failure", "detail": "stored file is missing"}
    assert "import.failed" in actions


def test_upload_restores_a_missing_blob_for_known_content(
    factory: sessionmaker[Session], space: Workspace, tmp_path: Path
) -> None:
    body = CSV + b"C-8," + uuid.uuid4().hex.encode() + b"\r\n"
    _upload(factory, space, tmp_path / "first-store", body)
    other = make_workspace(factory)
    second_store = tmp_path / "second-store"
    outcome = _upload(factory, other, second_store, body)
    drain(worker_context(factory, second_store))
    with session_scope(factory) as session:
        record = session.get_one(Import, outcome.import_.id)
    assert record.status == ImportStatus.PARSED.value


def test_worker_survives_a_malformed_job(factory: sessionmaker[Session], tmp_path: Path) -> None:
    with session_scope(factory) as session:
        jobs.enqueue(
            session, JobKind.PARSE_IMPORT, {"unexpected": 1}, dedupe_key=f"bad:{uuid.uuid4()}"
        )
    assert drain(worker_context(factory, tmp_path)) >= 1


# -------------------------------------------------------------------------------------------- jobs
def test_competing_workers_never_claim_the_same_job(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        jobs.enqueue(
            session,
            JobKind.PARSE_IMPORT,
            {"import_id": str(uuid.uuid4())},
            dedupe_key=f"test:{uuid.uuid4()}",
        )
    first = factory()
    second = factory()
    try:
        claimed_first = jobs.claim(first, "worker-a")
        assert claimed_first is not None
        claimed_second = jobs.claim(second, "worker-b")
        assert claimed_second is None or claimed_second.id != claimed_first.id
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_enqueue_is_deduplicated(factory: sessionmaker[Session]) -> None:
    key = f"dedupe:{uuid.uuid4()}"
    with session_scope(factory) as session:
        assert jobs.enqueue(session, JobKind.PARSE_IMPORT, {}, dedupe_key=key) is not None
        assert jobs.enqueue(session, JobKind.PARSE_IMPORT, {}, dedupe_key=key) is None


# ---------------------------------------------------------------------------------------- pipeline
def test_pipeline_request_is_idempotent_on_the_fingerprint(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    _upload(factory, space, blob_root, CSV)
    context = worker_context(factory, blob_root)
    drain(context)
    with session_scope(factory) as session:
        first = pipeline.request_run(
            session, actor=space.specialist, migration_id=space.migration_id
        )
    with session_scope(factory) as session:
        again = pipeline.request_run(
            session, actor=space.specialist, migration_id=space.migration_id
        )
    assert first.created
    assert not again.created
    assert again.run.id == first.run.id
    drain(context)
    with session_scope(factory) as session:
        run = session.get_one(PipelineRun, first.run.id)
        assert run.status == "succeeded"
        after = pipeline.request_run(
            session, actor=space.specialist, migration_id=space.migration_id
        )
    assert not after.created
    assert after.run.id == first.run.id


def test_a_rule_that_raises_is_persisted_as_errored_and_blocks_readiness(
    factory: sessionmaker[Session],
    space: Workspace,
    blob_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FC-10: the run still records its evidence, names the errored rule, and G4 fails."""
    _upload(factory, space, blob_root, CSV)
    context = worker_context(factory, blob_root)
    drain(context)
    rule_id = "PARTY.UNRESOLVED_DUPLICATE_CANDIDATE"  # applicable without any dataset
    spec, _ = REGISTRY[rule_id]

    def broken(_context: Any, _spec: Any) -> list[Any]:
        raise ZeroDivisionError("division by zero")

    monkeypatch.setitem(REGISTRY, rule_id, (spec, broken))
    with session_scope(factory) as session:
        run_id = pipeline.request_run(
            session, actor=space.specialist, migration_id=space.migration_id
        ).run.id
    drain(context)
    with session_scope(factory) as session:
        run = session.get_one(PipelineRun, run_id)
        assert run.status == "succeeded"
        errored = session.execute(
            text("SELECT status, error FROM rule_runs WHERE run_id = :run AND rule_id = :rule"),
            {"run": run_id, "rule": rule_id},
        ).one()
        assert errored == ("errored", "ZeroDivisionError: division by zero")
        gate = session.execute(
            text(
                "SELECT status, evidence FROM gate_results g JOIN readiness_evaluations e"
                " ON e.id = g.evaluation_id WHERE e.run_id = :run AND g.gate_id = 'G4'"
            ),
            {"run": run_id},
        ).one()
    assert gate[0] == "fail"
    assert gate[1] == [f"rule:{rule_id} — ZeroDivisionError: division by zero"]


def test_run_fails_cleanly_when_inputs_change_after_the_request(
    factory: sessionmaker[Session], space: Workspace, blob_root: Path
) -> None:
    context = worker_context(factory, blob_root)
    _upload(factory, space, blob_root, CSV)
    drain(context)
    with session_scope(factory) as session:
        request = pipeline.request_run(
            session, actor=space.specialist, migration_id=space.migration_id
        )
    with session_scope(factory) as session:
        # A new mapping set approval changes the fingerprint before the queued run executes.
        dataset = workspace.get_dataset(session, space.dataset_id)
        draft = mapping_sets.create_draft(
            session, actor=space.specialist, dataset=dataset,
            config={
                "fields": {
                    "party_code": {"source": "Customer ID"},
                    "name": {"source": "Customer Name"},
                }
            },
        )  # fmt: skip
        mapping_sets.mark_pending(draft)
        mapping_sets.approve(
            session,
            actor=space.lead,
            mapping_set=draft,
            change_request_id=_cr(session, space),
            migration_id=space.migration_id,
        )
    drain(context)
    with session_scope(factory) as session:
        run = session.get_one(PipelineRun, request.run.id)
    assert run.status == "failed"
    assert run.error == {
        "code": "pipeline.inputs_changed",
        "detail": "configuration changed after the request",
    }


def _cr(session: Session, space: Workspace) -> uuid.UUID:
    change = ChangeRequest(
        id=uuid7(), migration_id=space.migration_id, key=f"CR-T-{uuid.uuid4().hex[:6]}",
        kind=ChangeRequestKind.COLUMN_MAPPING_SET.value, status="applied", title="t", payload={},
        origin="operator", requested_by=space.specialist.user_id,
    )  # fmt: skip
    session.add(change)
    session.flush()
    return change.id


def test_system_actor_cannot_request_changes(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    from relay.changes import service as changes  # noqa: PLC0415

    with pytest.raises(changes.ChangeRequestStateError), session_scope(factory) as session:
        changes.create_draft(
            session,
            actor=Actor.system(),
            migration=workspace.get_migration(session, space.migration_id),
            kind=ChangeRequestKind.COLUMN_MAPPING_SET,
            title="t",
            payload={"mapping_set_id": str(uuid.uuid4())},
        )  # fmt: skip


def test_unique_constraints_guard_duplicates(
    factory: sessionmaker[Session], space: Workspace
) -> None:
    def create_twice() -> None:
        with session_scope(factory) as session:
            migration = workspace.get_migration(session, space.migration_id)
            for _ in range(2):
                workspace.create_source_system(
                    session,
                    actor=space.lead,
                    migration=migration,
                    name="Same",
                    kind=SourceSystemKind.OTHER,
                )

    with pytest.raises(IntegrityError):
        create_twice()
