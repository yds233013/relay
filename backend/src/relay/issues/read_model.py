"""Query side for issues."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from relay.core.errors import NotFoundError
from relay.issues.models import Issue, IssueLink


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


def get_issue_by_key(session: Session, migration_id: uuid.UUID, key: str) -> Issue | None:
    return session.scalars(
        select(Issue).where(Issue.migration_id == migration_id, Issue.key == key)
    ).first()


def links_for(session: Session, issue_id: uuid.UUID) -> list[tuple[IssueLink, Issue]]:
    """Links of an issue with the issue at the other end."""
    rows = session.scalars(
        select(IssueLink)
        .where(or_(IssueLink.from_issue_id == issue_id, IssueLink.to_issue_id == issue_id))
        .order_by(IssueLink.created_at, IssueLink.id)
    ).all()
    other_ids = {
        (link.to_issue_id if link.from_issue_id == issue_id else link.from_issue_id)
        for link in rows
    }
    others = {
        issue.id: issue for issue in session.scalars(select(Issue).where(Issue.id.in_(other_ids)))
    }
    linked = []
    for link in rows:
        other = others.get(
            link.to_issue_id if link.from_issue_id == issue_id else link.from_issue_id
        )
        if other is not None:
            linked.append((link, other))
    return linked
