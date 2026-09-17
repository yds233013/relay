"""Money construction, validation, arithmetic, comparison and serialization (FC-01 - FC-04)."""

from __future__ import annotations

import copy
import json
import pickle
from collections.abc import Callable
from decimal import Decimal, localcontext

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from relay.core.currency import Currency, UnknownCurrencyError
from relay.core.errors import InvalidInputError
from relay.core.money import (
    AMOUNT_LIMIT,
    AmountOutOfRangeError,
    CurrencyMismatchError,
    InvalidAmountError,
    Money,
    sum_money,
    validate_amount,
    within_tolerance,
)

# --------------------------------------------------------------------------- construction (FC-01)


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("12.5"), "USD", "12.50"),
        (Decimal("12.500"), "USD", "12.50"),
        ("12.50", "USD", "12.50"),
        ("-1234.5", "USD", "-1234.50"),
        (100, "USD", "100.00"),
        (0, "USD", "0.00"),
        ("100", "JPY", "100"),
        ("1.5", "BHD", "1.500"),
        ("0.1234", "USD", "0.1234"),
        (Decimal("1E+3"), "USD", "1000.00"),
        (Decimal("9999999999999999.9999"), "USD", "9999999999999999.9999"),
        (Decimal("-9999999999999999.9999"), "USD", "-9999999999999999.9999"),
    ],
)
def test_construction_canonicalizes(
    amount: Decimal | int | str, currency: str, expected: str
) -> None:
    money = Money(amount, currency)
    assert money.amount_str == expected
    assert money.currency == Currency.of(currency)
    assert isinstance(money.amount, Decimal)


@pytest.mark.parametrize("value", [0.1, 1.0, float("nan"), float("inf"), -0.0])
def test_float_amounts_are_rejected(value: float) -> None:
    with pytest.raises(InvalidAmountError, match="float"):
        Money(value, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False])
def test_bool_amounts_are_rejected(value: bool) -> None:
    with pytest.raises(InvalidAmountError, match="boolean"):
        Money(value, "USD")


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_non_finite_decimals_are_rejected(value: Decimal) -> None:
    with pytest.raises(InvalidAmountError, match="finite"):
        Money(value, "USD")


@pytest.mark.parametrize(
    "value",
    [
        "", " 1.00", "1.00 ", "+1.00", "1e3", "1E3", "1,000.00", "1.000,00", "01.00", "-01",
        ".5", "5.", "--1", "1.0.0", "$1.00", "(1.00)", "NaN", "Infinity", "٣", "1_000",
    ],
)  # fmt: skip
def test_non_plain_decimal_strings_are_rejected(value: str) -> None:
    with pytest.raises(InvalidAmountError):
        Money(value, "USD")


@pytest.mark.parametrize("value", [None, [], {}, object(), b"1.00", 1 + 0j])
def test_other_types_are_rejected(value: object) -> None:
    with pytest.raises(InvalidAmountError):
        Money(value, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["1.23456", Decimal("0.00001"), "-0.00005", Decimal("1.23456")])
def test_more_than_four_decimal_places_raise_instead_of_rounding(value: str | Decimal) -> None:
    with pytest.raises(AmountOutOfRangeError, match="refusing to round"):
        Money(value, "USD")


def test_trailing_zeros_beyond_scale_are_not_extra_precision() -> None:
    assert Money(Decimal("1.230000000"), "USD").amount_str == "1.23"


@pytest.mark.parametrize(
    "value",
    [AMOUNT_LIMIT, -AMOUNT_LIMIT, "10000000000000000", Decimal("1E+16"), Decimal("1E+100")],
)
def test_magnitude_limit(value: Decimal | str) -> None:
    with pytest.raises(AmountOutOfRangeError):
        Money(value, "USD")


def test_extremely_long_digit_strings_are_rejected_cleanly() -> None:
    with pytest.raises(AmountOutOfRangeError):
        Money("0." + "1" * 200, "USD")


def test_negative_zero_is_normalized() -> None:
    money = Money(Decimal("-0.00"), "USD")
    assert money.amount_str == "0.00"
    assert not money.amount.is_signed()
    assert money == Money.zero("USD")


def test_unknown_currency_is_rejected() -> None:
    with pytest.raises(UnknownCurrencyError):
        Money("1.00", "usd")


def test_sub_minor_precision_is_preserved_and_flagged() -> None:
    money = Money("12.345", "USD")
    assert money.amount_str == "12.345"
    assert money.has_sub_minor_precision
    assert not Money("12.34", "USD").has_sub_minor_precision
    assert Money("1", "JPY").has_sub_minor_precision is False
    assert Money("1.5", "JPY").has_sub_minor_precision


