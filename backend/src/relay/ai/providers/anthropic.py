"""Anthropic Messages API provider over the standard library (no SDK dependency).

Request and response shapes follow the Messages API documentation (checked 2026-09-17):
``POST /v1/messages`` with ``x-api-key`` and ``anthropic-version`` headers; ``tools`` carry
``name``, ``description`` and ``input_schema``; responses contain ``text`` and ``tool_use`` content
blocks, a ``stop_reason`` and ``usage``. Tool results go back as ``tool_result`` blocks. The API key
is used only in the request header and never logged. ``temperature`` is not sent: the current
documentation marks it deprecated.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Final

from relay.ai.providers.base import (
    Message,
    ProviderError,
    ToolSchema,
    ToolUse,
    TurnResult,
    Usage,
)

API_VERSION: Final = "2023-06-01"
RETRYABLE: Final = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS: Final = 4

type Transport = Callable[[urllib.request.Request, float], tuple[int, bytes]]


def _urlopen(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https base URL from settings
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        transport: Transport = _urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ProviderError("the provider base URL must use https")
        self._api_key = api_key
        self.model = model
        self._url = base_url.rstrip("/") + "/v1/messages"
        self._transport = transport
        self._sleep = sleep

    def run_turn(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
        timeout_s: float,
    ) -> TurnResult:
        body = json.dumps(self.request_body(system, messages, tools, max_output_tokens)).encode()
        request = urllib.request.Request(  # noqa: S310 - https enforced in __init__
            self._url,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
        )
        deadline = time.monotonic() + timeout_s
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderError("the provider did not answer within the investigation budget")
            try:
                status, payload = self._transport(request, remaining)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise ProviderError(f"could not reach the provider ({type(exc).__name__})") from exc
            if status == 200:
                return self.parse_response(json.loads(payload))
            if status not in RETRYABLE or attempt == MAX_ATTEMPTS:
                raise ProviderError(f"the provider returned HTTP {status}")
            self._sleep(min(8.0, 0.5 * 2**attempt) * (0.5 + random.random()))  # noqa: S311 - jitter
        raise ProviderError("the provider did not answer")

    def request_body(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "system": system,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": dict(t.input_schema)}
                for t in tools
            ],
            "messages": [_message(m) for m in messages],
        }

    @staticmethod
    def parse_response(payload: dict[str, Any]) -> TurnResult:
        texts: list[str] = []
        uses: list[ToolUse] = []
        for block in payload.get("content", []):
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                uses.append(
                    ToolUse(
                        id=str(block["id"]),
                        name=str(block["name"]),
                        arguments=dict(block.get("input") or {}),
                    )
                )
        usage = payload.get("usage") or {}
        return TurnResult(
            text="\n".join(texts),
            tool_uses=tuple(uses),
            stop_reason=str(payload.get("stop_reason", "")),
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
            ),
        )


def _message(message: Message) -> dict[str, Any]:
    if message.role == "assistant":
        content: list[dict[str, Any]] = []
        if message.text:
            content.append({"type": "text", "text": message.text})
        content.extend(
            {"type": "tool_use", "id": u.id, "name": u.name, "input": dict(u.arguments)}
            for u in message.tool_uses
        )
        return {"role": "assistant", "content": content}
    if message.tool_results:
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": r.tool_use_id,
                    "content": r.content,
                    "is_error": r.is_error,
                }
                for r in message.tool_results
            ],
        }
    return {"role": "user", "content": message.text}
