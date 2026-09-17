"""Finding schema submitted by the investigator (ai-safety.md §4.2)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=300)]
Key = Annotated[str, Field(min_length=1, max_length=200)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class QuotedValue(_Strict):
    label: Annotated[str, Field(min_length=1, max_length=80)]
    value: Annotated[str, Field(min_length=1, max_length=120)]


class EvidenceItem(_Strict):
    claim: Text
    step_seqs: list[int] = Field(min_length=1, max_length=20)
    record_refs: list[Key] = Field(default_factory=list, max_length=50)
    quoted_values: list[QuotedValue] = Field(default_factory=list, max_length=20)


class ChangeAccountMapping(_Strict):
    type: Literal["change_account_mapping"]
    legacy_account: Key
    target_account: Key


class RecordOverrideAction(_Strict):
    type: Literal["record_override"]
    natural_key: Key
    field: Literal["entry_date", "posting_period", "quarantined_row_repair"]
    new_value: Annotated[str, Field(default="", max_length=2000)] = ""


class EntityDecisionAction(_Strict):
    type: Literal["entity_decision"]
    party_type: Literal["customer", "vendor"]
    decision: Literal["same_entity", "distinct"]
    members: list[Key] = Field(min_length=2, max_length=10)
    survivor: Key | None = None


class RequestReimport(_Strict):
    type: Literal["request_reimport"]
    dataset_type: Key
    reason: Text


class DispositionAction(_Strict):
    type: Literal["disposition"]
    issue_key: Key
    kind: Literal["carry_forward_adjustment", "accepted_risk", "false_positive", "not_applicable"]
    amount: Annotated[str, Field(max_length=40)] | None = None


class InvestigateFurther(_Strict):
    type: Literal["investigate_further"]
    what: Text


class NoAction(_Strict):
    type: Literal["no_action"]
    reason: Text


SuggestedAction = Annotated[
    ChangeAccountMapping | RecordOverrideAction | EntityDecisionAction | RequestReimport
    | DispositionAction | InvestigateFurther | NoAction,
    Field(discriminator="type"),
]  # fmt: skip

NO_APPROVAL_ACTIONS = frozenset({"investigate_further", "no_action"})


class Finding(_Strict):
    hypothesis: Annotated[str, Field(min_length=1, max_length=600)]
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=10)
    affected_records: list[Key] = Field(default_factory=list, max_length=50)
    confidence: Literal["low", "medium", "high"]
    suggested_action: SuggestedAction
    open_questions: list[Text] = Field(default_factory=list, max_length=5)


class FindingsSubmission(_Strict):
    findings: list[Finding] = Field(min_length=1, max_length=5)


def requires_approval(action_type: str) -> bool:
    """Server policy, never the model's opinion (ai-safety.md §4.3)."""
    return action_type not in NO_APPROVAL_ACTIONS
