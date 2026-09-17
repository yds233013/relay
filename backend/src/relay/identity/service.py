"""Users: lookup and creation. Creating users is an audited platform event."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.errors import RelayError
from relay.core.ids import uuid7
from relay.identity.models import Role, User
from relay.identity.permissions import Permission, allowed


class AuthenticationRequiredError(RelayError):
    code: ClassVar[str] = "auth.required"
    title: ClassVar[str] = "Authentication required"
    http_status: ClassVar[int] = 401


class PermissionDeniedError(RelayError):
    code: ClassVar[str] = "auth.forbidden"
    title: ClassVar[str] = "Permission denied"
    http_status: ClassVar[int] = 403


def actor_for(user: User) -> Actor:
    return Actor.user(user.id, user.role)


def require(actor: Actor, permission: Permission) -> None:
    if actor.kind != "user" or actor.role is None or not allowed(actor.role, permission):
        raise PermissionDeniedError(f"this action requires the {permission.value} permission")


def find_active_user_by_email(session: Session, email: str) -> User | None:
    return session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower(), User.is_active)
    ).first()


def display_names(session: Session, user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Display names for a set of users in one query (issue owners, reviewers)."""
    wanted = set(user_ids)
    if not wanted:
        return {}
    return {
        user.id: user.display_name
        for user in session.scalars(select(User).where(User.id.in_(wanted)))
    }


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def list_active_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).where(User.is_active).order_by(User.email)))


def create_user(
    session: Session, *, email: str, display_name: str, role: Role, actor: Actor
) -> User:
    user = User(id=uuid7(), email=email.strip(), display_name=display_name, role=role.value)
    session.add(user)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        migration_id=None,
        after={"email": user.email, "role": user.role},
    )
    return user
