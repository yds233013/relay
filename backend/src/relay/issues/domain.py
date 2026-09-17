"""Issue synchronization for one current run (governance.md §1.1). Pure.

Given the run's findings and the migration's existing rule-backed issues, decide which issues to
create, update, reopen and verify as resolved. Nobody else sets ``resolved``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Final

from relay.issues.models import OPEN_STATUSES, IssueStatus


class SyncAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    REOPEN = "reopen"
    VERIFICATION_FAILED = "verification_failed"
    """An applied fix was expected to remove the finding, but the current run still reports it."""
    VERIFY_RESOLVED = "verify_resolved"


@dataclass(frozen=True, slots=True)
class Finding:
    fingerprint: str
    rule_id: str
    severity: str
    amount_at_risk: Decimal | None


@dataclass(frozen=True, slots=True)
class ExistingIssue:
    id: uuid.UUID
    fingerprint: str
    status: str
    severity: str
    amount_at_risk: Decimal | None


@dataclass(frozen=True, slots=True)
class Decision:
    action: SyncAction
    fingerprint: str
    issue_id: uuid.UUID | None = None
    changes: dict[str, object] = field(default_factory=dict)


def synchronize(
    findings: Iterable[Finding], existing: Mapping[str, ExistingIssue]
) -> list[Decision]:
    decisions: list[Decision] = []
    present: set[str] = set()
    for finding in sorted(findings, key=lambda f: f.fingerprint):
        present.add(finding.fingerprint)
        issue = existing.get(finding.fingerprint)
        if issue is None:
            decisions.append(Decision(SyncAction.CREATE, finding.fingerprint))
            continue
        changes: dict[str, object] = {}
        if issue.severity != finding.severity:
            changes["severity"] = finding.severity
        if issue.amount_at_risk != finding.amount_at_risk:
            changes["amount_at_risk"] = finding.amount_at_risk
        if issue.status == IssueStatus.RESOLVED.value:
            decisions.append(Decision(SyncAction.REOPEN, finding.fingerprint, issue.id, changes))
        elif issue.status == IssueStatus.AWAITING_VERIFICATION.value:
            decisions.append(
                Decision(SyncAction.VERIFICATION_FAILED, finding.fingerprint, issue.id, changes)
            )
        else:
            decisions.append(Decision(SyncAction.UPDATE, finding.fingerprint, issue.id, changes))
    for fingerprint, issue in sorted(existing.items()):
        if fingerprint not in present and IssueStatus(issue.status) in OPEN_STATUSES:
            decisions.append(Decision(SyncAction.VERIFY_RESOLVED, fingerprint, issue.id))
    return decisions


MAX_LINK_GROUP: Final = 25
"""Issues sharing one key beyond this size are not pairwise linked (the key is too common)."""


def link_keys(subject: str) -> set[str]:
    """Keys that tie issues to one root cause: the subject itself, and the entry of a JE line."""
    keys = {subject}
    prefix, _, rest = subject.partition(":")
    if prefix == "jl" and rest.count(":") >= 1:
        keys.add("je:" + rest.rsplit(":", 1)[0])
    return keys


def root_cause_pairs(
    issues: Iterable[tuple[uuid.UUID, Iterable[str]]],
) -> dict[tuple[uuid.UUID, uuid.UUID], str]:
    """Issue pairs (smaller id first) sharing a subject or journal entry, with the shared key."""
    by_key: dict[str, set[uuid.UUID]] = {}
    for issue_id, subjects in issues:
        for subject in subjects:
            for key in link_keys(subject):
                by_key.setdefault(key, set()).add(issue_id)
    pairs: dict[tuple[uuid.UUID, uuid.UUID], str] = {}
    for key in sorted(by_key):
        members = sorted(by_key[key])
        if len(members) < 2 or len(members) > MAX_LINK_GROUP:
            continue
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pairs.setdefault((left, right), key)
    return pairs
