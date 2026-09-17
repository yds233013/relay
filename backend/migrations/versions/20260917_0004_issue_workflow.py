"""M6: entity decisions, dispositions, issue links and comments.

Generated with autogenerate, then edited: plain SQL column types, explicit index names, and the
append-only trigger for issue comments (comments are immutable; edits are new comments).

Revision ID: 0004_issue_workflow
Revises: 0003_governance
Create Date: 2026-09-17 15:48:38.216507+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_issue_workflow"
down_revision: str | None = "0003_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("party_type", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("members", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("survivor", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
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
            "decision IN ('same_entity', 'distinct')", name=op.f("ck_entity_decisions_decision")
        ),
        sa.CheckConstraint(
            "party_type IN ('customer', 'vendor')", name=op.f("ck_entity_decisions_party_type")
        ),
        sa.CheckConstraint(
            "status IN ('active', 'reverted')", name=op.f("ck_entity_decisions_status")
        ),
        sa.ForeignKeyConstraint(
            ["change_request_id"],
            ["change_requests.id"],
            name=op.f("fk_entity_decisions_change_request_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"],
            ["migrations.id"],
            name=op.f("fk_entity_decisions_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_cr_id"],
            ["change_requests.id"],
            name=op.f("fk_entity_decisions_reverted_by_cr_id_change_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_decisions")),
    )
    op.create_index(
        op.f("ix_entity_decisions_migration_status"),
        "entity_decisions",
        ["migration_id", "status"],
        unique=False,
    )
    op.create_table(
        "dispositions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("currency", sa.CHAR(length=3), nullable=True),
        sa.Column("follow_up", sa.Text(), nullable=False),
        sa.Column("follow_up_owner_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_request_id", sa.UUID(), nullable=False),
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
            "kind IN ('carry_forward_adjustment', 'accepted_risk', 'false_positive', "
            "'not_applicable')",
            name=op.f("ck_dispositions_kind"),
        ),
        sa.CheckConstraint("status IN ('active', 'reverted')", name=op.f("ck_dispositions_status")),
        sa.ForeignKeyConstraint(
            ["change_request_id"],
            ["change_requests.id"],
            name=op.f("fk_dispositions_change_request_id_change_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["follow_up_owner_id"],
            ["users.id"],
            name=op.f("fk_dispositions_follow_up_owner_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["issues.id"], name=op.f("fk_dispositions_issue_id_issues")
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"],
            ["migrations.id"],
            name=op.f("fk_dispositions_migration_id_migrations"),
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_cr_id"],
            ["change_requests.id"],
            name=op.f("fk_dispositions_reverted_by_cr_id_change_requests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispositions")),
    )
    op.create_index(
        op.f("ix_dispositions_migration_status"),
        "dispositions",
        ["migration_id", "status"],
        unique=False,
    )
    op.create_table(
        "issue_comments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("issue_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"], ["users.id"], name=op.f("fk_issue_comments_author_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["issues.id"], name=op.f("fk_issue_comments_issue_id_issues")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_comments")),
    )
    op.create_index(
        op.f("ix_issue_comments_issue"), "issue_comments", ["issue_id", "created_at"], unique=False
    )
    op.create_table(
        "issue_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("migration_id", sa.UUID(), nullable=False),
        sa.Column("from_issue_id", sa.UUID(), nullable=False),
        sa.Column("to_issue_id", sa.UUID(), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("created_by_actor_type", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "created_by_actor_type IN ('system', 'user')",
            name=op.f("ck_issue_links_created_by_actor_type"),
        ),
        sa.CheckConstraint(
            "link_type IN ('same_root_cause', 'caused_by', 'blocks', 'duplicates')",
            name=op.f("ck_issue_links_link_type"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_issue_links_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["from_issue_id"], ["issues.id"], name=op.f("fk_issue_links_from_issue_id_issues")
        ),
        sa.ForeignKeyConstraint(
            ["migration_id"], ["migrations.id"], name=op.f("fk_issue_links_migration_id_migrations")
        ),
        sa.ForeignKeyConstraint(
            ["to_issue_id"], ["issues.id"], name=op.f("fk_issue_links_to_issue_id_issues")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_links")),
        sa.UniqueConstraint(
            "from_issue_id",
            "to_issue_id",
            "link_type",
            name=op.f("uq_issue_links_from_issue_id_to_issue_id_link_type"),
        ),
    )
    op.execute(
        "CREATE TRIGGER issue_comments_append_only BEFORE UPDATE OR DELETE ON issue_comments "
        "FOR EACH ROW EXECUTE FUNCTION relay_reject_modification()"
    )
    op.execute(
        "CREATE TRIGGER issue_comments_no_truncate BEFORE TRUNCATE ON issue_comments "
        "FOR EACH STATEMENT EXECUTE FUNCTION relay_reject_modification()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER issue_comments_no_truncate ON issue_comments")
    op.execute("DROP TRIGGER issue_comments_append_only ON issue_comments")
    op.drop_table("issue_links")
    op.drop_index(op.f("ix_issue_comments_issue"), table_name="issue_comments")
    op.drop_table("issue_comments")
    op.drop_index(op.f("ix_dispositions_migration_status"), table_name="dispositions")
    op.drop_table("dispositions")
    op.drop_index(op.f("ix_entity_decisions_migration_status"), table_name="entity_decisions")
    op.drop_table("entity_decisions")
