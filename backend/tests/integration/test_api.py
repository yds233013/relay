"""HTTP API against PostgreSQL: identity, authorization, uploads, runs and read endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine

from relay.api.app import create_app
from relay.core.config import Environment, Settings
from relay.core.db import create_session_factory
from relay.worker import drain
from tests.integration.support import Workspace, ensure_head, make_workspace, worker_context

CSV = b"Customer ID,Customer Name\r\nC-1,Alpha Foods\r\nC-2,Beta Market\r\n"


@pytest.fixture(scope="module")
def blob_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("api-blobs")


@pytest.fixture
def space(migrated: str, engine: Engine) -> Workspace:
    ensure_head(migrated)
    return make_workspace(create_session_factory(engine))


@pytest.fixture
def client(settings: Settings, blob_root: Path) -> Iterator[TestClient]:
    configured = settings.model_copy(update={"storage_dir": blob_root, "max_upload_bytes": 4096})
    with TestClient(create_app(configured)) as test_client:
        yield test_client


def as_user(email: str) -> dict[str, str]:
    return {"X-Relay-User": email}


def upload(
    client: TestClient, space: Workspace, body: bytes, name: str = "customers.csv"
) -> Response:
    return client.post(
        f"/api/v1/datasets/{space.dataset_id}/imports",
        content=body,
        headers={
            **as_user(space.specialist_email),
            "X-Relay-Filename": name,
            "Content-Type": "text/csv",
        },
    )


def test_requests_without_a_known_user_are_rejected(client: TestClient, space: Workspace) -> None:
    missing = client.get("/api/v1/migrations")
    assert missing.status_code == 401
    assert missing.json()["code"] == "auth.required"
    unknown = client.get("/api/v1/migrations", headers=as_user("nobody@test.example"))
    assert unknown.status_code == 401
    me = client.get("/api/v1/me", headers=as_user(space.viewer_email))
    assert me.status_code == 200
    assert me.json()["role"] == "viewer"


def test_dev_identity_header_is_ignored_in_production(blob_root: Path) -> None:
    production = Settings(
        env=Environment.PRODUCTION,
        database_url="postgresql+psycopg://relay:Xk2-long-random@127.0.0.1:1/relay",  # type: ignore[arg-type]
        storage_dir=blob_root,
    )
    with TestClient(create_app(production)) as test_client:
        response = test_client.get("/api/v1/migrations", headers=as_user("maya.chen@relay.example"))
        assert response.status_code == 401
        dev_users = test_client.get("/api/v1/dev/users")
        assert dev_users.status_code == 404


def test_viewers_cannot_mutate(client: TestClient, space: Workspace) -> None:
    headers = as_user(space.viewer_email)
    assert (
        client.get(f"/api/v1/migrations/{space.migration_id}", headers=headers).status_code == 200
    )
    run = client.post(f"/api/v1/migrations/{space.migration_id}/pipeline-runs", headers=headers)
    assert run.status_code == 403
    assert run.json()["code"] == "auth.forbidden"
    posted = client.post(
        f"/api/v1/datasets/{space.dataset_id}/imports",
        content=CSV,
        headers={**headers, "X-Relay-Filename": "x.csv"},
    )
    assert posted.status_code == 403


def test_upload_is_idempotent_and_limited(client: TestClient, space: Workspace) -> None:
    first = upload(client, space, CSV)
    assert first.status_code == 202
    second = upload(client, space, CSV, name="other.csv")
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    too_large = upload(client, space, b"a,b\n" + b"1,2\n" * 2000)
    assert too_large.status_code == 413
    assert too_large.json()["code"] == "import.too_large"
    binary = upload(client, space, b"PK\x03\x04zip", name="data.csv")
    assert binary.status_code == 415
    missing_name = client.post(
        f"/api/v1/datasets/{space.dataset_id}/imports",
        content=CSV,
        headers=as_user(space.specialist_email),
    )
    assert missing_name.status_code == 422


def test_run_flow_and_read_endpoints(
    client: TestClient, space: Workspace, engine: Engine, blob_root: Path
) -> None:
    headers = as_user(space.specialist_email)
    created = upload(client, space, CSV + b"C-3,Gamma\r\n")
    import_id = created.json()["id"]
    factory = create_session_factory(engine)
    drain(worker_context(factory, blob_root))
    rows = client.get(f"/api/v1/imports/{import_id}/rows?limit=2", headers=headers).json()
    assert [r["values"]["Customer ID"] for r in rows["items"]] == ["C-1", "C-2"]
    assert rows["next_cursor"] == "2"
    assert (
        client.get(f"/api/v1/imports/{import_id}/profile", headers=headers).json()["row_count"] == 3
    )

    requested = client.post(
        f"/api/v1/migrations/{space.migration_id}/pipeline-runs", headers=headers
    )
    assert requested.status_code == 202
    again = client.post(f"/api/v1/migrations/{space.migration_id}/pipeline-runs", headers=headers)
    assert again.status_code == 200
    assert again.json()["id"] == requested.json()["id"]
    drain(worker_context(factory, blob_root))
    run = client.get(f"/api/v1/pipeline-runs/{requested.json()['id']}", headers=headers).json()
    assert run["status"] == "succeeded"
    assert run["is_current"] is True

    readiness = client.get(
        f"/api/v1/migrations/{space.migration_id}/readiness", headers=headers
    ).json()
    assert readiness["run_is_current"] is True
    gates = {g["gate_id"]: g["status"] for g in readiness["gates"]}
    assert gates["G2"] == "fail"  # the dataset has no approved column mapping
    assert gates["G12"] == "fail"
    rules = client.get(f"/api/v1/pipeline-runs/{run['id']}/rules", headers=headers).json()
    assert {r["status"] for r in rules} <= {"passed", "failed", "not_applicable"}
    verify = client.get(
        f"/api/v1/migrations/{space.migration_id}/audit-events/verify", headers=headers
    ).json()
    assert verify["valid"] is True
    events = client.get(
        f"/api/v1/migrations/{space.migration_id}/audit-events?limit=500", headers=headers
    ).json()
    actions = {e["action"] for e in events["items"]}
    assert {
        "import.uploaded",
        "import.parsed",
        "pipeline_run.requested",
        "pipeline_run.succeeded",
    } <= actions
    missing = client.get(f"/api/v1/pipeline-runs/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404
    assert "traceback" not in missing.text.lower()
