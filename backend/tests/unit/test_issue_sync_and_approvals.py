"""Pure lifecycle and approval policy: issue synchronization (governance §1.1) and GV-02."""

from __future__ import annotations

import uuid
from decimal import Decimal

from relay.changes.domain import (
    RecordedApproval,
    disposition_approvals,
    eligibility,
    fully_approved,
    required_approvals,
)
from relay.changes.models import ChangeRequestKind
from relay.issues.domain import (
    MAX_LINK_GROUP,
    Decision,
    ExistingIssue,
    Finding,
    SyncAction,
    root_cause_pairs,
    synchronize,
)


def _finding(fingerprint: str, severity: str = "high", amount: str | None = "10.00") -> Finding:
    return Finding(fingerprint, "R", severity, Decimal(amount) if amount else None)


def _issue(
    fingerprint: str, status: str, severity: str = "high", amount: str | None = "10.00"
) -> ExistingIssue:
    return ExistingIssue(
        uuid.uuid4(), fingerprint, status, severity, Decimal(amount) if amount else None
    )


def _actions(decisions: list[Decision]) -> dict[str, SyncAction]:
    return {d.fingerprint: d.action for d in decisions}


def test_new_findings_create_issues_and_absent_open_issues_are_verified_resolved() -> None:
    existing = {
        "b": _issue("b", "open"),
        "c": _issue("c", "in_progress"),
        "d": _issue("d", "awaiting_verification"),
    }
    decisions = synchronize([_finding("a"), _finding("b")], existing)
    assert _actions(decisions) == {
        "a": SyncAction.CREATE,
        "b": SyncAction.UPDATE,
        "c": SyncAction.VERIFY_RESOLVED,
        "d": SyncAction.VERIFY_RESOLVED,
    }


def test_regressions_reopen_resolved_issues() -> None:
    decisions = synchronize([_finding("a")], {"a": _issue("a", "resolved")})
    assert _actions(decisions) == {"a": SyncAction.REOPEN}


def test_dispositioned_and_closed_issues_are_never_auto_resolved() -> None:
    decisions = synchronize(
        [],
        {
            "a": _issue("a", "dispositioned"),
            "b": _issue("b", "closed"),
            "c": _issue("c", "resolved"),
        },
    )
    assert decisions == []


def test_severity_and_amount_changes_are_reported() -> None:
    [decision] = synchronize([_finding("a", "critical", "12.00")], {"a": _issue("a", "open")})
    assert decision.changes == {"severity": "critical", "amount_at_risk": Decimal("12.00")}


def test_requesters_can_never_review_their_own_change() -> None:
    requester = uuid.uuid4()
    requirements = required_approvals(ChangeRequestKind.ACCOUNT_MAPPING_SET)
    check = eligibility(
        requirements=requirements,
        approvals=[],
        requested_by=requester,
        reviewer_id=requester,
        reviewer_role="implementation_lead",
    )
    assert not check.allowed


def test_each_requirement_needs_a_distinct_eligible_reviewer() -> None:
    requester, lead, other_lead, controller = (uuid.uuid4() for _ in range(4))
    requirements = required_approvals(ChangeRequestKind.ACCOUNT_MAPPING_SET)
    first = eligibility(
        requirements=requirements,
        approvals=[],
        requested_by=requester,
        reviewer_id=lead,
        reviewer_role="implementation_lead",
    )
    assert first.allowed
    assert first.requirement_index == 0
    approvals = [RecordedApproval(lead, 0, "approve")]
    assert not fully_approved(requirements, approvals)
    assert not eligibility(
        requirements=requirements,
        approvals=approvals,
        requested_by=requester,
        reviewer_id=lead,
        reviewer_role="customer_controller",
    ).allowed
    assert not eligibility(
        requirements=requirements,
        approvals=approvals,
        requested_by=requester,
        reviewer_id=other_lead,
        reviewer_role="implementation_lead",
    ).allowed
    second = eligibility(
        requirements=requirements,
        approvals=approvals,
        requested_by=requester,
        reviewer_id=controller,
        reviewer_role="customer_controller",
    )
    assert second.allowed
    assert fully_approved(requirements, [*approvals, RecordedApproval(controller, 1, "approve")])


def test_viewer_and_specialist_roles_satisfy_no_requirement() -> None:
    requirements = required_approvals(ChangeRequestKind.COLUMN_MAPPING_SET)
    for role in ("viewer", "implementation_specialist", "admin"):
        check = eligibility(
            requirements=requirements,
            approvals=[],
            requested_by=uuid.uuid4(),
            reviewer_id=uuid.uuid4(),
            reviewer_role=role,
        )
        assert not check.allowed


def test_a_finding_still_reported_after_an_applied_fix_fails_verification() -> None:
    decisions = synchronize([_finding("a")], {"a": _issue("a", "awaiting_verification")})
    assert _actions(decisions) == {"a": SyncAction.VERIFICATION_FAILED}


def test_root_cause_pairs_link_shared_subjects_and_journal_entries() -> None:
    a, b, c, d = sorted(uuid.uuid4() for _ in range(4))
    pairs = root_cause_pairs(
        [
            (a, ["je:JE-1"]),
            (b, ["jl:JE-1:3"]),
            (c, ["acct:legacy:6999"]),
            (d, ["recon:R1:account=6999,period_end=2026-01-31"]),
        ]
    )
    assert pairs == {(a, b): "je:JE-1"}
    crowd = [(uuid.uuid4(), ["tb:1000:2026-01"]) for _ in range(MAX_LINK_GROUP + 1)]
    assert root_cause_pairs(crowd) == {}


def test_disposition_approvals_follow_kind_and_severity() -> None:
    assert disposition_approvals(kind="not_applicable", severity="low") == [
        {"role": "implementation_lead"}
    ]
    assert disposition_approvals(kind="false_positive", severity="medium") == [
        {"role": "implementation_lead"}
    ]
    for kind, severity in (
        ("carry_forward_adjustment", "medium"),
        ("accepted_risk", "low"),
        ("false_positive", "high"),
        ("not_applicable", "critical"),
    ):
        assert disposition_approvals(kind=kind, severity=severity) == [
            {"role": "customer_controller"}
        ], (kind, severity)
