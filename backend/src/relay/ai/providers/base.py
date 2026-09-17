"""Provider protocol (ai-safety.md §2.1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

from relay.core.errors import RelayError


class AIUnavailableError(RelayError):
    code: ClassVar[str] = "ai.unavailable"
    title: ClassVar[str] = "AI investigation is not available"
    http_status: ClassVar[int] = 409


class ProviderError(RelayError):
    code: ClassVar[str] = "ai.provider_error"
    title: ClassVar[str] = "The AI provider failed"
    http_status: ClassVar[int] = 502


@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolUse:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Message:
    """``role`` is ``user`` or ``assistant``. Assistant messages carry text and tool uses; user
    messages carry text or tool results."""

    role: Literal["user", "assistant"]
    text: str = ""
    tool_uses: tuple[ToolUse, ...] = ()
    tool_results: tuple[ToolResultBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TurnResult:
    text: str
    tool_uses: tuple[ToolUse, ...]
    stop_reason: str
    usage: Usage = field(default_factory=Usage)


class LLMProvider(Protocol):
    name: str
    model: str

    def run_turn(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
        timeout_s: float,
    ) -> TurnResult: ...
