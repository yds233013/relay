"""Financial amount primitives.

Implements requirements FC-01 through FC-05 from ``docs/security-and-correctness.md``.

Decisions (see also ``docs/decisions/0001-money-representation.md``):

* **Representation.** Amounts are :class:`decimal.Decimal`. Binary floats are rejected everywhere:
  in constructors, arithmetic, comparisons, Pydantic models and database binds. ``bool`` is
  rejected even though it is an ``int`` subclass.
* **Storage envelope.** Amounts must fit ``NUMERIC(20,4)``: at most 4 decimal places and an absolute
  value below 10**16. Values outside the envelope raise; they are never rounded to fit.
* **No silent rounding.** All arithmetic runs in a decimal context that *traps* ``Inexact`` and
  ``Rounded``. The only rounding operation is FX conversion (:func:`convert`), which uses
  ``ROUND_HALF_UP`` to the target currency's minor units and reports the rounding difference.
* **Sub-minor precision is preserved, not rejected.** ``Money("12.345", "USD")`` is valid because
  legacy systems do export such values; rejecting them would lose evidence and rounding them would
  alter source data. :attr:`Money.has_sub_minor_precision` lets rules flag them.
* **Canonical form.** Equal amounts have identical representations: the canonical scale is the
  larger of the currency's minor units and the smallest scale that represents the value exactly.
  ``Money("12.5", "USD")`` and ``Money("12.500", "USD")`` both serialize as ``"12.50"``. Negative
  zero is normalized to zero.
* **Currency mismatches raise.** Adding, subtracting or ordering amounts in different currencies
  raises :class:`CurrencyMismatchError`. Equality across currencies is ``False`` (so that ``Money``
  values remain usable in sets and dicts), never an implicit conversion.
* **Sign convention (FC-05).** Canonical ledger amounts are debit-positive and credit-negative.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Clamped,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    Subnormal,
    Underflow,
)
from typing import Any, ClassVar, Final, final

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from relay.core.currency import Currency
from relay.core.errors import InvalidInputError

# ---------------------------------------------------------------------------------------------
# Errors


class MoneyError(InvalidInputError):
    code: ClassVar[str] = "money.invalid"
    title: ClassVar[str] = "Invalid monetary value"


class InvalidAmountError(MoneyError):
    code: ClassVar[str] = "money.invalid_amount"
    title: ClassVar[str] = "Invalid amount"


class AmountOutOfRangeError(MoneyError):
    code: ClassVar[str] = "money.amount_out_of_range"
    title: ClassVar[str] = "Amount outside the supported range"


class CurrencyMismatchError(MoneyError):
    code: ClassVar[str] = "money.currency_mismatch"
    title: ClassVar[str] = "Currency mismatch"


class AmountFormatError(MoneyError):
    code: ClassVar[str] = "money.unparseable_amount"
    title: ClassVar[str] = "Amount text does not match the declared format"


class InvalidFxRateError(MoneyError):
    code: ClassVar[str] = "money.invalid_fx_rate"
    title: ClassVar[str] = "Invalid FX rate"


class DebitCreditError(MoneyError):
    code: ClassVar[str] = "money.invalid_debit_credit"
    title: ClassVar[str] = "Invalid debit/credit pair"


# ---------------------------------------------------------------------------------------------
# Envelope and decimal contexts

AMOUNT_PRECISION: Final = 20
"""Total digits of the database amount column: ``NUMERIC(20,4)``."""
AMOUNT_SCALE: Final = 4
"""Maximum decimal places of an amount."""
AMOUNT_LIMIT: Final = Decimal(10) ** (AMOUNT_PRECISION - AMOUNT_SCALE)
"""Exclusive upper bound on the absolute value of an amount."""

FX_RATE_PRECISION: Final = 20
FX_RATE_SCALE: Final = 10
FX_RATE_LIMIT: Final = Decimal(10) ** (FX_RATE_PRECISION - FX_RATE_SCALE)

FX_ROUNDING: Final = ROUND_HALF_UP
"""The single documented rounding mode, used only by :func:`convert` (FC-02)."""

_EXACT_TRAPS: Final = [
    Clamped, DivisionByZero, Inexact, InvalidOperation, Overflow, Rounded, Subnormal, Underflow,
]  # fmt: skip

# Arithmetic context: any operation that would lose information raises instead.
_EXACT: Final = Context(prec=60, rounding=ROUND_HALF_EVEN, traps=_EXACT_TRAPS)

# Rescaling (quantize/normalize) of an exact value. Removing trailing zeros signals ``Rounded`` even
# though no value is lost, so only ``Inexact`` (a non-zero digit discarded) is trapped here.
_EXACT_RESCALE: Final = Context(
    prec=60, rounding=ROUND_HALF_EVEN, traps=[Inexact, InvalidOperation, Overflow, Clamped]
)

# Only for the explicit FX quantize step: rounding is expected there.
_FX_QUANTIZE: Final = Context(
    prec=60, rounding=FX_ROUNDING, traps=[DivisionByZero, InvalidOperation, Overflow]
)

# Strict textual form for API and serialized data: optional minus, digits, optional fraction.
# No exponent, no plus sign, no whitespace, no separators, no leading zeros.
# Digits are ASCII only: `\d` would also accept Devanagari, Arabic-Indic or full-width digits, and
# an amount whose digits are not the ones a reader sees is never something to guess at.
_STRICT_AMOUNT_PATTERN: Final = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


# ---------------------------------------------------------------------------------------------
# Amount validation


def _exponent_of(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # 'n', 'N' or 'F': NaN, sNaN, Infinity
        raise InvalidAmountError("amount must be a finite number")
    return exponent


def _smallest_exact_scale(value: Decimal) -> int:
    """The fewest decimal places that represent ``value`` exactly."""
    _exponent_of(value)
    if value.is_zero():
        return 0
    try:
        normalized = value.normalize(_EXACT_RESCALE)
    except (Inexact, Overflow, Clamped) as exc:
        raise AmountOutOfRangeError("value has too many significant digits") from exc
    return max(0, -_exponent_of(normalized))


def _to_decimal(value: object, *, what: str) -> Decimal:
    # bool is checked first: it is an int subclass and must never be treated as a number.
    if isinstance(value, bool):
        raise InvalidAmountError(f"{what} must not be a boolean")
    if isinstance(value, float):
        raise InvalidAmountError(
            f"{what} must not be a float; use a decimal string or decimal.Decimal"
        )
    if isinstance(value, Decimal):
        _exponent_of(value)
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        if _STRICT_AMOUNT_PATTERN.fullmatch(value) is None:
            raise InvalidAmountError(
                f"{what} string must be a plain decimal such as '-1234.50' "
                "(no exponent, sign '+', separators, whitespace or leading zeros)"
            )
        return Decimal(value)
    raise InvalidAmountError(f"{what} must be a decimal.Decimal, int or decimal string")


def validate_amount(value: object) -> Decimal:
    """Validate a raw amount against the storage envelope and return it as a ``Decimal``.

    Raises instead of rounding when the value has more than :data:`AMOUNT_SCALE` decimal places or
    its magnitude is outside the envelope. Negative zero becomes zero.
    """
    amount = _to_decimal(value, what="amount")
    if _smallest_exact_scale(amount) > AMOUNT_SCALE:
        raise AmountOutOfRangeError(
            f"amount has more than {AMOUNT_SCALE} decimal places; refusing to round"
        )
    if abs(amount) >= AMOUNT_LIMIT:
        raise AmountOutOfRangeError("amount magnitude must be below 10^16")
    if amount.is_zero():
        return Decimal(0)
    return amount


def _canonical(amount: Decimal, currency: Currency) -> Decimal:
    scale = max(currency.minor_units, _smallest_exact_scale(amount))
    if amount.is_zero():
        return Decimal(0).quantize(Decimal(1).scaleb(-scale), context=_EXACT_RESCALE)
    return amount.quantize(Decimal(1).scaleb(-scale), context=_EXACT_RESCALE)


def _coerce_currency(currency: Currency | str) -> Currency:
    if isinstance(currency, Currency):
        return currency
    return Currency.of(currency)


# ---------------------------------------------------------------------------------------------
# Money


def _is_money(value: object) -> bool:
    # Operators are annotated as accepting only Money so the type checker rejects, for example,
    # ``money + 1.5``. This runtime check still protects untyped callers.
    return isinstance(value, Money)


@final
class Money:
    """An exact amount in an explicit ISO 4217 currency. Immutable and hashable."""

    __slots__ = ("_amount", "_currency")

    _amount: Decimal
    _currency: Currency

    def __init__(self, amount: Decimal | int | str, currency: Currency | str) -> None:
        resolved = _coerce_currency(currency)
        object.__setattr__(self, "_currency", resolved)
        object.__setattr__(self, "_amount", _canonical(validate_amount(amount), resolved))

    # -- immutability -----------------------------------------------------------------------

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Money is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Money is immutable")

    def __reduce__(self) -> tuple[Callable[..., Money], tuple[str, str]]:
        return (Money, (self.amount_str, self._currency.code))

    # -- accessors --------------------------------------------------------------------------

    @property
    def amount(self) -> Decimal:
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    @property
    def amount_str(self) -> str:
        """Canonical fixed-point string, e.g. ``"1234.50"``. Never uses exponent notation."""
        return format(self._amount, "f")

    @property
    def has_sub_minor_precision(self) -> bool:
        """True when the amount has more decimal places than the currency's minor units."""
        return _smallest_exact_scale(self._amount) > self._currency.minor_units

    @classmethod
    def zero(cls, currency: Currency | str) -> Money:
        return cls(0, currency)

    def is_zero(self) -> bool:
        return self._amount.is_zero()

    def is_positive(self) -> bool:
        return self._amount > 0

    def is_negative(self) -> bool:
        return self._amount < 0

    def __bool__(self) -> bool:
        raise TypeError("truthiness of Money is ambiguous; use is_zero()")

    # -- arithmetic -------------------------------------------------------------------------

    def _require_same_currency(self, other: Money, operation: str) -> None:
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"cannot {operation} {self._currency.code} and {other._currency.code}"
            )

    def __add__(self, other: Money) -> Money:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "add")
        return Money(_EXACT.add(self._amount, other._amount), self._currency)

    def __sub__(self, other: Money) -> Money:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "subtract")
        return Money(_EXACT.subtract(self._amount, other._amount), self._currency)

    def __neg__(self) -> Money:
        return Money(self._amount.copy_negate(), self._currency)

    def __abs__(self) -> Money:
        return Money(self._amount.copy_abs(), self._currency)

    # -- comparison -------------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        return self._currency == other._currency and self._amount == other._amount

    def __hash__(self) -> int:
        return hash((self._currency.code, self._amount))

    def __lt__(self, other: Money) -> bool:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "compare")
        return self._amount < other._amount

    def __le__(self, other: Money) -> bool:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "compare")
        return self._amount <= other._amount

    def __gt__(self, other: Money) -> bool:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "compare")
        return self._amount > other._amount

    def __ge__(self, other: Money) -> bool:
        if not _is_money(other):
            return NotImplemented
        self._require_same_currency(other, "compare")
        return self._amount >= other._amount

    # -- representation & serialization -------------------------------------------------------

    def __repr__(self) -> str:
        return f"Money('{self.amount_str}', '{self._currency.code}')"

    def __str__(self) -> str:
        return f"{self.amount_str} {self._currency.code}"

    def to_json(self) -> dict[str, str]:
        """``{"amount": "<canonical string>", "currency": "<ISO code>"}``."""
        return {"amount": self.amount_str, "currency": self._currency.code}

    @classmethod
    def from_json(cls, data: object) -> Money:
        """Strict inverse of :meth:`to_json`. The amount must be a string, never a JSON number."""
        if not isinstance(data, Mapping):
            raise InvalidAmountError("money must be an object with 'amount' and 'currency'")
        keys = set(data)
        if keys != {"amount", "currency"}:
            raise InvalidAmountError(
                "money object must have exactly the keys 'amount' and 'currency'"
            )
        amount, currency = data["amount"], data["currency"]
        if not isinstance(amount, str):
            raise InvalidAmountError("money amount must be serialized as a string")
        if not isinstance(currency, str):
            raise InvalidAmountError("money currency must be a string")
        return cls(amount, currency)

    # -- pydantic integration ---------------------------------------------------------------

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> Money:
            if isinstance(value, Money):
                return value
            return cls.from_json(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value.to_json(), when_used="always"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {
            "type": "object",
            "title": "Money",
            "properties": {
                "amount": {"type": "string", "pattern": f"^{_STRICT_AMOUNT_PATTERN.pattern}$"},
                "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            },
            "required": ["amount", "currency"],
            "additionalProperties": False,
        }


def sum_money(values: Iterable[Money], currency: Currency | str) -> Money:
    """Exact sum. ``currency`` is required so that an empty sum still has a currency (FC-04)."""
    total = Money.zero(currency)
    for value in values:
        total = total + value
    return total


# ---------------------------------------------------------------------------------------------
# Tolerance (FC-03)


def within_tolerance(difference: Money, tolerance: Money) -> bool:
    """True when ``|difference| <= tolerance``, compared exactly. Nothing is rounded first."""
    if tolerance.is_negative():
        raise InvalidAmountError("tolerance must not be negative")
    return abs(difference) <= tolerance


# ---------------------------------------------------------------------------------------------
# FX conversion: the only rounding operation (FC-02)


def validate_fx_rate(value: object) -> Decimal:
    if isinstance(value, bool | float):
        raise InvalidFxRateError("FX rate must be a decimal string or decimal.Decimal, not float")
    try:
        rate = _to_decimal(value, what="FX rate")
    except InvalidAmountError as exc:
        raise InvalidFxRateError(exc.detail) from exc
    if rate <= 0:
        raise InvalidFxRateError("FX rate must be positive")
    if _smallest_exact_scale(rate) > FX_RATE_SCALE:
        raise InvalidFxRateError(f"FX rate has more than {FX_RATE_SCALE} decimal places")
    if rate >= FX_RATE_LIMIT:
        raise InvalidFxRateError("FX rate magnitude must be below 10^10")
    return rate


@dataclass(frozen=True, slots=True)
class FxConversion:
    source: Money
    rate: Decimal
    exact_amount: Decimal
    """Unrounded product ``source.amount * rate``."""
    converted: Money
    """``exact_amount`` rounded ``ROUND_HALF_UP`` to the target currency's minor units."""
    rounding_difference: Decimal
    """``converted.amount - exact_amount``; recorded so rounding is always explainable."""


def to_functional(amount: Money, rate: Decimal | str, functional: Currency | str) -> Money:
    """``amount`` expressed in the functional currency (FC-02).

    An amount already in the functional currency is returned exactly as it is; anything else goes
    through :func:`convert`, which is the only place that rounds, and rounds half away from zero to
    the functional currency's minor units. Callers must never quantize by hand: doing so picks
    Python's default banker's rounding and assumes two decimal places.
    """
    target = _coerce_currency(functional)
    if amount.currency == target:
        return amount
    return convert(amount, rate, target).converted


def convert(source: Money, rate: Decimal | str, target: Currency | str) -> FxConversion:
    """Convert ``source`` into ``target`` at ``rate`` (units of target per unit of source).

    Rounds half away from zero to the target's minor units. Same-currency conversion is rejected:
    it can only hide a mapping error.
    """
    target_currency = _coerce_currency(target)
    if target_currency == source.currency:
        raise InvalidFxRateError("source and target currency are the same")
    checked_rate = validate_fx_rate(rate)
    exact = _EXACT.multiply(source.amount, checked_rate)
    quantum = Decimal(1).scaleb(-target_currency.minor_units)
    rounded = exact.quantize(quantum, context=_FX_QUANTIZE)
    converted = Money(rounded, target_currency)
    return FxConversion(
        source=source,
        rate=checked_rate,
        exact_amount=exact,
        converted=converted,
        rounding_difference=_EXACT.subtract(converted.amount, exact),
    )


# ---------------------------------------------------------------------------------------------
# Sign convention (FC-05)


def signed_ledger_amount(debit: Decimal | None, credit: Decimal | None) -> Decimal:
    """Combine separate debit and credit columns into a debit-positive signed amount.

    * Both missing is an error: the line has no amount.
    * A missing side counts as zero.
    * Negative values in either column are rejected: the sign is carried by the column.
    * Both sides non-zero is rejected: the line is ambiguous.
    """
    if debit is None and credit is None:
        raise DebitCreditError("debit and credit are both missing")
    debit_amount = validate_amount(debit) if debit is not None else Decimal(0)
    credit_amount = validate_amount(credit) if credit is not None else Decimal(0)
    if debit_amount < 0 or credit_amount < 0:
        raise DebitCreditError("debit and credit columns must not be negative")
    if not debit_amount.is_zero() and not credit_amount.is_zero():
        raise DebitCreditError("a line cannot have both a debit and a credit amount")
    return validate_amount(_EXACT.subtract(debit_amount, credit_amount))


# ---------------------------------------------------------------------------------------------
# Parsing amounts from source-system text with an explicitly declared format (FC-01, FC-05)


@dataclass(frozen=True, slots=True)
class AmountFormat:
    """How a source column writes amounts. Nothing is guessed: every choice is explicit."""

    decimal_separator: str = "."
    thousands_separator: str | None = None
    parentheses_negative: bool = False
    currency_symbols: frozenset[str] = frozenset()

    _DECIMAL_SEPARATORS: ClassVar[frozenset[str]] = frozenset({".", ","})
    _THOUSANDS_SEPARATORS: ClassVar[frozenset[str]] = frozenset({",", ".", " ", "'", "\u00a0"})

    def __post_init__(self) -> None:
        if self.decimal_separator not in self._DECIMAL_SEPARATORS:
            raise AmountFormatError("decimal separator must be '.' or ','")
        if self.thousands_separator is not None:
            if self.thousands_separator not in self._THOUSANDS_SEPARATORS:
                raise AmountFormatError("unsupported thousands separator")
            if self.thousands_separator == self.decimal_separator:
                raise AmountFormatError("thousands and decimal separators must differ")
        for symbol in self.currency_symbols:
            if not symbol or any(ch.isdigit() or ch in "-().,'" for ch in symbol):
                raise AmountFormatError(f"invalid currency symbol {symbol!r}")

    def number_pattern(self) -> re.Pattern[str]:
        return _number_pattern(self.decimal_separator, self.thousands_separator)


@functools.cache
def _number_pattern(decimal_separator: str, thousands_separator: str | None) -> re.Pattern[str]:
    decimal = re.escape(decimal_separator)
    # ASCII digits only (see _STRICT_AMOUNT_PATTERN): a mis-encoded or manipulated export must not
    # parse as a number that reads differently to a person.
    if thousands_separator is None:
        integer = r"[0-9]+"
    else:
        sep = re.escape(thousands_separator)
        integer = rf"(?:[0-9]{{1,3}}(?:{sep}[0-9]{{3}})+|[0-9]+)"
    return re.compile(rf"{integer}(?:{decimal}[0-9]+)?")


def parse_amount_text(text: str, amount_format: AmountFormat) -> Decimal:
    """Parse a source-system amount such as ``"(1,234.56)"`` using an explicit format.

    Surrounding whitespace is ignored. Anything else that does not match the declared format is an
    error, including an empty string: whether an empty cell means zero or missing is a mapping
    decision, not a parsing guess.
    """
    if not isinstance(text, str):
        raise AmountFormatError("amount text must be a string")
    body = text.strip()
    if not body:
        raise AmountFormatError("amount text is empty")

    negative = False
    if body.startswith("(") or body.endswith(")"):
        if not (amount_format.parentheses_negative and body.startswith("(") and body.endswith(")")):
            raise AmountFormatError("parentheses are not valid in this amount format")
        negative = True
        body = body[1:-1].strip()

    if body.startswith("-"):
        if negative:
            raise AmountFormatError("amount cannot be both parenthesized and signed")
        negative = True
        body = body[1:].lstrip()

    for symbol in sorted(amount_format.currency_symbols, key=len, reverse=True):
        if body.startswith(symbol):
            body = body[len(symbol) :].lstrip()
            break
        if body.endswith(symbol):
            body = body[: -len(symbol)].rstrip()
            break

    if amount_format.number_pattern().fullmatch(body) is None:
        raise AmountFormatError("amount text does not match the declared format")

    normalized = body
    if amount_format.thousands_separator is not None:
        normalized = normalized.replace(amount_format.thousands_separator, "")
    normalized = normalized.replace(amount_format.decimal_separator, ".")
    value = Decimal(normalized)
    return validate_amount(value.copy_negate() if negative else value)


__all__ = [
    "AMOUNT_LIMIT",
    "AMOUNT_PRECISION",
    "AMOUNT_SCALE",
    "FX_RATE_PRECISION",
    "FX_RATE_SCALE",
    "FX_ROUNDING",
    "AmountFormat",
    "AmountFormatError",
    "AmountOutOfRangeError",
    "CurrencyMismatchError",
    "DebitCreditError",
    "FxConversion",
    "InvalidAmountError",
    "InvalidFxRateError",
    "Money",
    "MoneyError",
    "convert",
    "parse_amount_text",
    "signed_ledger_amount",
    "sum_money",
    "validate_amount",
    "validate_fx_rate",
    "within_tolerance",
]
