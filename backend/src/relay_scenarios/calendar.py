"""Business-day helpers (weekends only; the scenarios do not model bank holidays)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta


def is_business_day(value: date) -> bool:
    return value.weekday() < 5


def next_business_day(value: date) -> date:
    """``value`` itself if it is a business day, otherwise the following Monday."""
    while not is_business_day(value):
        value += timedelta(days=1)
    return value


def previous_business_day(value: date) -> date:
    while not is_business_day(value):
        value -= timedelta(days=1)
    return value


def add_business_days(value: date, days: int) -> date:
    result = value
    remaining = days
    while remaining > 0:
        result += timedelta(days=1)
        if is_business_day(result):
            remaining -= 1
    return result


def days(start: date, end: date) -> Iterator[date]:
    """Inclusive date range."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def month_end(year: int, month: int) -> date:
    first_next = date(year + (month // 12), month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def last_business_day(year: int, month: int) -> date:
    return previous_business_day(month_end(year, month))
