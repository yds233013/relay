"""M5 governance: account mapping sets, record overrides, revert change requests.

Written by hand following the conventions of 0002 (plain SQL types, explicit constraint names).

Revision ID: 0003_governance
Revises: 0002_persistence
Create Date: 2026-09-17 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_governance"
down_revision: str | None = "0002_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
    "'column_mapping_set', 'account_mapping_set', 'record_override', 'entity_decision', "
    "'disposition', 'policy_change', 'gate_waiver', 'readiness_signoff'"
)
_SET_STATUSES = "'draft', 'pending_approval', 'approved', 'superseded', 'rejected'"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    _replace_check("change_requests", "ck_change_requests_kind", f"kind IN ({_KINDS}, 'revert')")
    _replace_check(
        "column_mapping_sets",
        "ck_column_mapping_sets_status",
        f"status IN ({_SET_STATUSES}, 'abandoned')",
    )
    op.create_table(
        "account_mapping_sets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("based_on_set_id", sa.UUID(), nullable=True),
        sa.Column("based_on_import_id", sa.UUID(), nullable=True),
        sa.Column("change_request_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_SET_STATUSES}, 'abandoned')", name=op.f("ck_account_mapping_sets_status")
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["migrations.id"],
            name=op.f("fk_account_mapping_sets_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["based_on_set_id"], ["account_mapping_sets.id"],
            name=op.f("fk_account_mapping_sets_based_on_set_id_account_mapping_sets"),
        ),
        sa.ForeignKeyConstraint(
            ["based_on_import_id"], ["imports.id"],
            name=op.f("fk_account_mapping_sets_based_on_import_id_imports"),
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"], ["change_requests.id"], name=op.f("fk_account_mapping_sets_cr")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_account_mapping_sets_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_mapping_sets")),
        sa.UniqueConstraint(
            "migration_id", "version", name=op.f("uq_account_mapping_sets_migration_id_version")
        ),
    )  # fmt: skip
    op.create_index(
        op.f("uq_account_mapping_sets_one_approved"),
        "account_mapping_sets",
        ["migration_id"],
        unique=True,
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_table(
        "account_mappings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("mapping_set_id", sa.UUID(), nullable=False),
        sa.Column("legacy_account_code", sa.Text(), nullable=False),
        sa.Column("target_account_code", sa.Text(), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "basis IN ('imported', 'exact', 'name_match', 'operator', 'ai_suggested')",
            name=op.f("ck_account_mappings_basis"),
        ),
        sa.ForeignKeyConstraint(
            ["mapping_set_id"], ["account_mapping_sets.id"],
            name=op.f("fk_account_mappings_mapping_set_id_account_mapping_sets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_mappings")),
        sa.UniqueConstraint(
            "mapping_set_id", "legacy_account_code",
            name=op.f("uq_account_mappings_mapping_set_id_legacy_account_code"),
        ),
    )  # fmt: skip
    op.create_table(
        "record_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("dataset_type", sa.Text(), nullable=False),
        sa.Column("natural_key", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=True),
        sa.Column("import_id", sa.UUID(), nullable=True),
        sa.Column("expected_current_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
        sa.Column("reverted_by_cr_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "target IN ('canonical_field', 'quarantined_row_repair')",
            name=op.f("ck_record_overrides_target"),
        ),
        sa.CheckConstraint("status IN ('active', 'reverted')", name=op.f("ck_record_overrides_status")),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["migrations.id"], name=op.f("fk_record_overrides_migration_id_migrations")
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["imports.id"], name=op.f("fk_record_overrides_import_id_imports")
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"], ["change_requests.id"],
            name=op.f("fk_record_overrides_change_request_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_cr_id"], ["change_requests.id"],
            name=op.f("fk_record_overrides_reverted_by_cr_id_change_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_record_overrides")),
    )  # fmt: skip
    op.create_index(
        op.f("ix_record_overrides_migration_status"), "record_overrides", ["migration_id", "status"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    blocked = bind.scalar(
        sa.text(
            "SELECT (SELECT count(*) FROM change_requests WHERE kind = 'revert')"
            " + (SELECT count(*) FROM column_mapping_sets WHERE status = 'abandoned')"
        )
    )
    if blocked:
        # Governed history is never rewritten; a database that used M5 cannot go back to 0002.
        raise RuntimeError("cannot downgrade: revert change requests or abandoned sets exist")
    op.drop_index(op.f("ix_record_overrides_migration_status"), table_name=op.f("record_overrides"))
    op.drop_table("record_overrides")
    op.drop_table("account_mappings")
    op.drop_index(
        op.f("uq_account_mapping_sets_one_approved"), table_name=op.f("account_mapping_sets")
    )
    op.drop_table("account_mapping_sets")
    _replace_check(
        "column_mapping_sets", "ck_column_mapping_sets_status", f"status IN ({_SET_STATUSES})"
    )
    _replace_check("change_requests", "ck_change_requests_kind", f"kind IN ({_KINDS})")
