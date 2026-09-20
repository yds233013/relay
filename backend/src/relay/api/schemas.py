"""API response models. Money is a decimal string plus a currency; business dates are YYYY-MM-DD."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from relay.core.currency import Currency
from relay.core.money import Money


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Page[T](Schema):
    items: list[T]
    next_cursor: str | None


def amount_text(value: Decimal | None, currency: Currency) -> str | None:
    return None if value is None else Money(value, currency).amount_str


class UserOut(Schema):
    id: uuid.UUID
    email: str
    display_name: str
    role: str


class MigrationOut(Schema):
    id: uuid.UUID
    name: str
    company_name: str
    status: str
    functional_currency: str
    opening_balance_date: date
    history_start_date: date
    cutover_date: date
    go_live_date: date
    bank_clearing_window_days: int


class DatasetOut(Schema):
    id: uuid.UUID
    dataset_type: str
    name: str
    as_of_date: date | None
    is_required: bool
    active_import_id: uuid.UUID | None
    version: int


class ImportOut(Schema):
    id: uuid.UUID
    dataset_id: uuid.UUID
    sequence: int
    original_filename: str
    status: str
    encoding: str | None
    delimiter: str | None
    header: list[str] | None
    row_count: int | None
    quarantined_count: int | None
    error: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class SourceRowOut(Schema):
    row_number: int
    line_start: int
    line_end: int
    values: dict[str, str]


class QuarantinedRowOut(Schema):
    id: uuid.UUID
    quarantine_key: str
    line_start: int
    line_end: int
    reason: str
    field_counts: list[int]
    raw_text: str


class FingerprintOut(Schema):
    fingerprint: str
    components: dict[str, Any]
    latest_run_id: uuid.UUID | None
    latest_run_is_current: bool


class RunOut(Schema):
    id: uuid.UUID
    sequence: int
    status: str
    trigger: str
    fingerprint: str
    result_fingerprint: str | None
    is_current: bool | None
    error: dict[str, Any] | None
    stage_timings: dict[str, Any]
    counts: dict[str, Any]
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RuleRunOut(Schema):
    rule_id: str
    rule_version: int
    title: str
    status: str
    exception_count: int
    missing_datasets: list[str]
    error: str | None = None


class LineageOut(Schema):
    import_id: uuid.UUID
    row_number: int
    line_start: int
    line_end: int


class ExceptionOut(Schema):
    id: uuid.UUID
    rule_id: str
    rule_version: int
    fingerprint: str
    severity: str
    nature: str
    category: str
    subjects: list[str]
    message: str
    expected: Any
    observed: Any
    amount_at_risk: str | None
    currency: str
    details: dict[str, Any]
    lineage: list[LineageOut]


class ReconciliationResultOut(Schema):
    id: uuid.UUID
    recon_id: str
    recon_version: int
    title: str
    purpose: str
    status: str
    applicable: bool
    left_label: str
    right_label: str
    tolerance: str
    line_count: int
    discrepancy_count: int
    note: str


class ReconcilingItemOut(Schema):
    classification: str
    amount: str
    record_keys: list[str]
    message: str


class ReconciliationLineOut(Schema):
    id: uuid.UUID
    grain_key: str
    grain: dict[str, str]
    left_amount: str
    right_amount: str
    difference: str
    explained_amount: str
    unexplained_amount: str
    status: str
    extra: dict[str, Any]
    currency: str
    items: list[ReconcilingItemOut]


class CandidateOut(Schema):
    id: uuid.UUID
    party_type: str
    left_code: str
    right_code: str
    score: str
    strong: bool
    status: str
    features: dict[str, Any]


class EvidenceLinkOut(Schema):
    kind: str
    """issue, reconciliation_line, entity_candidate or text."""
    label: str
    issue_id: uuid.UUID | None = None
    line_id: uuid.UUID | None = None


class GateOut(Schema):
    gate_id: str
    title: str
    status: str
    observed: str
    threshold: str
    summary: str
    evidence: list[str]
    evidence_links: list[EvidenceLinkOut]
    waiver_id: str | None
    waivable: bool = False
    scope: dict[str, str] | None = None


class PolicyOut(Schema):
    version: int
    policy: dict[str, Any]
    change_request_id: uuid.UUID | None
    created_at: datetime


class WaiverOut(Schema):
    id: uuid.UUID
    gate_id: str
    status: str
    reason: str
    scope: dict[str, str]
    run_id: uuid.UUID
    change_request_id: uuid.UUID
    created_at: datetime


class SignoffOut(Schema):
    id: uuid.UUID
    run_id: uuid.UUID
    run_fingerprint: str
    status: str
    change_request_id: uuid.UUID
    invalidated_by_fingerprint: str | None
    created_at: datetime


class ReadinessOut(Schema):
    run_id: uuid.UUID | None
    run_sequence: int | None = None
    run_fingerprint: str | None = None
    current_fingerprint: str | None = None
    run_is_current: bool
    overall: str
    unresolved_exposure: str | None
    currency: str
    gates: list[GateOut]
    migration_status: str = ""
    evaluation_sequence: int | None = None
    evaluated_at: datetime | None = None
    waivers: list[WaiverOut] = []
    signoffs: list[SignoffOut] = []


class IssueOut(Schema):
    id: uuid.UUID
    key: str
    fingerprint: str | None
    source: str
    rule_or_recon_id: str | None
    category: str
    nature: str
    severity: str
    title: str
    subjects: list[str]
    status: str
    owner_user_id: uuid.UUID | None
    owner_name: str | None = None
    amount_at_risk: str | None
    currency: str
    first_seen_run_id: uuid.UUID | None
    last_seen_run_id: uuid.UUID | None
    verified_absent_run_id: uuid.UUID | None
    version: int


class IssueDetailOut(IssueOut):
    latest_exception: ExceptionOut | None


class AuditEventOut(Schema):
    id: uuid.UUID
    migration_seq: int
    occurred_at: datetime
    actor_type: str
    actor_user_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    change_request_id: uuid.UUID | None
    request_id: str | None
    hash: str


class ChainVerificationOut(Schema):
    valid: bool
    events_checked: int
    first_broken_seq: int | None
    problem: str | None


class RuleCatalogOut(Schema):
    rule_id: str
    version: int
    title: str
    severity: str
    nature: str
    category: str
    requires: list[str]


class RecordOut(Schema):
    run_id: uuid.UUID
    record: dict[str, Any]
    data: dict[str, Any]
    source_row: SourceRowOut | None
    source_header: list[str] | None
    """Column order of the source file (row values are an unordered mapping)."""
    related_issues: list[IssueOut]
    """Issues naming this record, with their keys: a person cites BWP-41, never a UUID."""


class MigrationSummaryOut(MigrationOut):
    overall: str
    failing_gate_count: int | None
    gate_count: int | None
    unresolved_exposure: str | None
    days_to_go_live: int


class BlockerOut(Schema):
    gate_id: str
    title: str
    summary: str
    observed: str
    evidence_count: int
    evidence: list[EvidenceLinkOut]


class StageOut(Schema):
    stage: str
    status: str
    detail: str


class ChangeRequestSummaryOut(Schema):
    id: uuid.UUID
    key: str
    kind: str
    title: str
    status: str


class AmountByNatureOut(Schema):
    nature: str
    amount: str


class WorkItemOut(Schema):
    """One decision waiting on a person, with the evidence that produced it."""

    key: str
    kind: str
    title: str
    summary: str
    judgement: str | None
    amount: str | None
    currency: str
    count: int
    action_label: str
    target_kind: str
    target_id: str | None
    issue_id: uuid.UUID | None = None
    """The finding an AI investigation of this item would be about, when one exists."""
    issue_key: str | None = None
    investigation: dict[str, Any] | None = None
    """Latest investigation of that finding: id, status, finding_count. Null when never run."""
    blocks: list[str]
    detail: dict[str, Any]


class AutomationSummaryOut(Schema):
    """What the last verification run did, counted from what it stored."""

    run_sequence: int | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    staged_records: int | None = None
    controls_evaluated: int | None = None
    controls_errored: int | None = None
    reconciliations_performed: int | None = None
    reconciliations_with_differences: int | None = None
    findings: int | None = None
    entity_candidates: int | None = None
    issues_created: int | None = None
    issues_resolved: int | None = None


class WorkQueueOut(Schema):
    items: list[WorkItemOut]
    automation: AutomationSummaryOut


class OverviewOut(Schema):
    migration: MigrationOut
    run_id: uuid.UUID | None
    run_sequence: int | None
    run_is_current: bool
    overall: str
    gate_count: int
    failing_gate_count: int
    blockers: list[BlockerOut]
    unresolved_exposure: str | None
    open_issue_count: int
    open_issue_amounts_by_nature: list[AmountByNatureOut]
    top_issues: list[IssueOut]
    my_issues: list[IssueOut]
    my_approvals: list[ChangeRequestSummaryOut]
    stages: list[StageOut]
    recent_activity: list[AuditEventOut]
    currency: str
    work_items: list[WorkItemOut] = []
    """The decisions waiting on a person, most consequential first."""
    automation: AutomationSummaryOut = AutomationSummaryOut()
    """What the latest verification did without anyone asking."""


class FindingChangeOut(Schema):
    fingerprint: str
    rule_id: str
    message: str


class StatusChangeOut(Schema):
    key: str
    before: str | None
    after: str | None


class RunDiffOut(Schema):
    base_run_id: uuid.UUID
    other_run_id: uuid.UUID
    changed_fingerprint_components: list[str]
    findings_added: list[FindingChangeOut]
    findings_removed: list[FindingChangeOut]
    reconciliation_changes: list[StatusChangeOut]
    gate_changes: list[StatusChangeOut]
    entity_candidates_before: int
    entity_candidates_after: int


class StagedRecordOut(Schema):
    natural_key: str
    record_type: str
    account_code: str | None
    party_code: str | None
    document_number: str | None
    entry_number: str | None
    record_date: date | None
    posting_period: str | None
    functional_amount: str | None
    lineage: LineageOut | None
    role: str | None = None
    counted_by_entry_date: bool | None = None
    counted_by_posting_period: bool | None = None
    open_amount: str | None = None


class DocumentComparisonOut(Schema):
    document: str
    status: str
    left_amount: str
    right_amount: str
    difference: str
    left_records: list[StagedRecordOut]
    right_records: list[StagedRecordOut]


class QuarantineRefOut(Schema):
    import_id: uuid.UUID
    line_start: int
    line_end: int
    reason: str


class DrilldownItemOut(Schema):
    classification: str
    amount: str
    message: str
    records: list[StagedRecordOut]


class OpeningSummaryOut(Schema):
    opening_control_balance: str
    opening_aging_total: str
    opening_unassigned: str


class DrilldownOut(Schema):
    """Contributors to one reconciliation line. Which sections are present depends on ``basis``."""

    recon_id: str
    grain: dict[str, str]
    left_amount: str
    right_amount: str
    difference: str
    unexplained_amount: str
    status: str
    currency: str
    run_id: uuid.UUID
    basis: str
    """documents (R3/R4 families), accounts (R1/R2), reconciling_items (R5) or periods (R6)."""
    limits: str | None = None
    left_label: str | None = None
    right_label: str | None = None
    accounts: list[str] = []
    documents: list[DocumentComparisonOut] = []
    matched_document_count: int | None = None
    opening: OpeningSummaryOut | None = None
    control_balances: list[StagedRecordOut] = []
    detail_line_count: int | None = None
    detail_total: str | None = None
    date_period_disagreements: list[StagedRecordOut] = []
    quarantined_rows: list[QuarantineRefOut] = []
    items: list[DrilldownItemOut] = []
    extra: dict[str, Any] = {}


# ---------------------------------------------------------------------------------- governance
class CanonicalFieldOut(Schema):
    name: str
    kind: str
    required: bool
    values: list[str]


class FieldSuggestionOut(Schema):
    field: str
    kind: str
    required: bool
    specification: dict[str, Any] | None
    basis: str | None
    notes: list[str]


class ColumnMappingSuggestionOut(Schema):
    dataset_id: uuid.UUID
    dataset_type: str
    import_id: uuid.UUID
    header: list[str]
    fields: list[FieldSuggestionOut]
    unmatched_columns: list[str]
    canonical_fields: list[CanonicalFieldOut]


class ColumnMappingOut(Schema):
    target_field: str
    specification: dict[str, Any]
    required: bool
    basis: str


class ColumnMappingSetOut(Schema):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version: int
    status: str
    based_on_import_id: uuid.UUID | None
    change_request_id: uuid.UUID | None
    created_at: datetime
    exclude_rows_where_blank: list[str]
    mappings: list[ColumnMappingOut]
    missing_required_fields: list[str]


class MappingConfigIn(Schema):
    fields: dict[str, dict[str, Any]]
    exclude_rows_where_blank: list[str] = []


class PreviewRowOut(Schema):
    row_number: int
    values: dict[str, str | None]
    errors: dict[str, str]
    excluded: bool


class ColumnMappingPreviewOut(Schema):
    import_id: uuid.UUID
    rows: list[PreviewRowOut]
    missing_required_fields: list[str]
    unknown_fields: list[str]


class SignalsOut(Schema):
    target_exists: bool
    type_compatible: bool | None
    subtype_compatible: bool | None


class AccountProposalOut(Schema):
    target: str
    basis: str
    score: str | None
    signals: SignalsOut


class AccountMappingRowOut(Schema):
    legacy_account_code: str
    legacy_name: str | None
    legacy_subtype: str | None
    target_account_code: str | None
    target_name: str | None
    target_subtype: str | None
    signals: SignalsOut | None
    proposal: AccountProposalOut | None
    basis: str | None = None
    rationale: str | None = None


class AccountMappingSetOut(Schema):
    id: uuid.UUID
    version: int
    status: str
    based_on_set_id: uuid.UUID | None
    based_on_import_id: uuid.UUID | None
    change_request_id: uuid.UUID | None
    created_at: datetime
    entry_count: int


class AccountMappingOverviewOut(Schema):
    approved_set: AccountMappingSetOut | None
    source: str
    """``approved_set`` or ``account_mapping_file``: where the mapping in effect comes from."""
    rows: list[AccountMappingRowOut]
    sets: list[AccountMappingSetOut]


class AccountMappingSetDetailOut(Schema):
    mapping_set: AccountMappingSetOut
    rows: list[AccountMappingRowOut]


class AccountMappingChangeIn(Schema):
    legacy: str
    target: str | None
    rationale: str | None = None


class AccountMappingDraftIn(Schema):
    base: str
    changes: list[AccountMappingChangeIn]


class FieldOverrideIn(Schema):
    run_id: uuid.UUID
    natural_key: str
    field: str
    new_value: str


class QuarantineRepairIn(Schema):
    exception_id: uuid.UUID
    replacement_text: str


class ChangeRequestIn(Schema):
    kind: str
    title: str
    payload: dict[str, Any] | None = None
    field_override: FieldOverrideIn | None = None
    quarantine_repair: QuarantineRepairIn | None = None
    evidence_refs: list[dict[str, Annotated[str, Field(max_length=500)]]] = Field(
        default_factory=list, max_length=20
    )


class ChangeRequestUpdateIn(Schema):
    version: int
    title: str | None = None
    payload: dict[str, Any] | None = None


class JustificationIn(Schema):
    justification: str


class ReviewIn(Schema):
    comment: str = ""


class WithdrawIn(Schema):
    reason: str = ""


class RequirementOut(Schema):
    index: int
    role: str
    satisfied_by: str | None


class ApprovalOut(Schema):
    reviewer_user_id: uuid.UUID
    reviewer_name: str
    role: str
    decision: str
    comment: str
    decided_at: datetime


class ReviewerOut(Schema):
    can_review: bool
    reason: str
    is_requester: bool


class ChangeRequestOut(Schema):
    id: uuid.UUID
    migration_id: uuid.UUID
    key: str
    kind: str
    status: str
    title: str
    justification: str
    origin: str
    origin_finding_id: uuid.UUID | None = None
    requested_by: uuid.UUID
    requested_by_name: str
    created_at: datetime
    submitted_at: datetime | None
    decided_at: datetime | None
    applied_at: datetime | None
    version: int
    approvals_required: int
    approvals_given: int


class ChangeRequestDetailOut(Schema):
    change_request: ChangeRequestOut
    payload: dict[str, Any]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    impact: dict[str, Any] | None
    evidence_refs: list[Any]
    base_entity_versions: dict[str, Any]
    requirements: list[RequirementOut]
    approvals: list[ApprovalOut]
    viewer: ReviewerOut
    runs: list[uuid.UUID]
    history: list[AuditEventOut]


class ReviewOutcomeOut(Schema):
    change_request: ChangeRequestOut
    run_id: uuid.UUID | None
    """The pipeline run requested because the change was applied, if any."""


class RecordOverrideOut(Schema):
    id: uuid.UUID
    natural_key: str
    dataset_type: str
    target: str
    field: str | None
    expected_current_value: Any
    new_value: Any
    reason: str
    status: str
    change_request_id: uuid.UUID
    reverted_by_cr_id: uuid.UUID | None
    created_at: datetime


# -------------------------------------------------------------------------- issues workflow
class IssueUpdateIn(Schema):
    version: int
    owner_user_id: uuid.UUID | None = None
    clear_owner: bool = False
    status: str | None = Field(default=None, max_length=32)
    note: str = Field(default="", max_length=2000)


class ManualIssueIn(Schema):
    title: str = Field(min_length=1, max_length=300)
    severity: Literal["critical", "high", "medium", "low"]
    category: Literal[
        "completeness", "mapping", "ledger_integrity", "subledger", "cash", "master_data",
        "currency", "dates", "ai_safety", "other",
    ]  # fmt: skip
    nature: Literal["migration_defect", "source_anomaly"]
    description: str = Field(default="", max_length=10_000)


class CommentIn(Schema):
    body: str = Field(min_length=1, max_length=10_000)


class CommentOut(Schema):
    id: uuid.UUID
    author_user_id: uuid.UUID
    author_name: str
    body: str
    created_at: datetime


class IssueLinkOut(Schema):
    id: uuid.UUID
    link_type: str
    other_issue_id: uuid.UUID
    other_issue_key: str
    other_issue_title: str
    other_issue_status: str
    created_by_actor_type: str
    reason: str


class EntityDecisionOut(Schema):
    id: uuid.UUID
    party_type: str
    decision: str
    members: list[str]
    survivor: str | None
    reason: str
    status: str
    change_request_id: uuid.UUID
    reverted_by_cr_id: uuid.UUID | None
    created_at: datetime


class DispositionOut(Schema):
    id: uuid.UUID
    issue_id: uuid.UUID
    issue_key: str
    kind: str
    amount: str | None
    currency: str | None
    follow_up: str
    follow_up_owner_id: uuid.UUID | None
    reason: str
    status: str
    change_request_id: uuid.UUID
    reverted_by_cr_id: uuid.UUID | None
    created_at: datetime


class PartyOut(Schema):
    natural_key: str
    code: str
    data: dict[str, Any]
    open_documents: int


class CandidateDetailOut(Schema):
    candidate: CandidateOut
    run_id: uuid.UUID
    parties: list[PartyOut]
    decisions: list[EntityDecisionOut]


# ---------------------------------------------------------------------------- migration setup
class CompanyIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str = Field(min_length=1, max_length=200)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    functional_currency: str = Field(pattern=r"^[A-Z]{3}$")
    fiscal_year_start_month: int = Field(ge=1, le=12)


class MigrationIn(Schema):
    company: CompanyIn
    name: str = Field(min_length=1, max_length=200)
    issue_key_prefix: str = Field(pattern=r"^[A-Z]{2,6}$")
    opening_balance_date: date
    history_start_date: date
    cutover_date: date
    go_live_date: date
    bank_clearing_window_days: int = Field(default=15, ge=0, le=90)


class SourceSystemIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["legacy_erp", "spreadsheet", "bank", "billing", "crm", "other"]
    description: str = Field(default="", max_length=2000)


class SourceSystemOut(Schema):
    id: uuid.UUID
    name: str
    kind: str
    description: str


class DatasetIn(Schema):
    source_system_id: uuid.UUID
    dataset_type: str = Field(max_length=32)
    name: str = Field(min_length=1, max_length=200)
    as_of_date: date | None = None
    is_required: bool = True
    bank_account: str | None = Field(default=None, min_length=1, max_length=64)
    gl_account: str | None = Field(default=None, min_length=1, max_length=64)


# ---------------------------------------------------------------------------------------- AI
class AIStatusOut(Schema):
    provider: str
    configured: bool
    migration_enabled: bool
    available: bool


class InvestigationIn(Schema):
    question: str = Field(min_length=1, max_length=2_000)
    issue_id: uuid.UUID | None = None


class InvestigationOut(Schema):
    id: uuid.UUID
    migration_id: uuid.UUID
    issue_id: uuid.UUID | None
    run_id: uuid.UUID
    question: str
    status: str
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    tool_call_count: int
    created_at: datetime
    finished_at: datetime | None
    error: dict[str, Any] | None


class InvestigationStepOut(Schema):
    seq: int
    type: str
    tool_name: str | None
    arguments: dict[str, Any] | None
    result: str | None
    truncated: bool
    is_error: bool
    text: str
    latency_ms: int


class FindingOut(Schema):
    id: uuid.UUID
    hypothesis: str
    evidence: list[dict[str, Any]]
    affected_record_refs: list[str]
    confidence: str
    suggested_action: dict[str, Any]
    open_questions: list[str]
    requires_approval: bool
    verification_status: str
    verification_report: dict[str, Any]
    review_status: str
    review_comment: str
    drafted_change_request_id: uuid.UUID | None
    draftable: bool = Field(description="Whether a change request can be drafted from it now.")


class InvestigationDetailOut(Schema):
    investigation: InvestigationOut
    steps: list[InvestigationStepOut]
    findings: list[FindingOut]


class FindingReviewIn(Schema):
    comment: str = Field(default="", max_length=2_000)
