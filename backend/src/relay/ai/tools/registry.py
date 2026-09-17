"""Tool contract (ai-safety.md §3.1). The model never chooses the migration or the run."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from relay.core.errors import RelayError


class ToolError(RelayError):
    """A tool could not answer (not found, out of scope). Returned to the model as an error."""

    code: ClassVar[str] = "ai.tool_error"
    title: ClassVar[str] = "Tool error"
    http_status: ClassVar[int] = 422


@dataclass(frozen=True, slots=True)
class ToolContext:
    session: Session
    """A READ ONLY session (``SET TRANSACTION READ ONLY``)."""
    migration_id: uuid.UUID
    run_id: uuid.UUID


type Handler = Callable[[ToolContext, Any], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Handler
    max_items: int = 50
    terminal: bool = False

    def schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema
