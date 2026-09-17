"""API response models. Money is a decimal string plus a currency; business dates are YYYY-MM-DD."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

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


class ReadinessOut(Schema):
    run_id: uuid.UUID | None
    run_is_current: bool
    overall: str
    unresolved_exposure: str | None
    currency: str
    gates: list[GateOut]


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
    related_issue_ids: list[uuid.UUID]


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
