"""Business dates vs. system timestamps (FC-06, FC-07)."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, ValidationError

from relay.core.clock import FrozenClock, SystemClock
from relay.core.dates import (
    BusinessDate,
    BusinessDateError,
    DateFormat,
    FiscalPeriod,
    ensure_business_date,
    fiscal_period_for,
    format_business_date,
    is_ambiguous_day_month,
    parse_business_date,
    parse_iso_business_date,
)
from relay.core.timestamps import (
    TimestampError,
    UtcTimestamp,
    ensure_utc,
    format_timestamp,
    parse_timestamp,
)

business_dates = st.dates(min_value=date(1900, 1, 1), max_value=date(2999, 12, 31))
TIMEZONES = [
    "UTC",
    "Pacific/Kiritimati",
    "Pacific/Pago_Pago",
    "America/Los_Angeles",
    "Asia/Kolkata",
]


@pytest.fixture(params=TIMEZONES)
def process_timezone(request: pytest.FixtureRequest) -> Iterator[str]:
    """Run a test with the process-local timezone set to extremes (UTC+14 and UTC-11 included)."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = request.param
    time.tzset()
    try:
        yield request.param
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


# --------------------------------------------------------------------------- business dates


@pytest.mark.parametrize(
    ("text", "date_format", "expected"),
    [
        ("2026-03-14", DateFormat.ISO, date(2026, 3, 14)),
        ("20260314", DateFormat.COMPACT, date(2026, 3, 14)),
        ("03/14/2026", DateFormat.US_PADDED, date(2026, 3, 14)),
        ("3/4/2026", DateFormat.US, date(2026, 3, 4)),
        ("03/04/2026", DateFormat.US, date(2026, 3, 4)),
        ("04/03/2026", DateFormat.EU_PADDED, date(2026, 3, 4)),
        ("4/3/2026", DateFormat.EU, date(2026, 3, 4)),
        ("14.03.2026", DateFormat.EU_DOTTED, date(2026, 3, 14)),
        (" 2026-06-30 ", DateFormat.ISO, date(2026, 6, 30)),
        ("2028-02-29", DateFormat.ISO, date(2028, 2, 29)),
    ],
)
def test_parse_with_explicit_format(text: str, date_format: DateFormat, expected: date) -> None:
    parsed = parse_business_date(text, date_format)
    assert parsed == expected
    assert type(parsed) is date


@pytest.mark.parametrize(
    ("text", "date_format"),
    [
        ("2026-02-29", DateFormat.ISO),  # not a leap year
        ("2026-13-01", DateFormat.ISO),
        ("2026-3-14", DateFormat.ISO),
        ("14/03/2026", DateFormat.US_PADDED),  # month 14
        ("3/4/26", DateFormat.US),  # two-digit year unsupported
        ("2026-03-14T00:00:00", DateFormat.ISO),
        ("2026-03-14Z", DateFormat.ISO),
        ("03-14-2026", DateFormat.US_PADDED),
        ("", DateFormat.ISO),
        ("1899-12-31", DateFormat.ISO),
        ("3000-01-01", DateFormat.ISO),
    ],
)
def test_parse_rejects_mismatch(text: str, date_format: DateFormat) -> None:
    with pytest.raises(BusinessDateError):
        parse_business_date(text, date_format)


def test_datetime_is_not_a_business_date() -> None:
    # datetime is a subclass of date; accepting it would let timezones leak into accounting dates.
    with pytest.raises(BusinessDateError, match="timestamp"):
        ensure_business_date(datetime(2026, 3, 14, tzinfo=UTC))
    with pytest.raises(BusinessDateError):
        ensure_business_date(datetime(2026, 3, 14))  # noqa: DTZ001 - naive on purpose
    with pytest.raises(BusinessDateError):
        ensure_business_date("2026-03-14")
    with pytest.raises(BusinessDateError):
        format_business_date(datetime(2026, 3, 14, tzinfo=UTC))


@given(business_dates)
def test_iso_round_trip(value: date) -> None:
    assert parse_iso_business_date(format_business_date(value)) == value


