"""API foundation: health, problem responses, request correlation and logging (no database)."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from pydantic import BaseModel

from relay.api.app import create_app
from relay.core.config import Settings
from relay.core.errors import InvalidInputError
from relay.core.money import Money

# Port 1 on localhost: connection refused immediately, no network access.
UNREACHABLE_DB = "postgresql+psycopg://relay:unused@127.0.0.1:1/relay"


class _Body(BaseModel):
    total: Money


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(database_url=UNREACHABLE_DB, db_connect_timeout_seconds=1)  # type: ignore[arg-type]
    app = create_app(settings)

    probe = APIRouter()

    @probe.get("/_test/relay-error")
    def relay_error() -> None:
        raise InvalidInputError("bad thing")

    @probe.get("/_test/crash")
    def crash() -> None:
        raise RuntimeError("secret internal detail")

    @probe.post("/_test/money")
    def echo(body: _Body) -> _Body:
        return body

    app.include_router(probe)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "relay-api", "version": "0.1.0"}


def test_ready_reports_unreachable_database_without_leaking_details(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"]["reachable"] is False
    assert body["database"]["head_revision"] == "0005_readiness"
    assert "unused" not in response.text
    assert "127.0.0.1" not in response.text


def test_security_headers_and_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert len(response.headers["x-request-id"]) == 36


def test_safe_incoming_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health", headers={"x-request-id": "trace-abc-12345"})
    assert response.headers["x-request-id"] == "trace-abc-12345"


@pytest.mark.parametrize(
    "unsafe",
    [b"short", b"has space in it", b"a" * 200, b"<script>x</script>", "injectévalue".encode()],
)
def test_unsafe_request_id_is_replaced(client: TestClient, unsafe: bytes) -> None:
    response = client.get("/health", headers=[(b"x-request-id", unsafe)])
    assert response.headers["x-request-id"].encode("latin-1") != unsafe
    assert len(response.headers["x-request-id"]) == 36


def test_not_found_is_problem_json(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "status": 404,
        "code": "http.not_found",
        "title": "Not Found",
    }


def test_relay_error_maps_to_problem_json(client: TestClient) -> None:
    response = client.get("/_test/relay-error")
    assert response.status_code == 422
    assert response.json()["code"] == "input.invalid"
    assert response.json()["detail"] == "bad thing"


def test_unhandled_error_hides_internals(client: TestClient) -> None:
    response = client.get("/_test/crash")
    assert response.status_code == 500
    assert response.json()["code"] == "internal.unexpected_error"
    assert "secret internal detail" not in response.text


def test_validation_errors_do_not_echo_submitted_values(client: TestClient) -> None:
    response = client.post("/_test/money", json={"total": {"amount": 1234.5678, "currency": "USD"}})
    assert response.status_code == 422
    assert response.json()["code"] == "request.validation_failed"
    assert "1234.5678" not in response.text
    assert response.json()["errors"][0]["loc"][:2] == ["body", "total"]


def test_money_round_trips_through_the_api(client: TestClient) -> None:
    response = client.post("/_test/money", json={"total": {"amount": "9340.5", "currency": "USD"}})
    assert response.status_code == 200
    assert response.json() == {"total": {"amount": "9340.50", "currency": "USD"}}


def test_openapi_is_versioned(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]


def test_request_log_is_json_without_query_string(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    client.get(
        "/health?customer=Rose%20City%20Market%20Hall", headers={"x-request-id": "req-00000001"}
    )
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    request_logs = [line for line in lines if line.get("event") == "http_request"]
    assert request_logs, lines
    entry = request_logs[-1]
    assert entry["request_id"] == "req-00000001"
    assert entry["path"] == "/health"
    assert entry["status"] == 200
    assert entry["level"] == "info"
    assert entry["timestamp"].endswith("Z")
    assert "Rose" not in json.dumps(entry)


def test_database_sessions_commit_before_the_response_is_sent() -> None:
    """With the default scope a yield dependency ends after the response; the commit must not."""
    from typing import get_args  # noqa: PLC0415 - test-local

    from relay.api.deps import SessionDep  # noqa: PLC0415

    dependency = get_args(SessionDep)[1]
    assert dependency.scope == "function"
