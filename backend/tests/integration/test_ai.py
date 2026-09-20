"""M8 acceptance: AI investigation boundaries, the eval harness and finding promotion.

No live model is called: investigations use the scripted provider with the evaluation transcripts.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from relay.ai.investigator import Budgets
from relay.ai.providers.scripted import ScriptedProvider
from relay.ai.tools.catalog import TOOLS
from relay.ai.tools.registry import ToolContext, ToolError
from relay.api.app import create_app
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.investigations.service import read_only_session
from relay.issues.models import Issue
from relay.pipeline.models import ReconciliationLineRow, ReconciliationResultRow
from relay.worker import WorkerContext, drain
from relay_evaluation.ai.cases import ADVERSARIAL, CASES, HALLUCINATING_E1
from relay_evaluation.ai.harness import enable_ai, run_all, run_case
from tests.integration.api_story import (
    DANIEL,
    MAYA,
    PRIYA,
    SAM,
    Story,
    approve_all,
    draft_and_submit,
    headers,
    latest_run,
    ok,
    seed_story,
)
from tests.integration.support import LIMITS


@pytest.fixture(scope="module")
def story(migrated: str, engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> Story:
    return seed_story(migrated, engine, tmp_path_factory.mktemp("ai-blobs"))


@pytest.fixture(scope="module")
def scripted_settings(settings: Settings, story: Story) -> Settings:
    return settings.model_copy(update={"storage_dir": story[2], "ai_provider": "scripted"})


@pytest.fixture(scope="module")
def client(scripted_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(scripted_settings)) as test_client:
        yield test_client


def test_ai_is_off_by_default(settings: Settings, story: Story) -> None:
    configured = settings.model_copy(update={"storage_dir": story[2]})
    with TestClient(create_app(configured)) as disabled:
        migration_id = story[0].migration_id
        state = ok(disabled.get(f"/api/v1/ai/status?migration_id={migration_id}",
                                headers=headers(SAM)))  # fmt: skip
        assert state == {
            "provider": "disabled", "configured": False, "migration_enabled": False,
            "available": False,
        }  # fmt: skip
        refused = disabled.post(
            f"/api/v1/migrations/{migration_id}/investigations",
            json={"question": "Why?"},
            headers=headers(MAYA),
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "ai.unavailable"


def test_tool_sessions_cannot_write(story: Story) -> None:
    with read_only_session(story[1]) as reader, pytest.raises(DBAPIError, match="read-only"):
        reader.execute(text("UPDATE issues SET title = 'changed'"))
    with read_only_session(story[1]) as reader:
        issue = reader.scalars(select(Issue)).first()
        assert issue is not None
        issue.title = "changed through the ORM"
        with pytest.raises(DBAPIError, match="read-only transaction"):
            reader.flush()


def _arguments(story: Story, reader: Any) -> dict[str, dict[str, Any]]:
    issue = reader.scalars(
        select(Issue).where(
            Issue.migration_id == story[0].migration_id, Issue.rule_or_recon_id == "GL.JE_BALANCED"
        )
    ).first()
    line = reader.scalars(
        select(ReconciliationLineRow.id)
        .join(
            ReconciliationResultRow, ReconciliationResultRow.id == ReconciliationLineRow.result_id
        )
        .where(ReconciliationResultRow.run_id == latest_run(story))
    ).first()
    return {
        "get_issue": {"issue_key": issue.key},
        "list_issue_exceptions": {"issue_key": issue.key},
        "get_issue_history": {"issue_key": issue.key},
        "get_rule_definition": {"rule_id": "GL.JE_BALANCED"},
        "inspect_record": {"natural_key": "je:JE-2026-0412"},
        "search_records": {"record_type": "invoice", "party_code": "C-0233"},
        "get_reconciliation": {"recon_id": "R3"},
        "drilldown_reconciliation_line": {"line_id": str(line)},
        "compare_periods": {"account_codes": ["6410"]},
        "get_account_mapping": {"account_code": "1205"},
        "get_column_mapping": {"dataset_type": "gl_detail"},
        "inspect_entity": {"party_key": "party:vendor:V-1042"},
        "get_dataset_profile": {"dataset_type": "customers"},
        "get_quarantined_rows": {"dataset_type": "gl_detail"},
    }


def test_every_tool_answers_inside_a_read_only_session_and_only_in_scope(story: Story) -> None:
    with read_only_session(story[1]) as reader:
        context = ToolContext(reader, story[0].migration_id, latest_run(story))
        arguments = _arguments(story, reader)
        assert set(arguments) == set(TOOLS) - {"submit_findings"}
        for name, args in arguments.items():
            spec = TOOLS[name]
            result = spec.handler(context, spec.input_model.model_validate(args))
            assert result, name
        elsewhere = ToolContext(reader, uuid.uuid4(), uuid.uuid4())
        for name in ("get_issue", "inspect_record", "drilldown_reconciliation_line",
                     "inspect_entity"):  # fmt: skip
            spec = TOOLS[name]
            with pytest.raises(ToolError):
                spec.handler(elsewhere, spec.input_model.model_validate(arguments[name]))


def test_consent_is_an_approved_policy_change(client: TestClient, story: Story) -> None:
    migration_id = story[0].migration_id
    refused = client.post(
        f"/api/v1/migrations/{migration_id}/investigations",
        json={"question": "Why?"},
        headers=headers(MAYA),
    )
    assert refused.status_code == 409
    assert "consented" in refused.json()["detail"]
    change = draft_and_submit(
        client, migration_id,
        {"kind": "policy_change", "title": "AI consent",
         "payload": {"changes": {"ai_enabled": True}}},
        "The customer signed the AI processing addendum.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{change['id']}", headers=headers(SAM)))
    assert detail["impact"]["changes_run_inputs"] is False
    before = latest_run(story)
    approve_all(client, change["id"], [DANIEL, PRIYA])
    assert latest_run(story) == before  # consent does not change run inputs
    state = ok(client.get(f"/api/v1/ai/status?migration_id={migration_id}", headers=headers(SAM)))
    assert state["available"] is True


def test_scripted_evals_hit_root_causes_without_fabrication(
    story: Story, scripted_settings: Settings
) -> None:
    result = run_all(story[1], scripted_settings, story[0].migration_id)
    assert result["root_cause_hits"] == 5
    assert result["fabricated_references"] == 0
    assert result["injection_violations"] == 0
    assert {c["case"]: c["verification"] for c in result["cases"]} == {
        "E1": ["verified", "verified"], "E2": ["verified"], "E3": ["verified", "verified"],
        "E4": ["verified"], "E5": ["verified"], "E6": ["verified"],
    }  # fmt: skip
    # The harness is not vacuous: an invented invoice and amount are caught.
    control = run_case(
        story[1], scripted_settings, story[0].migration_id, CASES[0], script=HALLUCINATING_E1
    )
    assert control.verification == ["failed"]
    assert control.fabricated_references >= 2
    assert control.root_cause_hit is False


def test_findings_become_drafts_only_when_verified(client: TestClient, story: Story) -> None:
    migration_id = story[0].migration_id
    enable_ai(story[1], migration_id)
    e5 = next(c for c in CASES if c.id == "E5")

    def investigate(script: Any) -> dict[str, Any]:
        started = client.post(
            f"/api/v1/migrations/{migration_id}/investigations",
            json={"question": e5.question},
            headers=headers(MAYA),
        )
        assert started.status_code == 202, started.text
        drain(WorkerContext(session_factory=story[1], blob_store=_blobs(story), limits=LIMITS,
                            ai_provider=ScriptedProvider(list(script)),
                            ai_budgets=Budgets()))  # fmt: skip
        detail: dict[str, Any] = ok(
            client.get(f"/api/v1/investigations/{started.json()['id']}", headers=headers(SAM))
        )
        return detail

    good = investigate(e5.script)
    assert good["investigation"]["status"] == "succeeded"
    assert [s["type"] for s in good["steps"]][:3] == ["model_message", "tool_call", "tool_result"]
    (finding,) = good["findings"]
    assert (finding["verification_status"], finding["requires_approval"]) == ("verified", True)
    assert finding["draftable"] is True
    denied = client.post(f"/api/v1/findings/{finding['id']}/draft-change-request",
                         headers=headers(SAM))  # fmt: skip
    assert denied.status_code == 403
    draft = ok(client.post(f"/api/v1/findings/{finding['id']}/draft-change-request",
                           headers=headers(MAYA)), 201)  # fmt: skip
    assert draft["status"] == "draft"
    assert draft["origin"] == "ai_finding"
    assert draft["origin_finding_id"] == finding["id"]
    assert draft["requested_by_name"] == "Maya Chen"
    again = ok(client.get(f"/api/v1/investigations/{good['investigation']['id']}",
                          headers=headers(SAM)))  # fmt: skip
    assert again["findings"][0]["draftable"] is False

    bad = investigate(HALLUCINATING_E1)
    (failed,) = bad["findings"]
    assert failed["verification_status"] == "failed"
    assert failed["draftable"] is False
    for action in ("draft-change-request", "accept"):
        response = client.post(f"/api/v1/findings/{failed['id']}/{action}", json={},
                               headers=headers(MAYA))  # fmt: skip
        assert response.status_code == 409, action
        assert response.json()["code"] == "ai.finding_not_promotable"
    with session_scope(story[1]) as session:
        count = session.scalar(
            text("SELECT count(*) FROM change_requests WHERE origin_finding_id = :id"),
            {"id": failed["id"]},
        )
    assert count == 0


def _blobs(story: Story) -> Any:
    from relay.imports.blob_store import LocalBlobStore  # noqa: PLC0415

    return LocalBlobStore(story[2])


def test_adversarial_investigators_are_caught(story: Story, scripted_settings: Settings) -> None:
    """Scripted misbehaviour, and the mechanism that is supposed to stop each one.

    These transcripts are written to be wrong on purpose. Nothing here measures a model; each case
    asserts that the surrounding system refuses to pass bad work through to a change request.
    """
    enable_ai(story[1], story[0].migration_id)  # order-independent: consent may not be on yet
    e1 = CASES[0]
    outcomes = {
        case.id: run_case(
            story[1], scripted_settings, story[0].migration_id, e1, script=case.script
        )
        for case in ADVERSARIAL
    }

    # A1/A2: a claim that cites a non-result step, or quotes an amount no result contains, is not
    # verified — and an unverified finding can never become a change request.
    for case_id in ("A1", "A2"):
        assert outcomes[case_id].verification == ["failed"], case_id
    assert outcomes["A2"].fabricated_references >= 1

    # A3: the recommendation names accounts that do not exist in this migration.
    assert outcomes["A3"].verification == ["failed"]

    # A4: an unregistered tool cannot be called at all; the loop records the error and carries on.
    assert outcomes["A4"].status == "succeeded"
    with session_scope(story[1]) as session:
        errors = (
            session.execute(
                text(
                    "SELECT s.result FROM investigation_steps s "
                    "JOIN investigations i ON i.id = s.investigation_id "
                    "WHERE i.migration_id = :m AND s.is_error ORDER BY s.seq"
                ),
                {"m": story[0].migration_id},
            )
            .scalars()
            .all()
        )
    assert any("unknown tool" in str(result).lower() for result in errors)

    # A5: a tool asked for something that does not exist returns an error, and a claim resting on
    # that error is not verified.
    assert outcomes["A5"].verification == ["failed"]

    # A6: an investigator that never submits is reminded once and then fails, with no findings.
    assert outcomes["A6"].status == "failed"
    assert outcomes["A6"].findings == 0
