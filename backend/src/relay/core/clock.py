"""Injectable clock.

Application code obtains the current time only through a :class:`Clock`, never through
``datetime.now()`` directly, so tests can freeze time and results stay deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from relay.core.timestamps import ensure_utc


class Clock(Protocol):
    def now(self) -> datetime:
        """Current instant, timezone-aware, in UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Test clock that only moves when told to."""

    def __init__(self, at: datetime) -> None:
        self._now = ensure_utc(at)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("a clock cannot move backwards")
        self._now = self._now + delta

    def set(self, at: datetime) -> None:
        self._now = ensure_utc(at)
