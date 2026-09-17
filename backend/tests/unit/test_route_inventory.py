"""Every route is authenticated, and every mutating route is a known governed operation.

SEC-10 (default deny) and GV-01: a new endpoint that forgets its actor dependency, or that mutates
state outside the governed set, fails here rather than in production.
"""

from __future__ import annotations

from typing import Final

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic import SecretStr

from relay.api.app import create_app
from relay.api.deps import current_actor
from relay.core.config import Environment, Settings

# Deliberately public: liveness, readiness and the schema. `/api/v1/dev/users` lists the seeded
# users to sign in as and exists only while the development identity is active (SEC-11).
PUBLIC: Final = frozenset(
    {
        "GET /health",
        "GET /health/ready",
        "GET /api/v1/openapi.json",
        "GET /api/v1/docs",
        "GET /api/v1/docs/oauth2-redirect",
        "GET /api/v1/redoc",
        "GET /api/v1/dev/users",
    }
)

# Every non-GET route, with what it does. Adding a row here is a deliberate act: state changes
# belong to a service that audits them (GV-01, GV-05), and nothing applies an overlay except an
# approved change request. Issue links are created by the pipeline, never over the API.
MUTATIONS: Final = {
    "POST /api/v1/migrations": "create a migration",
    "POST /api/v1/migrations/{migration_id}/source-systems": "register a source system",
    "POST /api/v1/migrations/{migration_id}/datasets": "register a dataset",
    "POST /api/v1/datasets/{dataset_id}/imports": "upload a source file",
    "POST /api/v1/datasets/{dataset_id}/column-mapping-sets": "draft a column mapping set",
    "POST /api/v1/datasets/{dataset_id}/column-mapping-preview": "preview a mapping (no change)",
    "POST /api/v1/migrations/{migration_id}/account-mapping-sets": "draft an account mapping set",
    "POST /api/v1/migrations/{migration_id}/change-requests": "draft a change request",
    "PUT /api/v1/change-requests/{change_id}": "edit a draft change request",
    "POST /api/v1/change-requests/{change_id}/submit": "submit a change request",
    "POST /api/v1/change-requests/{change_id}/approve": "record an approval",
    "POST /api/v1/change-requests/{change_id}/reject": "record a rejection",
    "POST /api/v1/change-requests/{change_id}/withdraw": "withdraw a change request",
    "POST /api/v1/migrations/{migration_id}/pipeline-runs": "request a pipeline run",
    "POST /api/v1/migrations/{migration_id}/issues": "raise a manual issue",
    "PATCH /api/v1/issues/{issue_id}": "own, prioritise or close an issue",
    "POST /api/v1/issues/{issue_id}/comments": "comment on an issue",
    "POST /api/v1/migrations/{migration_id}/investigations": "start an AI investigation",
    "POST /api/v1/findings/{finding_id}/accept": "accept an AI finding",
    "POST /api/v1/findings/{finding_id}/dismiss": "dismiss an AI finding",
    "POST /api/v1/findings/{finding_id}/draft-change-request": "draft a change request",
}


def _routes() -> list[tuple[str, Dependant]]:
    """Every mounted route with its dependency tree, including routers included with a prefix."""
    settings = Settings(
        env=Environment.TEST,
        database_url=SecretStr("postgresql+psycopg://relay:relay@127.0.0.1:1/relay_test"),
    )
    app = create_app(settings)
    found: list[tuple[str, Dependant]] = []
    for route in app.routes:
        contexts = getattr(route, "effective_route_contexts", None)
        for context in contexts() if callable(contexts) else ():
            found.extend(
                (f"{method} {context.path}", context.dependant)
                for method in sorted(context.methods or ())
            )
        if isinstance(route, APIRoute):
            found.extend(
                (f"{method} {route.path}", route.dependant)
                for method in sorted(route.methods or ())
            )
    return sorted(found, key=lambda item: item[0])


def _authenticates(dependant: Dependant, seen: set[int] | None = None) -> bool:
    seen = seen if seen is not None else set()
    if dependant.call is current_actor:
        return True
    for sub in dependant.dependencies:
        if id(sub) in seen:
            continue
        seen.add(id(sub))
        if _authenticates(sub, seen):
            return True
    return False


ROUTES: Final = _routes()


def test_the_application_exposes_routes() -> None:
    assert len(ROUTES) > 40  # the inventory below is not vacuous


@pytest.mark.parametrize(("name", "dependant"), ROUTES, ids=[name for name, _ in ROUTES])
def test_every_route_authenticates_unless_it_is_deliberately_public(
    name: str, dependant: Dependant
) -> None:
    if name in PUBLIC:
        assert not _authenticates(dependant), f"{name} is listed as public but authenticates"
        return
    assert _authenticates(dependant), f"{name} has no actor dependency"


def test_mutating_routes_are_the_known_governed_operations() -> None:
    mutating = {name for name, _ in ROUTES if not name.startswith("GET ")}
    assert mutating == set(MUTATIONS), (
        "mutating routes changed: "
        f"added {sorted(mutating - set(MUTATIONS))}, removed {sorted(set(MUTATIONS) - mutating)}"
    )
