"""Helpers for API-level story tests: act as the seeded people, approve, run the worker, look up."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from relay.core.db import create_session_factory, session_scope
from relay.imports.blob_store import LocalBlobStore
from relay.imports.service import ImportLimits
from relay.issues.models import Issue
from relay.pipeline.models import PipelineRun, RuleExceptionRow
from relay.worker import drain
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


def seed_story(migrated: str, engine: Engine, root: Path) -> Story:
    ensure_head(migrated)
    factory = create_session_factory(engine)
    result = seed(
        factory, LocalBlobStore(root), ImportLimits(52_428_800, 500_000), BRIGHTWATER_FIXTURES,
        DEFAULT_MAPPING_SET,
    )  # fmt: skip
    return result, factory, root


def latest_run(story: Story) -> uuid.UUID:
    with session_scope(story[1]) as session:
        return session.scalars(
            select(PipelineRun.id)
            .where(
                PipelineRun.migration_id == story[0].migration_id, PipelineRun.status == "succeeded"
            )
            .order_by(PipelineRun.sequence.desc())
        ).first()  # type: ignore[return-value]


def issues_with_rule(story: Story, rule_id: str) -> list[Issue]:
    with session_scope(story[1]) as session:
        rows = session.scalars(
            select(Issue)
            .where(Issue.migration_id == story[0].migration_id, Issue.rule_or_recon_id == rule_id)
            .order_by(Issue.key)
        ).all()
        session.expunge_all()
        return list(rows)


def upload(client: TestClient, dataset_id: uuid.UUID, name: str, content: bytes) -> Any:
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/imports",
        content=content,
        headers={**headers(MAYA), "X-Relay-Filename": name, "Content-Type": "text/csv"},
    )
    assert response.status_code in {200, 202}, response.text
    return response.json()


def drain_jobs(story: Story) -> None:
    drain(worker_context(story[1], story[2]))
