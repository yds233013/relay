"""M9: rule runs can record that a rule errored (FC-10).

Revision ID: 0007_errored_stages
Revises: 0006_investigations
Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_errored_stages"
down_revision = "0006_investigations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_rule_runs_status"), "rule_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_rule_runs_status"),
        "rule_runs",
        "status IN ('passed', 'failed', 'not_applicable', 'errored')",
    )
    op.add_column("rule_runs", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rule_runs", "error")
    op.execute("DELETE FROM rule_runs WHERE status = 'errored'")
    op.drop_constraint(op.f("ck_rule_runs_status"), "rule_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_rule_runs_status"),
        "rule_runs",
        "status IN ('passed', 'failed', 'not_applicable')",
    )
