"""Query side for companies, migrations and datasets."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.workspace.models import Company, Migration


def migrations(session: Session) -> list[tuple[Migration, Company]]:
    return [
        (migration, company)
        for migration, company in session.execute(
            select(Migration, Company)
            .join(Company, Company.id == Migration.company_id)
            .order_by(Migration.created_at)
        ).tuples()
    ]
