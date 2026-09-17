"""Which AI findings can become draft change requests (ai-safety.md §4.4). No database needed."""

from __future__ import annotations

from typing import Any

import pytest

from relay.ai.findings import requires_approval
from relay.investigations.models import Finding
from relay.investigations.service import promotion_problem


def _finding(
    action: dict[str, Any], verification: str = "verified", review: str = "proposed"
) -> Finding:
    return Finding(
        suggested_action=action,
        requires_approval=requires_approval(str(action["type"])),
        verification_status=verification,
        review_status=review,
    )


MAPPING = {"type": "change_account_mapping", "legacy_account": "1", "target_account": "2"}


def test_a_verified_change_suggestion_is_promotable() -> None:
    assert promotion_problem(_finding(MAPPING)) is None
    assert promotion_problem(_finding(MAPPING, verification="partially_verified")) is None


@pytest.mark.parametrize(
    ("finding", "reason"),
    [
        (_finding(MAPPING, verification="failed"), "failed verification"),
        (_finding(MAPPING, review="dismissed"), "dismissed"),
        (_finding({"type": "no_action"}), "suggests no change"),
        (_finding({"type": "investigate_further", "what": "x"}), "suggests no change"),
        (
            _finding({"type": "request_reimport", "dataset_type": "invoices"}),
            "carried out by people",
        ),
    ],
)
def test_other_findings_are_not_promotable(finding: Finding, reason: str) -> None:
    problem = promotion_problem(finding)
    assert problem is not None
    assert reason in problem
