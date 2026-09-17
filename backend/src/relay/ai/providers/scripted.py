"""A deterministic provider that replays an authored transcript (tests, CI, offline demos).

A script is a list of turns. Each turn is ``{"text": ..., "tool_uses": [{"name", "arguments"}]}``.
Arguments may take values from earlier tool results with ``{"$result": <n>, "path": "a.0.b"}``,
where ``n`` counts tool results in the conversation from 1, so a script can use identifiers
(such as reconciliation line ids) that only exist in the database it runs against.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from relay.ai.providers.base import (
    Message,
    ProviderError,
    ToolSchema,
    ToolUse,
    TurnResult,
    Usage,
)


class ScriptedProvider:
    name = "scripted"

    def __init__(self, turns: Sequence[Mapping[str, Any]], model: str = "scripted") -> None:
        self.turns = list(turns)
        self.model = model

    def run_turn(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
        timeout_s: float,
    ) -> TurnResult:
        index = sum(1 for m in messages if m.role == "assistant")
        if index >= len(self.turns):
            return TurnResult(text="(script ended)", tool_uses=(), stop_reason="end_turn")
        turn = self.turns[index]
        results = [r.content for m in messages for r in m.tool_results]
        uses = tuple(
            ToolUse(
                id=f"script-{index}-{n}",
                name=str(use["name"]),
                arguments=_resolve(use.get("arguments", {}), results),
            )
            for n, use in enumerate(turn.get("tool_uses", []))
        )
        return TurnResult(
            text=str(turn.get("text", "")),
            tool_uses=uses,
            stop_reason="tool_use" if uses else "end_turn",
            usage=Usage(input_tokens=0, output_tokens=0),
        )


def _resolve(value: Any, results: list[str]) -> Any:
    if isinstance(value, dict):
        if "$result" in value:
            return _lookup(results, int(value["$result"]), str(value.get("path", "")))
        return {k: _resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(item, results) for item in value]
    return value


def _lookup(results: list[str], number: int, path: str) -> Any:
    if not 1 <= number <= len(results):
        raise ProviderError(f"script refers to tool result {number}, which does not exist")
    data: Any = json.loads(results[number - 1])
    for part in [p for p in path.split(".") if p]:
        try:
            data = data[int(part)] if isinstance(data, list) else data[part]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ProviderError(f"script path {path!r} not found in tool result {number}") from exc
    return data
