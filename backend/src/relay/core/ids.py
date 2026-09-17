"""UUIDv7 identifiers (RFC 9562).

Python 3.12's ``uuid`` module has no ``uuid7``, so it is implemented here. IDs embed a millisecond
Unix timestamp, so they sort by creation time across milliseconds. Ordering *within* one millisecond
is random: IDs are identifiers, not sequence numbers, and nothing in Relay relies on
intra-millisecond order (audit ordering uses explicit sequence columns).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from relay.core.clock import Clock, SystemClock
from relay.core.timestamps import ensure_utc

_MAX_UNIX_MS: Final = (1 << 48) - 1
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def unix_milliseconds(at: datetime) -> int:
    """Whole milliseconds since the Unix epoch, computed with integers (no float rounding)."""
    delta = ensure_utc(at) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def uuid7(
    clock: Clock | None = None, random_bytes: Callable[[int], bytes] = os.urandom
) -> uuid.UUID:
    unix_ms = unix_milliseconds(ensure_utc((clock or SystemClock()).now()))
    if not 0 <= unix_ms <= _MAX_UNIX_MS:
        raise ValueError("timestamp out of UUIDv7 range")
    rand = int.from_bytes(random_bytes(10), "big")
    rand_a = (rand >> 62) & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7_unix_ms(value: uuid.UUID) -> int:
    if value.version != 7:
        raise ValueError("not a UUIDv7")
    return value.int >> 80