@pytest.mark.usefixtures("process_timezone")
def test_business_dates_do_not_move_across_process_timezones() -> None:
    for text in ["2026-06-30", "2026-01-01", "2025-12-31", "2028-02-29"]:
        parsed = parse_iso_business_date(text)
        assert format_business_date(parsed) == text
        assert parse_business_date(text.replace("-", ""), DateFormat.COMPACT) == parsed


def test_the_same_instant_is_different_calendar_days_but_business_dates_are_unaffected() -> None:
    # 2026-06-30T23:30 in Los Angeles is already 2026-07-01 in UTC. A business date must never be
    # derived by converting such an instant; Relay's APIs prevent it by rejecting datetimes.
    instant = datetime(2026, 6, 30, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert instant.astimezone(UTC).date() == date(2026, 7, 1)
    cutover = parse_iso_business_date("2026-06-30")
    with pytest.raises(BusinessDateError):
        ensure_business_date(instant)
    assert cutover == date(2026, 6, 30)


@pytest.mark.parametrize(
    ("text", "ambiguous"),
    [
        ("03/04/2026", True),
        ("3/4/2026", True),
        ("03/03/2026", False),
        ("13/04/2026", False),
        ("04/13/2026", False),
        ("2026-03-04", False),
        ("03.04.2026", True),
    ],
)
def test_ambiguous_day_month(text: str, ambiguous: bool) -> None:
    assert is_ambiguous_day_month(text) is ambiguous


@pytest.mark.parametrize(
    ("value", "start_month", "expected"),
    [
        (date(2026, 1, 1), 1, FiscalPeriod(2026, 1, "2026-01")),
        (date(2026, 12, 31), 1, FiscalPeriod(2026, 12, "2026-12")),
        (date(2026, 7, 1), 7, FiscalPeriod(2027, 1, "2026-07")),
        (date(2026, 6, 30), 7, FiscalPeriod(2026, 12, "2026-06")),
        (date(2027, 1, 15), 7, FiscalPeriod(2027, 7, "2027-01")),
        (date(2028, 2, 29), 4, FiscalPeriod(2028, 11, "2028-02")),
        (date(2026, 3, 31), 4, FiscalPeriod(2026, 12, "2026-03")),
        (date(2026, 4, 1), 4, FiscalPeriod(2027, 1, "2026-04")),
    ],
)
def test_fiscal_periods(value: date, start_month: int, expected: FiscalPeriod) -> None:
    assert fiscal_period_for(value, start_month) == expected


@given(business_dates.filter(lambda d: d.year < 2999), st.integers(min_value=1, max_value=12))
def test_fiscal_period_invariants(value: date, start_month: int) -> None:
    period = fiscal_period_for(value, start_month)
    assert 1 <= period.period <= 12
    assert period.calendar_month == value.isoformat()[:7]
    # Every day of a calendar month lands in the same fiscal period.
    assert fiscal_period_for(value.replace(day=1), start_month) == period


@pytest.mark.parametrize("start_month", [0, 13, -1, True])
def test_fiscal_start_month_validation(start_month: int) -> None:
    with pytest.raises(BusinessDateError):
        fiscal_period_for(date(2026, 1, 1), start_month)


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_date: BusinessDate
    created_at: UtcTimestamp


def test_pydantic_business_date_and_timestamp_round_trip() -> None:
    payload = '{"entry_date":"2026-03-14","created_at":"2026-09-17T01:30:00-07:00"}'
    entry = _Entry.model_validate_json(payload)
    assert entry.entry_date == date(2026, 3, 14)
    assert type(entry.entry_date) is date
    assert entry.created_at == datetime(2026, 9, 17, 8, 30, tzinfo=UTC)
    assert entry.created_at.tzinfo is UTC
    assert entry.model_dump_json() == (
        '{"entry_date":"2026-03-14","created_at":"2026-09-17T08:30:00.000000Z"}'
    )
    assert _Entry.model_validate_json(entry.model_dump_json()) == entry


@pytest.mark.parametrize(
    "entry_date",
    [
        '"2026-03-14T00:00:00Z"',
        '"2026-03-14T00:00:00"',
        "20260314",
        '"03/14/2026"',
        '" 2026-03-14"',
        "null",
    ],
)
def test_pydantic_business_date_rejects_timestamps_and_other_forms(entry_date: str) -> None:
    with pytest.raises(ValidationError):
        _Entry.model_validate_json(
            f'{{"entry_date":{entry_date},"created_at":"2026-09-17T08:30:00Z"}}'
        )


def test_pydantic_business_date_rejects_datetime_objects() -> None:
    with pytest.raises(ValidationError):
        _Entry(
            entry_date=datetime(2026, 3, 14, tzinfo=UTC),
            created_at=datetime(2026, 9, 17, tzinfo=UTC),
        )


# --------------------------------------------------------------------------- system timestamps


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(TimestampError, match="timezone-aware"):
        ensure_utc(datetime(2026, 9, 17, 8, 30))  # noqa: DTZ001 - naive on purpose
    with pytest.raises(TimestampError):
        ensure_utc(date(2026, 9, 17))


def test_aware_datetimes_are_normalized_to_utc() -> None:
    local = datetime(2026, 9, 17, 1, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    normalized = ensure_utc(local)
    assert normalized.tzinfo is UTC
    assert normalized == local
    assert normalized.hour == 8


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-17T08:30:00Z", "2026-09-17T08:30:00.000000Z"),
        ("2026-09-17T08:30:00.5Z", "2026-09-17T08:30:00.500000Z"),
        ("2026-09-17T01:30:00-07:00", "2026-09-17T08:30:00.000000Z"),
        ("2026-09-18T00:30:00+14:00", "2026-09-17T10:30:00.000000Z"),
    ],
)
def test_timestamp_parse_and_format(text: str, expected: str) -> None:
    assert format_timestamp(parse_timestamp(text)) == expected


