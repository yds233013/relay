"""The public demo against a real database.

``tests/unit/test_demo_mode.py`` proves the policy refuses every mutating route. This proves the
other half, which needs rows: that an anonymous visitor really can read a migration without signing
in, that they are resolved to the read-only demo visitor whatever header they send, and that
neither local development nor production changed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from relay.api.app import create_app
from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.config import Environment, Settings
from relay.core.db import create_session_factory, session_scope
from relay.identity import service as identity
from relay.identity.models import DEMO_VISITOR_EMAIL, Role, User
from relay.identity.permissions import ROLE_PERMISSIONS, Permission

from .support import Workspace, ensure_head, make_workspace

# model_copy skips validation, so this must already be a SecretStr or the engine gets a str.
DEPLOYED_PASSWORD_URL = SecretStr(
    "postgresql+psycopg://relay:Xk2-long-random-password@127.0.0.1:1/relay"
)


@pytest.fixture
def space(migrated: str, engine: Engine) -> Workspace:
    ensure_head(migrated)
    return make_workspace(create_session_factory(engine))


@pytest.fixture
def demo_visitor(engine: Engine) -> None:
    """The one account a public demo resolves every caller to."""
    factory = create_session_factory(engine)
    with session_scope(factory) as session:
        if identity.find_active_user_by_email(session, DEMO_VISITOR_EMAIL) is None:
            identity.create_user(
                session,
                email=DEMO_VISITOR_EMAIL,
                display_name="Public demo visitor",
                role=Role.DEMO_VISITOR,
                actor=Actor.system(),
            )


def _demo_settings(settings: Settings) -> Settings:
    # model_copy skips validation, so `env` has to be the enum itself: a plain "demo" string would
    # fail the `is Environment.DEMO` identity checks and silently behave like local.
    return settings.model_copy(update={"env": Environment.DEMO, "ai_provider": "demo"})


@pytest.fixture
def demo_client(settings: Settings, demo_visitor: None) -> Iterator[TestClient]:  # noqa: ARG001 - fixture ordering: the visitor must exist before the app resolves one
    with TestClient(create_app(_demo_settings(settings))) as client:
        yield client


def test_an_anonymous_visitor_can_read_without_signing_in(
    demo_client: TestClient, space: Workspace
) -> None:
    """No account, no header, no 401 — the demo is open by design."""
    listing = demo_client.get("/api/v1/migrations")
    assert listing.status_code == 200
    assert any(row["id"] == str(space.migration_id) for row in listing.json())

    for path in ("", "/overview", "/readiness", "/work-queue", "/issues", "/datasets", "/policy"):
        response = demo_client.get(f"/api/v1/migrations/{space.migration_id}{path}")
        assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_the_visitor_cannot_choose_who_they_are(demo_client: TestClient, space: Workspace) -> None:
    """Sending someone else's address must not make you them (SEC-11)."""
    for email in (space.specialist_email, space.viewer_email):
        me = demo_client.get("/api/v1/me", headers={"X-Relay-User": email})
        assert me.status_code == 200
        assert me.json()["email"] == DEMO_VISITOR_EMAIL
        assert me.json()["role"] == Role.DEMO_VISITOR.value


def test_an_approver_header_does_not_unlock_approval(
    demo_client: TestClient, space: Workspace
) -> None:
    refused = demo_client.post(
        f"/api/v1/change-requests/{uuid.uuid4()}/approve",
        json={},
        headers={"X-Relay-User": space.specialist_email},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "demo.read_only"


def test_a_demo_that_was_never_prepared_refuses_rather_than_inventing_an_actor(
    settings: Settings, migrated: str, engine: Engine
) -> None:
    """Without the seeded visitor there is no identity to fall back on, and none is improvised."""
    ensure_head(migrated)
    factory = create_session_factory(engine)

    def set_active(user_id: uuid.UUID, active: bool) -> None:
        # Deactivating a user is a governed mutation like any other: GV-05 instrumentation fails
        # the transaction unless the audit event is written alongside it, which is the point.
        with session_scope(factory) as session:
            user = session.get(User, user_id)
            assert user is not None
            user.is_active = active
            audit.record(
                session,
                actor=Actor.system(),
                action="user.deactivated" if not active else "user.reactivated",
                entity_type="user",
                entity_id=user_id,
                migration_id=None,
                before={"is_active": not active},
                after={"is_active": active},
            )

    with session_scope(factory) as session:
        existing = identity.find_active_user_by_email(session, DEMO_VISITOR_EMAIL)
        user_id = existing.id if existing is not None else None
    if user_id is not None:
        set_active(user_id, False)
    try:
        with TestClient(create_app(_demo_settings(settings))) as client:
            assert client.get("/api/v1/migrations").status_code == 401
    finally:
        if user_id is not None:
            set_active(user_id, True)


def test_the_demo_visitor_holds_only_read_and_investigation() -> None:
    """Least privilege, asserted rather than assumed."""
    assert ROLE_PERMISSIONS[Role.DEMO_VISITOR] == frozenset(
        {Permission.READ, Permission.REQUEST_INVESTIGATION}
    )
    for forbidden in (
        Permission.MANAGE_WORKSPACE,
        Permission.UPLOAD_IMPORT,
        Permission.REQUEST_PIPELINE_RUN,
        Permission.DRAFT_CHANGE_REQUEST,
        Permission.REVIEW_CHANGE_REQUEST,
        Permission.MANAGE_ISSUES,
    ):
        assert forbidden not in ROLE_PERMISSIONS[Role.DEMO_VISITOR]


def test_every_role_that_could_investigate_before_still_can() -> None:
    """Splitting REQUEST_INVESTIGATION out of MANAGE_ISSUES changed nobody's access."""
    for role in (
        Role.IMPLEMENTATION_SPECIALIST,
        Role.IMPLEMENTATION_LEAD,
        Role.CUSTOMER_CONTROLLER,
    ):
        assert Permission.REQUEST_INVESTIGATION in ROLE_PERMISSIONS[role]
        assert Permission.MANAGE_ISSUES in ROLE_PERMISSIONS[role]
    for role in (Role.VIEWER, Role.ADMIN):
        assert Permission.REQUEST_INVESTIGATION not in ROLE_PERMISSIONS[role]


def test_local_development_still_requires_a_known_user(
    settings: Settings, space: Workspace
) -> None:
    """Nothing about local changed: no header is still 401, and a header still names the person."""
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/migrations").status_code == 401
        signed_in = client.get("/api/v1/me", headers={"X-Relay-User": space.specialist_email})
        assert signed_in.status_code == 200
        assert signed_in.json()["email"] == space.specialist_email


def test_production_still_refuses_everyone(settings: Settings) -> None:
    """Production is unchanged: no identity exists, so every authenticated route is 401."""
    production = settings.model_copy(
        update={"env": Environment.PRODUCTION, "database_url": DEPLOYED_PASSWORD_URL}
    )
    with TestClient(create_app(production)) as client:
        assert client.get("/api/v1/migrations").status_code == 401
        assert (
            client.get(
                "/api/v1/migrations", headers={"X-Relay-User": DEMO_VISITOR_EMAIL}
            ).status_code
            == 401
        )
