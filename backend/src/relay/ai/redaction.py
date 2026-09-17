"""Redaction of tool outputs before they reach a provider (SEC-21, ai-safety.md §6).

Tax ids and bank account numbers keep their last four characters, email addresses keep only their
domain, and free text is truncated. Redaction is applied by field name for canonical fields and by
pattern to every string, so unknown source columns are covered too.
"""

from __future__ import annotations

import re
from typing import Any, Final

MAX_TEXT: Final = 200
_EMAIL: Final = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_LONG_DIGITS: Final = re.compile(r"\b(?:\d[ -]?){9,}\d\b")
_SENSITIVE_NAMES: Final = ("tax", "ein", "ssn", "bank_account", "account_number", "iban", "routing")
_FREE_TEXT_NAMES: Final = ("notes", "note", "memo", "description", "raw_text", "comment")


def _mask(text: str) -> str:
    digits = re.sub(r"\W", "", text)
    return f"…{digits[-4:]}" if len(digits) > 4 else text


def redact_text(text: str, *, free_text: bool = False) -> str:
    redacted = _EMAIL.sub(lambda m: f"<email @{m.group(1)}>", text)
    redacted = _LONG_DIGITS.sub(lambda m: _mask(m.group(0)), redacted)
    if free_text and len(redacted) > MAX_TEXT:
        redacted = redacted[:MAX_TEXT] + "…[truncated]"
    return redacted


def redact(value: Any, key: str = "") -> Any:
    """Redact a JSON-like value recursively; ``key`` is the field or column name if known."""
    lowered = key.casefold().replace(" ", "_")
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    if isinstance(value, str):
        if any(name in lowered for name in _SENSITIVE_NAMES) and "last4" not in lowered:
            return _mask(value)
        if "email" in lowered:
            return _EMAIL.sub(lambda m: f"<email @{m.group(1)}>", value)
        return redact_text(value, free_text=any(name in lowered for name in _FREE_TEXT_NAMES))
    return value
