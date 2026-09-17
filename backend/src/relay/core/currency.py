"""ISO 4217 currency registry.

Only active, circulating ISO 4217 currencies are accepted. Fund codes, precious metals and testing
codes (for example ``XAU``, ``XDR``, ``XTS``, ``XXX``, ``BOV``, ``USN``) are deliberately excluded:
they are not valid transaction currencies for accounting records in Relay.

Codes must be supplied exactly as three upper-case letters. Relay never guesses a currency from a
symbol or lower-case text; normalization of source data is an explicit, mapped transform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Final

from relay.core.errors import InvalidInputError


class UnknownCurrencyError(InvalidInputError):
    code: ClassVar[str] = "money.unknown_currency"
    title: ClassVar[str] = "Unknown currency"


_CODE_PATTERN: Final = re.compile(r"[A-Z]{3}")

# Minor units per ISO 4217 (list one, active currencies). Everything not listed in the
# exceptional groups below has 2 minor units.
_ZERO_DECIMAL: Final = frozenset(
    {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV",
     "XAF", "XOF", "XPF"}
)  # fmt: skip
_THREE_DECIMAL: Final = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})
_FOUR_DECIMAL: Final = frozenset({"CLF", "UYW"})
_TWO_DECIMAL: Final = frozenset(
    {"AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM", "BBD", "BDT", "BGN",
     "BMD", "BND", "BOB", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHF", "CNY",
     "COP", "CRC", "CUP", "CVE", "CZK", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD",
     "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR",
     "ILS", "INR", "IRR", "JMD", "KES", "KGS", "KHR", "KPW", "KYD", "KZT", "LAK", "LBP", "LKR",
     "LRD", "LSL", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT", "MOP", "MRU", "MUR", "MVR", "MWK",
     "MXN", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "PAB", "PEN", "PGK", "PHP",
     "PKR", "PLN", "QAR", "RON", "RSD", "RUB", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP",
     "SLE", "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TOP", "TRY",
     "TTD", "TWD", "TZS", "UAH", "USD", "UYU", "UZS", "VED", "VES", "WST", "XCD", "YER", "ZAR",
     "ZMW", "ZWG"}
)  # fmt: skip


def _build_registry() -> dict[str, int]:
    registry: dict[str, int] = {}
    for codes, minor_units in (
        (_ZERO_DECIMAL, 0),
        (_TWO_DECIMAL, 2),
        (_THREE_DECIMAL, 3),
        (_FOUR_DECIMAL, 4),
    ):
        for code in codes:
            if code in registry:  # pragma: no cover - guarded by a unit test
                raise AssertionError(f"currency {code} listed twice")
            registry[code] = minor_units
    return registry


_MINOR_UNITS: Final[dict[str, int]] = _build_registry()


def _lookup_minor_units(code: object) -> int:
    if not isinstance(code, str) or _CODE_PATTERN.fullmatch(code) is None:
        raise UnknownCurrencyError(
            "currency code must be exactly three upper-case ISO 4217 letters"
        )
    minor_units = _MINOR_UNITS.get(code)
    if minor_units is None:
        raise UnknownCurrencyError(f"'{code}' is not an accepted ISO 4217 currency code")
    return minor_units


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO 4217 currency. Construct with :meth:`of`."""

    code: str
    minor_units: int

    def __post_init__(self) -> None:
        # Direct construction is validated too, so an inconsistent Currency can never exist.
        expected = _lookup_minor_units(self.code)
        if self.minor_units != expected:
            raise UnknownCurrencyError(
                f"{self.code} has {expected} minor units, not {self.minor_units}"
            )

    @classmethod
    def of(cls, code: str) -> Currency:
        return cls(code=code, minor_units=_lookup_minor_units(code))

    def __str__(self) -> str:
        return self.code


def is_known_currency(code: str) -> bool:
    return code in _MINOR_UNITS


def known_currency_codes() -> frozenset[str]:
    return frozenset(_MINOR_UNITS)
