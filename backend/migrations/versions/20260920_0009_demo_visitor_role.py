"""The demo_visitor role.

The public demo (``RELAY_ENV=demo``) resolves every anonymous caller to one seeded user holding
READ and REQUEST_INVESTIGATION and nothing else. ``users.role`` is TEXT with a CHECK listing the
allowed values, so the new role has to be admitted here before that user can exist.

Downgrade removes any user holding the role first: leaving one behind would violate the narrower
constraint it restores.

Revision ID: 0009_demo_visitor_role
Revises: 0008_superseded_runs
"""

from __future__ import annotations

from alembic import op

revision = "0009_demo_visitor_role"
down_revision = "0008_superseded_runs"
branch_labels = None
depends_on = None

_WITHOUT_DEMO = (
    "role IN ('implementation_specialist', 'implementation_lead', "
    "'customer_controller', 'admin', 'viewer')"
)
_WITH_DEMO = (
    "role IN ('implementation_specialist', 'implementation_lead', "
    "'customer_controller', 'admin', 'viewer', 'demo_visitor')"
)


# The metadata naming convention expands a bare name to ck_<table>_<name>, so "role" here is the
# constraint the baseline created as ck_users_role. Passing the full name would look for
# ck_users_ck_users_role.
_NAME = "role"


def upgrade() -> None:
    op.drop_constraint(_NAME, "users", type_="check")
    op.create_check_constraint(_NAME, "users", _WITH_DEMO)


def downgrade() -> None:
    # The demo visitor is created by `relay-demo public-demo`, never by a user action, so deleting
    # it is losing nothing that cannot be recreated by running that command again.
    op.execute("DELETE FROM users WHERE role = 'demo_visitor'")
    op.drop_constraint(_NAME, "users", type_="check")
    op.create_check_constraint(_NAME, "users", _WITHOUT_DEMO)
