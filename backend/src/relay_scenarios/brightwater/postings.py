"""LedgerPro module postings: how documents and payments become journal entries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Final

from relay.canonical.enums import PartyType, SourceModule
from relay.canonical.records import (
    Document,
    JournalEntry,
    JournalLine,
    PartyKey,
    Payment,
    period_of,
)
from relay.core.currency import Currency
from relay.core.money import Money
from relay_scenarios.brightwater.constants import PERPETUAL_INVENTORY_START

USD: Final = Currency.of("USD")

CASH: Final = "1010"
RECEIVABLES: Final = "1200"
INVENTORY: Final = "1300"
PAYABLES: Final = "2000"
COGS: Final = "5000"
FX_GAIN_LOSS: Final = "7100"


def digits_of(number: str) -> str:
    return number.rsplit("-", 1)[-1]


def invoice_entry_number(invoice_number: str) -> str:
    return f"JE-AR-{digits_of(invoice_number)}"


def bill_entry_number(bill_number: str) -> str:
    return f"JE-AP-{digits_of(bill_number)}"


def receipt_entry_number(payment_number: str) -> str:
    return f"JE-CR-{digits_of(payment_number)}"


def disbursement_entry_number(payment_number: str) -> str:
    return f"JE-CD-{digits_of(payment_number)}"


def _usd(amount: Decimal) -> Money:
    return Money(amount, USD)


def post_invoice(
    invoice: Document, revenue_account: str, cost: Decimal, *, entry_date: date | None = None
) -> JournalEntry:
    posted_on = entry_date or invoice.document_date
    party = PartyKey(party_type=PartyType.CUSTOMER, code=invoice.party_code)
    lines = [
        JournalLine(
            line_number=1,
            account_code=RECEIVABLES,
            amount=invoice.total,
            functional_amount=invoice.functional_total,
            party=party,
            document_number=invoice.number,
        ),
        JournalLine(
            line_number=2,
            account_code=revenue_account,
            amount=-invoice.total,
            functional_amount=-invoice.functional_total,
            document_number=invoice.number,
        ),
    ]
    if invoice.document_date >= PERPETUAL_INVENTORY_START and cost > 0:
        lines += [
            JournalLine(
                line_number=3,
                account_code=COGS,
                amount=_usd(cost),
                functional_amount=_usd(cost),
                document_number=invoice.number,
            ),
            JournalLine(
                line_number=4,
                account_code=INVENTORY,
                amount=_usd(-cost),
                functional_amount=_usd(-cost),
                document_number=invoice.number,
            ),
        ]
    return JournalEntry(
        entry_number=invoice_entry_number(invoice.number),
        entry_date=posted_on,
        posting_period=period_of(invoice.document_date),
        source_module=SourceModule.ACCOUNTS_RECEIVABLE,
        memo=f"Invoice {invoice.number}",
        lines=tuple(lines),
    )


def post_bill(
    bill: Document, expense_account: str, *, entry_date: date | None = None
) -> JournalEntry:
    posted_on = entry_date or bill.document_date
    party = PartyKey(party_type=PartyType.VENDOR, code=bill.party_code)
    lines = (
        JournalLine(
            line_number=1,
            account_code=expense_account,
            amount=bill.total,
            functional_amount=bill.functional_total,
            document_number=bill.number,
            memo=bill.party_reference or "",
        ),
        JournalLine(
            line_number=2,
            account_code=PAYABLES,
            amount=-bill.total,
            functional_amount=-bill.functional_total,
            party=party,
            document_number=bill.number,
            memo=bill.party_reference or "",
        ),
    )
    return JournalEntry(
        entry_number=bill_entry_number(bill.number),
        entry_date=posted_on,
        posting_period=period_of(bill.document_date),
        source_module=SourceModule.ACCOUNTS_PAYABLE,
        memo=f"Bill {bill.number}",
        lines=lines,
    )


def post_receipt(receipt: Payment, booked_functional: dict[str, Money]) -> JournalEntry:
    """Cash receipt: debit cash as received (functional), credit receivables at booked amounts.

    ``booked_functional`` maps each applied document to the functional amount that closes it; any
    difference to the cash received is a realized FX gain or loss.
    """
    party = PartyKey(party_type=PartyType.CUSTOMER, code=receipt.party_code)
    lines = [
        JournalLine(
            line_number=1,
            account_code=CASH,
            amount=receipt.functional_amount,
            functional_amount=receipt.functional_amount,
            document_number=receipt.number,
        ),
    ]
    credited = Decimal(0)
    for application in receipt.applications:
        booked = booked_functional[application.document_number]
        lines.append(
            JournalLine(
                line_number=len(lines) + 1,
                account_code=RECEIVABLES,
                amount=-application.applied_amount,
                functional_amount=-booked,
                party=party,
                document_number=application.document_number,
            )
        )
        credited += booked.amount
    if not receipt.unapplied_amount.is_zero():
        unapplied_functional = receipt.functional_amount.amount - sum(
            (a.applied_functional_amount.amount for a in receipt.applications), Decimal(0)
        )
        lines.append(
            JournalLine(
                line_number=len(lines) + 1,
                account_code=RECEIVABLES,
                amount=-receipt.unapplied_amount,
                functional_amount=_usd(-unapplied_functional),
                party=party,
                document_number=receipt.number,
                memo="Unapplied payment",
            )
        )
        credited += unapplied_functional
    difference = receipt.functional_amount.amount - credited
    if difference != 0:
        lines.append(
            JournalLine(
                line_number=len(lines) + 1,
                account_code=FX_GAIN_LOSS,
                amount=_usd(-difference),
                functional_amount=_usd(-difference),
                document_number=receipt.number,
                memo="Realized FX gain/loss",
            )
        )
    return JournalEntry(
        entry_number=receipt_entry_number(receipt.number),
        entry_date=receipt.payment_date,
        posting_period=period_of(receipt.payment_date),
        source_module=SourceModule.CASH_RECEIPTS,
        memo=f"Payment {receipt.number}",
        lines=tuple(lines),
    )


def post_disbursement(payment: Payment) -> JournalEntry:
    party = PartyKey(party_type=PartyType.VENDOR, code=payment.party_code)
    lines = [
        JournalLine(
            line_number=index + 1,
            account_code=PAYABLES,
            amount=application.applied_amount,
            functional_amount=application.applied_functional_amount,
            party=party,
            document_number=application.document_number,
        )
        for index, application in enumerate(payment.applications)
    ]
    lines.append(
        JournalLine(
            line_number=len(lines) + 1,
            account_code=CASH,
            amount=-payment.functional_amount,
            functional_amount=-payment.functional_amount,
            document_number=payment.number,
            memo=f"Check {payment.reference}" if payment.method.value == "check" else "",
        )
    )
    return JournalEntry(
        entry_number=disbursement_entry_number(payment.number),
        entry_date=payment.payment_date,
        posting_period=period_of(payment.payment_date),
        source_module=SourceModule.CASH_DISBURSEMENTS,
        memo=f"Bill payment {payment.number}",
        lines=tuple(lines),
    )
