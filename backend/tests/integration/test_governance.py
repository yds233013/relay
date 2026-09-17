"""M5 acceptance at the API: mappings, change requests, approvals, overrides, reverts, staleness.

Brightwater is seeded at day 9. Corrections for DS-03, DS-05, DS-08 and DS-11 are made the way a
team would make them through the HTTP API (the web UI calls the same endpoints), then the resulting
persisted run is compared with the pure engine applying the documented resolutions from
``relay_evaluation.brightwater.resolution``. Tests in this module run in order and build on each
other, like the demo story.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from relay.api.app import create_app
from relay.audit.models import AuditEvent
from relay.changes.models import ChangeRequest
from relay.core.config import Settings
from relay.core.db import create_session_factory, session_scope
from relay.engine.overlays import AccountMappingChange, Overlays
from relay.engine.pipeline import EngineResult, run_engine
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay.issues.models import Issue
from relay.pipeline.models import PipelineRun, RuleExceptionRow
from relay.worker import drain
from relay_evaluation.brightwater import persisted, resolution
from relay_evaluation.cli import _read_fixtures
from relay_evaluation.paths import BRIGHTWATER_FIXTURES
from relay_scenarios.brightwater.seed import SeedResult, seed
from relay_scenarios.cli import DEFAULT_MAPPING_SET
from tests.integration.support import ensure_head, worker_context

MAYA = "maya.chen@relay.example"
DANIEL = "daniel.okafor@relay.example"
PRIYA = "priya.raman@brightwater.example"
SAM = "sam.ortiz@brightwater.example"

Story = tuple[SeedResult, sessionmaker[Session], Path]


def headers(email: str) -> dict[str, str]:
    return {"X-Relay-User": email}


@pytest.fixture(scope="module")
def story(migrated: str, engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> Story:
    ensure_head(migrated)
    factory = create_session_factory(engine)
    root = tmp_path_factory.mktemp("governance-blobs")
    result = seed(
        factory, LocalBlobStore(root), ImportLimits(52_428_800, 500_000), BRIGHTWATER_FIXTURES,
        DEFAULT_MAPPING_SET,
    )  # fmt: skip
    return result, factory, root


@pytest.fixture(scope="module")
def client(settings: Settings, story: Story) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"storage_dir": story[2]})
    with TestClient(create_app(configured)) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def engine_run1() -> EngineResult:
    return run_engine(resolution.inputs_for(_read_fixtures(BRIGHTWATER_FIXTURES)))


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def ok_object(response: Any, code: int = 200) -> dict[str, Any]:
    body = ok(response, code)
    assert isinstance(body, dict)
    return body


def process_run(story: Story, run_id: str) -> uuid.UUID:
    _, factory, root = story
    drain(worker_context(factory, root))
    with session_scope(factory) as session:
        run = session.get_one(PipelineRun, uuid.UUID(run_id))
        assert run.status == "succeeded", run.error
        return run.id


def findings(story: Story, run_id: uuid.UUID, rule_id: str) -> list[RuleExceptionRow]:
    with session_scope(story[1]) as session:
        rows = session.scalars(
            select(RuleExceptionRow).where(
                RuleExceptionRow.run_id == run_id, RuleExceptionRow.rule_id == rule_id
            )
        ).all()
        session.expunge_all()
        return list(rows)


def issue_status(story: Story, rule_id: str, subject: str) -> str:
    with session_scope(story[1]) as session:
        issue = session.scalars(
            select(Issue).where(
                Issue.migration_id == story[0].migration_id,
                Issue.rule_or_recon_id == rule_id,
                Issue.subjects.contains([subject]),
            )
        ).one()
        return issue.status


def approve_all(client: TestClient, change_id: str, reviewers: list[str]) -> dict[str, Any]:
    outcome: dict[str, Any] = {}
    for reviewer in reviewers:
        outcome = ok(
            client.post(
                f"/api/v1/change-requests/{change_id}/approve",
                json={"comment": "Checked against the evidence."},
                headers=headers(reviewer),
            )
        )
    return outcome


def draft_and_submit(
    client: TestClient, migration_id: uuid.UUID, body: dict[str, Any], justification: str
) -> dict[str, Any]:
    change = ok(
        client.post(
            f"/api/v1/migrations/{migration_id}/change-requests", json=body, headers=headers(MAYA)
        ),
        201,
    )
    return ok_object(
        client.post(
            f"/api/v1/change-requests/{change['id']}/submit",
            json={"justification": justification},
            headers=headers(MAYA),
        )
    )


def draft_account_mapping(
    client: TestClient, migration_id: uuid.UUID, changes: list[dict[str, str | None]]
) -> dict[str, Any]:
    return ok_object(
        client.post(
            f"/api/v1/migrations/{migration_id}/account-mapping-sets",
            json={"base": "approved", "changes": changes},
            headers=headers(MAYA),
        ),
        201,
    )


# ------------------------------------------------------------------------------------ mappings
def test_account_mapping_signals_flag_the_contra_account(client: TestClient, story: Story) -> None:
    overview = ok(
        client.get(
            f"/api/v1/migrations/{story[0].migration_id}/account-mapping", headers=headers(SAM)
        )
    )
    assert overview["source"] == "approved_set"
    assert overview["approved_set"]["version"] == 1
    row = next(r for r in overview["rows"] if r["legacy_account_code"] == "1205")
    assert row["target_account_code"] == "1200"
    assert row["signals"] == {
        "target_exists": True, "type_compatible": True, "subtype_compatible": False
    }  # fmt: skip
    # The proposal comes from general name and subtype matching, not from the scenario.
    assert row["proposal"]["target"] == "1210"
    assert row["proposal"]["signals"]["subtype_compatible"] is True


def test_column_mapping_suggestion_and_preview(client: TestClient, story: Story) -> None:
    with session_scope(story[1]) as session:
        from relay.workspace.models import Dataset  # noqa: PLC0415 - test-local lookup

        dataset = session.scalars(
            select(Dataset).where(
                Dataset.migration_id == story[0].migration_id, Dataset.dataset_type == "gl_detail"
            )
        ).one()
        dataset_id = dataset.id
    suggestion = ok(
        client.get(f"/api/v1/datasets/{dataset_id}/column-mapping-suggestion", headers=headers(SAM))
    )
    by_field = {f["field"]: f for f in suggestion["fields"]}
    assert by_field["functional_amount"]["specification"]["debit_credit"]["debit"] == "Debit"
    assert by_field["entry_date"]["specification"]["steps"][-1] == {
        "step": "parse_date", "format": "MM/DD/YYYY"
    }  # fmt: skip
    preview = ok(
        client.post(
            f"/api/v1/datasets/{dataset_id}/column-mapping-preview",
            json={"fields": {"entry_date": by_field["entry_date"]["specification"]}},
            headers=headers(MAYA),
        )
    )
    assert len(preview["rows"]) == 50
    assert all(not r["errors"] for r in preview["rows"])
    assert "account_code" in preview["missing_required_fields"]
    denied = client.post(
        f"/api/v1/datasets/{dataset_id}/column-mapping-preview",
        json={"fields": {}},
        headers=headers(SAM),
    )
    assert denied.status_code == 403


# ------------------------------------------------------------------------------- E2E-2 (DS-03)
def test_e2e2_account_mapping_change_with_segregation_of_duties(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    draft = draft_account_mapping(
        client,
        migration_id,
        [{"legacy": "1205", "target": "1210", "rationale": "Allowance is a contra-asset"}],
    )
    assert draft["version"] == 2
    change = draft_and_submit(
        client,
        migration_id,
        {
            "kind": "account_mapping_set",
            "title": "Map allowance to allowance for credit losses",
            "payload": {"mapping_set_id": draft["id"]},
        },
        "1205 is a contra-asset and must not be merged into receivables.",
    )
    detail = ok(client.get(f"/api/v1/change-requests/{change['id']}", headers=headers(MAYA)))
    assert [r["role"] for r in detail["requirements"]] == [
        "implementation_lead", "customer_controller"
    ]  # fmt: skip
    assert detail["impact"]["changed_count"] == 1
    assert detail["impact"]["changes"][0]["before"] == "1200"
    assert detail["impact"]["changes"][0]["signals"]["subtype_compatible"] is True
    assert detail["viewer"] == {
        "can_review": False, "reason": "your role does not review change requests",
        "is_requester": True,
    }  # fmt: skip

    # Maya has no approve button, and the API rejects her regardless.
    denied = client.post(
        f"/api/v1/change-requests/{change['id']}/approve", json={}, headers=headers(MAYA)
    )
    assert denied.status_code == 403
    first = approve_all(client, change["id"], [DANIEL])
    assert first["change_request"]["status"] == "submitted"
    assert first["run_id"] is None
    twice = client.post(
        f"/api/v1/change-requests/{change['id']}/approve", json={}, headers=headers(DANIEL)
    )
    assert twice.status_code == 403
    outcome = approve_all(client, change["id"], [PRIYA])
    assert outcome["change_request"]["status"] == "applied"
    run_id = process_run(story, outcome["run_id"])

    assert [
        f
        for f in findings(story, run_id, "MAP.SUBTYPE_COMPATIBLE")
        if "acct:legacy:1205" in f.subjects
    ] == []
    assert issue_status(story, "MAP.SUBTYPE_COMPATIBLE", "acct:legacy:1205") == "resolved"
    with session_scope(story[1]) as session:
        result = persisted.load(session, run_id)
    r3 = next(r for r in result.reconciliations if r.recon_id == "R3")
    unassigned = [line for line in r3.lines if ("party", "unassigned") in line.grain]
    assert all(line.difference == Decimal(0) for line in unassigned)


def test_a_lead_cannot_approve_their_own_change(client: TestClient, story: Story) -> None:
    change = ok(
        client.post(
            f"/api/v1/migrations/{story[0].migration_id}/change-requests",
            json={
                "kind": "policy_change",
                "title": "Lead's own change",
                "payload": {"changes": {"duplicate_window_days": 8}},
            },
            headers=headers(DANIEL),
        ),
        201,
    )
    ok(
        client.post(
            f"/api/v1/change-requests/{change['id']}/submit",
            json={"justification": "Probe"},
            headers=headers(DANIEL),
        )
    )
    denied = client.post(
        f"/api/v1/change-requests/{change['id']}/approve", json={}, headers=headers(DANIEL)
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "approval.segregation_of_duties"
    ok(
        client.post(
            f"/api/v1/change-requests/{change['id']}/withdraw", json={}, headers=headers(DANIEL)
        )
    )


# ---------------------------------------------------------------------------------- staleness
def test_approving_one_change_makes_a_competing_change_stale(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    competing = []
    for target in ("1999", "6100"):
        draft = draft_account_mapping(client, migration_id, [{"legacy": "6999", "target": target}])
        competing.append(
            draft_and_submit(
                client,
                migration_id,
                {
                    "kind": "account_mapping_set",
                    "title": f"Map suspense to {target}",
                    "payload": {"mapping_set_id": draft["id"]},
                },
                "Suspense needs a target account.",
            )
        )
    winner, loser = competing
    ok(
        client.post(
            f"/api/v1/change-requests/{loser['id']}/approve", json={}, headers=headers(DANIEL)
        )
    )
    outcome = approve_all(client, winner["id"], [DANIEL, PRIYA])
    assert outcome["change_request"]["status"] == "applied"
    process_run(story, outcome["run_id"])

    stale = ok(client.get(f"/api/v1/change-requests/{loser['id']}", headers=headers(PRIYA)))
    assert stale["change_request"]["status"] == "stale"
    assert stale["viewer"]["can_review"] is False
    assert [e["action"] for e in stale["history"]][-1] == "change_request.stale"
    blocked = client.post(
        f"/api/v1/change-requests/{loser['id']}/approve", json={}, headers=headers(PRIYA)
    )
    assert blocked.status_code == 409
    sets = ok(
        client.get(f"/api/v1/migrations/{migration_id}/account-mapping", headers=headers(SAM))
    )
    statuses = {s["version"]: s["status"] for s in sets["sets"]}
    assert statuses == {1: "superseded", 2: "superseded", 3: "approved", 4: "abandoned"}


# ----------------------------------------------------------------------- DS-08 and DS-11 overrides
def _latest_run(story: Story) -> uuid.UUID:
    with session_scope(story[1]) as session:
        return session.scalars(
            select(PipelineRun.id)
            .where(
                PipelineRun.migration_id == story[0].migration_id, PipelineRun.status == "succeeded"
            )
            .order_by(PipelineRun.sequence.desc())
        ).first()  # type: ignore[return-value]


def _override(
    client: TestClient, story: Story, natural_key: str, value: str, justification: str
) -> dict[str, Any]:
    return draft_and_submit(
        client,
        story[0].migration_id,
        {
            "kind": "record_override",
            "title": f"Correct entry date of {natural_key}",
            "field_override": {
                "run_id": str(_latest_run(story)),
                "natural_key": natural_key,
                "field": "entry_date",
                "new_value": value,
            },
        },
        justification,
    )


def test_ds08_and_ds11_entry_date_overrides(client: TestClient, story: Story) -> None:
    ds08 = _override(
        client, story, "je:JE-2026-0388", "2026-03-31",
        "Adjustment belongs to the March close; original date preserved in lineage.",
    )  # fmt: skip
    ds11 = _override(
        client, story, "je:JE-AP-20455", "2026-03-14",
        "Keying error; bill date and posting period are March 2026.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{ds08['id']}", headers=headers(DANIEL)))
    assert detail["before"]["value"] == "2026-04-02"
    assert detail["impact"]["amount"] == "21730.00"
    assert [r["role"] for r in detail["requirements"]] == [
        "implementation_lead", "customer_controller"
    ]  # fmt: skip
    assert detail["viewer"]["can_review"] is True

    duplicate = client.post(
        f"/api/v1/migrations/{story[0].migration_id}/change-requests",
        json={
            "kind": "record_override",
            "title": "Tampered",
            "payload": {"override": {"expected_current": "anything"}},
        },
        headers=headers(MAYA),
    )
    assert duplicate.status_code == 422

    approve_all(client, ds08["id"], [DANIEL, PRIYA])
    outcome = approve_all(client, ds11["id"], [PRIYA, DANIEL])
    run_id = process_run(story, outcome["run_id"])
    assert findings(story, run_id, "GL.PERIOD_MATCHES_DATE") == []
    assert findings(story, run_id, "GL.DATE_IN_WINDOW") == []
    assert issue_status(story, "GL.PERIOD_MATCHES_DATE", "je:JE-2026-0388") == "resolved"
    assert issue_status(story, "GL.DATE_IN_WINDOW", "je:JE-AP-20455") == "resolved"


# ---------------------------------------------------------------------------- DS-05 repair
def test_ds05_quarantined_row_repair(
    client: TestClient, story: Story, engine_run1: EngineResult
) -> None:
    run_id = _latest_run(story)
    (malformed,) = findings(story, run_id, "NORM.MALFORMED_ROW")
    # The operator rewrites the broken record with its memo quoted; the evaluation helper does
    # exactly what a person would type from the raw text shown in the UI.
    replacement = resolution.quarantine_repair(engine_run1).replacement_text
    wrong = client.post(
        f"/api/v1/migrations/{story[0].migration_id}/change-requests",
        json={
            "kind": "record_override",
            "title": "Repair",
            "quarantine_repair": {"exception_id": str(malformed.id), "replacement_text": "a,b"},
        },
        headers=headers(MAYA),
    )
    assert wrong.status_code == 422
    change = draft_and_submit(
        client,
        story[0].migration_id,
        {
            "kind": "record_override",
            "title": "Repair JE line broken by a line break in its memo",
            "quarantine_repair": {
                "exception_id": str(malformed.id),
                "replacement_text": replacement,
            },
        },
        "The export split one line at an unquoted line break; the repaired text quotes the memo.",
    )
    assert [r["role"] for r in change_detail(client, change["id"])["requirements"]] == [
        "implementation_lead", "customer_controller"
    ]  # fmt: skip
    outcome = approve_all(client, change["id"], [DANIEL, PRIYA])
    run_id = process_run(story, outcome["run_id"])
    assert findings(story, run_id, "NORM.MALFORMED_ROW") == []
    assert [
        f for f in findings(story, run_id, "GL.JE_BALANCED") if "je:JE-2026-0412" in f.subjects
    ] == []


def change_detail(client: TestClient, change_id: str) -> dict[str, Any]:
    return ok_object(client.get(f"/api/v1/change-requests/{change_id}", headers=headers(SAM)))


def _signature(result: Any) -> tuple[Counter[str], set[tuple[str, tuple[str, ...]]], set[Any]]:
    rules = Counter(e.rule_id for e in result.exceptions)
    subjects = {
        (e.rule_id, tuple(e.subjects))
        for e in result.exceptions
        if not any(":" in s and ("/" in s or s.count("-") >= 4) for s in e.subjects)
    }
    lines = {
        (r.recon_id, line.grain, line.difference, line.unexplained)
        for r in result.reconciliations
        for line in r.lines
        if line.difference != 0 or line.unexplained != 0
    }
    return rules, subjects, lines


def test_persisted_run_matches_the_engine_with_the_documented_corrections(
    story: Story, engine_run1: EngineResult
) -> None:
    """The API-made corrections equal the documented resolutions applied in the pure engine."""
    files = _read_fixtures(BRIGHTWATER_FIXTURES)
    expected = run_engine(
        resolution.inputs_for(files),
        Overlays(
            account_mapping_changes=(
                AccountMappingChange("AM-DS03", "1205", "1210", "contra"),
                AccountMappingChange("AM-6999", "6999", "1999", "suspense"),
            ),
            quarantine_repairs=(resolution.quarantine_repair(engine_run1),),
            record_overrides=resolution.corrections(engine_run1).record_overrides,
        ),
    )  # fmt: skip
    with session_scope(story[1]) as session:
        actual = persisted.load(session, _latest_run(story))
    assert _signature(actual) == _signature(expected)


# ------------------------------------------------------------------------------------- revert
def test_reverting_an_override_reopens_its_issue(client: TestClient, story: Story) -> None:
    overrides = ok(
        client.get(
            f"/api/v1/migrations/{story[0].migration_id}/record-overrides", headers=headers(SAM)
        )
    )
    target = next(o for o in overrides if o["natural_key"] == "je:JE-AP-20455")
    change = draft_and_submit(
        client,
        story[0].migration_id,
        {
            "kind": "revert",
            "title": "Revert JE-AP-20455 date correction",
            "payload": {"record_override_id": target["id"]},
        },
        "Customer wants to confirm the date with the vendor first.",
    )
    detail = change_detail(client, change["id"])
    assert [r["role"] for r in detail["requirements"]] == [
        "implementation_lead", "customer_controller"
    ]  # fmt: skip
    outcome = approve_all(client, change["id"], [DANIEL, PRIYA])
    run_id = process_run(story, outcome["run_id"])
    assert len(findings(story, run_id, "GL.DATE_IN_WINDOW")) == 1
    assert issue_status(story, "GL.DATE_IN_WINDOW", "je:JE-AP-20455") == "open"
    again = client.post(
        f"/api/v1/migrations/{story[0].migration_id}/change-requests",
        json={
            "kind": "revert",
            "title": "Revert twice",
            "payload": {"record_override_id": target["id"]},
        },
        headers=headers(MAYA),
    )
    assert again.status_code == 409


# ------------------------------------------------------------------------------- policy change
def test_policy_change_creates_a_policy_version_and_changes_the_fingerprint(
    client: TestClient, story: Story
) -> None:
    migration_id = story[0].migration_id
    before = ok(client.get(f"/api/v1/migrations/{migration_id}/fingerprint", headers=headers(SAM)))
    invalid = client.post(
        f"/api/v1/migrations/{migration_id}/change-requests",
        json={"kind": "policy_change", "title": "Bad", "payload": {"changes": {"nope": 1}}},
        headers=headers(MAYA),
    )
    assert invalid.status_code == 422
    change = draft_and_submit(
        client,
        migration_id,
        {
            "kind": "policy_change",
            "title": "Tighten exposure threshold",
            "payload": {"changes": {"max_unresolved_exposure": "500.00"}},
        },
        "Controller asked for a lower exposure threshold.",
    )
    detail = change_detail(client, change["id"])
    assert Decimal(detail["before"]["max_unresolved_exposure"]) == Decimal("1000.00")
    assert Decimal(detail["after"]["max_unresolved_exposure"]) == Decimal("500.00")
    assert detail["impact"]["changed_keys"] == ["max_unresolved_exposure"]
    outcome = approve_all(client, change["id"], [PRIYA, DANIEL])
    process_run(story, outcome["run_id"])
    after = ok(client.get(f"/api/v1/migrations/{migration_id}/fingerprint", headers=headers(SAM)))
    assert after["components"]["policy_version"] == before["components"]["policy_version"] + 1
    assert after["fingerprint"] != before["fingerprint"]


# --------------------------------------------------------------------------------------- audit
def test_every_change_request_transition_is_audited_with_before_and_after(story: Story) -> None:
    with session_scope(story[1]) as session:
        events = session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.migration_id == story[0].migration_id,
                AuditEvent.action.like("change_request.%"),
            )
            .order_by(AuditEvent.migration_seq)
        ).all()
        assert events
        assert all(e.before is not None and e.after is not None for e in events), [
            e.action for e in events if e.before is None or e.after is None
        ]
        applied = session.scalars(
            select(ChangeRequest).where(
                ChangeRequest.migration_id == story[0].migration_id,
                ChangeRequest.status == "applied",
            )
        ).all()
        for change in applied:
            actions = [e.action for e in events if e.change_request_id == change.id]
            assert actions[:2] == ["change_request.drafted", "change_request.submitted"]
            assert actions[-2:] == ["change_request.approved", "change_request.applied"]
            assert actions.count("change_request.approval_recorded") == len(
                change.required_approvals
            )
