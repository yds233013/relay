"""M3 acceptance: Brightwater seeded through the services (day-9 state), verified from the DB."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from relay.audit import service as audit
from relay.core.db import create_session_factory, session_scope
from relay.imports.blob_store import LocalBlobStore
from relay.imports.models import SourceRow, StoredFile
from relay.imports.service import ImportLimits
from relay.issues.models import Issue
from relay.pipeline import read_model, work_queue
from relay.pipeline import service as pipeline
from relay.pipeline.models import ReconciliationLineRow, ReconciliationResultRow
from relay.workspace import service as workspace
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


# ---------------------------------------------------------------------------------- work queue
def test_the_work_queue_groups_findings_into_decisions(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    """Sixty-five findings are not sixty-five decisions: the queue is much shorter than the list."""
    result, factory = seeded
    with session_scope(factory) as session:
        migration = workspace.get_migration(session, result.migration_id)
        items = work_queue.work_items(session, migration, user_id=None, role=None)
        open_issues = session.scalar(
            select(func.count()).select_from(Issue).where(Issue.migration_id == migration.id)
        )
    assert open_issues == 65
    assert 0 < len(items) < open_issues / 2
    assert all(item.title and item.summary for item in items)
    assert all(item.action_label and item.target_kind for item in items)


def test_a_mapping_problem_carries_the_money_a_reconciliation_attributes_to_it(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    """The engine's own explainer joins the mapping to the difference; the queue does not guess.

    The generator plants a contra-asset mapped into the receivables control account. The engine
    reports the mapping conflict and, separately, a subledger difference it attributes to that one
    legacy account. The queue is expected to present them as a single decision carrying the amount.
    """
    result, factory = seeded
    with session_scope(factory) as session:
        migration = workspace.get_migration(session, result.migration_id)
        items = work_queue.work_items(session, migration, user_id=None, role=None)
    mapping = [item for item in items if item.kind == "account_mapping" and item.amount]
    assert mapping, "expected a mapping decision carrying an attributed amount"
    first = mapping[0]
    assert first.amount == Decimal("38400.00")
    assert first.detail["legacy_account"] == "1205"
    assert first.detail["target_account"] == "1200"
    assert first.target_kind == "mappings"
    # It leads the queue: nothing open is both larger and blocking.
    assert items[0].key == first.key


def test_every_block_claim_matches_a_failing_gate(
    seeded: tuple[SeedResult, sessionmaker[Session]], manifest: Manifest
) -> None:
    result, factory = seeded
    with session_scope(factory) as session:
        migration = workspace.get_migration(session, result.migration_id)
        items = work_queue.work_items(session, migration, user_id=None, role=None)
    claimed = {gate for item in items for gate in item.blocks}
    assert claimed
    assert claimed <= set(manifest.failing_gates)


def test_covered_causes_are_not_also_listed_as_findings(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    """A duplicate-party finding is the symptom of the entity decision, not a second task."""
    result, factory = seeded
    with session_scope(factory) as session:
        migration = workspace.get_migration(session, result.migration_id)
        items = work_queue.work_items(session, migration, user_id=None, role=None)
    rules = {item.detail.get("rule") for item in items}
    assert "PARTY.UNRESOLVED_DUPLICATE_CANDIDATE" not in rules
    assert "NORM.MALFORMED_ROW" not in rules
    assert any(item.kind == "entity_decision" for item in items)
    assert any(item.kind == "data_quality" for item in items)


def test_the_automation_summary_only_reports_what_the_run_stored(
    seeded: tuple[SeedResult, sessionmaker[Session]],
) -> None:
    result, factory = seeded
    with session_scope(factory) as session:
        run = read_model.latest_succeeded_run(session, result.migration_id)
        assert run is not None
        summary = work_queue.automation_summary(session, run)
        rules = read_model.rule_runs(session, run.id)
        results = read_model.reconciliation_results(session, run.id)
    assert summary["findings"] == run.counts["findings"]
    assert summary["staged_records"] == run.counts["staged_records"]
    assert summary["controls_evaluated"] == len(rules)
    assert summary["reconciliations_performed"] == len(results)
    assert summary["run_sequence"] == run.sequence
