"""Rebuild a comparable result from a persisted pipeline run (evaluation only).

Reads only persisted rows (findings, reconciliation lines and items, candidates), so comparing it
with the golden manifest checks what Relay stored and serves, not the in-memory engine output.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.canonical.enums import PartyType
from relay.engine.entities import Candidate
from relay.engine.exceptions import Category, Nature, RuleException, Severity, make_exception
from relay.engine.reconciliation import ReconcilingItem, ReconLine, ReconResult
from relay.pipeline.models import (
    EntityCandidateRow,
    ReconciliationLineRow,
    ReconciliationResultRow,
    ReconcilingItemRow,
    RuleExceptionRow,
)


@dataclass(frozen=True, slots=True)
class PersistedResult:
    exceptions: tuple[RuleException, ...]
    reconciliations: tuple[ReconResult, ...]
    candidates: tuple[Candidate, ...]


def _extra(values: dict[str, object]) -> dict[str, object]:
    converted: dict[str, object] = {}
    for key, value in values.items():
        if key == "count_difference":
            converted[key] = int(str(value))
        elif key.endswith("_difference"):
            converted[key] = Decimal(str(value))
        else:
            converted[key] = value
    return converted


def load(session: Session, run_id: uuid.UUID) -> PersistedResult:
    exceptions = tuple(
        make_exception(
            rule_id=row.rule_id,
            rule_version=row.rule_version,
            severity=Severity(row.severity),
            nature=Nature(row.nature),
            category=Category(row.category),
            subjects=list(row.subjects),
            message=row.message,
            discriminator=row.discriminator,
            expected=row.expected,
            observed=row.observed,
            amount_at_risk=row.amount_at_risk,
            details=row.details,
        )
        for row in session.scalars(
            select(RuleExceptionRow).where(RuleExceptionRow.run_id == run_id)
        )
    )
    reconciliations = []
    for result in session.scalars(
        select(ReconciliationResultRow).where(ReconciliationResultRow.run_id == run_id)
    ):
        lines = []
        for line in session.scalars(
            select(ReconciliationLineRow)
            .where(ReconciliationLineRow.result_id == result.id)
            .order_by(ReconciliationLineRow.grain_key)
        ):
            items = tuple(
                ReconcilingItem(
                    item.classification, item.amount, tuple(item.record_keys), item.message
                )
                for item in session.scalars(
                    select(ReconcilingItemRow).where(ReconcilingItemRow.line_id == line.id)
                )
            )
            lines.append(
                ReconLine(
                    grain=tuple(line.grain.items()),
                    left=line.left_amount,
                    right=line.right_amount,
                    explained=line.explained_amount,
                    items=items,
                    extra=_extra(line.extra),
                )
            )
        reconciliations.append(
            ReconResult(
                recon_id=result.recon_id,
                title=result.title,
                purpose=result.purpose,
                left_label=result.left_label,
                right_label=result.right_label,
                tolerance=result.tolerance,
                lines=tuple(lines),
                applicable=result.applicable,
                note=result.note,
            )
        )
    candidates = tuple(
        Candidate(PartyType(row.party_type), row.left_code, row.right_code, row.score, row.features)
        for row in session.scalars(
            select(EntityCandidateRow).where(EntityCandidateRow.run_id == run_id)
        )
    )
    return PersistedResult(exceptions, tuple(reconciliations), candidates)
