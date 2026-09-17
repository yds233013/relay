"""Query side for companies, migrations and datasets."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.workspace.models import Company, Dataset, Migration


def migrations(session: Session) -> list[tuple[Migration, Company]]:
    return [
        (migration, company)
        for migration, company in session.execute(
            select(Migration, Company)
            .join(Company, Company.id == Migration.company_id)
            .order_by(Migration.created_at)
        ).tuples()
    ]


def migration_with_company(
    session: Session, migration_id: uuid.UUID
) -> tuple[Migration, Company] | None:
    return (
        session.execute(
            select(Migration, Company)
            .join(Company, Company.id == Migration.company_id)
            .where(Migration.id == migration_id)
        )
        .tuples()
        .first()
    )


def datasets_for(session: Session, migration_id: uuid.UUID) -> list[Dataset]:
    return list(
        session.scalars(
            select(Dataset)
            .where(Dataset.migration_id == migration_id)
            .order_by(Dataset.dataset_type, Dataset.as_of_date, Dataset.name)
        )
    )
