"""M6 acceptance at the API: issue workflow, re-imports, entity decisions and dispositions.

Brightwater is seeded at day 9, then every documented resolution is made through the HTTP API as
the seeded people: re-exports (DS-04, DS-09, DS-12), mapping changes (DS-03, DS-12), overrides and
a repair (DS-05, DS-08, DS-11), entity decisions (DS-01, DS-06) and dispositions (DS-02, DS-07,
DS-10, DS-13). The final persisted run is compared with the pure engine applying the documented
resolutions from ``relay_evaluation.brightwater.resolution``. Tests run in order.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from relay.api.app import create_app
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.engine.pipeline import EngineResult, run_engine
from relay.issues.models import IssueComment, IssueLink
from relay.workspace.models import Dataset
from relay_evaluation.brightwater import persisted, resolution
from relay_evaluation.cli import _read_fixtures
from relay_evaluation.paths import BRIGHTWATER_FIXTURES, BRIGHTWATER_REEXPORT
from tests.integration.api_story import (
    DANIEL,
    MAYA,
    PRIYA,
    SAM,
    Story,
    approve_all,
    draft_account_mapping,
    draft_and_submit,
    drain_jobs,
    findings,
    headers,
    issues_with_rule,
    latest_run,
    ok,
    ok_object,
    process_run,
    seed_story,
    upload,
)


@pytest.fixture(scope="module")
def story(migrated: str, engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> Story:
    return seed_story(migrated, engine, tmp_path_factory.mktemp("workflow-blobs"))


@pytest.fixture(scope="module")
def client(settings: Settings, story: Story) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"storage_dir": story[2]})
    with TestClient(create_app(configured)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def engine_run1() -> EngineResult:
    return run_engine(resolution.inputs_for(_read_fixtures(BRIGHTWATER_FIXTURES)))


def _issue(client: TestClient, story: Story, rule: str, subject: str | None = None) -> Any:
    page = ok(
        client.get(
            f"/api/v1/migrations/{story[0].migration_id}/issues",
            params={"rule": rule, "limit": 500},
            headers=headers(SAM),
        )
    )
    matches = [i for i in page["items"] if subject is None or subject in i["subjects"]]
    assert matches, (rule, subject)
    return matches[0]


def _run_latest(client: TestClient, story: Story) -> uuid.UUID:
    response = client.post(
        f"/api/v1/migrations/{story[0].migration_id}/pipeline-runs", headers=headers(MAYA)
    )
    assert response.status_code == 202, response.text
    return process_run(story, response.json()["id"])


def _exposure(client: TestClient, story: Story) -> Decimal:
    overview = ok(
        client.get(f"/api/v1/migrations/{story[0].migration_id}/overview", headers=headers(SAM))
    )
    return Decimal(overview["unresolved_exposure"])


# ------------------------------------------------------------------------------------ workflow
def test_issue_workflow_owner_status_comments_and_resolution_rules(
    client: TestClient, story: Story
) -> None:
    issue = _issue(client, story, "GL.PERIOD_MATCHES_DATE", "je:JE-2026-0388")
    path = f"/api/v1/issues/{issue['id']}"
    users = {u["email"]: u for u in ok(client.get("/api/v1/dev/users"))}

    viewer = client.patch(path, json={"version": issue["version"], "status": "in_progress"},
                          headers=headers(SAM))  # fmt: skip
    assert viewer.status_code == 403
    updated = ok(
        client.patch(
            path,
            json={
                "version": issue["version"],
                "owner_user_id": users[MAYA]["id"],
                "status": "in_progress",
                "note": "Checking the March close binder",
            },
            headers=headers(MAYA),
        )
    )
    assert updated["status"] == "in_progress"
    assert updated["owner_user_id"] == users[MAYA]["id"]

    stale = client.patch(path, json={"version": issue["version"], "status": "open"},
                         headers=headers(MAYA))  # fmt: skip
    assert stale.status_code == 409
    assert stale.json()["code"] == "issue.version_conflict"
    resolved = client.patch(path, json={"version": updated["version"], "status": "resolved"},
                            headers=headers(DANIEL))  # fmt: skip
    assert resolved.status_code == 409
    assert resolved.json()["code"] == "issue.resolution_requires_verification"
    closed = client.patch(path, json={"version": updated["version"], "status": "closed"},
                          headers=headers(DANIEL))  # fmt: skip
    assert closed.json()["code"] == "issue.invalid_transition"

    comment = ok_object(
        client.post(f"{path}/comments", json={"body": "Binder confirms March."},
                    headers=headers(PRIYA)),
        201,
    )  # fmt: skip
    assert [c["body"] for c in ok(client.get(f"{path}/comments", headers=headers(SAM)))] == [
        "Binder confirms March."
    ]
    with pytest.raises(DBAPIError), session_scope(story[1]) as session:
        session.execute(
            text("UPDATE issue_comments SET body = 'edited' WHERE id = :id"),
            {"id": comment["id"]},
        )
    actions = [e["action"] for e in ok(client.get(f"{path}/history", headers=headers(SAM)))]
    assert actions == ["issue.created", "issue.workflow_updated", "issue.commented"]


def test_manual_issues_can_be_closed_by_their_owner(client: TestClient, story: Story) -> None:
    created = ok_object(
        client.post(
            f"/api/v1/migrations/{story[0].migration_id}/issues",
            json={
                "title": "Confirm the opening balance of the petty cash box",
                "severity": "low",
                "category": "cash",
                "nature": "source_anomaly",
                "description": "Not in any export.",
            },
            headers=headers(MAYA),
        ),
        201,
    )
    assert created["source"] == "manual"
    assert created["fingerprint"] is None
    closed = ok(
        client.patch(
            f"/api/v1/issues/{created['id']}",
            json={"version": created["version"], "status": "closed"},
            headers=headers(MAYA),
        )
    )
    assert closed["status"] == "closed"


def test_system_links_connect_issues_sharing_records(story: Story) -> None:
    with session_scope(story[1]) as session:
        links = session.scalars(
            select(IssueLink).where(IssueLink.migration_id == story[0].migration_id)
        ).all()
        assert links
        assert {link.link_type for link in links} == {"same_root_cause"}
        assert all(link.from_issue_id < link.to_issue_id for link in links)
        # DS-11: the impossible date and the period mismatch name the same journal entry.
        keys = {link.reason.split(" (run")[0] for link in links}
        assert "both name je:JE-AP-20455" in keys


# ------------------------------------------------------------------------------------ E2E-3
def test_e2e3_reimports_are_idempotent_and_corrected_exports_replace_the_active_import(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    with session_scope(story[1]) as session:
        datasets = {
            d.name: d.id
            for d in session.scalars(select(Dataset).where(Dataset.migration_id == migration_id))
        }
    original = (BRIGHTWATER_FIXTURES / "ledgerpro" / "ledgerpro_invoices.csv").read_bytes()
    again = upload(client, datasets["ledgerpro_invoices.csv"], "ledgerpro_invoices.csv", original)
    assert again["sequence"] == 1

    for path in sorted((BRIGHTWATER_REEXPORT / "ledgerpro").iterdir()):
        result = upload(client, datasets[path.name], path.name, path.read_bytes())
        assert result["sequence"] == 2
        assert result["status"] == "pending"
    drain_jobs(story)
    imports = ok(
        client.get(
            f"/api/v1/datasets/{datasets['ledgerpro_invoices.csv']}/imports",
            headers=headers(SAM),
        )
    )
    assert {i["sequence"]: i["status"] for i in imports} == {1: "superseded", 2: "parsed"}

    run_id = _run_latest(client, story)
    assert findings(story, run_id, "AR.INVOICE_PARTY_EXISTS") == []  # DS-09
    assert findings(story, run_id, "AR.PAYMENT_PARTY_EXISTS") == []
    assert findings(story, run_id, "GL.ACCOUNT_EXISTS") == []  # DS-12 account now in the chart
    # DS-04: the invoice missing from the first export is now an open item, so R3b ties.
    assert [line for line in persisted_lines(story, run_id, "R3b") if line.difference != 0] == []


def persisted_lines(story: Story, run_id: uuid.UUID, recon_id: str) -> list[Any]:
    with session_scope(story[1]) as session:
        result = persisted.load(session, run_id)
    return [line for r in result.reconciliations if r.recon_id == recon_id for line in r.lines]


# ------------------------------------------------------------------------------ E2E-4 (DS-01)
def test_e2e4_merging_duplicate_vendors_reveals_the_double_payment(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    candidate_issue = _issue(client, story, "PARTY.UNRESOLVED_DUPLICATE_CANDIDATE",
                             "party:vendor:V-1042")  # fmt: skip
    run_id = latest_run(story)
    missing = client.post(
        f"/api/v1/migrations/{migration_id}/change-requests",
        json={
            "kind": "entity_decision",
            "title": "Merge",
            "payload": {"party_type": "vendor", "decision": "same_entity",
                        "members": ["V-1042", "V-9999"], "survivor": "V-1042",
                        "run_id": str(run_id)},
        },
        headers=headers(MAYA),
    )  # fmt: skip
    assert missing.status_code == 422
    merge = draft_and_submit(
        client,
        migration_id,
        {
            "kind": "entity_decision",
            "title": "Merge Pacific Coast Packaging",
            "payload": {"party_type": "vendor", "decision": "same_entity",
                        "members": ["V-1187", "V-1042"], "survivor": "V-1042",
                        "run_id": str(run_id)},
            "evidence_refs": [{"kind": "issue", "issue_id": candidate_issue["id"]}],
        },
        "Same tax id, address and vendor invoice reference.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{merge['id']}", headers=headers(SAM)))
    assert [r["role"] for r in detail["requirements"]] == ["implementation_lead"]
    outcome = approve_all(client, merge["id"], [DANIEL])
    assert outcome["change_request"]["status"] == "applied"
    status = ok(client.get(f"/api/v1/issues/{candidate_issue['id']}", headers=headers(SAM)))
    assert status["status"] == "awaiting_verification"
    run = process_run(story, outcome["run_id"])

    assert (
        ok(client.get(f"/api/v1/issues/{candidate_issue['id']}", headers=headers(SAM)))["status"]
        == "resolved"
    )
    duplicates = issues_with_rule(story, "AP.DUPLICATE_BILL") + issues_with_rule(
        story, "PAY.DUPLICATE_PAYMENT"
    )
    assert duplicates
    assert {i.status for i in duplicates} == {"open"}
    assert all(i.first_seen_run_id == run for i in duplicates)

    before = _exposure(client, story)
    disposition = draft_and_submit(
        client,
        migration_id,
        {
            "kind": "disposition",
            "title": "Double payment to Pacific Coast Packaging",
            "payload": {"issue_ids": [str(i.id) for i in duplicates],
                        "kind": "carry_forward_adjustment", "amount": "14862.50",
                        "follow_up": "Request a refund or credit from the vendor"},
        },
        "Real overpayment in legacy books; record the vendor receivable in the new ERP.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{disposition['id']}", headers=headers(SAM)))
    assert [r["role"] for r in detail["requirements"]] == ["customer_controller"]
    denied = client.post(f"/api/v1/change-requests/{disposition['id']}/approve", json={},
                         headers=headers(DANIEL))  # fmt: skip
    assert denied.status_code == 403
    outcome = approve_all(client, disposition["id"], [PRIYA])
    assert outcome["change_request"]["status"] == "applied"
    process_run(story, outcome["run_id"])
    assert {i.status for i in issues_with_rule(story, "AP.DUPLICATE_BILL")} == {"dispositioned"}
    assert _exposure(client, story) < before


# ------------------------------------------------------------------------------ DS-06 decisions
def test_ds06_merge_the_co_op_and_keep_the_second_store_distinct(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    run_id = str(latest_run(story))
    decisions = [
        ("same_entity", ["C-0107", "C-0154"], "C-0107", "Same billing entity and AP contact"),
        ("distinct", ["C-0107", "C-0198"], None, "Separate store with its own billing"),
        ("distinct", ["C-0154", "C-0198"], None, "Separate store with its own billing"),
    ]
    for decision, members, survivor, why in decisions:
        change = draft_and_submit(
            client,
            migration_id,
            {"kind": "entity_decision", "title": f"{decision} {members}",
             "payload": {"party_type": "customer", "decision": decision, "members": members,
                         "survivor": survivor, "run_id": run_id}},
            why,
        )  # fmt: skip
        approve_all(client, change["id"], [DANIEL])
    overlap = client.post(
        f"/api/v1/migrations/{migration_id}/change-requests",
        json={"kind": "entity_decision", "title": "Contradiction",
              "payload": {"party_type": "customer", "decision": "distinct",
                          "members": ["C-0154", "C-0107"], "run_id": run_id}},
        headers=headers(MAYA),
    )  # fmt: skip
    assert overlap.status_code == 409
    decided = ok(
        client.get(f"/api/v1/migrations/{migration_id}/entity-decisions", headers=headers(SAM))
    )
    assert len([d for d in decided if d["status"] == "active"]) == 4


# ----------------------------------------------------------------- remaining documented fixes
def test_mapping_overrides_repair_and_dispositions_complete_the_documented_resolution(
    client: TestClient, story: Story, engine_run1: EngineResult
) -> None:
    migration_id = story[0].migration_id
    mapping = draft_account_mapping(
        client,
        migration_id,
        [{"legacy": "1205", "target": "1210"}, {"legacy": "6999", "target": "1999"}],
    )
    change = draft_and_submit(
        client, migration_id,
        {"kind": "account_mapping_set", "title": "Allowance and suspense",
         "payload": {"mapping_set_id": mapping["id"]}},
        "Contra account and inactive suspense account.",
    )  # fmt: skip
    approve_all(client, change["id"], [DANIEL, PRIYA])

    run_id = str(latest_run(story))
    for key, value in (("je:JE-2026-0388", "2026-03-31"), ("je:JE-AP-20455", "2026-03-14")):
        change = draft_and_submit(
            client, migration_id,
            {"kind": "record_override", "title": f"Date of {key}",
             "field_override": {"run_id": run_id, "natural_key": key, "field": "entry_date",
                                "new_value": value}},
            "Documented correction.",
        )  # fmt: skip
        approve_all(client, change["id"], [DANIEL, PRIYA])
    (malformed,) = findings(story, latest_run(story), "NORM.MALFORMED_ROW")
    change = draft_and_submit(
        client, migration_id,
        {"kind": "record_override", "title": "Repair",
         "quarantine_repair": {"exception_id": str(malformed.id),
                               "replacement_text": resolution.quarantine_repair(
                                   engine_run1).replacement_text}},
        "Memo contained a line break.",
    )  # fmt: skip
    outcome = approve_all(client, change["id"], [DANIEL, PRIYA])
    process_run(story, outcome["run_id"])

    for rule, kind, amount, reviewers in (
        ("CUR.PARTY_CURRENCY_MISMATCH", "carry_forward_adjustment", "2347.95", [PRIYA]),
        ("BANK.UNRECORDED_ACTIVITY", "carry_forward_adjustment", "270.00", [PRIYA]),
        ("DATA.INSTRUCTION_LIKE_TEXT", "not_applicable", None, [DANIEL]),
    ):
        open_issues = [i for i in issues_with_rule(story, rule) if i.status == "open"]
        assert open_issues, rule
        change = draft_and_submit(
            client, migration_id,
            {"kind": "disposition", "title": rule,
             "payload": {"issue_ids": [str(i.id) for i in open_issues], "kind": kind,
                         "amount": amount, "follow_up": "Documented in the cutover plan"}},
            "Documented decision.",
        )  # fmt: skip
        detail = ok(client.get(f"/api/v1/change-requests/{change['id']}", headers=headers(SAM)))
        roles = ["customer_controller"] if reviewers == [PRIYA] else ["implementation_lead"]
        assert [r["role"] for r in detail["requirements"]] == roles, rule
        outcome = approve_all(client, change["id"], reviewers)
        assert outcome["change_request"]["status"] == "applied", rule
    process_run(story, outcome["run_id"])


def _signature(result: Any) -> tuple[Counter[str], set[Any], set[Any]]:
    rules = Counter(e.rule_id for e in result.exceptions)
    subjects = {
        (e.rule_id, tuple(e.subjects))
        for e in result.exceptions
        if not any("/" in s or s.count("-") >= 4 for s in e.subjects)
    }
    lines = {
        (r.recon_id, line.grain, line.difference, line.unexplained)
        for r in result.reconciliations
        for line in r.lines
        if line.difference != 0 or line.unexplained != 0
    }
    return rules, subjects, lines


def test_final_run_equals_the_documented_resolution_and_only_signoff_remains(
    client: TestClient, story: Story, engine_run1: EngineResult
) -> None:
    reexported = {
        **_read_fixtures(BRIGHTWATER_FIXTURES),
        **{
            p.relative_to(BRIGHTWATER_REEXPORT).as_posix(): p.read_bytes()
            for p in BRIGHTWATER_REEXPORT.rglob("*.csv")
        },
    }
    inputs = resolution.inputs_for(reexported)
    corrected = resolution.corrections(engine_run1)
    expected = run_engine(
        inputs, resolution.with_dispositions(corrected, run_engine(inputs, corrected))
    )
    with session_scope(story[1]) as session:
        actual = persisted.load(session, latest_run(story))
    assert _signature(actual) == _signature(expected)
    # Not vacuous: dispositioned findings are still reported, so the comparison has content.
    assert _signature(expected)[0]["BANK.UNRECORDED_ACTIVITY"] == 6

    readiness = ok(
        client.get(f"/api/v1/migrations/{story[0].migration_id}/readiness", headers=headers(SAM))
    )
    assert [g["gate_id"] for g in readiness["gates"] if g["status"] == "fail"] == ["G12"]
    assert _exposure(client, story) == 0


def test_reverting_a_disposition_reopens_the_issue(client: TestClient, story: Story) -> None:
    dispositions = ok(
        client.get(f"/api/v1/migrations/{story[0].migration_id}/dispositions", headers=headers(SAM))
    )
    target = next(d for d in dispositions if d["kind"] == "not_applicable")
    change = draft_and_submit(
        client, story[0].migration_id,
        {"kind": "revert", "title": "Revisit the vendor note",
         "payload": {"target": "disposition", "target_id": target["id"]}},
        "Security wants to review the note first.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{change['id']}", headers=headers(SAM)))
    assert [r["role"] for r in detail["requirements"]] == ["implementation_lead"]
    outcome = approve_all(client, change["id"], [DANIEL])
    assert (
        ok(client.get(f"/api/v1/issues/{target['issue_id']}", headers=headers(SAM)))["status"]
        == "open"
    )
    process_run(story, outcome["run_id"])
    issue = ok(client.get(f"/api/v1/issues/{target['issue_id']}", headers=headers(SAM)))
    assert issue["status"] == "open"  # still reported by the rerun, so not resolved


def test_comments_are_append_only_rows(story: Story) -> None:
    with session_scope(story[1]) as session:
        assert session.scalars(select(IssueComment)).first() is not None
    with pytest.raises(DBAPIError), session_scope(story[1]) as session:
        session.execute(text("DELETE FROM issue_comments"))