def test_money_errors_are_input_errors_with_codes() -> None:
    with pytest.raises(InvalidInputError) as info:
        Money(0.5, "USD")  # type: ignore[arg-type]
    assert info.value.code == "money.invalid_amount"


def test_validation_is_independent_of_the_ambient_decimal_context() -> None:
    with localcontext() as ctx:
        ctx.prec = 3
        money = Money("1234567.8912", "USD") + Money("0.0001", "USD")
    assert money.amount_str == "1234567.8913"


# --------------------------------------------------------------------------- immutability


def test_immutable() -> None:
    money = Money("1.00", "USD")
    with pytest.raises(AttributeError):
        money._amount = Decimal(5)
    with pytest.raises(AttributeError):
        del money._currency


def test_copy_and_pickle_preserve_value() -> None:
    money = Money("-42.1234", "EUR")
    assert copy.deepcopy(money) == money
    assert pickle.loads(pickle.dumps(money)) == money  # noqa: S301 - trusted, local data


def test_truthiness_is_ambiguous() -> None:
    with pytest.raises(TypeError):
        bool(Money("0.00", "USD"))


# --------------------------------------------------------------------------- arithmetic (FC-04)


def test_addition_and_subtraction_are_exact() -> None:
    assert Money("0.10", "USD") + Money("0.20", "USD") == Money("0.30", "USD")
    # The classic binary-float failure (0.1 + 0.2 != 0.3) cannot occur.
    assert (Money("0.1", "USD") + Money("0.2", "USD")).amount == Decimal("0.3")
    total = Money.zero("USD")
    for _ in range(10):
        total = total + Money("0.1", "USD")
    assert total == Money("1.00", "USD")
    assert Money("100.00", "USD") - Money("100.01", "USD") == Money("-0.01", "USD")
    assert (Money("1.2345", "USD") + Money("0.0005", "USD")).amount_str == "1.235"


def test_addition_overflowing_the_envelope_raises() -> None:
    near_max = Money("9999999999999999.9999", "USD")
    with pytest.raises(AmountOutOfRangeError):
        near_max + Money("0.0001", "USD")


def test_negation_and_abs() -> None:
    assert -Money("5.00", "USD") == Money("-5.00", "USD")
    assert abs(Money("-5.00", "USD")) == Money("5.00", "USD")
    assert (-Money("0", "USD")).amount_str == "0.00"


def test_sign_predicates() -> None:
    assert Money("0.01", "USD").is_positive()
    assert Money("-0.01", "USD").is_negative()
    assert Money("0", "USD").is_zero()


@pytest.mark.parametrize("operation", ["add", "sub", "lt", "le", "gt", "ge"])
def test_currency_mismatch_raises(operation: str) -> None:
    usd, eur = Money("1.00", "USD"), Money("1.00", "EUR")
    operations: dict[str, Callable[[], object]] = {
        "add": lambda: usd + eur,
        "sub": lambda: usd - eur,
        "lt": lambda: usd < eur,
        "le": lambda: usd <= eur,
        "gt": lambda: usd > eur,
        "ge": lambda: usd >= eur,
    }
    with pytest.raises(CurrencyMismatchError):
        operations[operation]()


@pytest.mark.parametrize("other", [1, Decimal(1), 1.0, "1.00", None])
def test_mixing_with_non_money_is_a_type_error(other: object) -> None:
    money = Money("1.00", "USD")
    with pytest.raises(TypeError):
        _ = money + other  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = other + money  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = money - other  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = money < other  # type: ignore[operator]


@pytest.mark.parametrize("factor", [2, Decimal(2), 2.0])
def test_multiplication_and_division_are_not_supported(factor: object) -> None:
    money = Money("1.00", "USD")
    with pytest.raises(TypeError):
        _ = money * factor  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = money / factor  # type: ignore[operator]


def test_builtin_sum_is_rejected_and_sum_money_requires_currency() -> None:
    values = [Money("1.10", "USD"), Money("2.20", "USD")]
    with pytest.raises(TypeError):
        sum(values)  # type: ignore[arg-type]
    assert sum_money(values, "USD") == Money("3.30", "USD")
    assert sum_money([], "USD") == Money.zero("USD")
    with pytest.raises(CurrencyMismatchError):
        sum_money(values, "EUR")
    with pytest.raises(CurrencyMismatchError):
        sum_money([Money("1", "USD"), Money("1", "EUR")], "USD")


# --------------------------------------------------------------------------- comparison


def test_ordering_same_currency() -> None:
    assert Money("1.00", "USD") < Money("1.01", "USD")
    assert Money("1.00", "USD") <= Money("1.0", "USD")
    assert Money("-1", "USD") > Money("-2", "USD")
    assert Money("2", "USD") >= Money("2.0000", "USD")


