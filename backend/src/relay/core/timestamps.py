"""System and audit timestamps.

System timestamps record *when something happened in Relay* (an import, an approval, an audit
event). They are always timezone-aware and normalized to UTC (FC-06). Naive datetimes are rejected
rather than assumed to be UTC or local time.

Serialized form is RFC 3339 with microseconds and a ``Z`` suffix, e.g.
``2026-09-17T08:30:00.000000Z``, so identical instants always serialize identically.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Final

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from relay.core.errors import InvalidInputError


class TimestampError(InvalidInputError):
    code: ClassVar[str] = "timestamp.invalid"
    title: ClassVar[str] = "Invalid timestamp"


_RFC3339: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)


def ensure_utc(value: object) -> datetime:
    """Return an aware datetime converted to UTC. Naive datetimes are rejected."""
    if not isinstance(value, datetime):
        raise TimestampError("timestamp must be a datetime.datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise TimestampError("timestamp must be timezone-aware; naive datetimes are rejected")
    return value.astimezone(UTC)


def format_timestamp(value: datetime) -> str:
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(text: object) -> datetime:
    """Parse an RFC 3339 timestamp that carries an explicit offset; return it in UTC."""
    if not isinstance(text, str) or _RFC3339.fullmatch(text) is None:
        raise TimestampError("timestamp must be RFC 3339 with an explicit offset, e.g. ...Z")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise TimestampError(f"not a valid timestamp: {exc}") from exc
    return ensure_utc(parsed)


class _UtcTimestampSchema:
    """Pydantic schema for :data:`UtcTimestamp`: aware input only, serialized as UTC ``Z``."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> datetime:
            if isinstance(value, str):
                return parse_timestamp(value)
            return ensure_utc(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                format_timestamp, when_used="always"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "format": "date-time"}


UtcTimestamp = Annotated[datetime, _UtcTimestampSchema]
"""Pydantic field type for system timestamps. Static type is ``datetime``."""
