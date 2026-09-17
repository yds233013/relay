"""Request dependencies: database session (one unit of work per request), actor, permissions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session, sessionmaker

from relay.core.actor import Actor
from relay.core.clock import Clock
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.identity import service as identity
from relay.identity.permissions import Permission
from relay.imports.blob_store import BlobStore

DEV_USER_HEADER = "X-Relay-User"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """Commit when the endpoint returns normally; roll back when it raises."""
    factory: sessionmaker[Session] = request.app.state.session_factory
    with session_scope(factory) as session:
        yield session


def get_blob_store(request: Request) -> BlobStore:
    store: BlobStore = request.app.state.blob_store
    return store


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


# scope="function": commit (or roll back) before the response is sent. With FastAPI's default for
# yield dependencies the commit ran after the response, so a client could see 201 for data it
# could not yet read, or for a transaction that then failed to commit.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]
ClockDep = Annotated[Clock, Depends(get_clock)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
BlobStoreDep = Annotated[BlobStore, Depends(get_blob_store)]


def current_actor(
    session: SessionDep,
    settings: SettingsDep,
    x_relay_user: Annotated[str | None, Header(alias=DEV_USER_HEADER, max_length=254)] = None,
) -> Actor:
    """Development identity only (SEC-11): the header names a seeded user by email."""
    if not settings.dev_identity_active or not x_relay_user:
        raise identity.AuthenticationRequiredError("sign-in is required")
    user = identity.find_active_user_by_email(session, x_relay_user)
    if user is None:
        raise identity.AuthenticationRequiredError("unknown or inactive user")
    return identity.actor_for(user)


ActorDep = Annotated[Actor, Depends(current_actor)]


def require(permission: Permission) -> Callable[[Actor], Actor]:
    def check(actor: ActorDep) -> Actor:
        identity.require(actor, permission)
        return actor

    return check


ReaderDep = Annotated[Actor, Depends(require(Permission.READ))]
