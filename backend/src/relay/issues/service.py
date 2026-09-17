"""Apply issue synchronization decisions for a current run, with audit events."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.ids import uuid7
from relay.issues.domain import ExistingIssue, Finding, SyncAction, root_cause_pairs, synchronize
from relay.issues.models import (
    Issue,
    IssueLink,
    IssueLinkType,
    IssueOccurrence,
    IssueSource,
    IssueStatus,
    LinkAuthor,
)
from relay.workspace.models import Migration


@dataclass(frozen=True, slots=True)
class IssueSeed:
    """What the pipeline knows about a finding when an issue may need to be created."""

    rule_exception_id: uuid.UUID
    fingerprint: str
    rule_id: str
    category: str
    nature: str
    severity: str
    title: str
    subjects: tuple[str, ...]
    amount_at_risk: Decimal | None


@dataclass(frozen=True, slots=True)
class SyncSummary:
    links_created: int
    verification_failed: int
    created: int
    updated: int
    reopened: int
    verified_resolved: int


def _source(rule_id: str) -> IssueSource:
    if rule_id.startswith("RECON."):
        return IssueSource.RECONCILIATION
    if rule_id.startswith(("NORM.", "COA.", "OVERRIDE.")):
        return IssueSource.NORMALIZATION
    return IssueSource.RULE


def synchronize_issues(
    session: Session,
    *,
    migration: Migration,
    run_id: uuid.UUID,
    seeds: Mapping[str, IssueSeed],
    clock: Clock | None = None,
) -> SyncSummary:
    """Only a current run may call this (the pipeline guarantees it)."""
    system = Actor.system()
    issues = {
        issue.fingerprint: issue
        for issue in session.scalars(
            select(Issue)
            .where(Issue.migration_id == migration.id, Issue.fingerprint.is_not(None))
            .with_for_update()
        )
        if issue.fingerprint is not None
    }
    findings = [
        Finding(seed.fingerprint, seed.rule_id, seed.severity, seed.amount_at_risk)
        for seed in seeds.values()
    ]
    existing = {
        fp: ExistingIssue(issue.id, fp, issue.status, issue.severity, issue.amount_at_risk)
        for fp, issue in issues.items()
    }
    now = (clock or SystemClock()).now()
    counts = dict.fromkeys(SyncAction, 0)
    for decision in synchronize(findings, existing):
        counts[decision.action] += 1
        seed = seeds.get(decision.fingerprint)
        if decision.action is SyncAction.CREATE and seed is not None:
            issue = Issue(
                id=uuid7(clock),
                migration_id=migration.id,
                key=f"{migration.issue_key_prefix}-{migration.next_issue_number}",
                fingerprint=seed.fingerprint,
                source=_source(seed.rule_id).value,
                rule_or_recon_id=seed.rule_id,
                category=seed.category,
                nature=seed.nature,
                severity=seed.severity,
                title=seed.title,
                subjects=list(seed.subjects),
                status=IssueStatus.OPEN.value,
                amount_at_risk=seed.amount_at_risk,
                first_seen_run_id=run_id,
                last_seen_run_id=run_id,
                version=1,
            )
            migration.next_issue_number += 1
            session.add(issue)
            session.flush()
            session.add(
                IssueOccurrence(
                    issue_id=issue.id, rule_exception_id=seed.rule_exception_id, run_id=run_id
                )
            )
            audit.record(
                session,
                actor=system,
                action="issue.created",
                entity_type="issue",
                entity_id=issue.id,
                migration_id=migration.id,
                after={
                    "key": issue.key,
                    "rule_id": seed.rule_id,
                    "severity": seed.severity,
                    "run_id": run_id,
                },
                clock=clock,
            )
            continue
        issue = issues[decision.fingerprint]
        if decision.action is SyncAction.VERIFY_RESOLVED:
            before = issue.status
            issue.status = IssueStatus.RESOLVED.value
            issue.verified_absent_run_id = run_id
            issue.version += 1
            issue.updated_at = now
            audit.record(
                session,
                actor=system,
                action="issue.verified_resolved",
                entity_type="issue",
                entity_id=issue.id,
                migration_id=migration.id,
                before={"status": before},
                after={"status": issue.status, "run_id": run_id},
                clock=clock,
            )
            continue
        if seed is None:
            continue
        before_state = {
            "status": issue.status,
            "severity": issue.severity,
            "amount_at_risk": issue.amount_at_risk,
        }
        issue.last_seen_run_id = run_id
        issue.severity = seed.severity
        issue.amount_at_risk = seed.amount_at_risk
        session.add(
            IssueOccurrence(
                issue_id=issue.id, rule_exception_id=seed.rule_exception_id, run_id=run_id
            )
        )
        if decision.action is SyncAction.VERIFICATION_FAILED:
            issue.status = IssueStatus.OPEN.value
            issue.version += 1
            issue.updated_at = now
            audit.record(
                session,
                actor=system,
                action="issue.verification_failed",
                entity_type="issue",
                entity_id=issue.id,
                migration_id=migration.id,
                before=before_state,
                after={"status": issue.status, "run_id": run_id},
                reason=f"still reported by run {run_id} after the applied change",
                clock=clock,
            )
        elif decision.action is SyncAction.REOPEN:
            issue.status = IssueStatus.OPEN.value
            issue.verified_absent_run_id = None
            issue.version += 1
            issue.updated_at = now
            audit.record(
                session,
                actor=system,
                action="issue.reopened",
                entity_type="issue",
                entity_id=issue.id,
                migration_id=migration.id,
                before=before_state,
                after={"status": issue.status, "run_id": run_id},
                reason=f"regression detected in run {run_id}",
                clock=clock,
            )
        elif decision.changes:
            issue.version += 1
            issue.updated_at = now
            audit.record(
                session,
                actor=system,
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                migration_id=migration.id,
                before=before_state,
                after={
                    "severity": issue.severity,
                    "amount_at_risk": issue.amount_at_risk,
                    "run_id": run_id,
                },
                clock=clock,
            )
    session.flush()
    links = _link_same_root_cause(session, migration, run_id, seeds, clock)
    return SyncSummary(
        links_created=links,
        verification_failed=counts[SyncAction.VERIFICATION_FAILED],
        created=counts[SyncAction.CREATE],
        updated=counts[SyncAction.UPDATE],
        reopened=counts[SyncAction.REOPEN],
        verified_resolved=counts[SyncAction.VERIFY_RESOLVED],
    )


def _link_same_root_cause(
    session: Session,
    migration: Migration,
    run_id: uuid.UUID,
    seeds: Mapping[str, IssueSeed],
    clock: Clock | None,
) -> int:
    """System links between this run's issues that share a subject or journal entry."""
    current = session.scalars(
        select(Issue).where(Issue.migration_id == migration.id, Issue.fingerprint.in_(list(seeds)))
    ).all()
    pairs = root_cause_pairs((issue.id, issue.subjects) for issue in current)
    if not pairs:
        return 0
    existing = {
        (link.from_issue_id, link.to_issue_id)
        for link in session.scalars(
            select(IssueLink).where(
                IssueLink.migration_id == migration.id,
                IssueLink.link_type == IssueLinkType.SAME_ROOT_CAUSE.value,
            )
        )
    }
    created = 0
    for (left, right), key in sorted(pairs.items()):
        if (left, right) in existing:
            continue
        session.add(
            IssueLink(
                id=uuid7(clock),
                migration_id=migration.id,
                from_issue_id=left,
                to_issue_id=right,
                link_type=IssueLinkType.SAME_ROOT_CAUSE.value,
                created_by_actor_type=LinkAuthor.SYSTEM.value,
                reason=f"both name {key} (run {run_id})",
            )
        )
        created += 1
    if created:
        session.flush()
        audit.record(
            session,
            actor=Actor.system(),
            action="issue.links_created",
            entity_type="migration",
            entity_id=migration.id,
            migration_id=migration.id,
            before={"links": len(existing)},
            after={"links": len(existing) + created, "run_id": run_id},
            clock=clock,
        )
    return created
