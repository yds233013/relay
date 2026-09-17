"""Issue workflow driven by people and by applied change requests (governance.md §1.2).

People assign owners, move issues between ``open`` and ``in_progress``, comment, and close manual
issues. Nobody sets ``resolved``: only a current run that no longer reports the fingerprint does.
``dispositioned`` and ``awaiting_verification`` are entered when change requests are applied.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import ClassVar, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.errors import InvalidInputError, NotFoundError, RelayError
from relay.core.ids import uuid7
from relay.identity import service as identity
from relay.issues.models import (
    OPEN_STATUSES,
    Issue,
    IssueComment,
    IssueSource,
    IssueStatus,
)
from relay.workspace.models import Migration

MAX_COMMENT_LENGTH: Final = 10_000
MAX_TITLE_LENGTH: Final = 300
UNCHANGED: Final = object()

_USER_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    IssueStatus.OPEN.value: frozenset({IssueStatus.IN_PROGRESS.value}),
    IssueStatus.IN_PROGRESS.value: frozenset({IssueStatus.OPEN.value}),
}
_MANUAL_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    IssueStatus.OPEN.value: frozenset({IssueStatus.IN_PROGRESS.value, IssueStatus.CLOSED.value}),
    IssueStatus.IN_PROGRESS.value: frozenset({IssueStatus.OPEN.value, IssueStatus.CLOSED.value}),
    IssueStatus.CLOSED.value: frozenset({IssueStatus.OPEN.value}),
}


class IssueTransitionError(RelayError):
    code: ClassVar[str] = "issue.invalid_transition"
    title: ClassVar[str] = "Issue cannot move to that status"
    http_status: ClassVar[int] = 409


class ResolutionRequiresVerificationError(RelayError):
    code: ClassVar[str] = "issue.resolution_requires_verification"
    title: ClassVar[str] = "Issues are resolved only by a run that no longer reports them"
    http_status: ClassVar[int] = 409


class IssueVersionConflictError(RelayError):
    code: ClassVar[str] = "issue.version_conflict"
    title: ClassVar[str] = "The issue changed since it was loaded"
    http_status: ClassVar[int] = 409


def get_issue(session: Session, issue_id: uuid.UUID, *, for_update: bool = False) -> Issue:
    issue = session.get(Issue, issue_id, with_for_update=for_update)
    if issue is None:
        raise NotFoundError("issue not found")
    return issue


def update_issue(
    session: Session,
    *,
    actor: Actor,
    issue: Issue,
    expected_version: int,
    owner_user_id: uuid.UUID | object | None = UNCHANGED,
    status: str | None = None,
    note: str = "",
    clock: Clock | None = None,
) -> Issue:
    if issue.version != expected_version:
        raise IssueVersionConflictError("reload the issue and try again")
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    if owner_user_id is not UNCHANGED and owner_user_id != issue.owner_user_id:
        if owner_user_id is not None:
            if not isinstance(owner_user_id, uuid.UUID):
                raise InvalidInputError("owner must be a user id")
            owner = identity.get_user(session, owner_user_id)
            if owner is None or not owner.is_active:
                raise InvalidInputError("owner must be an active user")
        before["owner_user_id"] = issue.owner_user_id
        after["owner_user_id"] = owner_user_id
        issue.owner_user_id = owner_user_id if isinstance(owner_user_id, uuid.UUID) else None
    if status is not None and status != issue.status:
        if status == IssueStatus.RESOLVED.value:
            raise ResolutionRequiresVerificationError(
                "a current pipeline run marks an issue resolved when the finding is gone"
            )
        allowed = (
            _MANUAL_TRANSITIONS if issue.source == IssueSource.MANUAL.value else _USER_TRANSITIONS
        )
        if status not in allowed.get(issue.status, frozenset()):
            raise IssueTransitionError(f"an issue cannot move from {issue.status} to {status}")
        before["status"] = issue.status
        after["status"] = status
        issue.status = status
    if not after:
        return issue
    issue.version += 1
    issue.updated_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="issue.workflow_updated",
        entity_type="issue",
        entity_id=issue.id,
        migration_id=issue.migration_id,
        before=before,
        after=after,
        reason=note.strip() or None,
        clock=clock,
    )
    return issue


def create_manual_issue(
    session: Session,
    *,
    actor: Actor,
    migration: Migration,
    title: str,
    severity: str,
    category: str,
    nature: str,
    description: str,
    clock: Clock | None = None,
) -> Issue:
    if actor.user_id is None:
        raise InvalidInputError("manual issues are raised by a person")
    title = title.strip()
    if not title or len(title) > MAX_TITLE_LENGTH:
        raise InvalidInputError("a title of at most 300 characters is required")
    locked = session.get(Migration, migration.id, with_for_update=True)
    if locked is None:
        raise NotFoundError("migration not found")
    issue = Issue(
        id=uuid7(clock),
        migration_id=migration.id,
        key=f"{locked.issue_key_prefix}-{locked.next_issue_number}",
        fingerprint=None,
        source=IssueSource.MANUAL.value,
        rule_or_recon_id=None,
        category=category,
        nature=nature,
        severity=severity,
        title=title,
        subjects=[],
        status=IssueStatus.OPEN.value,
        owner_user_id=actor.user_id,
        version=1,
    )
    locked.next_issue_number += 1
    session.add(issue)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="issue.created",
        entity_type="issue",
        entity_id=issue.id,
        migration_id=migration.id,
        before={"status": None},
        after={"key": issue.key, "source": issue.source, "severity": severity, "title": title},
        clock=clock,
    )
    if description.strip():
        add_comment(session, actor=actor, issue=issue, body=description, clock=clock)
    return issue


def add_comment(
    session: Session, *, actor: Actor, issue: Issue, body: str, clock: Clock | None = None
) -> IssueComment:
    if actor.user_id is None:
        raise InvalidInputError("comments are written by people")
    text = body.strip()
    if not text or len(text) > MAX_COMMENT_LENGTH:
        raise InvalidInputError("a comment of at most 10,000 characters is required")
    comment = IssueComment(
        id=uuid7(clock), issue_id=issue.id, author_user_id=actor.user_id, body=text
    )
    session.add(comment)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="issue.commented",
        entity_type="issue",
        entity_id=issue.id,
        migration_id=issue.migration_id,
        before={"comment": None},
        after={"comment_id": comment.id, "length": len(text)},
        clock=clock,
    )
    return comment


def comments_for(session: Session, issue_id: uuid.UUID) -> list[IssueComment]:
    return list(
        session.scalars(
            select(IssueComment)
            .where(IssueComment.issue_id == issue_id)
            .order_by(IssueComment.created_at, IssueComment.id)
        )
    )


# ------------------------------------------------------------------ effects of change requests
def mark_dispositioned(
    session: Session,
    *,
    actor: Actor,
    issue_id: uuid.UUID,
    change_request_id: uuid.UUID,
    clock: Clock | None = None,
) -> None:
    issue = get_issue(session, issue_id, for_update=True)
    if IssueStatus(issue.status) not in OPEN_STATUSES:
        raise IssueTransitionError(f"a {issue.status} issue cannot be dispositioned")
    _system_transition(
        session,
        actor=actor,
        issue=issue,
        status=IssueStatus.DISPOSITIONED,
        action="issue.dispositioned",
        change_request_id=change_request_id,
        clock=clock,
    )


def undo_disposition(
    session: Session,
    *,
    actor: Actor,
    issue_id: uuid.UUID,
    change_request_id: uuid.UUID,
    clock: Clock | None = None,
) -> None:
    """A reverted disposition reopens the issue; the next current run verifies it again."""
    issue = get_issue(session, issue_id, for_update=True)
    if issue.status != IssueStatus.DISPOSITIONED.value:
        return
    _system_transition(
        session,
        actor=actor,
        issue=issue,
        status=IssueStatus.OPEN,
        action="issue.disposition_reverted",
        change_request_id=change_request_id,
        clock=clock,
    )


def await_verification(
    session: Session,
    *,
    actor: Actor,
    issue_ids: Iterable[uuid.UUID],
    change_request_id: uuid.UUID,
    clock: Clock | None = None,
) -> None:
    """Issues named as evidence by an applied change wait for the next current run."""
    for issue_id in sorted(set(issue_ids)):
        issue = session.get(Issue, issue_id, with_for_update=True)
        if issue is None or issue.fingerprint is None:
            continue
        if issue.status not in {IssueStatus.OPEN.value, IssueStatus.IN_PROGRESS.value}:
            continue
        _system_transition(
            session,
            actor=actor,
            issue=issue,
            status=IssueStatus.AWAITING_VERIFICATION,
            action="issue.awaiting_verification",
            change_request_id=change_request_id,
            clock=clock,
        )


def _system_transition(
    session: Session,
    *,
    actor: Actor,
    issue: Issue,
    status: IssueStatus,
    action: str,
    change_request_id: uuid.UUID,
    clock: Clock | None,
) -> None:
    before = issue.status
    issue.status = status.value
    issue.version += 1
    issue.updated_at = (clock or SystemClock()).now()
    session.flush()
    audit.record(
        session,
        actor=actor,
        action=action,
        entity_type="issue",
        entity_id=issue.id,
        migration_id=issue.migration_id,
        change_request_id=change_request_id,
        before={"status": before},
        after={"status": issue.status},
        clock=clock,
    )
