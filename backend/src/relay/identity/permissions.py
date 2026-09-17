"""Role → permission table. Authorization is decided here and nowhere else (SEC-10)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from relay.identity.models import Role


class Permission(StrEnum):
    READ = "read"
    MANAGE_WORKSPACE = "manage_workspace"
    UPLOAD_IMPORT = "upload_import"
    REQUEST_PIPELINE_RUN = "request_pipeline_run"
    DRAFT_CHANGE_REQUEST = "draft_change_request"
    REVIEW_CHANGE_REQUEST = "review_change_request"
    MANAGE_ISSUES = "manage_issues"


_OPERATOR: Final = frozenset(
    {
        Permission.READ,
        Permission.UPLOAD_IMPORT,
        Permission.REQUEST_PIPELINE_RUN,
        Permission.DRAFT_CHANGE_REQUEST,
        Permission.MANAGE_ISSUES,
    }
)

ROLE_PERMISSIONS: Final[dict[Role, frozenset[Permission]]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.IMPLEMENTATION_SPECIALIST: _OPERATOR,
    Role.IMPLEMENTATION_LEAD: _OPERATOR
    | {Permission.MANAGE_WORKSPACE, Permission.REVIEW_CHANGE_REQUEST},
    Role.CUSTOMER_CONTROLLER: frozenset(
        {
            Permission.READ,
            Permission.DRAFT_CHANGE_REQUEST,
            Permission.REVIEW_CHANGE_REQUEST,
            Permission.MANAGE_ISSUES,
        }
    ),
    Role.ADMIN: frozenset({Permission.READ, Permission.MANAGE_WORKSPACE}),
}


def allowed(role: str, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
