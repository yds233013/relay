"""Query side for audit events."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit.models import AuditEvent


def events(
    session: Session,
    migration_id: uuid.UUID,
    *,
    action: str | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    after_seq: int,
    limit: int,
) -> list[AuditEvent]:
    query = select(AuditEvent).where(
        AuditEvent.migration_id == migration_id, AuditEvent.migration_seq > after_seq
    )
    if action:
        query = query.where(AuditEvent.action == action)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    return list(session.scalars(query.order_by(AuditEvent.migration_seq).limit(limit)))


def events_for_change_request(session: Session, change_request_id: uuid.UUID) -> list[AuditEvent]:
    """Every event recorded under a change request, in chain order."""
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.change_request_id == change_request_id)
            .order_by(AuditEvent.migration_seq)
        )
    )
