"""Change request policy: required approvals and reviewer eligibility (governance.md §2.3). Pure."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from relay.changes.models import ChangeRequestKind
from relay.identity.models import Role

LEAD = Role.IMPLEMENTATION_LEAD.value
CONTROLLER = Role.CUSTOMER_CONTROLLER.value

_DEFAULT_APPROVALS: dict[ChangeRequestKind, tuple[str, ...]] = {
    ChangeRequestKind.COLUMN_MAPPING_SET: (LEAD,),
    ChangeRequestKind.ACCOUNT_MAPPING_SET: (LEAD, CONTROLLER),
    ChangeRequestKind.ENTITY_DECISION: (LEAD,),
    ChangeRequestKind.POLICY_CHANGE: (LEAD, CONTROLLER),
    ChangeRequestKind.GATE_WAIVER: (LEAD, CONTROLLER),
    ChangeRequestKind.READINESS_SIGNOFF: (LEAD, CONTROLLER),
}


def required_approvals(kind: ChangeRequestKind) -> list[dict[str, str]]:
    """Required approvals for a kind.

    Kinds whose requirements depend on the payload (overrides, dispositions) arrive in M5 and M6.
    """
    roles = _DEFAULT_APPROVALS.get(kind)
    if roles is None:
        raise NotImplementedError(f"approval policy for {kind.value} is not implemented yet")
    return [{"role": role} for role in roles]


@dataclass(frozen=True, slots=True)
class RecordedApproval:
    reviewer_user_id: uuid.UUID
    requirement_index: int | None
    decision: str


@dataclass(frozen=True, slots=True)
class Eligibility:
    allowed: bool
    requirement_index: int | None
    reason: str = ""


def eligibility(
    *,
    requirements: Sequence[dict[str, str]],
    approvals: Sequence[RecordedApproval],
    requested_by: uuid.UUID,
    reviewer_id: uuid.UUID,
    reviewer_role: str,
) -> Eligibility:
    """GV-02: never the requester; one decision per reviewer; must satisfy an unmet requirement."""
    if reviewer_id == requested_by:
        return Eligibility(False, None, "requesters cannot review their own change request")
    if any(a.reviewer_user_id == reviewer_id for a in approvals):
        return Eligibility(False, None, "this reviewer has already decided")
    satisfied = {a.requirement_index for a in approvals if a.decision == "approve"}
    for index, requirement in enumerate(requirements):
        if index not in satisfied and requirement["role"] == reviewer_role:
            return Eligibility(True, index)
    return Eligibility(False, None, "the reviewer's role satisfies no outstanding requirement")


def fully_approved(
    requirements: Sequence[dict[str, str]], approvals: Sequence[RecordedApproval]
) -> bool:
    satisfied = {a.requirement_index for a in approvals if a.decision == "approve"}
    return all(index in satisfied for index in range(len(requirements)))
