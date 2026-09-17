"""Query side for imports: imports per dataset, raw rows, quarantined rows, profiles."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.core.errors import NotFoundError
from relay.imports.models import DatasetProfile, Import, QuarantinedRow, SourceRow


def get_import(session: Session, import_id: uuid.UUID) -> Import:
    record = session.get(Import, import_id)
    if record is None:
        raise NotFoundError("import not found")
    return record


def imports_for(session: Session, dataset_id: uuid.UUID) -> list[Import]:
    return list(
        session.scalars(
            select(Import).where(Import.dataset_id == dataset_id).order_by(Import.sequence.desc())
        )
    )


def rows(session: Session, import_id: uuid.UUID, *, after_row: int, limit: int) -> list[SourceRow]:
    return list(
        session.scalars(
            select(SourceRow)
            .where(SourceRow.import_id == import_id, SourceRow.row_number > after_row)
            .order_by(SourceRow.row_number)
            .limit(limit)
        )
    )


def quarantine(session: Session, import_id: uuid.UUID) -> list[QuarantinedRow]:
    return list(
        session.scalars(
            select(QuarantinedRow)
            .where(QuarantinedRow.import_id == import_id)
            .order_by(QuarantinedRow.line_start)
        )
    )


def profile(session: Session, import_id: uuid.UUID) -> DatasetProfile | None:
    return session.scalars(
        select(DatasetProfile).where(DatasetProfile.import_id == import_id)
    ).first()
