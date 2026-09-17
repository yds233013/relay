"""SQLAlchemy column types that enforce financial and temporal invariants at the database boundary.

PostgreSQL silently rounds values that exceed a ``NUMERIC`` column's scale
(``1.23456::NUMERIC(20,4)`` is ``1.2346``). These types validate before binding so that can never
happen (FC-01, FC-02), and reject floats, naive timestamps and datetimes posing as dates (FC-06).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, DateTime, Dialect, Numeric
from sqlalchemy.types import TypeDecorator

from relay.core.currency import Currency
from relay.core.dates import ensure_business_date
from relay.core.money import (
    AMOUNT_PRECISION,
    AMOUNT_SCALE,
    FX_RATE_PRECISION,
    FX_RATE_SCALE,
    validate_amount,
    validate_fx_rate,
)
from relay.core.timestamps import ensure_utc


class AmountType(TypeDecorator[Decimal]):
    """``NUMERIC(20,4)`` amount. Binds only validated ``Decimal``/``int``/decimal strings."""

    impl = Numeric(AMOUNT_PRECISION, AMOUNT_SCALE, asdecimal=True)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return validate_amount(value)

    def process_result_value(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return validate_amount(value)


class FxRateType(TypeDecorator[Decimal]):
    """``NUMERIC(20,10)`` FX rate."""

    impl = Numeric(FX_RATE_PRECISION, FX_RATE_SCALE, asdecimal=True)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return validate_fx_rate(value)

    def process_result_value(self, value: object, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return validate_fx_rate(value)


class CurrencyCodeType(TypeDecorator[Currency]):
    """``CHAR(3)`` ISO 4217 code, loaded as :class:`Currency`."""

    impl = CHAR(3)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, Currency):
            return value.code
        if isinstance(value, str):
            return Currency.of(value).code
        raise TypeError("currency must be a Currency or ISO 4217 code string")

    def process_result_value(self, value: object, dialect: Dialect) -> Currency | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("unexpected currency column value")
        return Currency.of(value)


class BusinessDateType(TypeDecorator[date]):
    """``DATE`` column that refuses datetimes."""

    impl = Date
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> date | None:
        if value is None:
            return None
        return ensure_business_date(value)

    def process_result_value(self, value: object, dialect: Dialect) -> date | None:
        if value is None:
            return None
        return ensure_business_date(value)


class UtcTimestampType(TypeDecorator[datetime]):
    """``TIMESTAMPTZ`` column: aware datetimes in, UTC datetimes out."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)

    def process_result_value(self, value: object, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)
