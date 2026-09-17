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
    after_id: uuid.UUID | None,
    limit: int,
) -> list[Issue]:
    query = select(Issue).where(Issue.migration_id == migration_id)
    if status:
        query = query.where(Issue.status == status)
    if severity:
        query = query.where(Issue.severity == severity)
    if after_id:
        query = query.where(Issue.id > after_id)
    return list(session.scalars(query.order_by(Issue.id).limit(limit)))


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
