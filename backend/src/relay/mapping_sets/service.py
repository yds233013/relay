"""Column mapping sets: drafts, validation against the import header, approval by change request."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.core.actor import Actor
from relay.core.errors import InvalidInputError, NotFoundError, RelayError
from relay.core.ids import uuid7
from relay.imports.models import Import, ImportStatus, SourceRow
from relay.mapping import registry
from relay.mapping.transforms import DatasetMapping, FieldMapping, MappingConfigError, Value
from relay.mapping_sets.models import (
    ColumnMapping,
    ColumnMappingSet,
    MappingBasis,
    MappingSetStatus,
)
from relay.workspace.models import Dataset

MAX_MAPPED_RECORDS: Final = 50_000
"""Reference datasets read through their column mapping (charts, mapping files) are small."""


class MappingSetStateError(RelayError):
    code: ClassVar[str] = "mapping_set.invalid_state"
    title: ClassVar[str] = "Mapping set is not in a state that allows this"
    http_status: ClassVar[int] = 409


class InvalidMappingError(RelayError):
    code: ClassVar[str] = "mapping_set.invalid"
    title: ClassVar[str] = "Column mapping is invalid"
    http_status: ClassVar[int] = 422


def create_draft(
    session: Session,
    *,
    actor: Actor,
    dataset: Dataset,
    config: Mapping[str, Any],
    basis: MappingBasis = MappingBasis.OPERATOR,
) -> ColumnMappingSet:
    """Validate a mapping configuration ({"fields": ..., "exclude_rows_where_blank": ...})."""
    if dataset.active_import_id is None:
        raise MappingSetStateError("a mapping is drafted against a parsed, active import")
    active = session.get(Import, dataset.active_import_id)
    if active is None or active.status != ImportStatus.PARSED.value or active.header is None:
        raise MappingSetStateError("the dataset's active import is not parsed")
    if set(config) - {"fields", "exclude_rows_where_blank", "dataset_type"}:
        raise InvalidMappingError("mapping configuration has unknown keys")
    if config.get("dataset_type", dataset.dataset_type) != dataset.dataset_type:
        raise InvalidMappingError("mapping configuration is for another dataset type")
    fields_config = config.get("fields")
    if not isinstance(fields_config, Mapping):
        raise InvalidMappingError("mapping configuration needs a fields object")
    missing = registry.missing_required(dataset.dataset_type, set(fields_config))
    unknown = registry.unknown_fields(dataset.dataset_type, set(fields_config))
    if missing or unknown:
        raise InvalidMappingError(
            f"{dataset.dataset_type}: missing required fields {missing}, unknown fields {unknown}"
        )
    try:
        parsed = DatasetMapping.parse(dataset.dataset_type, config, [str(h) for h in active.header])
    except MappingConfigError as exc:
        raise InvalidMappingError(exc.detail) from exc
    version = (
        session.scalar(
            select(func.max(ColumnMappingSet.version)).where(
                ColumnMappingSet.dataset_id == dataset.id
            )
        )
        or 0
    ) + 1
    mapping_set = ColumnMappingSet(
        id=uuid7(),
        dataset_id=dataset.id,
        version=version,
        status=MappingSetStatus.DRAFT.value,
        based_on_import_id=active.id,
        exclude_rows_where_blank=list(parsed.exclude_rows_where_blank),
        created_by=actor.user_id,
        lock_version=1,
    )
    session.add(mapping_set)
    session.flush()
    for target, specification in config["fields"].items():
        field_mapping = FieldMapping.parse(target, specification)
        session.add(
            ColumnMapping(
                id=uuid7(),
                mapping_set_id=mapping_set.id,
                target_field=target,
                transform=dict(specification),
                required=field_mapping.required,
                basis=basis.value,
            )
        )
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="mapping_set.draft_created",
        entity_type="column_mapping_set",
        entity_id=mapping_set.id,
        migration_id=dataset.migration_id,
        after={"dataset_id": dataset.id, "version": version, "fields": len(config["fields"])},
    )
    return mapping_set


def mark_pending(mapping_set: ColumnMappingSet) -> None:
    if mapping_set.status != MappingSetStatus.DRAFT.value:
        raise MappingSetStateError("only draft mapping sets can be submitted")
    mapping_set.status = MappingSetStatus.PENDING_APPROVAL.value


def approve(
    session: Session,
    *,
    actor: Actor,
    mapping_set: ColumnMappingSet,
    change_request_id: uuid.UUID,
    migration_id: uuid.UUID,
) -> None:
    """Applier for an approved ``column_mapping_set`` change request."""
    if mapping_set.status != MappingSetStatus.PENDING_APPROVAL.value:
        raise MappingSetStateError("only mapping sets pending approval can be approved")
    previous = session.scalars(
        select(ColumnMappingSet)
        .where(
            ColumnMappingSet.dataset_id == mapping_set.dataset_id,
            ColumnMappingSet.status == MappingSetStatus.APPROVED.value,
        )
        .with_for_update()
    ).first()
    if previous is not None:
        previous.status = MappingSetStatus.SUPERSEDED.value
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="mapping_set.superseded",
            entity_type="column_mapping_set",
            entity_id=previous.id,
            migration_id=migration_id,
            change_request_id=change_request_id,
            before={"status": MappingSetStatus.APPROVED.value},
            after={"status": MappingSetStatus.SUPERSEDED.value},
        )
    mapping_set.status = MappingSetStatus.APPROVED.value
    mapping_set.change_request_id = change_request_id
    mapping_set.lock_version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="mapping_set.approved",
        entity_type="column_mapping_set",
        entity_id=mapping_set.id,
        migration_id=migration_id,
        change_request_id=change_request_id,
        before={"status": MappingSetStatus.PENDING_APPROVAL.value},
        after={"status": MappingSetStatus.APPROVED.value, "version": mapping_set.version},
    )


def reject(mapping_set: ColumnMappingSet) -> None:
    if mapping_set.status == MappingSetStatus.PENDING_APPROVAL.value:
        mapping_set.status = MappingSetStatus.REJECTED.value


def approved_set(session: Session, dataset_id: uuid.UUID) -> ColumnMappingSet | None:
    return session.scalars(
        select(ColumnMappingSet).where(
            ColumnMappingSet.dataset_id == dataset_id,
            ColumnMappingSet.status == MappingSetStatus.APPROVED.value,
        )
    ).first()


def engine_config(
    session: Session, mapping_set: ColumnMappingSet, dataset_type: str
) -> dict[str, Any]:
    """The configuration shape the engine's column mapping reader expects."""
    mappings = session.scalars(
        select(ColumnMapping)
        .where(ColumnMapping.mapping_set_id == mapping_set.id)
        .order_by(ColumnMapping.target_field)
    )
    return {
        "dataset_type": dataset_type,
        "fields": {m.target_field: m.transform for m in mappings},
        "exclude_rows_where_blank": list(mapping_set.exclude_rows_where_blank),
    }


