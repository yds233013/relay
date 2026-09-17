"""Query side for runs, findings, reconciliations, drill-downs, records and candidates.

Drill-downs are computed in SQL over the run's staged records, following the reconciliation
definitions (docs/validation-and-reconciliation.md Part B): every amount shown traces to staged
records, and every staged record traces to a source row (import, row number, physical lines).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from relay.core.errors import NotFoundError
from relay.imports.models import QuarantinedRow
from relay.issues.models import Issue, IssueOccurrence
from relay.pipeline.models import (
    EntityCandidateRow,
    GateResultRow,
    PipelineRun,
    ReadinessEvaluationRow,
    ReconciliationLineRow,
    ReconciliationResultRow,
    ReconcilingItemRow,
    RuleExceptionRow,
    RuleRun,
    RunStatus,
    StagedRecord,
)
from relay.workspace.models import Migration

_RECEIVABLE = "accounts_receivable"
_PAYABLE = "accounts_payable"


ResourceNotFoundError = NotFoundError


def get_run(session: Session, run_id: uuid.UUID) -> PipelineRun:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise ResourceNotFoundError("pipeline run not found")
    return run


def runs_for(session: Session, migration_id: uuid.UUID, limit: int) -> list[PipelineRun]:
    return list(
        session.scalars(
            select(PipelineRun)
            .where(PipelineRun.migration_id == migration_id)
            .order_by(PipelineRun.sequence.desc())
            .limit(limit)
        )
    )


def latest_succeeded_run(session: Session, migration_id: uuid.UUID) -> PipelineRun | None:
    return session.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.migration_id == migration_id,
            PipelineRun.status == RunStatus.SUCCEEDED.value,
        )
        .order_by(PipelineRun.sequence.desc())
        .limit(1)
    ).first()


def rule_runs(session: Session, run_id: uuid.UUID) -> list[RuleRun]:
    return list(
        session.scalars(select(RuleRun).where(RuleRun.run_id == run_id).order_by(RuleRun.rule_id))
    )


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def exceptions(
    session: Session,
    run_id: uuid.UUID,
    *,
    rule_id: str | None,
    severity: str | None,
    after_id: uuid.UUID | None,
    limit: int,
) -> list[RuleExceptionRow]:
    query = select(RuleExceptionRow).where(RuleExceptionRow.run_id == run_id)
    if rule_id:
        query = query.where(RuleExceptionRow.rule_id == rule_id)
    if severity:
        query = query.where(RuleExceptionRow.severity == severity)
    if after_id:
        query = query.where(RuleExceptionRow.id > after_id)
    return list(session.scalars(query.order_by(RuleExceptionRow.id).limit(limit)))


def reconciliation_results(session: Session, run_id: uuid.UUID) -> list[ReconciliationResultRow]:
    return list(
        session.scalars(
            select(ReconciliationResultRow)
            .where(ReconciliationResultRow.run_id == run_id)
            .order_by(ReconciliationResultRow.recon_id)
        )
    )


def get_result(session: Session, result_id: uuid.UUID) -> ReconciliationResultRow:
    result = session.get(ReconciliationResultRow, result_id)
    if result is None:
        raise ResourceNotFoundError("reconciliation result not found")
    return result


def lines(
    session: Session,
    result_id: uuid.UUID,
    *,
    status: str | None,
    after_key: str | None,
    limit: int,
) -> list[ReconciliationLineRow]:
    query = select(ReconciliationLineRow).where(ReconciliationLineRow.result_id == result_id)
    if status:
        query = query.where(ReconciliationLineRow.status == status)
    if after_key:
        query = query.where(ReconciliationLineRow.grain_key > after_key)
    return list(session.scalars(query.order_by(ReconciliationLineRow.grain_key).limit(limit)))


def get_line(session: Session, line_id: uuid.UUID) -> ReconciliationLineRow:
    line = session.get(ReconciliationLineRow, line_id)
    if line is None:
        raise ResourceNotFoundError("reconciliation line not found")
    return line


def items_for(session: Session, line_id: uuid.UUID) -> list[ReconcilingItemRow]:
    return list(
        session.scalars(
            select(ReconcilingItemRow)
            .where(ReconcilingItemRow.line_id == line_id)
            .order_by(ReconcilingItemRow.classification, ReconcilingItemRow.id)
        )
    )


def record_view(record: StagedRecord) -> dict[str, Any]:
    return {
        "natural_key": record.natural_key,
        "record_type": record.record_type,
        "account_code": record.account_code,
        "party_code": record.party_code,
        "document_number": record.document_number,
        "entry_number": record.entry_number,
        "record_date": record.record_date,
        "posting_period": record.posting_period,
        "functional_amount": record.functional_amount,
        "lineage": (
            {
                "import_id": record.source_import_id,
                "row_number": record.source_row_number,
                "line_start": record.line_start,
                "line_end": record.line_end,
            }
            if record.source_import_id
            else None
        ),
    }


def _staged(run_id: uuid.UUID) -> Select[tuple[StagedRecord]]:
    return select(StagedRecord).where(StagedRecord.run_id == run_id)


def get_record(session: Session, run_id: uuid.UUID, natural_key: str) -> StagedRecord:
    record = session.scalars(_staged(run_id).where(StagedRecord.natural_key == natural_key)).first()
    if record is None:
        raise ResourceNotFoundError("record not found in this run")
    return record


@dataclass
class DocumentComparison:
    document: str
    left: Decimal = Decimal(0)
    right: Decimal = Decimal(0)
    left_records: list[dict[str, Any]] = field(default_factory=list)
    right_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.left == self.right:
            return "matched"
        if not self.right_records:
            return "left_only"
        if not self.left_records:
            return "right_only"
        return "different"

    def view(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "status": self.status,
            "left_amount": self.left,
            "right_amount": self.right,
            "difference": self.left - self.right,
            "left_records": self.left_records,
            "right_records": self.right_records,
        }


def _open_value(record: StagedRecord) -> Decimal:
    """Functional open amount of a staged document, as the subledger reconciliation computes it."""
    open_amount = Decimal(str(record.data.get("open_amount", "0")))
    if open_amount == 0:
        return Decimal(0)
    if open_amount == Decimal(record.data["total"]["amount"]):
        return record.functional_amount or Decimal(0)
    return (open_amount * Decimal(str(record.data.get("fx_rate", "1")))).quantize(Decimal("0.01"))


def _mapped_legacy_accounts(session: Session, run_id: uuid.UUID, subtype: str) -> list[str]:
    targets = {
        r.account_code
        for r in session.scalars(
            _staged(run_id).where(StagedRecord.record_type == "target_account")
        )
        if r.data.get("subtype") == subtype
    }
    return sorted(
        r.data["legacy_account_code"]
        for r in session.scalars(
            _staged(run_id).where(StagedRecord.record_type == "account_mapping")
        )
        if r.data.get("target_account_code") in targets
    )


def _opening_unassigned(
    session: Session,
    run: PipelineRun,
    migration: Migration,
    accounts: list[str],
    *,
    aging_type: str,
    sign: Decimal,
) -> dict[str, Any]:
    opening_tb = sum(
        (
            r.functional_amount or Decimal(0)
            for r in session.scalars(
                _staged(run.id).where(
                    StagedRecord.record_type == "trial_balance",
                    StagedRecord.account_code.in_(accounts),
                    StagedRecord.record_date == migration.opening_balance_date,
                )
            )
        ),
        Decimal(0),
    )
    opening_aging = sum(
        (
            (r.functional_amount or Decimal(0))
            * (sign if r.data.get("kind") == "document" else -sign)
            for r in session.scalars(
                _staged(run.id).where(
                    StagedRecord.record_type == "aging_item",
                    StagedRecord.record_date == migration.opening_balance_date,
                )
            )
            if r.data.get("aging_type") == aging_type
        ),
        Decimal(0),
    )
    return {
        "opening_control_balance": opening_tb,
        "opening_aging_total": opening_aging,
        "opening_unassigned": opening_tb - opening_aging,
    }


def _subledger_drilldown(  # noqa: PLR0912, PLR0915 - follows the R3/R4 definition step by step
    session: Session, run: PipelineRun, migration: Migration, recon_id: str, grain: dict[str, str]
) -> dict[str, Any]:
    receivable = recon_id.startswith("R3")
    sign = Decimal(1) if receivable else Decimal(-1)
    accounts = _mapped_legacy_accounts(session, run.id, _RECEIVABLE if receivable else _PAYABLE)
    party = grain.get("party")
    document = grain.get("document")
    comparisons: dict[str, DocumentComparison] = {}

    def comparison(number: str) -> DocumentComparison:
        return comparisons.setdefault(number, DocumentComparison(number))

    ledger_query = _staged(run.id).where(
        StagedRecord.record_type == "journal_line",
        StagedRecord.account_code.in_(accounts),
        StagedRecord.record_date >= migration.history_start_date,
        StagedRecord.record_date <= migration.cutover_date,
    )
    if party == "unassigned":
        ledger_query = ledger_query.where(StagedRecord.party_code.is_(None))
    elif party:
        ledger_query = ledger_query.where(StagedRecord.party_code == party)
    if document:
        ledger_query = ledger_query.where(StagedRecord.document_number == document)
    for record in session.scalars(
        ledger_query.order_by(StagedRecord.record_date, StagedRecord.natural_key)
    ):
        item = comparison(record.document_number or "(no document)")
        item.left += record.functional_amount or Decimal(0)
        item.left_records.append(record_view(record))

    aging_type = "ar" if receivable else "ap"
    document_type = "invoice" if receivable else "bill"
    cutover_aging: list[StagedRecord] = []
    opening_summary: dict[str, Any] | None = None
    if party == "unassigned":
        # Open items and aging items always carry a party; the unassigned line's left side also
        # holds the opening control balance not explained by the opening aging (SC-04).
        opening_summary = _opening_unassigned(
            session, run, migration, accounts, aging_type=aging_type, sign=sign
        )
    else:
        aging_query = _staged(run.id).where(StagedRecord.record_type == "aging_item")
        if party:
            aging_query = aging_query.where(StagedRecord.party_code == party)
        if document:
            aging_query = aging_query.where(StagedRecord.document_number == document)
        for record in session.scalars(aging_query.order_by(StagedRecord.natural_key)):
            if record.data.get("aging_type") != aging_type:
                continue
            if record.record_date == migration.opening_balance_date and recon_id in {"R3", "R4"}:
                item = comparison(record.document_number or "(no document)")
                item.left += (record.functional_amount or Decimal(0)) * (
                    sign if record.data.get("kind") == "document" else -sign
                )
                item.left_records.append({**record_view(record), "role": "opening_aging"})
            elif record.record_date == migration.cutover_date:
                cutover_aging.append(record)

        open_query = _staged(run.id).where(StagedRecord.record_type == document_type)
        if party:
            open_query = open_query.where(StagedRecord.party_code == party)
        if document:
            open_query = open_query.where(StagedRecord.document_number == document)
        open_items = [
            (record, _open_value(record))
            for record in session.scalars(open_query.order_by(StagedRecord.natural_key))
        ]
        if recon_id in {"R3b", "R4b"}:
            comparisons = {}
            for record in cutover_aging:
                item = comparison(record.document_number or "")
                item.left += sign * (record.functional_amount or Decimal(0))
                item.left_records.append({**record_view(record), "role": "cutover_aging"})
        for record, value in open_items:
            if value == 0:
                continue
            item = comparison(record.document_number or "")
            item.right += sign * value
            item.right_records.append(
                {**record_view(record), "open_amount": record.data.get("open_amount")}
            )

    differing = sorted(
        (c for c in comparisons.values() if c.left != c.right), key=lambda c: c.document
    )
    return {
        "basis": "documents",
        "left_label": "Ledger activity and opening aging"
        if recon_id in {"R3", "R4"}
        else "Control aging at cutover",
        "right_label": "Staged open items",
        "accounts": accounts,
        "documents": [c.view() for c in differing],
        "matched_document_count": sum(1 for c in comparisons.values() if c.left == c.right),
        "opening": opening_summary,
        "limits": (
            "Opening balances come from the opening aging report; ledger lines are grouped by the "
            "document number the legacy system recorded on them."
        ),
    }


def _ledger_drilldown(
    session: Session,
    run: PipelineRun,
    migration: Migration,
    recon_id: str,
    grain: dict[str, str],
    *,
    limit: int,
) -> dict[str, Any]:
    period_end = date.fromisoformat(grain["period_end"])
    period = f"{period_end.year:04d}-{period_end.month:02d}"
    first_period = (
        f"{migration.history_start_date.year:04d}-{migration.history_start_date.month:02d}"
    )
    if recon_id == "R1":
        accounts = [grain["account"]]
    else:
        target = grain["target_account"]
        mapping = {
            r.data["legacy_account_code"]: r.data["target_account_code"]
            for r in session.scalars(
                _staged(run.id).where(StagedRecord.record_type == "account_mapping")
            )
        }
        if target == "unmapped":
            accounts = sorted(
                {
                    r.account_code
                    for r in session.scalars(
                        _staged(run.id).where(StagedRecord.record_type == "trial_balance")
                    )
                    if r.account_code and r.account_code not in mapping
                }
            )
        else:
            accounts = sorted(code for code, mapped in mapping.items() if mapped == target)
    balances = [
        record_view(r)
        for r in session.scalars(
            _staged(run.id)
            .where(
                StagedRecord.record_type == "trial_balance",
                StagedRecord.account_code.in_(accounts),
                StagedRecord.record_date.in_([migration.opening_balance_date, period_end]),
            )
            .order_by(StagedRecord.account_code, StagedRecord.record_date)
        )
    ]
    detail_query = _staged(run.id).where(
        StagedRecord.record_type == "journal_line",
        StagedRecord.account_code.in_(accounts),
        or_(
            and_(
                StagedRecord.record_date >= migration.history_start_date,
                StagedRecord.record_date <= period_end,
            ),
            and_(
                StagedRecord.posting_period >= first_period, StagedRecord.posting_period <= period
            ),
        ),
    )
    # Lines whose entry date and posting period disagree about this period explain R1 timing lines.
    disagreeing = []
    counted_total = Decimal(0)
    counted = 0
    for record in session.scalars(
        detail_query.order_by(StagedRecord.record_date, StagedRecord.natural_key)
    ):
        by_date = (
            record.record_date is not None
            and migration.history_start_date <= record.record_date <= period_end
        )
        by_period = (
            record.posting_period is not None and first_period <= record.posting_period <= period
        )
        if by_date:
            counted += 1
            counted_total += record.functional_amount or Decimal(0)
        if by_date != by_period:
            disagreeing.append(
                {
                    **record_view(record),
                    "counted_by_entry_date": by_date,
                    "counted_by_posting_period": by_period,
                }
            )
    quarantined = [
        {
            "import_id": q.import_id,
            "line_start": q.line_start,
            "line_end": q.line_end,
            "reason": q.reason,
        }
        for q in _run_quarantine(session, run)
    ]
    return {
        "basis": "accounts",
        "accounts": accounts,
        "control_balances": balances,
        "detail_line_count": counted,
        "detail_total": counted_total,
        "date_period_disagreements": disagreeing[:limit],
        "quarantined_rows": quarantined,
        "limits": (
            "The control trial balance is an aggregate report, so record-level matching is not "
            "possible. Lines whose entry date and posting period place them in different periods, "
            "and rows that could not be parsed, are listed as the likely contributors."
        ),
    }


def _run_quarantine(session: Session, run: PipelineRun) -> list[QuarantinedRow]:
    import_ids = [
        uuid.UUID(str(value["import_id"]))
        for value in run.fingerprint_components.get("active_imports", {}).values()
    ]
    if not import_ids:
        return []
    return list(
        session.scalars(
            select(QuarantinedRow)
            .where(QuarantinedRow.import_id.in_(import_ids))
            .order_by(QuarantinedRow.import_id, QuarantinedRow.line_start)
        )
    )


def drilldown(session: Session, line_id: uuid.UUID, limit: int = 200) -> dict[str, Any]:
    line = get_line(session, line_id)
    result = get_result(session, line.result_id)
    run = get_run(session, result.run_id)
    migration = session.get(Migration, run.migration_id)
    if migration is None:
        raise ResourceNotFoundError("migration not found")
    grain = dict(line.grain)
    base: dict[str, Any] = {
        "recon_id": result.recon_id,
        "grain": grain,
        "left_amount": line.left_amount,
        "right_amount": line.right_amount,
        "difference": line.difference,
        "unexplained_amount": line.unexplained_amount,
        "status": line.status,
    }
    if result.recon_id in {"R1", "R2"}:
        return {
            **base,
            **_ledger_drilldown(session, run, migration, result.recon_id, grain, limit=limit),
        }
    if result.recon_id in {"R3", "R4", "R3b", "R4b"}:
        return {**base, **_subledger_drilldown(session, run, migration, result.recon_id, grain)}
    items = items_for(session, line.id)
    keys = sorted({key for item in items for key in item.record_keys})
    records = {
        r.natural_key: record_view(r)
        for r in session.scalars(_staged(run.id).where(StagedRecord.natural_key.in_(keys)))
    }
    if result.recon_id == "R6":
        return {
            **base,
            "basis": "periods",
            "extra": line.extra,
            "quarantined_rows": [
                {
                    "import_id": q.import_id,
                    "line_start": q.line_start,
                    "line_end": q.line_end,
                    "reason": q.reason,
                }
                for q in _run_quarantine(session, run)
            ],
        }
    return {
        **base,
        "basis": "reconciling_items",
        "items": [
            {
                "classification": item.classification,
                "amount": item.amount,
                "message": item.message,
                "records": [records[k] for k in item.record_keys if k in records],
            }
            for item in items
        ],
    }


def candidates(session: Session, run_id: uuid.UUID) -> list[EntityCandidateRow]:
    return list(
        session.scalars(
            select(EntityCandidateRow)
            .where(EntityCandidateRow.run_id == run_id)
            .order_by(EntityCandidateRow.score.desc(), EntityCandidateRow.left_code)
        )
    )


def readiness_for_run(
    session: Session, run_id: uuid.UUID
) -> tuple[ReadinessEvaluationRow, list[GateResultRow]] | None:
    evaluation = session.scalars(
        select(ReadinessEvaluationRow)
        .where(ReadinessEvaluationRow.run_id == run_id)
        .order_by(ReadinessEvaluationRow.sequence.desc())
    ).first()
    if evaluation is None:
        return None
    gates = list(
        session.scalars(select(GateResultRow).where(GateResultRow.evaluation_id == evaluation.id))
    )
    gates.sort(key=lambda g: int(g.gate_id[1:]))
    return evaluation, gates


def staged_by_document(
    session: Session, run_id: uuid.UUID, document_number: str
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in session.scalars(
        _staged(run_id).where(StagedRecord.document_number == document_number)
    ):
        grouped[record.record_type].append(record_view(record))
    return dict(grouped)


def latest_exception(session: Session, issue: Issue) -> RuleExceptionRow | None:
    return session.scalars(
        select(RuleExceptionRow)
        .join(IssueOccurrence, IssueOccurrence.rule_exception_id == RuleExceptionRow.id)
        .where(IssueOccurrence.issue_id == issue.id)
        .order_by(RuleExceptionRow.id.desc())
        .limit(1)
    ).first()


def exceptions_for_fingerprint(
    session: Session, run_id: uuid.UUID, fingerprint: str, limit: int
) -> list[RuleExceptionRow]:
    return list(
        session.scalars(
            select(RuleExceptionRow)
            .where(RuleExceptionRow.run_id == run_id, RuleExceptionRow.fingerprint == fingerprint)
            .order_by(RuleExceptionRow.id)
            .limit(limit)
        )
    )


def search_records(
    session: Session,
    run_id: uuid.UUID,
    *,
    record_type: str,
    party_code: str | None = None,
    account_code: str | None = None,
    document_prefix: str | None = None,
    entry_number: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min: Decimal | None = None,
    amount_max: Decimal | None = None,
    limit: int = 50,
) -> list[StagedRecord]:
    """Structured search over one run's staged records; no free-form query language."""
    query = _staged(run_id).where(StagedRecord.record_type == record_type)
    if party_code:
        query = query.where(StagedRecord.party_code == party_code)
    if account_code:
        query = query.where(StagedRecord.account_code == account_code)
    if document_prefix:
        escaped = document_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(StagedRecord.document_number.like(f"{escaped}%", escape="\\"))
    if entry_number:
        query = query.where(StagedRecord.entry_number == entry_number)
    if date_from:
        query = query.where(StagedRecord.record_date >= date_from)
    if date_to:
        query = query.where(StagedRecord.record_date <= date_to)
    if amount_min is not None:
        query = query.where(StagedRecord.functional_amount >= amount_min)
    if amount_max is not None:
        query = query.where(StagedRecord.functional_amount <= amount_max)
    return list(session.scalars(query.order_by(StagedRecord.natural_key).limit(limit)))


