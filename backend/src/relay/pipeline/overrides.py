"""Resolve record override requests against a run's evidence.

A client names a record, a field and a new value (or a quarantine finding and replacement text).
The server reads the current value, the source import and the amount involved from the run, so a
change request always states what it was written against. The engine re-checks the expected value
on every run and reports ``OVERRIDE.STALE`` instead of applying an override that no longer matches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.changes.kinds import OVERRIDABLE_FIELDS, ChangeRequestPreconditionError
from relay.core.errors import InvalidInputError
from relay.core.money import Money
from relay.imports.models import Import
from relay.pipeline.models import PipelineRun, RuleExceptionRow, RunStatus, StagedRecord
from relay.pipeline.read_model import ResourceNotFoundError, get_record
from relay.workspace import service as workspace

QUARANTINE_RULE: Final = "NORM.MALFORMED_ROW"


def _succeeded_run(session: Session, migration_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
    run = session.get(PipelineRun, run_id)
    if run is None or run.migration_id != migration_id:
        raise ResourceNotFoundError("pipeline run not found")
    if run.status != RunStatus.SUCCEEDED.value:
        raise ChangeRequestPreconditionError("overrides are written against a succeeded run")
    return run


def _source_import(session: Session, import_id: uuid.UUID | None) -> Import:
    record = session.get(Import, import_id) if import_id else None
    if record is None:
        raise ChangeRequestPreconditionError("the record has no source import to override")
    return record


def field_override_payload(
    session: Session,
    *,
    migration_id: uuid.UUID,
    run_id: uuid.UUID,
    natural_key: str,
    field: str,
    new_value: str,
) -> dict[str, Any]:
    run = _succeeded_run(session, migration_id, run_id)
    prefix = natural_key.partition(":")[0]
    if field not in OVERRIDABLE_FIELDS.get(prefix, frozenset()):
        raise InvalidInputError(f"{field} cannot be overridden on {natural_key}")
    record = get_record(session, run.id, natural_key)
    current = record.data.get(field)
    if current is None:
        raise InvalidInputError(f"{natural_key} has no {field}")
    source = _source_import(session, record.source_import_id)
    dataset = workspace.get_dataset(session, source.dataset_id)
    migration = workspace.get_migration(session, migration_id)
    amount: Decimal | None = None
    if record.record_type == "journal_entry" and record.entry_number is not None:
        # The size of an entry is its debit total in functional currency.
        amount = session.scalar(
            select(func.coalesce(func.sum(StagedRecord.functional_amount), 0)).where(
                StagedRecord.run_id == run.id,
                StagedRecord.record_type == "journal_line",
                StagedRecord.entry_number == record.entry_number,
                StagedRecord.functional_amount > 0,
            )
        )
    return {
        "override": {
            "target": "canonical_field",
            "run_id": str(run.id),
            "dataset_type": dataset.dataset_type,
            "dataset_id": str(dataset.id),
            "import_id": str(source.id),
            "natural_key": natural_key,
            "field": field,
            "expected_current": str(current),
            "new_value": new_value,
            "amount": (
                Money(amount, migration.functional_currency).amount_str
                if amount is not None
                else None
            ),
            "currency": migration.functional_currency.code,
        }
    }


def quarantine_repair_payload(
    session: Session,
    *,
    migration_id: uuid.UUID,
    exception_id: uuid.UUID,
    replacement_text: str,
) -> dict[str, Any]:
    finding = session.get(RuleExceptionRow, exception_id)
    if finding is None or finding.rule_id != QUARANTINE_RULE:
        raise ResourceNotFoundError("quarantine finding not found")
    run = _succeeded_run(session, migration_id, finding.run_id)
    subject = finding.subjects[0] if finding.subjects else ""
    parts = subject.split(":", 2)
    details = finding.details
    if len(parts) != 3 or parts[0] != "quarantine" or "file" not in details:
        raise InvalidInputError("the finding does not identify a quarantined row")
    try:
        import_id = uuid.UUID(str(details["file"]))
    except ValueError as exc:
        raise InvalidInputError("the finding does not identify a stored import") from exc
    source = _source_import(session, import_id)
    dataset = workspace.get_dataset(session, source.dataset_id)
    return {
        "override": {
            "target": "quarantined_row_repair",
            "run_id": str(run.id),
            "exception_id": str(finding.id),
            "dataset_type": dataset.dataset_type,
            "dataset_id": str(dataset.id),
            "import_id": str(source.id),
            "natural_key": subject,
            "quarantine_key": parts[2],
            "raw_text": str(details.get("raw_text", "")),
            "replacement_text": replacement_text,
            "expected_fields": len(source.header or []),
            "delimiter": source.delimiter or ",",
            "line_start": int(details.get("line_start", 0)),
            "line_end": int(details.get("line_end", 0)),
        }
    }
