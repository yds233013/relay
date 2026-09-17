"""Business (accounting) dates and fiscal periods.

Business dates are calendar dates: an invoice dated 2026-03-14 is dated 2026-03-14 everywhere in the
world. They are represented as :class:`datetime.date` and are **never** derived from, converted
through, or compared with timestamps (FC-06). ``datetime.datetime`` is a subclass of ``date``, so
every entry point here rejects it explicitly.

Parsing requires an explicitly declared format (FC-07). Two-digit years are not supported.

Fiscal years are labelled by the calendar year in which they **end** (a fiscal year starting July
2026 is FY2027). Periods are calendar months, identified by ``YYYY-MM`` labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Final

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from relay.core.errors import InvalidInputError


class BusinessDateError(InvalidInputError):
    code: ClassVar[str] = "date.invalid_business_date"
    title: ClassVar[str] = "Invalid business date"


class DateFormat(StrEnum):
    """Supported source date formats. ``M``/``D`` allow one or two digits; others require two."""

    ISO = "YYYY-MM-DD"
    COMPACT = "YYYYMMDD"
    US_PADDED = "MM/DD/YYYY"
    US = "M/D/YYYY"
    EU_PADDED = "DD/MM/YYYY"
    EU = "D/M/YYYY"
    EU_DOTTED = "DD.MM.YYYY"


# ASCII digits only: `\d` would also match Devanagari, Arabic-Indic and full-width digits, so a date
# could parse as one a reader of the file would not recognise.
_FORMAT_PATTERNS: Final[dict[DateFormat, re.Pattern[str]]] = {
    DateFormat.ISO: re.compile(r"(?P<y>[0-9]{4})-(?P<m>[0-9]{2})-(?P<d>[0-9]{2})"),
    DateFormat.COMPACT: re.compile(r"(?P<y>[0-9]{4})(?P<m>[0-9]{2})(?P<d>[0-9]{2})"),
    DateFormat.US_PADDED: re.compile(r"(?P<m>[0-9]{2})/(?P<d>[0-9]{2})/(?P<y>[0-9]{4})"),
    DateFormat.US: re.compile(r"(?P<m>[0-9]{1,2})/(?P<d>[0-9]{1,2})/(?P<y>[0-9]{4})"),
    DateFormat.EU_PADDED: re.compile(r"(?P<d>[0-9]{2})/(?P<m>[0-9]{2})/(?P<y>[0-9]{4})"),
    DateFormat.EU: re.compile(r"(?P<d>[0-9]{1,2})/(?P<m>[0-9]{1,2})/(?P<y>[0-9]{4})"),
    DateFormat.EU_DOTTED: re.compile(r"(?P<d>[0-9]{2})\.(?P<m>[0-9]{2})\.(?P<y>[0-9]{4})"),
}

_DAY_MONTH_CANDIDATE: Final = re.compile(r"(?P<a>[0-9]{1,2})[/.\-](?P<b>[0-9]{1,2})[/.\-][0-9]{4}")
_MIN_YEAR: Final = 1900
_MAX_YEAR: Final = 2999


def ensure_business_date(value: object) -> date:
    """Return ``value`` if it is a plain ``date``; reject datetimes and everything else."""
    if isinstance(value, datetime):
        raise BusinessDateError(
            "a timestamp is not a business date; business dates never pass through timezones"
        )
    if not isinstance(value, date):
        raise BusinessDateError("business date must be a datetime.date")
    if not _MIN_YEAR <= value.year <= _MAX_YEAR:
        raise BusinessDateError(f"business date year must be between {_MIN_YEAR} and {_MAX_YEAR}")
    return value


def parse_business_date(text: object, date_format: DateFormat) -> date:
    """Parse source text with an explicit format. Surrounding whitespace is ignored."""
    if not isinstance(text, str):
        raise BusinessDateError("business date text must be a string")
    match = _FORMAT_PATTERNS[date_format].fullmatch(text.strip())
    if match is None:
        raise BusinessDateError(f"date text does not match format {date_format.value}")
    try:
        parsed = date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError as exc:
        raise BusinessDateError(f"not a real calendar date: {exc}") from exc
    return ensure_business_date(parsed)


def parse_iso_business_date(text: object) -> date:
    """Strict ``YYYY-MM-DD`` parser used for API and serialized data. No surrounding whitespace."""
    if not isinstance(text, str) or text != text.strip():
        raise BusinessDateError("business date must be a YYYY-MM-DD string")
    return parse_business_date(text, DateFormat.ISO)


def format_business_date(value: date) -> str:
    return ensure_business_date(value).isoformat()


def is_ambiguous_day_month(text: str) -> bool:
    """True when text like ``03/04/2026`` reads as a different valid date in D/M and M/D order.

    Used by profiling to demand an explicit format. ``03/03/2026`` is not ambiguous: both readings
    are the same date.
    """
    match = _DAY_MONTH_CANDIDATE.fullmatch(text.strip())
    if match is None:
        return False
    first, second = int(match["a"]), int(match["b"])
    return 1 <= first <= 12 and 1 <= second <= 12 and first != second


@dataclass(frozen=True, slots=True, order=True)
class FiscalPeriod:
    fiscal_year: int
    period: int
    """1-based position within the fiscal year."""
    calendar_month: str
    """``YYYY-MM`` of the calendar month this period covers."""


def fiscal_period_for(value: date, fiscal_year_start_month: int) -> FiscalPeriod:
    """Fiscal period containing a business date."""
    business_date = ensure_business_date(value)
    if isinstance(fiscal_year_start_month, bool) or not 1 <= fiscal_year_start_month <= 12:
        raise BusinessDateError("fiscal year start month must be between 1 and 12")
    offset = (business_date.month - fiscal_year_start_month) % 12
    starts_in_year = (
        business_date.year
        if business_date.month >= fiscal_year_start_month
        else (business_date.year - 1)
    )
    fiscal_year = starts_in_year if fiscal_year_start_month == 1 else starts_in_year + 1
    return FiscalPeriod(
        fiscal_year=fiscal_year,
        period=offset + 1,
        calendar_month=f"{business_date.year:04d}-{business_date.month:02d}",
    )


class _BusinessDateSchema:
    """Pydantic schema for :data:`BusinessDate`.

    Accepts a ``date`` (not ``datetime``) or a strict ``YYYY-MM-DD`` string; serializes as
    ``YYYY-MM-DD``. Unlike Pydantic's default ``date``, it rejects timestamps such as
    ``2026-03-14T00:00:00Z`` and integers.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        def validate(value: object) -> date:
            if isinstance(value, str):
                return parse_iso_business_date(value)
            return ensure_business_date(value)

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                format_business_date, when_used="always"
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "format": "date", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


BusinessDate = Annotated[date, _BusinessDateSchema]
"""Pydantic field type for business dates. Static type is ``date``."""
