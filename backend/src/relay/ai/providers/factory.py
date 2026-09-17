"""Build the configured provider. Keys come only from settings (the environment)."""

from __future__ import annotations

import json
from typing import Final

from relay.ai.providers.anthropic import AnthropicProvider
from relay.ai.providers.base import AIUnavailableError, LLMProvider
from relay.ai.providers.disabled import DisabledProvider
from relay.ai.providers.scripted import ScriptedProvider
from relay.core.config import Settings

SCRIPT_FILE: Final = "investigator.json"


def provider_from_settings(settings: Settings) -> LLMProvider:
    if settings.ai_provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise AIUnavailableError("ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.ai_model,
            base_url=settings.ai_api_base_url,
        )
    if settings.ai_provider == "scripted":
        if settings.ai_scripts_dir is None:
            raise AIUnavailableError("RELAY_AI_SCRIPTS_DIR is not set for the scripted provider")
        path = settings.ai_scripts_dir / SCRIPT_FILE
        if not path.is_file():
            raise AIUnavailableError(f"no {SCRIPT_FILE} in RELAY_AI_SCRIPTS_DIR")
        return ScriptedProvider(json.loads(path.read_text(encoding="utf-8"))["turns"])
    return DisabledProvider()
