"""The public demo's security boundary (``RELAY_ENV=demo``).

A stranger with the link is anonymous, shares one identity with every other visitor, and must not
be able to change the shared Brightwater. The rules that keep that true are exercised here against
the real ASGI app rather than described.

The database URL points at a closed port, so anything the policy lets through fails on the
connection instead of touching data. That is the point: these tests assert *what the policy
decides*, not what a handler would do afterwards. Behaviour that needs real rows lives in
``tests/integration/test_demo_mode.py``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

from relay.api.app import create_app
from relay.api.demo_policy import DEMO_READ_ONLY_CODE, SAFE_METHODS, is_allowed
from relay.core.config import Settings

# Port 1 on localhost: connection refused immediately, no network access.
UNREACHABLE_DB: Final = "postgresql+psycopg://relay:Xk2-long-random-password@127.0.0.1:1/relay"
LOCAL_DB: Final = "postgresql+psycopg://relay:relay_local_dev_only@127.0.0.1:1/relay"

# The one mutation a visitor may perform; everything else must be refused.
ALLOWED_IN_DEMO: Final = {"POST /api/v1/migrations/{migration_id}/investigations"}


def _settings(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "env": "demo",
        "database_url": UNREACHABLE_DB,
        "ai_provider": "demo",
        "db_connect_timeout_seconds": 1,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def demo() -> Iterator[TestClient]:
    with _client(_settings()) as client:
        yield client


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every mounted route, including routers included with a prefix.

    This FastAPI version wraps an included router rather than flattening its routes onto the app,
    so both shapes have to be walked — the same traversal ``test_route_inventory`` uses.
    """
    found: list[tuple[str, str]] = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        for context in contexts() if callable(contexts) else ():
            found.extend((method, context.path) for method in sorted(context.methods or ()))
        if isinstance(route, APIRoute):
            found.extend((method, route.path) for method in sorted(route.methods or ()))
    return sorted(set(found))


def _concrete(path: str) -> str:
    """A callable URL: every path parameter replaced by something well-formed."""
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_the_app_exposes_routes_to_check() -> None:
    """Guard against the enumeration silently finding nothing and every test below passing."""
    routes = _routes(create_app(_settings()))
    mutating = [r for r in routes if r[0] not in SAFE_METHODS]
    assert len(routes) > 50
    assert len(mutating) >= 20


def test_every_mutating_route_is_refused(demo: TestClient) -> None:
    """Deny by default.

    Enumerated from the app rather than a hand-kept list, so a mutating route added later is
    refused in the demo until someone deliberately allows it — and this test says so by name.
    """
    refused: list[str] = []
    for method, path in _routes(create_app(_settings())):
        if method in SAFE_METHODS or f"{method} {path}" in ALLOWED_IN_DEMO:
            continue
        response = demo.request(method, _concrete(path), json={})
        assert response.status_code == 403, f"{method} {path} was not refused"
        assert response.json()["code"] == DEMO_READ_ONLY_CODE, f"{method} {path}"
        assert response.headers["content-type"].startswith("application/problem+json")
        refused.append(f"{method} {path}")
    assert len(refused) >= 20


@pytest.mark.parametrize(
    "method_and_path",
    [
        "POST /api/v1/migrations",  # create arbitrary migrations
        "POST /api/v1/datasets/{dataset_id}/imports",  # upload arbitrary files
        "POST /api/v1/migrations/{migration_id}/account-mapping-sets",  # modify mappings
        "POST /api/v1/migrations/{migration_id}/change-requests",  # propose corrections
        "POST /api/v1/change-requests/{change_id}/submit",
        "POST /api/v1/change-requests/{change_id}/approve",  # approve real changes
        "POST /api/v1/change-requests/{change_id}/reject",
        "POST /api/v1/change-requests/{change_id}/withdraw",
        "POST /api/v1/migrations/{migration_id}/pipeline-runs",  # unbounded background jobs
        "PATCH /api/v1/issues/{issue_id}",
        "POST /api/v1/migrations/{migration_id}/issues",
        "POST /api/v1/findings/{finding_id}/draft-change-request",
    ],
)
def test_named_dangerous_mutations_are_refused(demo: TestClient, method_and_path: str) -> None:
    """The specific things a visitor must never reach, named so a regression reads clearly.

    Policies change: mappings, corrections, approvals, policy versions, waivers and sign-off all
    travel through the change-request routes above, so refusing those refuses all of them.
    """
    method, path = method_and_path.split(" ", 1)
    response = demo.request(method, _concrete(path), json={})
    assert response.status_code == 403
    assert response.json()["code"] == DEMO_READ_ONLY_CODE


