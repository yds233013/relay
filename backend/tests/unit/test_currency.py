"""ISO 4217 currency registry (FC-04)."""

from __future__ import annotations

import pytest

from relay.core import currency as currency_module
from relay.core.currency import Currency, UnknownCurrencyError, is_known_currency


@pytest.mark.parametrize(
    ("code", "minor_units"),
    [("USD", 2), ("EUR", 2), ("JPY", 0), ("KRW", 0), ("BHD", 3), ("KWD", 3), ("CLF", 4)],
)
def test_minor_units(code: str, minor_units: int) -> None:
    assert Currency.of(code).minor_units == minor_units


@pytest.mark.parametrize(
    "code", ["usd", "Usd", "US", "USDD", " USD", "USD ", "", "XAU", "XTS", "XXX", "ABC", "12A"]
)
def test_rejects_invalid_or_non_transactional_codes(code: str) -> None:
    with pytest.raises(UnknownCurrencyError):
        Currency.of(code)


@pytest.mark.parametrize("value", [None, 840, b"USD"])
def test_rejects_non_string(value: object) -> None:
    with pytest.raises(UnknownCurrencyError):
        Currency.of(value)  # type: ignore[arg-type]


def test_direct_construction_is_validated() -> None:
    with pytest.raises(UnknownCurrencyError):
        Currency(code="USD", minor_units=3)
    with pytest.raises(UnknownCurrencyError):
        Currency(code="QQQ", minor_units=2)


def test_currency_groups_do_not_overlap() -> None:
    groups = [
        currency_module._ZERO_DECIMAL,
        currency_module._TWO_DECIMAL,
        currency_module._THREE_DECIMAL,
        currency_module._FOUR_DECIMAL,
    ]
    seen: set[str] = set()
    for group in groups:
        assert not (seen & group)
        seen |= group
    assert all(len(code) == 3 and code.isupper() for code in seen)


def test_equality_and_str() -> None:
    assert Currency.of("USD") == Currency.of("USD")
    assert Currency.of("USD") != Currency.of("EUR")
    assert str(Currency.of("EUR")) == "EUR"
    assert is_known_currency("GBP")
    assert not is_known_currency("gbp")
