"""M7 acceptance at the API: fast-forward, sign-off, invalidation, waivers and their lapse.

Brightwater is seeded and fast-forwarded to just before sign-off with the demo tool (which acts as
the seeded people through the same orchestration as the API). Tests run in order.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from relay.api.app import create_app
from relay.audit.models import AuditEvent
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay_scenarios.brightwater.fast_forward import fast_forward
from tests.integration.api_story import (
    DANIEL,
    MAYA,
    PRIYA,
    SAM,
    Story,
    approve_all,
    draft_and_submit,
    drain_jobs,
    headers,
    ok,
    ok_object,
    seed_story,
)


@pytest.fixture(scope="module")
def story(migrated: str, engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> Story:
    return seed_story(migrated, engine, tmp_path_factory.mktemp("readiness-blobs"))


@pytest.fixture(scope="module")
def client(settings: Settings, story: Story) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"storage_dir": story[2]})
    with TestClient(create_app(configured)) as test_client:
        yield test_client


def readiness(client: TestClient, story: Story) -> dict[str, Any]:
    drain_jobs(story)
    return ok_object(
        client.get(f"/api/v1/migrations/{story[0].migration_id}/readiness", headers=headers(SAM))
    )


def failing(state: dict[str, Any]) -> list[str]:
    return [g["gate_id"] for g in state["gates"] if g["status"] == "fail"]


def gate(state: dict[str, Any], gate_id: str) -> dict[str, Any]:
    return next(g for g in state["gates"] if g["gate_id"] == gate_id)


def test_fast_forward_reaches_the_state_before_sign_off(story: Story, client: TestClient) -> None:
    result, factory, root = story
    forwarded = fast_forward(
        factory, LocalBlobStore(root), ImportLimits(52_428_800, 500_000),
        migration_id=result.migration_id,
    )  # fmt: skip
    assert forwarded.failing_gates == ("G12",)
    assert len(forwarded.applied) >= 10
    state = readiness(client, story)
    assert failing(state) == ["G12"]
    assert state["overall"] == "not_ready"
    assert state["unresolved_exposure"] == "0.00"
    # Running it again changes nothing.
    again = fast_forward(
        factory, LocalBlobStore(root), ImportLimits(52_428_800, 500_000),
        migration_id=result.migration_id,
    )  # fmt: skip
    assert again.applied == ()


def test_sign_off_needs_no_other_pending_change(story: Story, client: TestClient) -> None:
    migration_id = story[0].migration_id
    pending = draft_and_submit(
        client, migration_id,
        {"kind": "policy_change", "title": "Pending",
         "payload": {"changes": {"duplicate_window_days": 8}}},
        "A change still waiting for approval.",
    )  # fmt: skip
    blocked = client.post(
        f"/api/v1/migrations/{migration_id}/change-requests",
        json={"kind": "readiness_signoff", "title": "Sign off", "payload": {}},
        headers=headers(MAYA),
    )
    assert blocked.status_code == 409
    assert pending["key"] in blocked.json()["detail"]
    ok(
        client.post(
            f"/api/v1/change-requests/{pending['id']}/withdraw", json={}, headers=headers(MAYA)
        )
    )


def test_sign_off_makes_the_migration_ready(story: Story, client: TestClient) -> None:
    migration_id = story[0].migration_id
    before = readiness(client, story)
    change = draft_and_submit(
        client, migration_id,
        {"kind": "readiness_signoff", "title": "Go-live sign-off", "payload": {}},
        "All gates pass on the current run; dispositions documented.",
    )  # fmt: skip
    detail = ok(client.get(f"/api/v1/change-requests/{change['id']}", headers=headers(SAM)))
    assert detail["payload"]["run_fingerprint"] == before["run_fingerprint"]
    assert [r["role"] for r in detail["requirements"]] == [
        "implementation_lead", "customer_controller"
    ]  # fmt: skip
    outcome = approve_all(client, change["id"], [DANIEL, PRIYA])
    assert outcome["change_request"]["status"] == "applied"
    state = readiness(client, story)
    assert state["overall"] == "ready"
    assert failing(state) == []
    assert gate(state, "G12")["status"] == "pass"
    assert state["migration_status"] == "signed_off"
    assert [s["status"] for s in state["signoffs"]] == ["active"]
    assert state["evaluation_sequence"] > 1  # re-evaluated on the same run, not a new run
    assert state["run_fingerprint"] == before["run_fingerprint"]


def test_any_input_change_invalidates_the_sign_off(story: Story, client: TestClient) -> None:
    migration_id = story[0].migration_id
    dispositions = ok(
        client.get(f"/api/v1/migrations/{migration_id}/dispositions", headers=headers(SAM))
    )
    bank = sorted(
        (d for d in dispositions if d["follow_up"].startswith("Book the bank fees")),
        key=lambda d: d["issue_key"],
    )
    assert len(bank) == 6
    for disposition in bank[:2]:
        change = draft_and_submit(
            client, migration_id,
            {"kind": "revert", "title": f"Revisit {disposition['issue_key']}",
             "payload": {"target": "disposition", "target_id": disposition["id"]}},
            "The bank says these two fees were refunded; confirm first.",
        )  # fmt: skip
        approve_all(client, change["id"], [PRIYA])
    state = readiness(client, story)
    assert state["overall"] == "not_ready"
    assert state["migration_status"] == "in_progress"
    assert [s["status"] for s in state["signoffs"]] == ["invalidated"]
    assert set(failing(state)) == {"G8", "G12"}
    with session_scope(story[1]) as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.migration_id == migration_id)
            )
        )
    assert {"readiness.signoff_invalidated", "migration.status_changed"} <= actions


def test_waivers_cover_only_waivable_failing_gates_and_lapse_when_amounts_change(
    story: Story, client: TestClient
) -> None:
    migration_id = story[0].migration_id

    def request_waiver(gate_id: str) -> Any:
        return client.post(
            f"/api/v1/migrations/{migration_id}/change-requests",
            json={
                "kind": "gate_waiver",
                "title": f"Waive {gate_id}",
                "payload": {"gate_id": gate_id},
            },
            headers=headers(MAYA),
        )

    assert request_waiver("G5").status_code == 409  # not failing
    assert request_waiver("G12").status_code == 409  # not failing on its own scope
    state = readiness(client, story)
    g8 = gate(state, "G8")
    assert g8["waivable"] is True
    assert g8["scope"]
    waiver = request_waiver("G8")
    assert waiver.status_code == 201, waiver.text
    ok(
        client.post(
            f"/api/v1/change-requests/{waiver.json()['id']}/submit",
            json={"justification": "Refund confirmed by the bank; booked in July."},
            headers=headers(MAYA),
        )
    )
    detail = ok(client.get(f"/api/v1/change-requests/{waiver.json()['id']}", headers=headers(SAM)))
    assert detail["payload"]["scope"] == g8["scope"]
    approve_all(client, waiver.json()["id"], [DANIEL, PRIYA])
    state = readiness(client, story)
    assert gate(state, "G8")["status"] == "waived"
    assert [w["status"] for w in state["waivers"]] == ["active"]
    assert failing(state) == ["G12"]

    # Dispositioning one of the two open fees changes the waived scope: the waiver lapses.
    issues = ok(
        client.get(
            f"/api/v1/migrations/{migration_id}/issues",
            params={"rule": "BANK.UNRECORDED_ACTIVITY", "status": "open"},
            headers=headers(SAM),
        )
    )["items"]
    assert len(issues) == 2
    change = draft_and_submit(
        client, migration_id,
        {"kind": "disposition", "title": "One fee",
         "payload": {"issue_ids": [issues[0]["id"]], "kind": "carry_forward_adjustment",
                     "amount": "45.00"}},
        "This fee was not refunded.",
    )  # fmt: skip
    approve_all(client, change["id"], [PRIYA])
    state = readiness(client, story)
    assert gate(state, "G8")["status"] == "fail"
    assert [w["status"] for w in state["waivers"]] == ["lapsed"]
    with session_scope(story[1]) as session:
        lapsed = session.scalars(
            select(AuditEvent).where(
                AuditEvent.migration_id == migration_id, AuditEvent.action == "gate_waiver.lapsed"
            )
        ).all()
        assert len(lapsed) == 1
