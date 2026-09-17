"""The default provider: AI is off, and callers check availability before asking."""

from __future__ import annotations

from collections.abc import Sequence

from relay.ai.providers.base import AIUnavailableError, Message, ToolSchema, TurnResult


class DisabledProvider:
    name = "disabled"
    model = ""

    def run_turn(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
        timeout_s: float,
    ) -> TurnResult:
        raise AIUnavailableError("AI investigation is disabled (RELAY_AI_PROVIDER=disabled)")