def test_reads_are_not_refused_by_the_policy(demo: TestClient) -> None:
    """Exploring is unrestricted: a GET never trips the demo policy.

    It fails on the unreachable database instead, which is what these assertions distinguish.
    """
    for method, path in _routes(create_app(_settings())):
        if method not in SAFE_METHODS:
            continue
        response = demo.request(method, _concrete(path))
        if response.status_code == 403:
            assert response.json().get("code") != DEMO_READ_ONLY_CODE, f"{method} {path}"


def test_the_investigation_route_passes_the_policy(demo: TestClient) -> None:
    """The hero interaction is allowed through; the demo is not a set of screenshots."""
    response = demo.request(
        "POST",
        f"/api/v1/migrations/{uuid.uuid4()}/investigations",
        json={"question": "Why does this happen?"},
    )
    assert response.status_code != 403 or response.json().get("code") != DEMO_READ_ONLY_CODE


def test_the_policy_function_denies_by_default() -> None:
    migration = uuid.uuid4()
    assert is_allowed("GET", "/api/v1/migrations")
    assert is_allowed("HEAD", "/api/v1/migrations")
    assert is_allowed("POST", f"/api/v1/migrations/{migration}/investigations")
    assert not is_allowed("POST", "/api/v1/migrations")
    assert not is_allowed("DELETE", f"/api/v1/migrations/{migration}/investigations")
    # Not a prefix match: nothing may ride in behind the one allowed path.
    assert not is_allowed("POST", f"/api/v1/migrations/{migration}/investigations/x")
    assert not is_allowed("POST", f"/api/v1/migrations/{migration}/investigations/../datasets")


def test_demo_does_not_publish_its_schema_or_docs() -> None:
    """A deployed process describes neither its routes nor its payloads."""
    app = create_app(_settings())
    assert app.openapi_url is None
    assert app.docs_url is None
    with _client(_settings()) as client:
        assert client.get("/api/v1/openapi.json").status_code == 404
        assert client.get("/api/v1/docs").status_code == 404


def test_local_development_still_publishes_its_schema() -> None:
    app = create_app(Settings(database_url=LOCAL_DB, db_connect_timeout_seconds=1))  # type: ignore[arg-type]
    assert app.openapi_url == "/api/v1/openapi.json"
    assert app.docs_url == "/api/v1/docs"


def test_local_development_is_unaffected_by_the_demo_policy() -> None:
    """The policy exists only in demo: local keeps behaving exactly as before."""
    with _client(Settings(database_url=LOCAL_DB, db_connect_timeout_seconds=1)) as client:  # type: ignore[arg-type]
        response = client.post("/api/v1/migrations", json={})
        assert response.json().get("code") != DEMO_READ_ONLY_CODE


def test_production_is_unaffected_by_the_demo_policy() -> None:
    """Production still refuses on identity, not on the demo policy (docs/deployment.md §1)."""
    settings = Settings(
        env="production",  # type: ignore[arg-type]
        database_url=UNREACHABLE_DB,  # type: ignore[arg-type]
        db_connect_timeout_seconds=1,
    )
    with _client(settings) as client:
        response = client.post("/api/v1/migrations", json={})
        assert response.json().get("code") != DEMO_READ_ONLY_CODE
        assert client.get("/api/v1/openapi.json").status_code == 404


def test_demo_cannot_be_configured_to_spend_money() -> None:
    """No request path can reach a paid provider because the process will not start with one."""
    for provider in ("anthropic", "scripted"):
        with pytest.raises(ValidationError, match="public demo accepts only"):
            _settings(ai_provider=provider)
    assert _settings(ai_provider="demo").ai_provider == "demo"
    assert _settings(ai_provider="disabled").ai_provider == "disabled"


def test_demo_ignores_the_identity_header() -> None:
    """A visitor cannot choose who they are (SEC-11)."""
    settings = _settings()
    assert not settings.dev_identity_active
    assert settings.public_demo
