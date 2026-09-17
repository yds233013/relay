"""Baseline: empty schema.

M0 creates no domain tables. This revision exists so that every environment has a known
``alembic_version`` from the start and ``/health/ready`` can verify the schema is at head.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-17
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
