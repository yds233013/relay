"""A deterministic provider that replays authored transcripts, for demonstrations without a model.

This is **not** a model and must never be presented as one. It exists so the investigation workflow
can be shown, and tested, with no network, no key and no variance: the same issue always produces
the same transcript, and the same tools really run against the real database, so the evidence in a
demo investigation is genuine even though the reasoning is canned.

A scripts directory holds one JSON file per transcript::

    {"match": {"rules": ["RECON.R3", "MAP.SUBTYPE_COMPATIBLE"]}, "turns": [...]}

The opening message the investigator sends names the issue's rule, so a transcript is chosen by
matching that rule. When nothing matches, the fallback transcript is replayed — and the fallback
says, in the model's own output, that the evidence in front of it does not settle the question.
That is the honest behaviour for a canned provider faced with a question it was not written for.

Turn syntax is the scripted provider's (see :mod:`relay.ai.providers.scripted`), including
``{"$result": n, "path": "a.0.b"}`` substitution so a transcript can use identifiers that only
exist in the database it is replayed against.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from relay.ai.providers.base import (
    AIUnavailableError,
    Message,
    ToolSchema,
    TurnResult,
)
from relay.ai.providers.scripted import ScriptedProvider

FALLBACK_FILE: Final = "fallback.json"

#: The opening message carries the server-rendered issue summary, which names the issue.
_ISSUE_KEY: Final = re.compile(r'"key"\s*:\s*"([A-Z]{2,8}-\d+)"')


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "turns" not in data:
        raise AIUnavailableError(f"{path.name} has no turns")
    return data


class DemoProvider:
    """Replays the transcript whose declared rules match the issue under investigation."""

    name = "demo"

    def __init__(self, scripts_dir: Path, model: str = "scripted demonstration") -> None:
        files = sorted(scripts_dir.glob("*.json"))
        if not files:
            raise AIUnavailableError(f"no transcripts in {scripts_dir}")
        self.model = model
        self._by_rule: dict[str, dict[str, Any]] = {}
        self._fallback: dict[str, Any] | None = None
        for path in files:
            data = _load(path)
            if path.name == FALLBACK_FILE:
                self._fallback = data
                continue
            for rule in data.get("match", {}).get("rules", []):
                self._by_rule[str(rule)] = data
        if self._fallback is None:
            raise AIUnavailableError(f"no {FALLBACK_FILE} in {scripts_dir}")
        self._delegate: ScriptedProvider | None = None

    @staticmethod
    def _render(value: Any, issue_key: str) -> Any:
        """Fill ``{{issue_key}}`` so a transcript can be written without knowing the key."""
        if isinstance(value, str):
            return value.replace("{{issue_key}}", issue_key)
        if isinstance(value, list):
            return [DemoProvider._render(item, issue_key) for item in value]
        if isinstance(value, dict):
            return {k: DemoProvider._render(v, issue_key) for k, v in value.items()}
        return value

    def _select(self, messages: Sequence[Message]) -> dict[str, Any]:
        opening = messages[0].text if messages else ""
        # Longest rule first so a specific rule wins over a prefix of itself.
        for rule in sorted(self._by_rule, key=len, reverse=True):
            if rule in opening:
                return self._by_rule[rule]
        return self._fallback or {"turns": []}

    def run_turn(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSchema],
        max_output_tokens: int,
        timeout_s: float,
    ) -> TurnResult:
        if self._delegate is None:
            opening = messages[0].text if messages else ""
            found = _ISSUE_KEY.search(opening)
            turns = self._render(self._select(messages)["turns"], found.group(1) if found else "")
            self._delegate = ScriptedProvider(turns, model=self.model)
        return self._delegate.run_turn(
            system=system,
            messages=messages,
            tools=tools,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s,
        )
