"""Canonical accounting model: shape validation, natural keys, subtype semantics."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

import pytest

from relay.canonical import natural_keys as nk
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
from relay.canonical.lineage import LineageError, SourceLocation
from relay.canonical.records import (
    Account,
    AgingItem,
    BankTransaction,
    CanonicalRecordError,
    Document,
    FxRate,
    JournalEntry,
    JournalLine,
    Party,
    PartyKey,
    Payment,
    PaymentApplication,
    period_of,
    validate_period,
)
from relay.core.currency import Currency
from relay.core.dates import BusinessDateError
from relay.core.money import InvalidFxRateError, Money

USD = Currency.of("USD")
EUR = Currency.of("EUR")


def usd(value: str) -> Money:
    return Money(value, USD)


def test_every_subtype_has_a_type_and_normal_balance() -> None:
    for subtype in AccountSubtype:
        assert isinstance(account_type_of(subtype), AccountType)
        assert isinstance(normal_balance_of(subtype), NormalBalance)
    assert normal_balance_of(AccountSubtype.CONTRA_ASSET) is NormalBalance.CREDIT
    assert account_type_of(AccountSubtype.CONTRA_ASSET) is AccountType.ASSET
    assert normal_balance_of(AccountSubtype.ACCOUNTS_RECEIVABLE) is NormalBalance.DEBIT


def test_account_properties() -> None:
    account = Account(code="1205", name="Allowance", subtype=AccountSubtype.CONTRA_ASSET)
    assert account.account_type is AccountType.ASSET
    assert account.normal_balance is NormalBalance.CREDIT
    with pytest.raises(CanonicalRecordError):
        Account(code=" 1205", name="x", subtype=AccountSubtype.CASH)


def test_unbalanced_entries_and_impossible_dates_are_representable() -> None:
    entry = JournalEntry(
        entry_number="JE-1",
        entry_date=date(2999, 3, 14),
        posting_period="2026-03",
        source_module=SourceModule.MANUAL,
        memo="",
        lines=(
            JournalLine(
                line_number=1,
                account_code="6400",
                amount=usd("10.00"),
                functional_amount=usd("10.00"),
            ),
        ),
    )
    assert entry.functional_total() == Decimal("10.00")


def test_journal_entry_shape_validation() -> None:
    line = JournalLine(
        line_number=1, account_code="1010", amount=usd("1.00"), functional_amount=usd("1.00")
    )
    with pytest.raises(CanonicalRecordError):
        JournalEntry(
            entry_number="JE",
            entry_date=date(2026, 1, 1),
            posting_period="2026-13",
            source_module=SourceModule.MANUAL,
            memo="",
            lines=(line,),
        )
    with pytest.raises(CanonicalRecordError):
        JournalEntry(
            entry_number="JE",
            entry_date=date(2026, 1, 1),
            posting_period="2026-01",
            source_module=SourceModule.MANUAL,
            memo="",
            lines=(line, line),
        )
    with pytest.raises(CanonicalRecordError):
        JournalEntry(
            entry_number="JE",
            entry_date=date(2026, 1, 1),
            posting_period="2026-01",
            source_module=SourceModule.MANUAL,
            memo="",
            lines=(),
        )
    with pytest.raises(BusinessDateError):
        JournalEntry(
            entry_number="JE",
            entry_date="2026-01-01",  # type: ignore[arg-type]
            posting_period="2026-01",
            source_module=SourceModule.MANUAL,
            memo="",
            lines=(line,),
        )


def test_line_signs_must_agree() -> None:
    with pytest.raises(CanonicalRecordError):
        JournalLine(
            line_number=1,
            account_code="1200",
            amount=Money("10.00", EUR),
            functional_amount=usd("-10.85"),
        )


def test_document_validation() -> None:
    kwargs: dict[str, object] = {
        "document_type": DocumentType.INVOICE,
        "number": "INV-1",
        "party_code": "C-1",
        "party_reference": None,
        "document_date": date(2026, 3, 12),
        "due_date": date(2026, 6, 10),
        "currency": EUR,
        "subtotal": Money("7800", EUR),
        "tax": Money("0", EUR),
        "total": Money("7800", EUR),
        "fx_rate": Decimal("1.0850"),
        "functional_total": usd("8463.00"),
    }
    Document(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(CanonicalRecordError):
        Document(**{**kwargs, "total": usd("7800")})  # type: ignore[arg-type]
    with pytest.raises(InvalidFxRateError):
        Document(**{**kwargs, "fx_rate": 1.085})  # type: ignore[arg-type]
    with pytest.raises(CanonicalRecordError):
        Document(**{**kwargs, "subtotal": Money("-1", EUR)})  # type: ignore[arg-type]


def test_payment_and_bank_validation() -> None:
    application = PaymentApplication(
        document_number="INV-1", applied_amount=usd("5"), applied_functional_amount=usd("5")
    )
    payment = Payment(
        number="PMT-1",
        direction=PaymentDirection.RECEIVED,
        method=PaymentMethod.CHECK,
        reference="1001",
        party_code="C-1",
        payment_date=date(2026, 1, 5),
        currency=USD,
        amount=usd("5"),
        fx_rate=Decimal(1),
        functional_amount=usd("5"),
        applications=(application,),
        unapplied_amount=usd("0"),
        bank_account="4471",
    )
    assert payment.applications[0].document_number == "INV-1"
    with pytest.raises(CanonicalRecordError):
        BankTransaction(
            bank_account="4471", posted_date=date(2026, 1, 5), description="FEE", amount=usd("0")
        )


def test_other_records() -> None:
    party = Party(
        party_type=PartyType.VENDOR,
        code="V-1",
        name="Acme",
        address_line1="1 Main",
        city="Portland",
        region="OR",
        postal_code="97201",
        country="US",
        email=None,
        tax_id_last4="1234",
        default_currency=USD,
        payment_terms_days=30,
        is_active=True,
        created_on=date(2020, 1, 1),
    )
    assert party.key == PartyKey(party_type=PartyType.VENDOR, code="V-1")
    with pytest.raises(CanonicalRecordError):
        dataclasses.replace(party, tax_id_last4="12a4")
    with pytest.raises(CanonicalRecordError):
        FxRate(rate_date=date(2026, 1, 1), base_currency=USD, quote_currency=USD, rate=Decimal("1"))
    item = AgingItem(
        aging_type=AgingType.AR,
        as_of=date(2026, 6, 30),
        party_code="C-1",
        kind=AgingItemKind.DOCUMENT,
        reference="INV-1",
        item_date=date(2026, 6, 18),
        due_date=date(2026, 7, 18),
        currency=USD,
        open_amount=usd("9340.00"),
        functional_open_amount=usd("9340.00"),
    )
    assert item.open_amount == usd("9340")


def test_periods() -> None:
    assert period_of(date(2026, 3, 14)) == "2026-03"
    assert validate_period("2026-12") == "2026-12"
    for bad in ("2026-3", "26-03", "2026-00"):
        with pytest.raises(CanonicalRecordError):
            validate_period(bad)


def test_natural_keys_are_stable_strings() -> None:
    assert nk.journal_entry("JE-1") == "je:JE-1"
    assert nk.journal_line("JE-1", 2) == "jl:JE-1:2"
    assert nk.document(DocumentType.BILL, "B-1") == "doc:bill:B-1"
    assert nk.payment(PaymentDirection.DISBURSED, "PAY-1") == "pay:disbursed:PAY-1"
    assert nk.party(PartyType.CUSTOMER, "C-1") == "party:customer:C-1"
    assert nk.aging_item(AgingType.AP, date(2025, 12, 31), "B-1") == "aging:ap:2025-12-31:B-1"
    posted = date(2026, 3, 5)
    fee = {"description": "FEE", "reference": None}
    key = nk.bank_transaction("4471", posted, amount=usd("-45.00"), ordinal=0, **fee)  # type: ignore[arg-type]
    assert key == nk.bank_transaction("4471", posted, amount=usd("-45.0"), ordinal=0, **fee)  # type: ignore[arg-type]
    assert key != nk.bank_transaction("4471", posted, amount=usd("-45.00"), ordinal=1, **fee)  # type: ignore[arg-type]


def test_natural_keys_do_not_encode_chronology() -> None:
    """Identifiers establish identity only (SC-05): key order carries no date meaning."""
    later_date_lower_number = nk.document(DocumentType.INVOICE, "INV-10542")
    earlier_date_higher_number = nk.document(DocumentType.INVOICE, "INV-10877")
    assert later_date_lower_number < earlier_date_higher_number  # string order is not chronology


def test_source_location() -> None:
    SourceLocation(dataset="gl_detail", file_name="gl.csv", row_number=3, line_start=4, line_end=5)
    with pytest.raises(LineageError):
        SourceLocation(
            dataset="gl_detail", file_name="gl.csv", row_number=3, line_start=5, line_end=4
        )
