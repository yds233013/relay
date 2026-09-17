"""Canonical fields per dataset type: what a column mapping must and may provide. Pure.

Normalization (``relay.engine.snapshot``) reads exactly these fields. A mapping that omits a
required field is rejected before approval, so a run never fails on a missing field.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from relay.canonical.enums import (
    AccountSubtype,
    AgingItemKind,
    PaymentDirection,
    PaymentMethod,
    SourceModule,
)


class FieldKind(StrEnum):
    CODE = "code"
    TEXT = "text"
    DATE = "date"
    PERIOD = "period"
    AMOUNT = "amount"
    SIGNED_AMOUNT = "signed_amount"
    """Debit-positive amount, usually from separate debit and credit columns."""
    RATE = "rate"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    CURRENCY = "currency"
    ENUM = "enum"


@dataclass(frozen=True, slots=True)
class CanonicalField:
    name: str
    kind: FieldKind
    required: bool
    synonyms: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    """Allowed canonical values for enum fields."""


def _f(
    name: str,
    kind: FieldKind,
    required: bool = True,
    synonyms: tuple[str, ...] = (),
    values: tuple[str, ...] = (),
) -> CanonicalField:
    return CanonicalField(name, kind, required, (name.replace("_", " "), *synonyms), values)


_K = FieldKind
_SUBTYPES = tuple(s.value for s in AccountSubtype)
_PARTY_COMMON = (
    _f("party_code", _K.CODE, synonyms=("customer id", "vendor id", "id", "code", "number")),
    _f("name", _K.TEXT, synonyms=("customer name", "vendor name", "company", "name")),
    _f("address_line1", _K.TEXT, False, ("address", "street", "address 1")),
    _f("city", _K.TEXT, False),
    _f("region", _K.TEXT, False, ("state", "province")),
    _f("postal_code", _K.TEXT, False, ("zip", "postcode", "postal")),
    _f("tax_id_last4", _K.TEXT, False, ("tax id", "ein", "tin", "vat")),
    _f("payment_terms_days", _K.INTEGER, False, ("terms",)),
    _f("is_active", _K.BOOLEAN, False, ("status", "active")),
    _f("created_on", _K.DATE, False, ("created", "created date")),
)

FIELDS: Final[dict[str, tuple[CanonicalField, ...]]] = {
    "legacy_coa": (
        _f("account_code", _K.CODE, synonyms=("account", "account number", "acct")),
        _f("name", _K.TEXT, synonyms=("description", "account name")),
        _f(
            "subtype",
            _K.ENUM,
            synonyms=("detail type", "account subtype", "type"),
            values=_SUBTYPES,
        ),
        _f("is_active", _K.BOOLEAN, synonyms=("active", "status")),
    ),
    "target_coa": (
        _f("account_code", _K.CODE, synonyms=("account number", "account", "code")),
        _f("name", _K.TEXT, synonyms=("account name", "description")),
        _f("subtype", _K.ENUM, synonyms=("account subtype", "subtype"), values=_SUBTYPES),
    ),
    "account_mapping": (
        _f("legacy_account_code", _K.CODE, synonyms=("legacy account", "source account")),
        _f("target_account_code", _K.CODE, synonyms=("target account", "new account")),
    ),
    "trial_balance": (
        _f("account_code", _K.CODE, synonyms=("account",)),
        _f("period_end", _K.DATE, synonyms=("period ending", "period end", "as of")),
        _f("balance", _K.SIGNED_AMOUNT, synonyms=("balance", "amount")),
        _f("account_name", _K.TEXT, False, ("description",)),
    ),
    "gl_detail": (
        _f("account_code", _K.CODE, synonyms=("account", "gl account")),
        _f("entry_date", _K.DATE, synonyms=("date", "posting date", "transaction date")),
        _f("posting_period", _K.PERIOD, synonyms=("period", "fiscal period")),
        _f(
            "source_module",
            _K.ENUM,
            synonyms=("type", "source", "module"),
            values=tuple(m.value for m in SourceModule),
        ),
        _f("entry_number", _K.CODE, synonyms=("num", "entry", "journal number", "je number")),
        _f("line_number", _K.INTEGER, synonyms=("line", "line no")),
        _f("functional_amount", _K.SIGNED_AMOUNT, synonyms=("amount",)),
        _f("currency", _K.CURRENCY, synonyms=("currency code",)),
        _f("document_number", _K.CODE, False, ("document", "reference")),
        _f("party_code", _K.CODE, False, ("customer id", "vendor id")),
        _f("memo", _K.TEXT, False, ("description", "memo")),
        _f("foreign_amount", _K.AMOUNT, False, ("foreign amount", "transaction amount")),
        _f("reversal_of", _K.CODE, False, ("reversal of", "reverses")),
    ),
    "customers": (
        *_PARTY_COMMON,
        _f("country", _K.TEXT, False),
        _f("email", _K.TEXT, False, ("email address",)),
        _f("default_currency", _K.CURRENCY, False, ("currency",)),
    ),
    "vendors": (*_PARTY_COMMON, _f("notes", _K.TEXT, False, ("notes", "comments"))),
    "invoices": (
        _f("document_number", _K.CODE, synonyms=("invoice no", "invoice number", "invoice")),
        _f("party_code", _K.CODE, synonyms=("customer id",)),
        _f("document_date", _K.DATE, synonyms=("invoice date", "date")),
        _f("due_date", _K.DATE, synonyms=("due",)),
        _f("currency", _K.CURRENCY),
        _f("total", _K.AMOUNT, synonyms=("amount",)),
        _f("open_amount", _K.AMOUNT, synonyms=("balance due", "open balance", "balance")),
        _f("subtotal", _K.AMOUNT, False),
        _f("tax", _K.AMOUNT, False),
        _f("fx_rate", _K.RATE, False, ("exchange rate", "rate")),
        _f("functional_total", _K.AMOUNT, False, ("functional total", "base total")),
        _f("party_name", _K.TEXT, False, ("customer name",)),
    ),
    "bills": (
        _f("document_number", _K.CODE, synonyms=("bill no", "bill number", "bill")),
        _f("party_code", _K.CODE, synonyms=("vendor id",)),
        _f("document_date", _K.DATE, synonyms=("bill date", "date")),
        _f("due_date", _K.DATE, synonyms=("due",)),
        _f("currency", _K.CURRENCY),
        _f("total", _K.AMOUNT, synonyms=("amount",)),
        _f("open_amount", _K.AMOUNT, synonyms=("balance due", "open balance")),
        _f(
            "party_reference",
            _K.TEXT,
            False,
            ("vendor invoice", "vendor invoice number", "reference"),
        ),
        _f("fx_rate", _K.RATE, False, ("exchange rate",)),
        _f("functional_total", _K.AMOUNT, False, ("functional total", "base total")),
        _f("party_name", _K.TEXT, False, ("vendor name",)),
    ),
    "payments": (
        _f("payment_number", _K.CODE, synonyms=("payment no", "payment number")),
        _f(
            "direction",
            _K.ENUM,
            synonyms=("type",),
            values=tuple(d.value for d in PaymentDirection),
        ),
        _f("payment_date", _K.DATE, synonyms=("date",)),
        _f("party_code", _K.CODE, synonyms=("customer id", "vendor id")),
        _f(
            "method",
            _K.ENUM,
            synonyms=("payment method",),
            values=tuple(m.value for m in PaymentMethod),
        ),
        _f("currency", _K.CURRENCY),
        _f("amount", _K.AMOUNT),
        _f("fx_rate", _K.RATE, synonyms=("exchange rate",)),
        _f("functional_amount", _K.AMOUNT, synonyms=("functional amount", "base amount")),
        _f("reference", _K.TEXT, False, ("check number", "reference")),
        _f("applied_document", _K.CODE, False, ("applied to",)),
        _f("applied_amount", _K.AMOUNT, False),
        _f("unapplied_amount", _K.AMOUNT, False, ("unapplied",)),
        _f("party_name", _K.TEXT, False, ("name",)),
    ),
    "ar_aging": (),
    "ap_aging": (),
    "bank_transactions": (
        _f("posted_date", _K.DATE, synonyms=("date", "posting date")),
        _f("description", _K.TEXT, synonyms=("memo", "details")),
        _f("amount", _K.AMOUNT),
        _f("running_balance", _K.AMOUNT, False, ("balance",)),
        _f("reference", _K.TEXT, False),
    ),
    "fx_rates": (
        _f("rate_date", _K.DATE, synonyms=("date",)),
        _f("base_currency", _K.CURRENCY, synonyms=("from currency", "base")),
        _f("quote_currency", _K.CURRENCY, synonyms=("to currency", "quote")),
        _f("rate", _K.RATE),
    ),
}

_AGING = (
    _f("party_code", _K.CODE, synonyms=("customer id", "vendor id")),
    _f("kind", _K.ENUM, synonyms=("type",), values=tuple(k.value for k in AgingItemKind)),
    _f("reference", _K.CODE, synonyms=("num", "document", "invoice", "bill")),
    _f("item_date", _K.DATE, synonyms=("date",)),
    _f("currency", _K.CURRENCY),
    _f("functional_open_amount", _K.AMOUNT, synonyms=("open balance", "balance")),
    _f("due_date", _K.DATE, False, ("due date",)),
    _f("party_name", _K.TEXT, False, ("customer", "vendor")),
)
FIELDS["ar_aging"] = _AGING
FIELDS["ap_aging"] = _AGING


def fields_for(dataset_type: str) -> tuple[CanonicalField, ...]:
    return FIELDS.get(dataset_type, ())


def missing_required(dataset_type: str, mapped: set[str]) -> list[str]:
    return [f.name for f in fields_for(dataset_type) if f.required and f.name not in mapped]


def unknown_fields(dataset_type: str, mapped: set[str]) -> list[str]:
    known = {f.name for f in fields_for(dataset_type)}
    return sorted(mapped - known)
