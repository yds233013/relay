"""M3 acceptance: Brightwater seeded through the services (day-9 state), verified from the DB."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from relay.audit import service as audit
from relay.core.db import create_session_factory, session_scope
from relay.imports.blob_store import LocalBlobStore
from relay.imports.models import SourceRow, StoredFile
from relay.imports.service import ImportLimits
from relay.issues.models import Issue
from relay.pipeline import read_model
from relay.pipeline import service as pipeline
from relay.pipeline.models import ReconciliationLineRow, ReconciliationResultRow
from relay_evaluation.brightwater import persisted
from relay_evaluation.brightwater.engine_compare import compare_run1
from relay_evaluation.brightwater.manifest import Manifest, load_manifest
from relay_evaluation.cli import _read_fixtures
from relay_evaluation.paths import BRIGHTWATER_FIXTURES
from relay_scenarios.brightwater.seed import PEOPLE, SeedResult, seed
from relay_scenarios.cli import DEFAULT_MAPPING_SET
from tests.integration.support import ensure_head


@pytest.fixture(scope="module")
def seeded(
    migrated: str, engine: Engine, tmp_path_factory: pytest.TempPathFactory
) -> tuple[SeedResult, sessionmaker[Session]]:
    ensure_head(migrated)
    factory = create_session_factory(engine)
    root = tmp_path_factory.mktemp("brightwater-blobs")
    result = seed(
        factory,
        LocalBlobStore(root),
        ImportLimits(52_428_800, 500_000),
        BRIGHTWATER_FIXTURES,
        DEFAULT_MAPPING_SET,
    )
    return result, factory


@pytest.fixture(scope="module")
def manifest() -> Manifest:
    return load_manifest()


def test_persisted_run1_matches_the_golden_manifest(
    seeded: tuple[SeedResult, sessionmaker[Session]], manifest: Manifest
) -> None:
    result, factory = seeded
    assert result.run_id is not None
    with session_scope(factory) as session:
        stored = persisted.load(session, result.run_id)
    report = compare_run1(stored, _read_fixtures(BRIGHTWATER_FIXTURES), manifest)
    assert [r for r in report.results if not r[1]] == []
    assert len(report.results) == 89


def test_persisted_gates_and_issues(
    seeded: tuple[SeedResult, sessionmaker[Session]], manifest: Manifest
) -> None:
    result, factory = seeded
    assert result.run_id is not None
    with session_scope(factory) as session:
        stored = read_model.readiness_for_run(session, result.run_id)
        assert stored is not None
        evaluation, gates = stored
        assert evaluation.overall == "not_ready"
        assert [g.gate_id for g in gates if g.status == "fail"] == list(manifest.failing_gates)
        issues = session.scalars(
            select(Issue).where(Issue.migration_id == result.migration_id)
        ).all()
        assert len(issues) == 65
        assert {i.status for i in issues} == {"open"}
        assert len({i.key for i in issues}) == 65


def test_r3_drilldown_shows_the_missing_invoice_with_gl_lineage(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    result, factory = seeded
    with session_scope(factory) as session:
        line = session.scalars(
            select(ReconciliationLineRow)
            .join(
                ReconciliationResultRow,
                ReconciliationLineRow.result_id == ReconciliationResultRow.id,
            )
            .where(
                ReconciliationResultRow.run_id == result.run_id,
                ReconciliationLineRow.grain_key == "recon:R3:party=C-0233",
            )
        ).one()
        view = read_model.drilldown(session, line.id)
        [document] = view["documents"]
        assert (document["document"], document["status"]) == ("INV-10877", "left_only")
        [ledger] = document["left_records"]
        lineage = ledger["lineage"]
        source = session.scalars(
            select(SourceRow).where(
                SourceRow.import_id == lineage["import_id"],
                SourceRow.row_number == lineage["row_number"],
            )
        ).one()
        # The lineage points at the GL export row that posted the invoice.
        assert source.values["Num"] == "JE-AR-10877"
        assert source.values["Doc No"] == "INV-10877"
        assert source.line_start == lineage["line_start"]


def test_audit_chain_verifies_after_seeding(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    result, factory = seeded
    with session_scope(factory) as session:
        migration_chain = audit.verify_chain(session, result.migration_id)
        platform_chain = audit.verify_chain(session, None)
    assert migration_chain.valid
    assert migration_chain.events_checked > 100
    assert platform_chain.valid


def test_rerun_request_returns_the_same_run(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    result, factory = seeded
    with session_scope(factory) as session:
        from relay.identity import service as identity  # noqa: PLC0415

        user = identity.find_active_user_by_email(session, PEOPLE[0][0])
        assert user is not None
        again = pipeline.request_run(
            session, actor=identity.actor_for(user), migration_id=result.migration_id
        )
    assert not again.created
    assert again.run.id == result.run_id


def test_blob_store_path_is_content_addressed(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    _, factory = seeded
    with session_scope(factory) as session:
        keys = session.scalars(select(StoredFile.storage_key)).all()
    assert keys
    assert all(len(Path(k).name) == 64 for k in keys)


def test_overview_links_every_blocker_to_evidence(
    seeded: tuple[SeedResult, sessionmaker[Session]], manifest: Manifest
) -> None:
    from relay.pipeline import overview  # noqa: PLC0415
    from relay.workspace import service as workspace  # noqa: PLC0415

    result, factory = seeded
    with session_scope(factory) as session:
        migration = workspace.get_migration(session, result.migration_id)
        data = overview.overview(session, migration, user_id=None, role=None)
    assert data["overall"] == "not_ready"
    assert data["run_is_current"] is True
    assert [b["gate_id"] for b in data["blockers"]] == list(manifest.failing_gates)
    kinds = {b["gate_id"]: {link["kind"] for link in b["evidence"]} for b in data["blockers"]}
    assert "reconciliation_line" in kinds["G6"]
    assert "reconciliation_line" in kinds["G7"]
    assert "issue" in kinds["G5"]
    assert "entity_candidate" in kinds["G10"]
    linked = [link for b in data["blockers"] for link in b["evidence"] if link["kind"] != "text"]
    assert all(
        link.get("issue_id") or link.get("line_id") or link["kind"] == "entity_candidate"
        for link in linked
    )
    amounts = [issue.amount_at_risk for issue in data["top_issues"]]
    assert amounts == sorted(amounts, reverse=True)
    assert data["open_issue_count"] == 65


def test_run_diff_of_a_run_with_itself_is_empty(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    from relay.pipeline import overview  # noqa: PLC0415

    result, factory = seeded
    assert result.run_id is not None
    with session_scope(factory) as session:
        diff = overview.run_diff(session, result.run_id, result.run_id)
    assert diff["changed_fingerprint_components"] == []
    assert diff["findings_added"] == []
    assert diff["findings_removed"] == []
    assert diff["gate_changes"] == []