def test_equality_is_by_value_and_currency() -> None:
    assert Money("1.5", "USD") == Money("1.5000", "USD")
    assert Money("1.00", "USD") != Money("1.00", "EUR")
    assert Money("1.00", "USD") != Decimal("1.00")
    assert Money("1.00", "USD") != "1.00 USD"


def test_hash_consistent_with_equality() -> None:
    assert hash(Money("1.5", "USD")) == hash(Money("1.50", "USD"))
    assert len({Money("1.5", "USD"), Money("1.50", "USD"), Money("1.5", "EUR")}) == 2


# --------------------------------------------------------------------------- tolerance (FC-03)


def test_within_tolerance_is_exact() -> None:
    tolerance = Money("0.01", "USD")
    assert within_tolerance(Money("0.01", "USD"), tolerance)
    assert within_tolerance(Money("-0.01", "USD"), tolerance)
    # 0.0101 would round to 0.01 at two places; the exact comparison must fail it.
    assert not within_tolerance(Money("0.0101", "USD"), tolerance)
    assert not within_tolerance(Money("-0.0101", "USD"), tolerance)
    assert within_tolerance(Money("0", "USD"), Money("0", "USD"))
    assert not within_tolerance(Money("0.0001", "USD"), Money("0", "USD"))


def test_tolerance_validation() -> None:
    with pytest.raises(InvalidAmountError):
        within_tolerance(Money("0", "USD"), Money("-0.01", "USD"))
    with pytest.raises(CurrencyMismatchError):
        within_tolerance(Money("0", "USD"), Money("0.01", "EUR"))


# --------------------------------------------------------------------------- serialization


def test_json_round_trip() -> None:
    money = Money("-1234.5", "EUR")
    data = money.to_json()
    assert data == {"amount": "-1234.50", "currency": "EUR"}
    assert Money.from_json(json.loads(json.dumps(data))) == money


def test_serialization_is_deterministic_for_equal_values() -> None:
    variants = [
        Money(Decimal("12.5"), "USD"),
        Money("12.50", "USD"),
        Money(Decimal("12.5000"), "USD"),
    ]
    encoded = {json.dumps(v.to_json(), sort_keys=True) for v in variants}
    assert encoded == {'{"amount": "12.50", "currency": "USD"}'}


def test_repr_and_str() -> None:
    money = Money("7", "USD")
    assert repr(money) == "Money('7.00', 'USD')"
    assert str(money) == "7.00 USD"


def test_amount_string_never_uses_exponent_notation() -> None:
    assert Money(Decimal("1E+15"), "USD").amount_str == "1000000000000000.00"
    assert Money(Decimal("1E-4"), "USD").amount_str == "0.0001"


@pytest.mark.parametrize(
    "data",
    [
        {"amount": 1.5, "currency": "USD"},
        {"amount": 1, "currency": "USD"},
        {"amount": "1.50"},
        {"currency": "USD"},
        {"amount": "1.50", "currency": "USD", "extra": "x"},
        {"amount": "1.50", "currency": 840},
        {"amount": "1,50", "currency": "USD"},
        "1.50 USD",
        ["1.50", "USD"],
        None,
    ],
)
def test_from_json_is_strict(data: object) -> None:
    with pytest.raises(InvalidInputError):
        Money.from_json(data)


class _Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: Money


def test_pydantic_round_trip_serializes_amount_as_string() -> None:
    invoice = _Invoice.model_validate_json('{"total": {"amount": "9340.00", "currency": "USD"}}')
    assert invoice.total == Money("9340", "USD")
    assert invoice.model_dump_json() == '{"total":{"amount":"9340.00","currency":"USD"}}'
    assert invoice.model_dump() == {"total": {"amount": "9340.00", "currency": "USD"}}
    assert _Invoice(total=Money("1", "USD")).total.amount_str == "1.00"


@pytest.mark.parametrize(
    "payload",
    [
        '{"total": {"amount": 9340.0, "currency": "USD"}}',
        '{"total": {"amount": 9340, "currency": "USD"}}',
        '{"total": {"amount": "9340.001234", "currency": "USD"}}',
        '{"total": {"amount": "9340.00", "currency": "XXX"}}',
        '{"total": "9340.00"}',
        '{"total": 9340.0}',
    ],
)
def test_pydantic_rejects_floats_numbers_and_invalid_money(payload: str) -> None:
    with pytest.raises(ValidationError):
        _Invoice.model_validate_json(payload)


def test_pydantic_json_schema_declares_string_amount() -> None:
    schema = _Invoice.model_json_schema()
    money_schema = schema["properties"]["total"]
    assert money_schema["properties"]["amount"]["type"] == "string"
    assert money_schema["additionalProperties"] is False


def test_validate_amount_returns_decimal() -> None:
    assert validate_amount("12.30") == Decimal("12.30")
    assert validate_amount(Decimal("-0")) == Decimal(0)
