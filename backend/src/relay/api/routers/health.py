"""Health endpoints.

* ``GET /health`` — liveness: the process is serving requests. Never touches the database.
* ``GET /health/ready`` — the API can do useful work: the database is reachable and its schema is at
  the Alembic head revision. Returns 503 otherwise. (Named "ready" in the HTTP sense; unrelated to
  launch readiness.)
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from relay import __version__
from relay.core.db import current_revision, head_revision, ping
from relay.core.logging import get_logger

router = APIRouter(tags=["health"])
_log = get_logger("relay.api.health")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    service: Literal["relay-api"]
    version: str


class DatabaseStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reachable: bool
    migrations: Literal["at_head", "not_at_head", "unknown"]
    current_revision: str | None
    head_revision: str | None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok", "unavailable"]
    database: DatabaseStatus


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="relay-api", version=__version__)


@router.get(
    "/health/ready",
    responses={503: {"model": ReadinessResponse, "description": "Dependencies unavailable"}},
)
def ready(response: Response, engine: Annotated[Engine, Depends(get_engine)]) -> ReadinessResponse:
    head = head_revision()
    try:
        ping(engine)
        current = current_revision(engine)
    except SQLAlchemyError as exc:
        # Log only the error class: driver messages can include host names and user names.
        _log.warning("database_unreachable", error_type=type(exc).__name__)
        response.status_code = 503
        return ReadinessResponse(
            status="unavailable",
            database=DatabaseStatus(
                reachable=False, migrations="unknown", current_revision=None, head_revision=head
            ),
        )

    at_head = current is not None and current == head
    if not at_head:
        response.status_code = 503
    return ReadinessResponse(
        status="ok" if at_head else "unavailable",
        database=DatabaseStatus(
            reachable=True,
            migrations="at_head" if at_head else "not_at_head",
            current_revision=current,
            head_revision=head,
        ),
    )
