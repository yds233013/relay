"""A pipeline run whose inputs changed before it started is superseded, not failed.

Revision ID: 0008_superseded_runs
Revises: 0007_errored_stages
Create Date: 2026-09-17
"""

from __future__ import annotations

from alembic import op

revision = "0008_superseded_runs"
down_revision = "0007_errored_stages"
branch_labels = None
depends_on = None

_STATUSES = "'queued', 'running', 'succeeded', 'failed'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_pipeline_runs_status"), "pipeline_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_pipeline_runs_status"),
        "pipeline_runs",
        f"status IN ({_STATUSES}, 'superseded')",
    )
    # Runs already recorded as failed for this reason are the same thing under the old name.
    op.execute(
        "UPDATE pipeline_runs SET status = 'superseded'"
        " WHERE status = 'failed' AND error->>'code' = 'pipeline.inputs_changed'"
    )


def downgrade() -> None:
    op.execute("UPDATE pipeline_runs SET status = 'failed' WHERE status = 'superseded'")
    op.drop_constraint(op.f("ck_pipeline_runs_status"), "pipeline_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_pipeline_runs_status"), "pipeline_runs", f"status IN ({_STATUSES})"
    )
