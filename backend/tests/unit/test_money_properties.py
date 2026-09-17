"""Property-based tests for money invariants (FC-01 - FC-05)."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from relay.core.money import (
    AMOUNT_SCALE,
    AmountFormat,
    Money,
    parse_amount_text,
    signed_ledger_amount,
    sum_money,
    within_tolerance,
)

# Amounts that fit NUMERIC(20,4), built from integers so no float is ever involved.
amounts = st.integers(min_value=-(10**20) + 1, max_value=10**20 - 1).map(
    lambda units: Decimal(units).scaleb(-AMOUNT_SCALE)
)
small_amounts = st.integers(min_value=-(10**12), max_value=10**12).map(
    lambda units: Decimal(units).scaleb(-AMOUNT_SCALE)
)
currencies = st.sampled_from(["USD", "EUR", "JPY", "KWD", "CLF"])


@given(amounts, currencies)
def test_json_round_trip_is_lossless(amount: Decimal, currency: str) -> None:
    money = Money(amount, currency)
    restored = Money.from_json(money.to_json())
    assert restored == money
    assert restored.amount == amount
    assert restored.to_json() == money.to_json()


@given(amounts, currencies)
def test_equal_values_have_identical_serialization(amount: Decimal, currency: str) -> None:
    padded = Decimal(amount).quantize(Decimal("1.0000"))
    assert Money(amount, currency).to_json() == Money(padded, currency).to_json()


@given(small_amounts, small_amounts, small_amounts)
def test_addition_is_exact_associative_and_invertible(a: Decimal, b: Decimal, c: Decimal) -> None:
    x, y, z = Money(a, "USD"), Money(b, "USD"), Money(c, "USD")
    assert (x + y) + z == x + (y + z)
    assert x + y == y + x
    assert (x + y) - y == x
    assert (x + y).amount == a + b


@given(st.lists(small_amounts, max_size=50))
def test_sum_is_order_independent(values: list[Decimal]) -> None:
    items = [Money(v, "EUR") for v in values]
    assert sum_money(items, "EUR") == sum_money(reversed(items), "EUR")
    assert sum_money(items, "EUR").amount == sum(values, Decimal(0))


@given(st.lists(small_amounts, min_size=1, max_size=30))
def test_balanced_entry_sums_to_zero(values: list[Decimal]) -> None:
    # Debit-positive lines plus their offsetting credits always net to exactly zero.
    lines = [Money(v, "USD") for v in values] + [-Money(v, "USD") for v in values]
    assert sum_money(lines, "USD").is_zero()


@given(
    small_amounts, st.integers(min_value=0, max_value=10**8).map(lambda u: Decimal(u).scaleb(-4))
)
def test_tolerance_matches_exact_absolute_comparison(
    difference: Decimal, tolerance: Decimal
) -> None:
    assert within_tolerance(Money(difference, "USD"), Money(tolerance, "USD")) is (
        abs(difference) <= tolerance
    )


@given(
    st.integers(min_value=0, max_value=10**15),
    st.integers(min_value=0, max_value=99),
    st.booleans(),
)
def test_us_format_parse_round_trip(units: int, cents: int, negative: bool) -> None:
    grouped = f"{units:,}.{cents:02d}"
    text = f"({grouped})" if negative else grouped
    fmt = AmountFormat(thousands_separator=",", parentheses_negative=True)
    expected = Decimal(f"{units}.{cents:02d}")
    assert parse_amount_text(text, fmt) == (-expected if negative else expected)


@given(small_amounts)
def test_debit_credit_columns_round_trip_through_signed_amount(amount: Decimal) -> None:
    debit = amount if amount > 0 else None
    credit = -amount if amount < 0 else None
    if debit is None and credit is None:
        debit = Decimal(0)
    assert signed_ledger_amount(debit, credit) == amount
