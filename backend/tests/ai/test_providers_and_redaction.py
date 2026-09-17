"""Providers (request/response shapes, retries, key handling) and output redaction."""

from __future__ import annotations

import json
import urllib.request

import pytest

from relay.ai.providers.anthropic import API_VERSION, AnthropicProvider
from relay.ai.providers.base import (
    AIUnavailableError,
    Message,
    ProviderError,
    ToolResultBlock,
    ToolSchema,
    ToolUse,
)
from relay.ai.providers.disabled import DisabledProvider
from relay.ai.providers.scripted import ScriptedProvider
from relay.ai.redaction import redact

SCHEMA = ToolSchema("get_issue", "An issue", {"type": "object", "properties": {}})


def test_anthropic_request_carries_the_key_only_in_its_header() -> None:
    seen: list[urllib.request.Request] = []

    def transport(request: urllib.request.Request, _timeout: float) -> tuple[int, bytes]:
        seen.append(request)
        body = {
            "content": [
                {"type": "text", "text": "Looking."},
                {"type": "tool_use", "id": "toolu_1", "name": "get_issue",
                 "input": {"issue_key": "X-1"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }  # fmt: skip
        return 200, json.dumps(body).encode()

    provider = AnthropicProvider(
        api_key="sk-test-secret", model="claude-opus-5", transport=transport
    )
    history = [
        Message(role="user", text="Why?"),
        Message(role="assistant", tool_uses=(ToolUse("toolu_0", "get_issue", {"issue_key": "X"}),)),
        Message(role="user", tool_results=(ToolResultBlock("toolu_0", "{}", is_error=True),)),
    ]
    turn = provider.run_turn(
        system="rules", messages=history, tools=[SCHEMA], max_output_tokens=100, timeout_s=5
    )
    assert turn.tool_uses == (ToolUse("toolu_1", "get_issue", {"issue_key": "X-1"}),)
    assert (turn.usage.input_tokens, turn.usage.output_tokens, turn.stop_reason) == (
        12, 7, "tool_use"
    )  # fmt: skip
    (request,) = seen
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["x-api-key"] == "sk-test-secret"
    assert headers["anthropic-version"] == API_VERSION
    assert isinstance(request.data, bytes)
    body = json.loads(request.data)
    assert "sk-test-secret" not in request.data.decode()
    assert body["model"] == "claude-opus-5"
    assert "temperature" not in body
    assert body["tools"] == [{"name": "get_issue", "description": "An issue",
                              "input_schema": {"type": "object", "properties": {}}}]  # fmt: skip
    assert body["messages"][1]["content"][0]["type"] == "tool_use"
    assert body["messages"][2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "toolu_0", "content": "{}", "is_error": True
    }  # fmt: skip
    assert "sk-test-secret" not in repr(provider.__dict__.get("model"))


def test_anthropic_retries_rate_limits_and_fails_on_client_errors() -> None:
    answers = iter(
        [(429, b"{}"), (529, b"{}"), (200, b'{"content": [], "stop_reason": "end_turn"}')]
    )
    sleeps: list[float] = []
    provider = AnthropicProvider(
        api_key="k", model="m", transport=lambda _r, _t: next(answers), sleep=sleeps.append
    )
    turn = provider.run_turn(system="", messages=[], tools=[], max_output_tokens=1, timeout_s=60)
    assert turn.stop_reason == "end_turn"
    assert len(sleeps) == 2
    failing = AnthropicProvider(api_key="k", model="m", transport=lambda _r, _t: (400, b"{}"))
    with pytest.raises(ProviderError, match="HTTP 400"):
        failing.run_turn(system="", messages=[], tools=[], max_output_tokens=1, timeout_s=60)
    with pytest.raises(ProviderError, match="https"):
        AnthropicProvider(api_key="k", model="m", base_url="http://example.test")


def test_disabled_provider_refuses_and_scripted_provider_resolves_earlier_results() -> None:
    with pytest.raises(AIUnavailableError):
        DisabledProvider().run_turn(
            system="", messages=[], tools=[], max_output_tokens=1, timeout_s=1
        )
    scripted = ScriptedProvider(
        [
            {"tool_uses": [{"name": "a", "arguments": {}}]},
            {
                "tool_uses": [
                    {"name": "b", "arguments": {"id": {"$result": 1, "path": "lines.0.id"}}}
                ]
            },
        ]
    )
    first = scripted.run_turn(system="", messages=[], tools=[], max_output_tokens=1, timeout_s=1)
    history = [
        Message(role="assistant", tool_uses=first.tool_uses),
        Message(role="user", tool_results=(ToolResultBlock("x", '{"lines": [{"id": "L7"}]}'),)),
    ]
    second = scripted.run_turn(
        system="", messages=history, tools=[], max_output_tokens=1, timeout_s=1
    )
    assert second.tool_uses[0].arguments == {"id": "L7"}


def test_redaction_masks_identifiers_emails_and_long_free_text() -> None:
    value = {
        "tax_id": "12-3457781",
        "tax_id_last4": "7781",
        "email": "ap@greenvalley.coop",
        "notes": "Call 503-555-0101 x" + "y" * 400,
        "bank_account_number": "000123456789",
        "Check/Ref No": "40219",
        "memo": "Paid to ops@vendor.example from 9876543210123",
    }
    redacted = redact(value)
    assert redacted["tax_id"] == "…7781"
    assert redacted["tax_id_last4"] == "7781"
    assert redacted["email"] == "<email @greenvalley.coop>"
    assert redacted["notes"].endswith("…[truncated]")
    assert len(redacted["notes"]) < 230
    assert redacted["bank_account_number"] == "…6789"
    assert redacted["Check/Ref No"] == "40219"
    assert "ops@" not in redacted["memo"]
    assert "9876543210123" not in redacted["memo"]
