"""Change request policy: required approvals and reviewer eligibility (governance.md §2.3). Pure."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from relay.changes.models import ChangeRequestKind
from relay.identity.models import Role

LEAD = Role.IMPLEMENTATION_LEAD.value
CONTROLLER = Role.CUSTOMER_CONTROLLER.value
CONTROLLER_AMOUNT_THRESHOLD: Final = Decimal("10000.00")
"""Record overrides touching at least this functional amount also need the customer controller."""
ACCOUNTING_FIELDS: Final = frozenset(
    {"entry_date", "posting_period", "account_code", "functional_amount", "amount", "balance"}
)
"""Date, period, account and amount fields: overriding one always needs the customer controller."""

_DEFAULT_APPROVALS: dict[ChangeRequestKind, tuple[str, ...]] = {
    ChangeRequestKind.COLUMN_MAPPING_SET: (LEAD,),
    ChangeRequestKind.ACCOUNT_MAPPING_SET: (LEAD, CONTROLLER),
    ChangeRequestKind.ENTITY_DECISION: (LEAD,),
    ChangeRequestKind.POLICY_CHANGE: (LEAD, CONTROLLER),
    ChangeRequestKind.GATE_WAIVER: (LEAD, CONTROLLER),
    ChangeRequestKind.READINESS_SIGNOFF: (LEAD, CONTROLLER),
}


def required_approvals(kind: ChangeRequestKind) -> list[dict[str, str]]:
    """Required approvals for kinds whose requirements do not depend on the payload."""
    roles = _DEFAULT_APPROVALS.get(kind)
    if roles is None:
        raise NotImplementedError(f"approval policy for {kind.value} depends on its payload")
    return [{"role": role} for role in roles]


def record_override_approvals(
    *, field: str | None, restores_row: bool, impact: Decimal | None
) -> list[dict[str, str]]:
    """Lead; plus controller for accounting fields, restored rows, or |impact| ≥ threshold.

    A quarantined row repair restores a whole source line, including its amount, so it is treated
    as an amount change regardless of size.
    """
    roles = [LEAD]
    if (
        restores_row
        or (field is not None and field in ACCOUNTING_FIELDS)
        or (impact is not None and abs(impact) >= CONTROLLER_AMOUNT_THRESHOLD)
    ):
        roles.append(CONTROLLER)
    return [{"role": role} for role in roles]


CONTROLLER_DISPOSITIONS: Final = frozenset({"accepted_risk", "carry_forward_adjustment"})
BLOCKING_SEVERITIES: Final = frozenset({"critical", "high"})


def disposition_approvals(*, kind: str, severity: str) -> list[dict[str, str]]:
    """Controller for accepted risk and carry-forward adjustments, and for any disposition of a
    critical or high finding; the lead for low and medium false positives and not-applicable.

    governance.md §2.3 lists ``not_applicable`` under the lead without a severity; applying the
    controller requirement to critical and high findings is the conservative reading (0007).
    """
    if kind in CONTROLLER_DISPOSITIONS or severity in BLOCKING_SEVERITIES:
        return [{"role": CONTROLLER}]
    return [{"role": LEAD}]


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