def mapped_records(session: Session, dataset: Dataset) -> list[dict[str, Value]]:
    """The active import's rows read through the approved column mapping, for reference datasets.

    Rows that are excluded or fail a transform are skipped: the pipeline reports them as findings.
    Returns an empty list when the dataset has no parsed import or no approved mapping.
    """
    approved = approved_set(session, dataset.id)
    active = session.get(Import, dataset.active_import_id) if dataset.active_import_id else None
    if approved is None or active is None or active.status != ImportStatus.PARSED.value:
        return []
    if (active.row_count or 0) > MAX_MAPPED_RECORDS:
        raise MappingSetStateError(f"{dataset.name} is too large to read as reference data")
    mapping = DatasetMapping.parse(
        dataset.dataset_type, engine_config(session, approved, dataset.dataset_type)
    )
    records = []
    rows = session.scalars(
        select(SourceRow.values)
        .where(SourceRow.import_id == active.id)
        .order_by(SourceRow.row_number)
    )
    for values in rows:
        if mapping.excludes(values):
            continue
        try:
            records.append({f.target: f.apply(values) for f in mapping.fields})
        except (InvalidInputError, MappingConfigError):
            continue
    return records


def get_set(session: Session, set_id: uuid.UUID) -> ColumnMappingSet:
    mapping_set = session.get(ColumnMappingSet, set_id)
    if mapping_set is None:
        raise NotFoundError("column mapping set not found")
    return mapping_set


def sets_for(session: Session, dataset_id: uuid.UUID) -> list[ColumnMappingSet]:
    return list(
        session.scalars(
            select(ColumnMappingSet)
            .where(ColumnMappingSet.dataset_id == dataset_id)
            .order_by(ColumnMappingSet.version.desc())
        )
    )


def mappings(session: Session, set_id: uuid.UUID) -> list[ColumnMapping]:
    return list(
        session.scalars(
            select(ColumnMapping)
            .where(ColumnMapping.mapping_set_id == set_id)
            .order_by(ColumnMapping.target_field)
        )
    )
