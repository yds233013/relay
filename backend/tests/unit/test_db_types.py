"""Column type guards, exercised without a database (bind/result processing)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql

from relay.core.currency import Currency, UnknownCurrencyError
from relay.core.dates import BusinessDateError
from relay.core.db_types import (
    AmountType,
    BusinessDateType,
    CurrencyCodeType,
    FxRateType,
    UtcTimestampType,
)
from relay.core.money import AmountOutOfRangeError, InvalidAmountError, InvalidFxRateError
from relay.core.timestamps import TimestampError

DIALECT = postgresql.dialect()  # type: ignore[no-untyped-call]


def test_amount_column_is_numeric_20_4() -> None:
    assert str(AmountType().impl.compile(dialect=DIALECT)) == "NUMERIC(20, 4)"
    assert str(FxRateType().impl.compile(dialect=DIALECT)) == "NUMERIC(20, 10)"


def test_amount_bind_accepts_exact_values() -> None:
    column = AmountType()
    assert column.process_bind_param(Decimal("12.5"), DIALECT) == Decimal("12.5")
    assert column.process_bind_param("-0.0001", DIALECT) == Decimal("-0.0001")
    assert column.process_bind_param(None, DIALECT) is None


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (12.5, InvalidAmountError),
        (True, InvalidAmountError),
        (Decimal("1.23456"), AmountOutOfRangeError),  # Postgres would silently store 1.2346
        (Decimal("1E+16"), AmountOutOfRangeError),
        (Decimal("NaN"), InvalidAmountError),
    ],
)
def test_amount_bind_rejects_values_postgres_would_round_or_reject(
    value: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        AmountType().process_bind_param(value, DIALECT)


def test_fx_rate_bind() -> None:
    assert FxRateType().process_bind_param("1.0850", DIALECT) == Decimal("1.0850")
    with pytest.raises(InvalidFxRateError):
        FxRateType().process_bind_param(1.085, DIALECT)


def test_currency_column() -> None:
    column = CurrencyCodeType()
    assert column.process_bind_param(Currency.of("EUR"), DIALECT) == "EUR"
    assert column.process_bind_param("USD", DIALECT) == "USD"
    assert column.process_result_value("JPY", DIALECT) == Currency.of("JPY")
    with pytest.raises(UnknownCurrencyError):
        column.process_bind_param("usd", DIALECT)
    with pytest.raises(TypeError):
        column.process_bind_param(840, DIALECT)


def test_business_date_column_rejects_datetimes() -> None:
    column = BusinessDateType()
    assert column.process_bind_param(date(2026, 6, 30), DIALECT) == date(2026, 6, 30)
    with pytest.raises(BusinessDateError):
        column.process_bind_param(datetime(2026, 6, 30, tzinfo=UTC), DIALECT)


def test_timestamp_column_requires_aware_and_normalizes_to_utc() -> None:
    column = UtcTimestampType()
    local = datetime(2026, 9, 17, 1, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    bound = column.process_bind_param(local, DIALECT)
    assert bound is not None
    assert bound.tzinfo is UTC
    assert bound == local
    with pytest.raises(TimestampError):
        column.process_bind_param(datetime(2026, 9, 17, 8, 30), DIALECT)  # noqa: DTZ001
    result = column.process_result_value(local, DIALECT)
    assert result is not None
    assert result.tzinfo is UTC
