"""Query side for mapping sets (no writes)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.mapping_sets.models import (
    AccountMapping,
    AccountMappingSet,
    ColumnMapping,
    ColumnMappingSet,
    MappingSetStatus,
)
from relay.workspace.models import Dataset


def approved_account_mapping(
    session: Session, migration_id: uuid.UUID
) -> tuple[AccountMappingSet, list[AccountMapping]] | None:
    mapping_set = session.scalars(
        select(AccountMappingSet).where(
            AccountMappingSet.migration_id == migration_id,
            AccountMappingSet.status == MappingSetStatus.APPROVED.value,
        )
    ).first()
    if mapping_set is None:
        return None
    entries = list(
        session.scalars(
            select(AccountMapping)
            .where(AccountMapping.mapping_set_id == mapping_set.id)
            .order_by(AccountMapping.legacy_account_code)
        )
    )
    return mapping_set, entries


def approved_column_mapping(
    session: Session, migration_id: uuid.UUID, dataset_type: str
) -> list[dict[str, Any]]:
    """Per dataset of the type: name, approved version and field specifications."""
    datasets = session.scalars(
        select(Dataset)
        .where(Dataset.migration_id == migration_id, Dataset.dataset_type == dataset_type)
        .order_by(Dataset.name)
    )
    output = []
    for dataset in datasets:
        approved = session.scalars(
            select(ColumnMappingSet).where(
                ColumnMappingSet.dataset_id == dataset.id,
                ColumnMappingSet.status == MappingSetStatus.APPROVED.value,
            )
        ).first()
        fields = (
            {
                m.target_field: m.transform
                for m in session.scalars(
                    select(ColumnMapping).where(ColumnMapping.mapping_set_id == approved.id)
                )
            }
            if approved
            else {}
        )
        output.append(
            {
                "dataset": dataset.name,
                "approved_version": approved.version if approved else None,
                "fields": fields,
            }
        )
    return output