@pytest.mark.parametrize(
    "text",
    ["2026-09-17T08:30:00", "2026-09-17 08:30:00Z", "2026-09-17", "2026-09-17T25:00:00Z", ""],
)
def test_timestamps_without_offset_or_invalid_are_rejected(text: str) -> None:
    with pytest.raises(TimestampError):
        parse_timestamp(text)


@given(
    st.datetimes(
        min_value=datetime(1970, 1, 1),  # noqa: DTZ001 - hypothesis bounds are naive
        max_value=datetime(2999, 12, 31),  # noqa: DTZ001
        timezones=st.sampled_from(
            [UTC, timezone(timedelta(hours=-11)), timezone(timedelta(hours=14))]
        ),
    )
)
def test_timestamp_round_trip_preserves_instant(value: datetime) -> None:
    restored = parse_timestamp(format_timestamp(value))
    assert restored == value
    assert restored.tzinfo is UTC


@pytest.mark.usefixtures("process_timezone")
def test_system_clock_is_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is UTC
    assert abs(now - datetime.now(UTC)) < timedelta(seconds=5)


def test_frozen_clock() -> None:
    clock = FrozenClock(datetime(2026, 9, 17, 1, 30, tzinfo=ZoneInfo("America/Los_Angeles")))
    assert clock.now() == datetime(2026, 9, 17, 8, 30, tzinfo=UTC)
    assert clock.now().tzinfo is UTC
    clock.advance(timedelta(minutes=5))
    assert clock.now() == datetime(2026, 9, 17, 8, 35, tzinfo=UTC)
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(timedelta(seconds=-1))
    with pytest.raises(TimestampError):
        FrozenClock(datetime(2026, 9, 17))  # noqa: DTZ001 - naive on purpose


@pytest.mark.parametrize("zero", [0xFF10, 0x0660, 0x0966])
def test_dates_written_in_non_ascii_digits_are_refused(zero: int) -> None:
    """Review pass 2: the same hardening as amounts. A date must read as itself."""
    written = "2026-03-31"
    assert parse_business_date(written, DateFormat.ISO) == date(2026, 3, 31)
    other = "".join(chr(zero + int(ch)) if ch.isdigit() else ch for ch in written)
    with pytest.raises(BusinessDateError):
        parse_business_date(other, DateFormat.ISO)
    with pytest.raises(BusinessDateError):
        parse_business_date("2026-" + other[5:7] + "-31", DateFormat.ISO)
