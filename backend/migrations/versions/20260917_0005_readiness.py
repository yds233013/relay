"""M7 readiness: gate waivers, sign-offs, repeated readiness evaluations, readiness jobs.

Generated with autogenerate, then edited: plain SQL column types, explicit index names, defaults
for existing evaluation rows, and check constraints autogenerate does not detect.

Revision ID: 0005_readiness
Revises: 0004_issue_workflow
Create Date: 2026-09-17 16:47:58.044497+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_readiness"
down_revision: str | None = "0004_issue_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gate_waivers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("gate_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("run_fingerprint", sa.Text(), nullable=False),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
        sa.Column("reverted_by_cr_id", sa.UUID(), nullable=True),
        sa.Column("lapsed_run_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'lapsed', 'reverted')", name=op.f("ck_gate_waivers_status")
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"],
            ["change_requests.id"],
            name=op.f("fk_gate_waivers_change_request_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["lapsed_run_id"],
            ["pipeline_runs.id"],
            name=op.f("fk_gate_waivers_lapsed_run_id_pipeline_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"],
            ["migrations.id"],
            name=op.f("fk_gate_waivers_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_cr_id"],
            ["change_requests.id"],
            name=op.f("fk_gate_waivers_reverted_by_cr_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_gate_waivers_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gate_waivers")),
    )
    op.create_index(
        op.f("ix_gate_waivers_migration_status"),
        "gate_waivers",
        ["migration_id", "status"],
        unique=False,
    )
    op.create_table(
        "readiness_signoffs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("run_fingerprint", sa.Text(), nullable=False),
        sa.Column("readiness_evaluation_id", sa.UUID(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
        sa.Column("invalidated_by_fingerprint", sa.Text(), nullable=True),
        sa.Column("reverted_by_cr_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invalidated', 'reverted')",
            name=op.f("ck_readiness_signoffs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"],
            ["change_requests.id"],
            name=op.f("fk_readiness_signoffs_change_request_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"],
            ["migrations.id"],
            name=op.f("fk_readiness_signoffs_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["readiness_evaluation_id"],
            ["readiness_evaluations.id"],
            name=op.f("fk_readiness_signoffs_readiness_evaluation_id_readiness_evaluations"),
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_cr_id"],
            ["change_requests.id"],
            name=op.f("fk_readiness_signoffs_reverted_by_cr_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline_runs.id"],
            name=op.f("fk_readiness_signoffs_run_id_pipeline_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_readiness_signoffs")),
    )
    op.create_index(
        op.f("ix_readiness_signoffs_migration_status"),
        "readiness_signoffs",
        ["migration_id", "status"],
        unique=False,
    )
    op.add_column(
        "gate_results", sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "readiness_evaluations",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "readiness_evaluations",
        sa.Column("trigger", sa.Text(), nullable=False, server_default="run"),
    )
    op.alter_column("readiness_evaluations", "sequence", server_default=None)
    op.alter_column("readiness_evaluations", "trigger", server_default=None)
    op.create_check_constraint(
        op.f("ck_readiness_evaluations_trigger"),
        "readiness_evaluations",
        "trigger IN ('run', 'governance')",
    )
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"),
        "jobs",
        "kind IN ('parse_import', 'profile_import', 'run_pipeline', 'evaluate_readiness')",
    )
    op.drop_constraint(
        op.f("uq_readiness_evaluations_run_id"), "readiness_evaluations", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_readiness_evaluations_run_id_sequence"),
        "readiness_evaluations",
        ["run_id", "sequence"],
    )


def downgrade() -> None:
    blocked = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM gate_waivers) + (SELECT count(*) FROM readiness_signoffs)"
        )
    )
    if blocked:
        # Approved waivers and sign-offs are governed history; never drop them to fit a schema.
        raise RuntimeError("cannot downgrade: gate waivers or readiness sign-offs exist")
    # Repeated evaluations and readiness jobs are derived and recomputable.
    op.execute(
        "DELETE FROM gate_results WHERE evaluation_id IN "
        "(SELECT id FROM readiness_evaluations WHERE sequence > 1)"
    )
    op.execute("DELETE FROM readiness_evaluations WHERE sequence > 1")
    op.execute("DELETE FROM jobs WHERE kind = 'evaluate_readiness'")
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"), "jobs", "kind IN ('parse_import', 'profile_import', 'run_pipeline')"
    )
    op.drop_constraint(
        op.f("ck_readiness_evaluations_trigger"), "readiness_evaluations", type_="check"
    )
    op.drop_constraint(
        op.f("uq_readiness_evaluations_run_id_sequence"), "readiness_evaluations", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_readiness_evaluations_run_id"),
        "readiness_evaluations",
        ["run_id"],
    )
    op.drop_column("readiness_evaluations", "trigger")
    op.drop_column("readiness_evaluations", "sequence")
    op.drop_column("gate_results", "scope")
    op.drop_index(op.f("ix_readiness_signoffs_migration_status"), table_name="readiness_signoffs")
    op.drop_table("readiness_signoffs")
    op.drop_index(op.f("ix_gate_waivers_migration_status"), table_name="gate_waivers")
    op.drop_table("gate_waivers")
