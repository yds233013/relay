"""Who is acting: a user, the system, or AI on behalf of a user."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

ActorKind = Literal["user", "system", "ai"]


@dataclass(frozen=True, slots=True)
class Actor:
    kind: ActorKind
    user_id: uuid.UUID | None = None
    role: str | None = None
    """The user's role at the time of the action (users only)."""

    def __post_init__(self) -> None:
        if self.kind == "user" and (self.user_id is None or self.role is None):
            raise ValueError("a user actor needs a user id and role")
        if self.kind == "system" and self.user_id is not None:
            raise ValueError("the system actor has no user id")

    @classmethod
    def system(cls) -> Actor:
        return cls("system")

    @classmethod
    def user(cls, user_id: uuid.UUID, role: str) -> Actor:
        return cls("user", user_id, role)
