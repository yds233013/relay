"""UUIDv7 identifiers and canonical hashing."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from relay.core.clock import FrozenClock
from relay.core.hashing import CanonicalEncodingError, canonical_json, fingerprint, sha256_hex
from relay.core.ids import unix_milliseconds, uuid7, uuid7_unix_ms
from relay.core.money import Money
from relay.core.timestamps import TimestampError

# --------------------------------------------------------------------------- UUIDv7


def test_uuid7_layout() -> None:
    clock = FrozenClock(datetime(2026, 9, 17, 8, 30, 0, 123456, tzinfo=UTC))
    value = uuid7(clock, random_bytes=lambda n: b"\xff" * n)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert uuid7_unix_ms(value) == unix_milliseconds(clock.now())
    assert uuid7_unix_ms(value) == 1_789_633_800_123


def test_uuid7_sorts_by_time_across_milliseconds() -> None:
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    ids = []
    for _ in range(50):
        ids.append(uuid7(clock))
        clock.advance(timedelta(milliseconds=1))
    assert ids == sorted(ids)
    assert len(set(ids)) == 50


def test_uuid7_is_random_within_a_millisecond() -> None:
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    assert len({uuid7(clock) for _ in range(1000)}) == 1000


def test_unix_milliseconds_is_integer_exact() -> None:
    # A float-based computation drifts for far-future microsecond values; this must not.
    at = datetime(2999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
    assert unix_milliseconds(at) == 32_503_680_000_000 - 1
    with pytest.raises(TimestampError):
        unix_milliseconds(datetime(2026, 1, 1))  # noqa: DTZ001 - naive on purpose


def test_uuid7_unix_ms_rejects_other_versions() -> None:
    with pytest.raises(ValueError, match="UUIDv7"):
        uuid7_unix_ms(uuid.uuid4())


# --------------------------------------------------------------------------- canonical hashing


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [True, None, "x"]}) == b'{"a":[true,null,"x"],"b":1}'


def test_supported_types_encode_deterministically() -> None:
    value = {
        "amount": Decimal("12.50"),
        "money": Money("12.5", "USD"),
        "date": date(2026, 6, 30),
        "at": datetime(2026, 9, 17, 8, 30, tzinfo=UTC),
        "id": uuid.UUID("01a0aeba-5071-78c7-a539-c0e5c702cdb7"),
        "tuple": ("a", 1),
        "text": "Café",
    }
    assert (
        canonical_json(value)
        == (
            '{"amount":"12.5","at":"2026-09-17T08:30:00.000000Z","date":"2026-06-30",'
            '"id":"01a0aeba-5071-78c7-a539-c0e5c702cdb7","money":{"amount":"12.50","currency":"USD"},'
            '"text":"Café","tuple":["a",1]}'
        ).encode()
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (Decimal("1.50"), Decimal("1.5")),
        (Decimal("-0.00"), Decimal(0)),
        (Decimal("1E+2"), Decimal(100)),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}),
        (Money("1.5", "USD"), Money("1.50", "USD")),
    ],
)
def test_equal_values_have_equal_fingerprints(left: object, right: object) -> None:
    assert fingerprint(left) == fingerprint(right)


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        {"a": 1.0},
        [float("nan")],
        {1: "non-string key"},
        {"a", "b"},
        frozenset({"a"}),
        b"bytes",
        datetime(2026, 1, 1),  # noqa: DTZ001 - naive on purpose
        Decimal("NaN"),
        object(),
    ],
)
def test_unsupported_values_are_rejected(value: object) -> None:
    with pytest.raises((CanonicalEncodingError, TimestampError)):
        canonical_json(value)


def test_sha256_hex() -> None:
    assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert len(fingerprint({"x": 1})) == 64


@given(st.dictionaries(st.text(max_size=5), st.integers() | st.text(max_size=5), max_size=10))
def test_fingerprint_independent_of_insertion_order(data: dict[str, int | str]) -> None:
    reversed_data = dict(reversed(list(data.items())))
    assert fingerprint(data) == fingerprint(reversed_data)
