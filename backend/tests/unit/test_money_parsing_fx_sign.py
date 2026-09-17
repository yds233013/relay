"""Source amount parsing (FC-01), FX rounding (FC-02) and debit/credit sign convention (FC-05)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pytest

from relay.core.currency import Currency, UnknownCurrencyError
from relay.core.money import (
    FX_ROUNDING,
    AmountFormat,
    AmountFormatError,
    AmountOutOfRangeError,
    DebitCreditError,
    InvalidFxRateError,
    Money,
    MoneyError,
    convert,
    parse_amount_text,
    signed_ledger_amount,
    to_functional,
)

US = AmountFormat(
    thousands_separator=",", parentheses_negative=True, currency_symbols=frozenset({"$"})
)
EU = AmountFormat(decimal_separator=",", thousands_separator=".", currency_symbols=frozenset({"€"}))
PLAIN = AmountFormat()

# --------------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("text", "amount_format", "expected"),
    [
        ("1,234.56", US, "1234.56"),
        ("(1,234.56)", US, "-1234.56"),
        ("-1,234.56", US, "-1234.56"),
        ("$1,234.56", US, "1234.56"),
        ("-$1,234.56", US, "-1234.56"),
        ("($1,234.56)", US, "-1234.56"),
        ("  12.50  ", US, "12.50"),
        ("1234.56", US, "1234.56"),
        ("1,234,567.8", US, "1234567.8"),
        ("0.00", US, "0"),
        ("(0.00)", US, "0"),
        ("1.234,56", EU, "1234.56"),
        ("1.234,56 €", EU, "1234.56"),
        ("-12,5", EU, "-12.5"),
        ("42", PLAIN, "42"),
        ("0001", PLAIN, "1"),
    ],
)
def test_parse_declared_formats(text: str, amount_format: AmountFormat, expected: str) -> None:
    result = parse_amount_text(text, amount_format)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert not result.is_signed() or result != 0


@pytest.mark.parametrize(
    ("text", "amount_format"),
    [
        ("", US),
        ("   ", US),
        ("-", US),
        ("1.234,56", US),  # European text under a US format: ambiguous, rejected
        ("1,234.56", EU),
        ("12,34.56", US),  # malformed grouping
        ("1,2345.00", US),
        ("(1.00)", PLAIN),  # parentheses not declared
        ("(1.00", US),
        ("1.00)", US),
        ("(-1.00)", US),
        ("--1.00", US),
        ("+1.00", US),
        ("1e3", US),
        ("£1.00", US),  # undeclared symbol
        ("1,234.56", PLAIN),  # separator not declared
        ("12.3.4", US),
        ("1.23456", US),  # exceeds 4 decimal places: error, not rounding
    ],
)
def test_parse_rejects_text_outside_format(text: str, amount_format: AmountFormat) -> None:
    with pytest.raises((AmountFormatError, AmountOutOfRangeError)):
        parse_amount_text(text, amount_format)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(AmountFormatError):
        parse_amount_text(12.5, US)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"decimal_separator": ";"},
        {"decimal_separator": ",", "thousands_separator": ","},
        {"thousands_separator": "_"},
        {"currency_symbols": frozenset({""})},
        {"currency_symbols": frozenset({"1"})},
    ],
)
def test_invalid_amount_formats(kwargs: dict[str, object]) -> None:
    with pytest.raises(AmountFormatError):
        AmountFormat(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- FX conversion (FC-02)


def test_rounding_mode_is_the_documented_one() -> None:
    assert FX_ROUNDING == ROUND_HALF_UP


@pytest.mark.parametrize(
    ("amount", "rate", "target", "exact", "converted"),
    [
        ("7800.00", "1.0850", "USD", "8463.000000", "8463.00"),
        ("5450.00", "1.0790", "USD", "5880.550000", "5880.55"),
        ("11200.00", "1.1120", "USD", "12454.400000", "12454.40"),
        ("0.01", "0.5", "USD", "0.005", "0.01"),  # tie rounds up
        ("-0.01", "0.5", "USD", "-0.005", "-0.01"),  # tie rounds away from zero, symmetrically
        ("0.01", "0.4", "USD", "0.004", "0.00"),
        ("10.00", "3.3333333333", "USD", "33.333333333000", "33.33"),
        ("100.00", "149.555", "JPY", "14955.50000", "14956"),
        ("1.00", "0.3765432", "KWD", "0.3765432", "0.377"),
    ],
)
def test_convert_rounds_half_up_to_target_minor_units(
    amount: str, rate: str, target: str, exact: str, converted: str
) -> None:
    source_currency = "EUR" if target != "EUR" else "USD"
    result = convert(Money(amount, source_currency), rate, target)
    assert result.exact_amount == Decimal(exact)
    assert result.converted == Money(converted, target)
    assert result.converted.amount_str.count(".") == (
        0 if result.converted.currency.minor_units == 0 else 1
    )
    assert result.converted.amount - result.exact_amount == result.rounding_difference
    assert result.rate == Decimal(rate)


def test_conversion_records_rounding_difference() -> None:
    result = convert(Money("10.00", "EUR"), "3.3333333333", "USD")
    assert result.rounding_difference == Decimal("-0.003333333")


@pytest.mark.parametrize(
    "rate",
    [0, "0", "-1.0", 1.085, True, "1e2", "abc", Decimal("NaN"), "0.00000000001", "10000000000"],
)
def test_invalid_fx_rates(rate: object) -> None:
    with pytest.raises(InvalidFxRateError):
        convert(Money("1.00", "EUR"), rate, "USD")  # type: ignore[arg-type]


def test_same_currency_conversion_rejected() -> None:
    with pytest.raises(InvalidFxRateError):
        convert(Money("1.00", "USD"), "1", "USD")


def test_unknown_target_currency_rejected() -> None:
    with pytest.raises(UnknownCurrencyError):
        convert(Money("1.00", "EUR"), "1.1", "usd")


def test_converted_amount_out_of_range_raises() -> None:
    with pytest.raises(AmountOutOfRangeError):
        convert(Money("9999999999999999.00", "EUR"), "2", "USD")


# ------------------------------------------------------------------------ sign convention (FC-05)


@pytest.mark.parametrize(
    ("debit", "credit", "expected"),
    [
        (Decimal("12500.00"), None, Decimal("12500.00")),
        (None, Decimal("12050.00"), Decimal("-12050.00")),
        (Decimal("450.00"), Decimal(0), Decimal("450.00")),
        (Decimal(0), Decimal("450.00"), Decimal("-450.00")),
        (Decimal(0), Decimal(0), Decimal(0)),
        (Decimal(0), None, Decimal(0)),
    ],
)
def test_debit_positive_credit_negative(
    debit: Decimal | None, credit: Decimal | None, expected: Decimal
) -> None:
    result = signed_ledger_amount(debit, credit)
    assert result == expected
    assert not (result == 0 and result.is_signed())


@pytest.mark.parametrize(
    ("debit", "credit"),
    [
        (None, None),
        (Decimal("1.00"), Decimal("1.00")),
        (Decimal("-1.00"), None),
        (None, Decimal("-1.00")),
        (Decimal("1.00"), Decimal("-1.00")),
        (1.0, None),
        (Decimal("0.00001"), None),
    ],
)
def test_ambiguous_or_invalid_debit_credit_pairs(debit: object, credit: object) -> None:
    with pytest.raises(MoneyError):
        signed_ledger_amount(debit, credit)  # type: ignore[arg-type]


def test_both_sides_nonzero_is_a_debit_credit_error() -> None:
    with pytest.raises(DebitCreditError, match="both a debit and a credit"):
        signed_ledger_amount(Decimal("5"), Decimal("5"))


# Digit systems whose code points `\\d` also matches. Written as offsets rather than literals so
# this file stays unambiguous ASCII.
FULLWIDTH, ARABIC_INDIC, DEVANAGARI = 0xFF10, 0x0660, 0x0966


def in_digits(text: str, zero: int) -> str:
    return "".join(chr(zero + int(ch)) if ch.isdigit() else ch for ch in text)


@pytest.mark.parametrize("zero", [FULLWIDTH, ARABIC_INDIC, DEVANAGARI])
@pytest.mark.parametrize("written", ["123", "1,234.56", "0.50"])
def test_amounts_written_in_non_ascii_digits_are_refused(written: str, zero: int) -> None:
    """Review pass 2: `\\d` accepts these, and the stored number would not be the one a reader of
    the file sees. An explicit format means ASCII digits."""
    amount_format = AmountFormat(thousands_separator=",", parentheses_negative=True)
    assert parse_amount_text(written, amount_format) is not None  # the ASCII form parses
    with pytest.raises(AmountFormatError):
        parse_amount_text(in_digits(written, zero), amount_format)


def test_a_single_non_ascii_digit_inside_an_amount_is_refused() -> None:
    mixed = "1" + chr(FULLWIDTH + 2) + "3.45"
    with pytest.raises(AmountFormatError):
        parse_amount_text(mixed, AmountFormat())


def test_to_functional_rounds_half_away_from_zero_not_to_even() -> None:
    """Review pass 1 (D3): converting by hand picked Python's banker's rounding and two decimals.

    0.125 and 0.135 are the pair that separates the two modes; JPY shows the minor units matter.
    """
    usd = Currency.of("USD")
    assert to_functional(Money(Decimal("0.25"), Currency.of("EUR")), "0.5", usd).amount == Decimal(
        "0.13"
    )  # half away from zero, not 0.12
    assert to_functional(Money(Decimal("0.27"), Currency.of("EUR")), "0.5", usd).amount == Decimal(
        "0.14"
    )
    assert to_functional(Money(Decimal("-0.25"), Currency.of("EUR")), "0.5", usd).amount == Decimal(
        "-0.13"
    )
    yen = to_functional(Money(Decimal("100.00"), Currency.of("USD")), "150.456", "JPY")
    assert yen.amount == Decimal("15046")  # zero minor units, not two


def test_to_functional_returns_a_functional_amount_unchanged() -> None:
    exact = Money(Decimal("1234.5678"), Currency.of("USD"))
    assert to_functional(exact, "1", Currency.of("USD")) == exact
