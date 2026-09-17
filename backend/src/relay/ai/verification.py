"""Provenance verification of findings (ai-safety.md §4.3). Deterministic; no model involved.

Checks per evidence item: cited steps exist and are tool results; record references and quoted
values appear in a cited result (numbers compared after normalizing their formatting). Per finding:
affected records appear in some tool result, and the suggested action names things that exist in
the investigated run. ``failed`` findings can never become change requests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, Protocol

from relay.ai.findings import Finding, FindingsSubmission

Status = Literal["verified", "partially_verified", "failed"]
_NUMBER: Final = re.compile(r"\(?-?[0-9][0-9,]*(?:\.[0-9]+)?\)?")


class ReferenceChecker(Protocol):
    """Existence checks against the investigated run, supplied by the server."""

    def issue_exists(self, key: str) -> bool: ...
    def record_exists(self, natural_key: str) -> bool: ...
    def account_exists(self, code: str, side: Literal["legacy", "target"]) -> bool: ...
    def party_exists(self, party_type: str, code: str) -> bool: ...
    def dataset_type_exists(self, dataset_type: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class FindingVerification:
    status: Status
    report: dict[str, Any]


def normalize_number(text: str) -> Decimal | None:
    cleaned = text.strip().replace(",", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return (-value if negative else value).normalize()


def _contains_ref(text: str, ref: str) -> bool:
    return re.search(rf"(?<![\w:.\-]){re.escape(ref)}(?![\w\-])", text) is not None


def _contains_value(text: str, value: str) -> bool:
    number = normalize_number(value)
    if number is None:
        return value in text
    return any(normalize_number(token) == number for token in _NUMBER.findall(text))


def _action_references_exist(finding: Finding, refs: ReferenceChecker) -> tuple[bool, str]:
    action = finding.suggested_action
    match action.type:
        case "change_account_mapping":
            ok = refs.account_exists(action.legacy_account, "legacy") and refs.account_exists(
                action.target_account, "target"
            )
            return ok, "accounts exist" if ok else "an account does not exist in the run"
        case "record_override":
            ok = refs.record_exists(action.natural_key)
            return ok, "record exists" if ok else f"{action.natural_key} is not in the run"
        case "entity_decision":
            missing = [m for m in action.members if not refs.party_exists(action.party_type, m)]
            return not missing, f"missing parties: {missing}" if missing else "parties exist"
        case "request_reimport":
            ok = refs.dataset_type_exists(action.dataset_type)
            return ok, "dataset exists" if ok else f"no {action.dataset_type} dataset"
        case "disposition":
            ok = refs.issue_exists(action.issue_key)
            return ok, "issue exists" if ok else f"{action.issue_key} does not exist"
        case _:
            return True, "no references"


def verify(
    submission: FindingsSubmission,
    tool_results: Mapping[int, str],
    refs: ReferenceChecker,
) -> list[FindingVerification]:
    """``tool_results`` maps step numbers of successful tool results to their full JSON."""
    everything = "\n".join(tool_results.values())
    verifications = []
    for finding in submission.findings:
        items = []
        for item in finding.evidence:
            problems = []
            cited = [tool_results[s] for s in item.step_seqs if s in tool_results]
            if len(cited) != len(item.step_seqs):
                problems.append("a cited step is not a successful tool result")
            text = "\n".join(cited)
            problems.extend(
                f"record {ref} not in the cited results"
                for ref in item.record_refs
                if not _contains_ref(text, ref)
            )
            problems.extend(
                f"value {quoted.value} ({quoted.label}) not in the cited results"
                for quoted in item.quoted_values
                if not _contains_value(text, quoted.value)
            )
            items.append({"claim": item.claim, "ok": not problems, "problems": problems})
        unknown_affected = [r for r in finding.affected_records if not _contains_ref(everything, r)]
        action_ok, action_note = _action_references_exist(finding, refs)
        passing = sum(1 for i in items if i["ok"])
        if passing == 0 or not action_ok:
            status: Status = "failed"
        elif passing == len(items) and not unknown_affected:
            status = "verified"
        else:
            status = "partially_verified"
        verifications.append(
            FindingVerification(
                status,
                {
                    "evidence": items,
                    "affected_records_not_returned": unknown_affected,
                    "suggested_action": {"ok": action_ok, "note": action_note},
                },
            )
        )
    return verifications
