"""E2E-8 at the API: a new migration from a small CSV, through suggestions and approval to issues.

The company is invented here and unrelated to Brightwater.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from relay.api.app import create_app
from relay.core.config import Settings
from relay.core.db import create_session_factory
from relay.worker import drain
from tests.integration.support import ensure_head, make_workspace, worker_context

CUSTOMERS = (
    b"Customer Code,Customer Name,City,Status\r\n"
    b"K-1,Northwind Cafe,Boise,Active\r\n"
    b"K-2,Harbor Bakery,Tacoma,Active\r\n"
    b"K-2,Harbor Bakery LLC,Tacoma,Active\r\n"
)


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("new-migration-blobs")


@pytest.fixture(scope="module")
def client(settings: Settings, root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(settings.model_copy(update={"storage_dir": root}))) as test_client:
        yield test_client


def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json()


def test_e2e8_new_migration_from_csv(
    client: TestClient, migrated: str, engine: Engine, root: Path
) -> None:
    ensure_head(migrated)
    factory = create_session_factory(engine)
    space = make_workspace(factory)  # seeded users with every role
    lead = {"X-Relay-User": _email(client, "implementation_lead")}
    specialist = {"X-Relay-User": space.specialist_email}

    denied = client.post("/api/v1/migrations", json={}, headers=specialist)
    assert denied.status_code in {403, 422}
    body = {
        "company": {"name": "Cascade Coffee Roasters", "legal_name": "Cascade Coffee LLC",
                    "country": "US", "functional_currency": "USD", "fiscal_year_start_month": 1},
        "name": "Spreadsheets to new ERP", "issue_key_prefix": "C2R",
        "opening_balance_date": "2025-12-31", "history_start_date": "2026-01-01",
        "cutover_date": "2026-03-31", "go_live_date": "2026-04-01",
    }  # fmt: skip
    invalid = client.post("/api/v1/migrations", json=body, headers=lead)
    assert invalid.status_code == 422  # the database would reject digits; the API says so first
    migration = ok(
        client.post(
            "/api/v1/migrations",
            json={
                "company": {"name": "Cascade Coffee Roasters", "legal_name": "Cascade Coffee LLC",
                            "country": "US", "functional_currency": "USD",
                            "fiscal_year_start_month": 1},
                "name": "Spreadsheets to new ERP",
                "issue_key_prefix": "CCR",
                "opening_balance_date": "2025-12-31",
                "history_start_date": "2026-01-01",
                "cutover_date": "2026-03-31",
                "go_live_date": "2026-04-01",
            },
            headers=lead,
        ),
        201,
    )  # fmt: skip
    mid = migration["id"]
    system = ok(
        client.post(
            f"/api/v1/migrations/{mid}/source-systems",
            json={"name": "Office spreadsheets", "kind": "spreadsheet"},
            headers=lead,
        ),
        201,
    )
    dataset = ok(
        client.post(
            f"/api/v1/migrations/{mid}/datasets",
            json={"source_system_id": system["id"], "dataset_type": "customers",
                  "name": "customers.csv"},
            headers=lead,
        ),
        201,
    )  # fmt: skip
    upload = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        content=CUSTOMERS,
        headers={**specialist, "X-Relay-Filename": "customers.csv", "Content-Type": "text/csv"},
    )
    assert upload.status_code == 202, upload.text
    drain(worker_context(factory, root))

    suggestion = ok(
        client.get(f"/api/v1/datasets/{dataset['id']}/column-mapping-suggestion", headers=lead)
    )
    by_field = {f["field"]: f for f in suggestion["fields"]}
    assert by_field["party_code"]["specification"]["source"] == "Customer Code"
    assert by_field["name"]["specification"]["source"] == "Customer Name"
    config = {
        "fields": {
            name: spec["specification"]
            for name, spec in by_field.items()
            if spec["specification"] and name in {"party_code", "name", "city"}
        },
        "exclude_rows_where_blank": [],
    }
    preview = ok(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/column-mapping-preview",
            json=config,
            headers=specialist,
        )
    )
    assert preview["missing_required_fields"] == []
    assert [r["values"]["party_code"] for r in preview["rows"]] == ["K-1", "K-2", "K-2"]

    mapping_set = ok(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/column-mapping-sets", json=config, headers=specialist
        ),
        201,
    )
    change = ok(
        client.post(
            f"/api/v1/migrations/{mid}/change-requests",
            json={"kind": "column_mapping_set", "title": "Customers mapping",
                  "payload": {"mapping_set_id": mapping_set["id"]}},
            headers=specialist,
        ),
        201,
    )  # fmt: skip
    ok(
        client.post(
            f"/api/v1/change-requests/{change['id']}/submit",
            json={"justification": "Checked against the preview."},
            headers=specialist,
        )
    )
    outcome = ok(
        client.post(f"/api/v1/change-requests/{change['id']}/approve", json={}, headers=lead)
    )
    assert outcome["change_request"]["status"] == "applied"
    drain(worker_context(factory, root))

    run = ok(client.get(f"/api/v1/pipeline-runs/{outcome['run_id']}", headers=lead))
    assert run["status"] == "succeeded"
    issues = ok(client.get(f"/api/v1/migrations/{mid}/issues", headers=lead))["items"]
    assert [(i["key"], i["rule_or_recon_id"]) for i in issues] == [
        ("CCR-1", "NORM.DUPLICATE_NATURAL_KEY")
    ]
    readiness = ok(client.get(f"/api/v1/migrations/{mid}/readiness", headers=lead))
    failing = {g["gate_id"] for g in readiness["gates"] if g["status"] == "fail"}
    # G1 passes: it checks the datasets this migration declares. Mapping and blocking gates fail.
    assert {"G3", "G5", "G12"} <= failing
    assert "G1" not in failing


def _email(client: TestClient, role: str) -> str:
    users = ok(client.get("/api/v1/dev/users"))
    return str(next(u["email"] for u in users if u["role"] == role))
