"""Query side for change requests and active overlays (no writes)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.changes.models import ChangeRequest, EntityDecision, OverlayStatus


def active_entity_decisions(session: Session, migration_id: uuid.UUID) -> list[EntityDecision]:
    return list(
        session.scalars(
            select(EntityDecision)
            .where(
                EntityDecision.migration_id == migration_id,
                EntityDecision.status == OverlayStatus.ACTIVE.value,
            )
            .order_by(EntityDecision.created_at, EntityDecision.id)
        )
    )


def change_request(session: Session, change_id: uuid.UUID) -> ChangeRequest | None:
    return session.get(ChangeRequest, change_id)
