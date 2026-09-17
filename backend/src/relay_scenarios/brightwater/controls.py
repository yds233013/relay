"""Control reports computed from the full LedgerPro universe.

These are what LedgerPro's own reports would print. They read the complete legacy database, not the
filtered exports, which is what makes them *independent* controls:

* **Trial balance** (by posting period) sums every posted journal line in the ledger, so it still
  includes activity whose detail rows are lost or corrupted in the GL export (DS-05) and accounts
  the chart-of-accounts export filters out (DS-12).
* **AR/AP agings** list every open document and unapplied payment in the subledger, so they include
  documents the invoice export filters out (DS-04) and are dated by business date, not identifiers.
* **Bank statement** is First Cascade Bank's record of cash movements, including activity never
  recorded in the ledger (DS-10) and the timing of outstanding checks and deposits in transit.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from relay.canonical.enums import AgingItemKind, AgingType, DocumentType, PaymentDirection
from relay.canonical.records import AgingItem, ControlBalance, Document, Payment, period_of
from relay.core.currency import Currency
from relay.core.money import Money
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.calendar import month_end
from relay_scenarios.errors import ScenarioConsistencyError

USD = Currency.of("USD")


def reporting_period_ends(universe: LegacyUniverse) -> list[date]:
    plan = universe.plan
    ends = [plan.opening_balance_date]
    current = plan.history_start_date
    while current <= plan.cutover_date:
        ends.append(month_end(current.year, current.month))
        current = date(current.year + (current.month // 12), current.month % 12 + 1, 1)
    return ends


def trial_balance(universe: LegacyUniverse) -> list[ControlBalance]:
    """Closing balance of every legacy account at the opening date and at each period end."""
    plan = universe.plan
    by_period: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    opening_period = period_of(plan.opening_balance_date)
    for entry in universe.journals.values():
        if entry.posting_period <= opening_period:
            continue  # already reflected in the opening balances
        for line in entry.lines:
            by_period[entry.posting_period][line.account_code] += line.functional_amount.amount
    result: list[ControlBalance] = []
    running = {code: universe.opening_balances.get(code, Decimal(0)) for code in universe.accounts}
    for period_end in reporting_period_ends(universe):
        period = period_of(period_end)
        if period_end != plan.opening_balance_date:
            for code, amount in by_period[period].items():
                running[code] = running.get(code, Decimal(0)) + amount
        result.extend(
            ControlBalance(
                account_code=code,
                period_end=period_end,
                balance=Money(running.get(code, Decimal(0)), USD),
            )
            for code in sorted(universe.accounts)
        )
    unknown = {code for period in by_period.values() for code in period} - set(universe.accounts)
    if unknown:
        raise ScenarioConsistencyError(
            f"journal lines post to accounts missing from the ledger: {sorted(unknown)}"
        )
    return result


def _documents(universe: LegacyUniverse, aging_type: AgingType) -> dict[str, Document]:
    return universe.invoices if aging_type is AgingType.AR else universe.bills


def _direction(aging_type: AgingType) -> PaymentDirection:
    return PaymentDirection.RECEIVED if aging_type is AgingType.AR else PaymentDirection.DISBURSED


def open_amount(universe: LegacyUniverse, document: Document, as_of: date) -> Decimal:
    applied = Decimal(0)
    for payment in universe.payments.values():
        if payment.payment_date > as_of:
            continue
        for application in payment.applications:
            if application.document_number == document.number and _matches_type(payment, document):
                applied += application.applied_amount.amount
    return document.total.amount - applied


def _matches_type(payment: Payment, document: Document) -> bool:
    expected = (
        PaymentDirection.RECEIVED
        if document.document_type is DocumentType.INVOICE
        else PaymentDirection.DISBURSED
    )
    return payment.direction is expected


def aging(universe: LegacyUniverse, aging_type: AgingType, as_of: date) -> list[AgingItem]:
    items: list[AgingItem] = []
    for document in _documents(universe, aging_type).values():
        if document.document_date > as_of:
            continue
        remaining = open_amount(universe, document, as_of)
        if remaining < 0:
            raise ScenarioConsistencyError(f"{document.number} is over-applied")
        if remaining == 0:
            continue
        if remaining != document.total.amount and document.currency != USD:
            raise ScenarioConsistencyError(
                "partially paid foreign-currency documents are not modeled"
            )
        functional = (
            document.functional_total
            if remaining == document.total.amount
            else Money(remaining, USD)
        )
        items.append(
            AgingItem(
                aging_type=aging_type,
                as_of=as_of,
                party_code=document.party_code,
                kind=AgingItemKind.DOCUMENT,
                reference=document.number,
                item_date=document.document_date,
                due_date=document.due_date,
                currency=document.currency,
                open_amount=Money(remaining, document.currency),
                functional_open_amount=functional,
            )
        )
    for payment in universe.payments.values():
        if payment.direction is not _direction(aging_type) or payment.payment_date > as_of:
            continue
        if payment.unapplied_amount.is_zero():
            continue
        unapplied_functional = payment.functional_amount.amount - sum(
            (a.applied_functional_amount.amount for a in payment.applications), Decimal(0)
        )
        items.append(
            AgingItem(
                aging_type=aging_type,
                as_of=as_of,
                party_code=payment.party_code,
                kind=AgingItemKind.UNAPPLIED_PAYMENT,
                reference=payment.number,
                item_date=payment.payment_date,
                due_date=None,
                currency=payment.currency,
                open_amount=payment.unapplied_amount,
                functional_open_amount=Money(unapplied_functional, USD),
            )
        )
    return sorted(items, key=lambda i: (i.party_code, i.item_date, i.reference))


def aging_total(items: list[AgingItem]) -> Decimal:
    """Signed open balance: documents positive, unapplied payments negative."""
    total = Decimal(0)
    for item in items:
        sign = 1 if item.kind is AgingItemKind.DOCUMENT else -1
        total += sign * item.functional_open_amount.amount
    return total


@dataclass(frozen=True, slots=True)
class BankStatementLine:
    posted_date: date
    description: str
    amount: Decimal
    reference: str | None
    running_balance: Decimal


def bank_statement(
    universe: LegacyUniverse, opening_balance: Decimal, through: date
) -> list[BankStatementLine]:
    running = opening_balance
    lines: list[BankStatementLine] = []
    for bank_line in sorted(
        universe.bank_lines, key=lambda b: (b.transaction.posted_date, b.sequence)
    ):
        txn = bank_line.transaction
        if txn.posted_date > through:
            continue
        running += txn.amount.amount
        lines.append(
            BankStatementLine(
                txn.posted_date, txn.description, txn.amount.amount, txn.reference, running
            )
        )
    return lines


def bank_balance(universe: LegacyUniverse, as_of: date) -> Decimal:
    total = bank_opening_balance(universe)
    for bank_line in universe.bank_lines:
        if bank_line.transaction.posted_date <= as_of:
            total += bank_line.transaction.amount.amount
    return total


def bank_opening_balance(universe: LegacyUniverse) -> Decimal:
    """No reconciling items existed at the opening balance date (scenario assumption)."""
    return universe.opening_balances["1010"]


def gl_balance(universe: LegacyUniverse, account_code: str, as_of: date) -> Decimal:
    """Balance by entry date (opening balance plus lines dated in (opening, as_of])."""
    total = universe.opening_balances.get(account_code, Decimal(0))
    for entry in universe.journals.values():
        if universe.plan.opening_balance_date < entry.entry_date <= as_of:
            for line in entry.lines:
                if line.account_code == account_code:
                    total += line.functional_amount.amount
    return total
