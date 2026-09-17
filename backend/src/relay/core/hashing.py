"""Canonical JSON and SHA-256 fingerprints.

Used for content hashes and, later, pipeline input fingerprints. The encoding is deterministic:
sorted keys, no insignificant whitespace, UTF-8. Types are restricted so that equal values always
encode identically:

* ``float`` is rejected (FC-01).
* ``set``/``frozenset`` are rejected: their order is not defined. Sort into a list first.
* ``Decimal`` encodes as a minimal fixed-point string (``1.50`` -> ``"1.5"``, ``-0`` -> ``"0"``).
* ``Money`` encodes as its canonical ``{"amount", "currency"}`` object.
* ``date`` encodes as ``YYYY-MM-DD``; ``datetime`` must be aware and encodes in UTC.
* ``UUID`` encodes as its canonical string.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import ClassVar

from relay.core.dates import format_business_date
from relay.core.errors import InvalidInputError
from relay.core.money import Money
from relay.core.timestamps import format_timestamp


class CanonicalEncodingError(InvalidInputError):
    code: ClassVar[str] = "hashing.unsupported_value"
    title: ClassVar[str] = "Value cannot be canonically encoded"


type JsonValue = bool | int | str | list[JsonValue] | dict[str, JsonValue] | None


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise CanonicalEncodingError("non-finite decimals cannot be encoded")
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")


def to_canonical(value: object) -> JsonValue:  # noqa: PLR0911 - one branch per supported type
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        raise CanonicalEncodingError("floats are not allowed in canonical data")
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Money):
        return dict(value.to_json())
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, date):
        return format_business_date(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError("mapping keys must be strings")
            result[key] = to_canonical(item)
        return result
    if isinstance(value, set | frozenset):
        raise CanonicalEncodingError("sets have no defined order; sort them into a list")
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [to_canonical(item) for item in value]
    raise CanonicalEncodingError(f"unsupported type {type(value).__name__}")


def canonical_json(value: object) -> bytes:
    return json.dumps(
        to_canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value: object) -> str:
    return sha256_hex(canonical_json(value))
