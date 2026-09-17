"""M8: AI investigations, transcript steps and findings; change requests drafted from findings.

Generated with autogenerate, then edited: plain SQL column types, explicit constraint and index
names, and the job kind check constraint autogenerate does not detect.

Revision ID: 0006_investigations
Revises: 0005_readiness
Create Date: 2026-09-17 17:22:43.096153+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_investigations"
down_revision: str | None = "0005_readiness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("started_by", sa.UUID(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("sent_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'budget_exhausted')",
            name=op.f("ck_investigations_status"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["issues.id"], name=op.f("fk_investigations_issue_id_issues")
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"],
            ["migrations.id"],
            name=op.f("fk_investigations_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_investigations_run_id_pipeline_runs")
        ),
        sa.ForeignKeyConstraint(
            ["started_by"], ["users.id"], name=op.f("fk_investigations_started_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigations")),
    )
    op.create_index(
        op.f("ix_investigations_migration"),
        "investigations",
        ["migration_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("investigation_id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("affected_record_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("suggested_action", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("verification_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('proposed', 'accepted', 'dismissed')",
            name=op.f("ck_findings_review_status"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'partially_verified', 'failed')",
            name=op.f("ck_findings_verification_status"),
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name=op.f("fk_findings_investigation_id_investigations"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["issues.id"], name=op.f("fk_findings_issue_id_issues")
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["migrations.id"], name=op.f("fk_findings_migration_id_migrations")
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_findings_reviewed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(
        op.f("ix_findings_investigation"), "findings", ["investigation_id"], unique=False
    )
    op.create_table(
        "investigation_steps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("investigation_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("result_sha256", sa.Text(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("is_error", sa.Boolean(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "type IN ('model_message', 'tool_call', 'tool_result', 'final')",
            name=op.f("ck_investigation_steps_type"),
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
            name=op.f("fk_investigation_steps_investigation_id_investigations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigation_steps")),
        sa.UniqueConstraint(
            "investigation_id", "seq", name=op.f("uq_investigation_steps_investigation_id_seq")
        ),
    )
    op.add_column("change_requests", sa.Column("origin_finding_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_change_requests_origin_finding"),
        "change_requests",
        "findings",
        ["origin_finding_id"],
        ["id"],
    )
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"),
        "jobs",
        "kind IN ('parse_import', 'profile_import', 'run_pipeline', 'evaluate_readiness', "
        "'run_investigation')",
    )


def downgrade() -> None:
    blocked = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM change_requests WHERE origin_finding_id IS NOT NULL")
    )
    if blocked:
        # Change requests drafted from findings would lose their provenance.
        raise RuntimeError("cannot downgrade: change requests reference findings")
    op.execute("DELETE FROM jobs WHERE kind = 'run_investigation'")
    op.drop_constraint(op.f("ck_jobs_kind"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_kind"),
        "jobs",
        "kind IN ('parse_import', 'profile_import', 'run_pipeline', 'evaluate_readiness')",
    )
    op.drop_constraint(
        op.f("fk_change_requests_origin_finding"), "change_requests", type_="foreignkey"
    )
    op.drop_column("change_requests", "origin_finding_id")
    op.drop_table("investigation_steps")
    op.drop_index(op.f("ix_findings_investigation"), table_name="findings")
    op.drop_table("findings")
    op.drop_index(op.f("ix_investigations_migration"), table_name="investigations")
    op.drop_table("investigations")
