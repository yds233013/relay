"""Canonical records.

Conventions (docs/data-model.md):

* Ledger amounts (journal lines, control balances) are **signed**: debit positive, credit negative.
* Document, payment and aging amounts are **unsigned document amounts** (what is owed or paid).
* Every amount is a :class:`~relay.core.money.Money`; transaction and functional amounts are kept
  separately.
* Business dates are ``date``; posting periods are ``YYYY-MM`` strings.

Records validate *shape* (types, currencies, non-empty identifiers), never accounting invariants,
so that defective source data can be represented faithfully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import ClassVar, Final

from relay.canonical.enums import (
    AccountSubtype,
    AccountType,
    AgingItemKind,
    AgingType,
    DocumentType,
    NormalBalance,
    PartyType,
    PaymentDirection,
    PaymentMethod,
    SourceModule,
    account_type_of,
    normal_balance_of,
)
from relay.core.currency import Currency
from relay.core.dates import ensure_business_date
from relay.core.errors import InvalidInputError
from relay.core.money import Money, validate_fx_rate

_PERIOD: Final = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class CanonicalRecordError(InvalidInputError):
    code: ClassVar[str] = "canonical.invalid_record"
    title: ClassVar[str] = "Invalid canonical record"


def _require_identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CanonicalRecordError(f"{name} must be a non-empty identifier without padding")


def _require_money(value: Money, name: str, *, non_negative: bool = False) -> None:
    if not isinstance(value, Money):
        raise CanonicalRecordError(f"{name} must be Money")
    if non_negative and value.is_negative():
        raise CanonicalRecordError(f"{name} must not be negative")


def _require_same_currency(currency: Currency, *amounts: Money) -> None:
    for amount in amounts:
        if amount.currency != currency:
            raise CanonicalRecordError(
                f"amount in {amount.currency.code} does not match record currency {currency.code}"
            )


def validate_period(period: object) -> str:
    if not isinstance(period, str) or _PERIOD.fullmatch(period) is None:
        raise CanonicalRecordError("posting period must be YYYY-MM")
    return period


def period_of(value: date) -> str:
    """Calendar-month period label of a business date."""
    business_date = ensure_business_date(value)
    return f"{business_date.year:04d}-{business_date.month:02d}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Account:
    code: str
    name: str
    subtype: AccountSubtype
    is_active: bool = True

    def __post_init__(self) -> None:
        _require_identifier(self.code, "account code")
        _require_identifier(self.name, "account name")
        if not isinstance(self.subtype, AccountSubtype):
            raise CanonicalRecordError("account subtype must be an AccountSubtype")

    @property
    def account_type(self) -> AccountType:
        return account_type_of(self.subtype)

    @property
    def normal_balance(self) -> NormalBalance:
        return normal_balance_of(self.subtype)


@dataclass(frozen=True, slots=True, kw_only=True)
class PartyKey:
    party_type: PartyType
    code: str

    def __post_init__(self) -> None:
        _require_identifier(self.code, "party code")


@dataclass(frozen=True, slots=True, kw_only=True)
class Party:
    party_type: PartyType
    code: str
    name: str
    address_line1: str
    city: str
    region: str
    postal_code: str
    country: str
    email: str | None
    tax_id_last4: str | None
    default_currency: Currency
    payment_terms_days: int
    is_active: bool
    created_on: date
    notes: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.code, "party code")
        _require_identifier(self.name, "party name")
        ensure_business_date(self.created_on)
        if self.tax_id_last4 is not None and re.fullmatch(r"\d{4}", self.tax_id_last4) is None:
            raise CanonicalRecordError("tax_id_last4 must be four digits")
        if isinstance(self.payment_terms_days, bool) or self.payment_terms_days < 0:
            raise CanonicalRecordError("payment terms must be a non-negative number of days")

    @property
    def key(self) -> PartyKey:
        return PartyKey(party_type=self.party_type, code=self.code)


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalLine:
    line_number: int
    account_code: str
    amount: Money
    """Signed amount in the transaction currency (debit positive)."""
    functional_amount: Money
    """Signed amount in the functional currency (debit positive)."""
    party: PartyKey | None = None
    document_number: str | None = None
    memo: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.line_number, bool) or self.line_number < 1:
            raise CanonicalRecordError("line number must be a positive integer")
        _require_identifier(self.account_code, "account code")
        _require_money(self.amount, "amount")
        _require_money(self.functional_amount, "functional amount")
        if self.amount.is_negative() != self.functional_amount.is_negative() and not (
            self.amount.is_zero() or self.functional_amount.is_zero()
        ):
            raise CanonicalRecordError("transaction and functional amounts must have the same sign")


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalEntry:
    entry_number: str
    entry_date: date
    posting_period: str
    source_module: SourceModule
    memo: str
    lines: tuple[JournalLine, ...]
    reversal_of: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.entry_number, "entry number")
        ensure_business_date(self.entry_date)
        validate_period(self.posting_period)
        if not self.lines:
            raise CanonicalRecordError("a journal entry needs at least one line")
        numbers = [line.line_number for line in self.lines]
        if len(set(numbers)) != len(numbers):
            raise CanonicalRecordError("journal line numbers must be unique within an entry")

    def functional_total(self) -> Decimal:
        """Signed sum of functional amounts (zero for a balanced entry)."""
        total = Decimal(0)
        for line in self.lines:
            total += line.functional_amount.amount
        return total


@dataclass(frozen=True, slots=True, kw_only=True)
class Document:
    document_type: DocumentType
    number: str
    party_code: str
    party_reference: str | None
    document_date: date
    due_date: date
    currency: Currency
    subtotal: Money
    tax: Money
    total: Money
    fx_rate: Decimal
    """Functional-currency units per document-currency unit (1 for functional currency)."""
    functional_total: Money

    def __post_init__(self) -> None:
        _require_identifier(self.number, "document number")
        _require_identifier(self.party_code, "party code")
        ensure_business_date(self.document_date)
        ensure_business_date(self.due_date)
        for name, value in (("subtotal", self.subtotal), ("tax", self.tax), ("total", self.total)):
            _require_money(value, name, non_negative=True)
        _require_money(self.functional_total, "functional total", non_negative=True)
        _require_same_currency(self.currency, self.subtotal, self.tax, self.total)
        validate_fx_rate(self.fx_rate)


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentApplication:
    document_number: str
    applied_amount: Money
    applied_functional_amount: Money

    def __post_init__(self) -> None:
        _require_identifier(self.document_number, "document number")
        _require_money(self.applied_amount, "applied amount", non_negative=True)
        _require_money(
            self.applied_functional_amount, "applied functional amount", non_negative=True
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Payment:
    number: str
    direction: PaymentDirection
    method: PaymentMethod
    reference: str | None
    party_code: str
    payment_date: date
    currency: Currency
    amount: Money
    fx_rate: Decimal
    functional_amount: Money
    applications: tuple[PaymentApplication, ...]
    unapplied_amount: Money
    bank_account: str

    def __post_init__(self) -> None:
        _require_identifier(self.number, "payment number")
        _require_identifier(self.party_code, "party code")
        _require_identifier(self.bank_account, "bank account")
        ensure_business_date(self.payment_date)
        _require_money(self.amount, "amount", non_negative=True)
        _require_money(self.functional_amount, "functional amount", non_negative=True)
        _require_money(self.unapplied_amount, "unapplied amount", non_negative=True)
        _require_same_currency(self.currency, self.amount, self.unapplied_amount)
        for application in self.applications:
            _require_same_currency(self.currency, application.applied_amount)
        validate_fx_rate(self.fx_rate)


@dataclass(frozen=True, slots=True, kw_only=True)
class BankTransaction:
    bank_account: str
    posted_date: date
    description: str
    amount: Money
    """Signed: positive is an inflow to the account."""
    reference: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.bank_account, "bank account")
        _require_identifier(self.description, "description")
        ensure_business_date(self.posted_date)
        _require_money(self.amount, "amount")
        if self.amount.is_zero():
            raise CanonicalRecordError("a bank transaction cannot be zero")


@dataclass(frozen=True, slots=True, kw_only=True)
class FxRate:
    rate_date: date
    base_currency: Currency
    quote_currency: Currency
    rate: Decimal
    """Units of ``quote_currency`` per one unit of ``base_currency``."""

    def __post_init__(self) -> None:
        ensure_business_date(self.rate_date)
        validate_fx_rate(self.rate)
        if self.base_currency == self.quote_currency:
            raise CanonicalRecordError("FX rate currencies must differ")


@dataclass(frozen=True, slots=True, kw_only=True)
class ControlBalance:
    """A trial-balance line reported by the source system: closing balance at a period end."""

    account_code: str
    period_end: date
    balance: Money
    """Signed functional balance (debit positive)."""

    def __post_init__(self) -> None:
        _require_identifier(self.account_code, "account code")
        ensure_business_date(self.period_end)
        _require_money(self.balance, "balance")


@dataclass(frozen=True, slots=True, kw_only=True)
class AgingItem:
    """An open item reported by a source aging report."""

    aging_type: AgingType
    as_of: date
    party_code: str
    kind: AgingItemKind
    reference: str
    """Document number, or payment number for an unapplied payment."""
    item_date: date
    due_date: date | None
    currency: Currency
    open_amount: Money
    """Unsigned amount in ``currency``: owed on a document, or credit left on a payment."""
    functional_open_amount: Money
    extra: tuple[tuple[str, str], ...] = field(default=())

    def __post_init__(self) -> None:
        _require_identifier(self.party_code, "party code")
        _require_identifier(self.reference, "reference")
        ensure_business_date(self.as_of)
        ensure_business_date(self.item_date)
        if self.due_date is not None:
            ensure_business_date(self.due_date)
        _require_money(self.open_amount, "open amount", non_negative=True)
        _require_money(self.functional_open_amount, "functional open amount", non_negative=True)
        _require_same_currency(self.currency, self.open_amount)
