"""Query side for issues."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.core.errors import NotFoundError
from relay.issues.models import Issue


def issues_for(
    session: Session,
    migration_id: uuid.UUID,
    *,
    status: str | None,
    severity: str | None,
    nature: str | None = None,
    fingerprint: str | None = None,
    owner: uuid.UUID | None = None,
    rule: str | None = None,
    order: str = "key",
    offset: int = 0,
    limit: int,
) -> list[Issue]:
    """Issues for the queue. ``order`` is ``key`` or ``amount`` (largest first)."""
    query = select(Issue).where(Issue.migration_id == migration_id)
    if status:
        query = query.where(Issue.status == status)
    if severity:
        query = query.where(Issue.severity == severity)
    if nature:
        query = query.where(Issue.nature == nature)
    if fingerprint:
        query = query.where(Issue.fingerprint == fingerprint)
    if owner:
        query = query.where(Issue.owner_user_id == owner)
    if rule:
        query = query.where(Issue.rule_or_recon_id == rule)
    if order == "amount":
        query = query.order_by(Issue.amount_at_risk.desc().nulls_last(), Issue.id)
    else:
        query = query.order_by(Issue.id)
    return list(session.scalars(query.offset(offset).limit(limit)))


def get_issue(session: Session, issue_id: uuid.UUID) -> Issue:
    issue = session.get(Issue, issue_id)
    if issue is None:
        raise NotFoundError("issue not found")
    return issue


def issues_touching(session: Session, migration_id: uuid.UUID, natural_key: str) -> list[Issue]:
    return list(
        session.scalars(
            select(Issue)
            .where(Issue.migration_id == migration_id, Issue.subjects.contains([natural_key]))
            .order_by(Issue.id)
        )
    )