def result_by_recon(
    session: Session, run_id: uuid.UUID, recon_id: str
) -> ReconciliationResultRow | None:
    return session.scalars(
        select(ReconciliationResultRow).where(
            ReconciliationResultRow.run_id == run_id, ReconciliationResultRow.recon_id == recon_id
        )
    ).first()


def line_in_run(session: Session, run_id: uuid.UUID, line_id: uuid.UUID) -> ReconciliationLineRow:
    """A reconciliation line, only if it belongs to the given run."""
    line = get_line(session, line_id)
    if get_result(session, line.result_id).run_id != run_id:
        raise ResourceNotFoundError("reconciliation line not found")
    return line


def candidates_for_party(
    session: Session, run_id: uuid.UUID, party_type: str, code: str
) -> list[EntityCandidateRow]:
    return list(
        session.scalars(
            select(EntityCandidateRow)
            .where(
                EntityCandidateRow.run_id == run_id,
                EntityCandidateRow.party_type == party_type,
                or_(EntityCandidateRow.left_code == code, EntityCandidateRow.right_code == code),
            )
            .order_by(EntityCandidateRow.score.desc())
        )
    )


def count_documents(session: Session, run_id: uuid.UUID, record_type: str, party_code: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(StagedRecord)
            .where(
                StagedRecord.run_id == run_id,
                StagedRecord.record_type == record_type,
                StagedRecord.party_code == party_code,
            )
        )
        or 0
    )
