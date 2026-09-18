"""Clean books for Kestrel Instruments Ltd (fictional), the second-company generalization test.

Nothing here is copied from Brightwater. The company keeps its books in **EUR** on a fiscal year
that starts in **July**, buys and sells in USD as well, uses its own identifier schemes, and exports
from a different legacy system with different column names, a different date format, a different
decimal convention and a different row order.

The universe is built from documents: every invoice, bill, payment and accrual posts a balanced
journal entry, and the control reports (trial balance, agings, bank statement) are computed **from**
those postings, so clean books tie by construction. Defects are applied afterwards
(:mod:`relay_scenarios.kestrel.defects`), so each one breaks exactly the control it is meant to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

FUNCTIONAL: Final = "EUR"
FISCAL_YEAR_START_MONTH: Final = 7
OPENING: Final = date(2025, 12, 31)
HISTORY_START: Final = date(2026, 1, 1)
CUTOVER: Final = date(2026, 6, 30)
GO_LIVE: Final = date(2026, 7, 1)
PERIOD_ENDS: Final = (
    date(2026, 1, 31),
    date(2026, 2, 28),
    date(2026, 3, 31),
    date(2026, 4, 30),
    date(2026, 5, 31),
    date(2026, 6, 30),
)


def money(value: str | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class Account:
    code: str
    name: str
    subtype: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Party:
    code: str
    name: str
    city: str
    country: str
    currency: str
    terms: int
    email: str
    tax_last4: str
    active: bool = True


@dataclass(frozen=True, slots=True)
class Line:
    account: str
    amount: Decimal
    """Debit positive, credit negative, in the functional currency."""
    party: str | None = None
    document: str | None = None
    memo: str = ""
    foreign: Decimal | None = None
    currency: str = FUNCTIONAL


@dataclass(frozen=True, slots=True)
class Entry:
    number: str
    entry_date: date
    module: str
    lines: tuple[Line, ...]
    reverses: str | None = None

    @property
    def period(self) -> str:
        return f"{self.entry_date:%Y-%m}"


@dataclass(frozen=True, slots=True)
class Document:
    number: str
    party: str
    doc_date: date
    due_date: date
    currency: str
    total: Decimal
    """In the document currency."""
    functional_total: Decimal
    fx_rate: Decimal
    open_amount: Decimal
    """Open at cutover, in the document currency."""


@dataclass(frozen=True, slots=True)
class Settlement:
    number: str
    direction: str
    paid_on: date
    party: str
    method: str
    currency: str
    amount: Decimal
    functional_amount: Decimal
    fx_rate: Decimal
    applied: tuple[tuple[str, Decimal], ...]
    """(document number, amount applied in the document's currency)."""
    reference: str = ""

    @property
    def unapplied(self) -> Decimal:
        return money(self.amount - sum((a for _, a in self.applied), Decimal(0)))


@dataclass(frozen=True, slots=True)
class BankLine:
    posted: date
    description: str
    amount: Decimal
    reference: str


@dataclass
class Books:
    accounts: list[Account] = field(default_factory=list)
    target_accounts: list[Account] = field(default_factory=list)
    mapping: list[tuple[str, str]] = field(default_factory=list)
    customers: list[Party] = field(default_factory=list)
    suppliers: list[Party] = field(default_factory=list)
    invoices: list[Document] = field(default_factory=list)
    bills: list[Document] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    bank: list[BankLine] = field(default_factory=list)
    fx: list[tuple[date, str, str, Decimal]] = field(default_factory=list)
    opening: dict[str, Decimal] = field(default_factory=dict)
    """Opening trial balance by account (debit positive)."""

    def balance_at(self, account: str, at: date) -> Decimal:
        total = self.opening.get(account, Decimal(0))
        for entry in self.entries:
            if entry.entry_date <= at:
                total += sum(
                    (line.amount for line in entry.lines if line.account == account), Decimal(0)
                )
        return money(total)


# --------------------------------------------------------------------------------- chart

CASH = "1010"
RECEIVABLES = "1200"
INVENTORY = "1300"
PREPAID = "1400"
PAYABLES = "2000"
DEPOSITS = "2150"
VAT_PAYABLE = "2200"
EQUITY = "3000"
RETAINED = "3900"
REVENUE = "4000"
SERVICE_REVENUE = "4100"
COGS = "5000"
RENT = "6100"
SALARIES = "6200"
FX_LOSS = "6900"
UNMAPPED = "4990"

ACCOUNTS: Final = (
    Account(CASH, "Nordbank current account", "cash"),
    Account(RECEIVABLES, "Trade receivables", "accounts_receivable"),
    Account(INVENTORY, "Instrument stock", "inventory"),
    Account(PREPAID, "Prepaid insurance", "prepaid"),
    Account(PAYABLES, "Trade payables", "accounts_payable"),
    Account(DEPOSITS, "Customer deposits", "accrued_liability"),
    Account(VAT_PAYABLE, "VAT payable", "accrued_liability"),
    Account(EQUITY, "Share capital", "common_stock"),
    Account(RETAINED, "Retained earnings", "retained_earnings"),
    Account(REVENUE, "Instrument sales", "operating_revenue"),
    Account(SERVICE_REVENUE, "Calibration services", "operating_revenue"),
    Account(COGS, "Cost of instruments sold", "cost_of_goods_sold"),
    Account(RENT, "Workshop rent", "operating_expense"),
    Account(SALARIES, "Wages and salaries", "operating_expense"),
    Account(FX_LOSS, "Exchange differences", "other_expense"),
    Account(UNMAPPED, "Scrap recoveries", "other_income"),
)

TARGET_ACCOUNTS: Final = (
    Account("10-1000", "Bank - operating", "cash"),
    Account("11-1000", "Accounts receivable", "accounts_receivable"),
    Account("12-1000", "Inventory", "inventory"),
    Account("13-1000", "Prepayments", "prepaid"),
    Account("20-1000", "Accounts payable", "accounts_payable"),
    Account("21-1000", "Customer deposits", "accrued_liability"),
    Account("21-2000", "Indirect tax payable", "accrued_liability"),
    Account("30-1000", "Share capital", "common_stock"),
    Account("39-1000", "Retained earnings", "retained_earnings"),
    Account("40-1000", "Product revenue", "operating_revenue"),
    Account("41-1000", "Service revenue", "operating_revenue"),
    Account("50-1000", "Cost of sales", "cost_of_goods_sold"),
    Account("61-1000", "Occupancy", "operating_expense"),
    Account("62-1000", "Personnel", "operating_expense"),
    Account("69-1000", "Finance charges", "other_expense"),
    Account("49-1000", "Other income", "other_income"),
)

MAPPING: Final = (
    (CASH, "10-1000"),
    (RECEIVABLES, "11-1000"),
    (INVENTORY, "12-1000"),
    (PREPAID, "13-1000"),
    (PAYABLES, "20-1000"),
    (DEPOSITS, "21-1000"),
    (VAT_PAYABLE, "21-2000"),
    (EQUITY, "30-1000"),
    (RETAINED, "39-1000"),
    (REVENUE, "40-1000"),
    (SERVICE_REVENUE, "41-1000"),
    (COGS, "50-1000"),
    (RENT, "61-1000"),
    (SALARIES, "62-1000"),
    (FX_LOSS, "69-1000"),
    (UNMAPPED, "49-1000"),
)

CUSTOMERS: Final = (
    Party(
        "K-0001",
        "Halden Metrology AS",
        "Bergen",
        "NO",
        "EUR",
        30,
        "ap@halden-metrology.example",
        "4471",
    ),
    Party(
        "K-0002",
        "Ottersen Laboratorier",
        "Trondheim",
        "NO",
        "EUR",
        45,
        "invoices@ottersen.example",
        "9930",
    ),
    Party(
        "K-0003",
        "Brecht Präzision GmbH",
        "Aachen",
        "DE",
        "EUR",
        30,
        "rechnung@brecht-praezision.example",
        "2218",
    ),
    Party(
        "K-0004",
        "Lindqvist Verkstad AB",
        "Malmö",
        "SE",
        "EUR",
        30,
        "faktura@lindqvist-verkstad.example",
        "7742",
    ),
    Party(
        "K-0005",
        "Calder Scientific Ltd",
        "Dundee",
        "GB",
        "USD",
        60,
        "accounts@calder-scientific.example",
        "1183",
    ),
    Party(
        "K-0006",
        "Vossberg Institut",
        "Basel",
        "CH",
        "EUR",
        30,
        "kreditoren@vossberg-institut.example",
        "6604",
    ),
    Party(
        "K-0007",
        "Marchetti Strumenti Srl",
        "Padova",
        "IT",
        "EUR",
        45,
        "fatture@marchetti-strumenti.example",
        "3357",
    ),
    Party(
        "K-0008",
        "Teversham Optics",
        "Cambridge",
        "GB",
        "USD",
        30,
        "payables@teversham-optics.example",
        "8890",
    ),
)

SUPPLIERS: Final = (
    Party(
        "L-0001",
        "Norrsken Components AB",
        "Uppsala",
        "SE",
        "EUR",
        30,
        "sales@norrsken-components.example",
        "5521",
    ),
    Party(
        "L-0002",
        "Weierhof Kunststoff",
        "Mainz",
        "DE",
        "EUR",
        45,
        "buchhaltung@weierhof.example",
        "1094",
    ),
    Party(
        "L-0003",
        "Pallas Calibration NV",
        "Leuven",
        "BE",
        "EUR",
        30,
        "finance@pallas-calibration.example",
        "7238",
    ),
    Party(
        "L-0004",
        "Ridgeway Tooling Inc",
        "Portland",
        "US",
        "USD",
        30,
        "ar@ridgeway-tooling.example",
        "4415",
    ),
    Party(
        "L-0005",
        "Storvik Eiendom AS",
        "Bergen",
        "NO",
        "EUR",
        15,
        "leie@storvik-eiendom.example",
        "2867",
    ),
    Party(
        "L-0006",
        "Talvik Logistikk",
        "Oslo",
        "NO",
        "EUR",
        30,
        "faktura@talvik-logistikk.example",
        "9142",
    ),
)

USD_RATES: Final = {
    date(2026, 1, 8): Decimal("0.9120"),
    date(2026, 1, 15): Decimal("0.9151"),
    date(2026, 1, 22): Decimal("0.9109"),
    date(2026, 1, 29): Decimal("0.9140"),
    date(2026, 2, 5): Decimal("0.9171"),
    date(2026, 2, 12): Decimal("0.9129"),
    date(2026, 2, 19): Decimal("0.9160"),
    date(2026, 2, 26): Decimal("0.9191"),
    date(2026, 3, 5): Decimal("0.9149"),
    date(2026, 3, 12): Decimal("0.9180"),
    date(2026, 3, 19): Decimal("0.9211"),
    date(2026, 3, 26): Decimal("0.9169"),
    date(2026, 4, 2): Decimal("0.9200"),
    date(2026, 4, 9): Decimal("0.9231"),
    date(2026, 4, 16): Decimal("0.9189"),
    date(2026, 4, 23): Decimal("0.9220"),
    date(2026, 4, 30): Decimal("0.9251"),
    date(2026, 5, 7): Decimal("0.9209"),
    date(2026, 5, 14): Decimal("0.9240"),
    date(2026, 5, 21): Decimal("0.9271"),
    date(2026, 5, 28): Decimal("0.9229"),
    date(2026, 6, 4): Decimal("0.9260"),
    date(2026, 6, 11): Decimal("0.9291"),
    date(2026, 6, 18): Decimal("0.9249"),
    date(2026, 6, 25): Decimal("0.9280"),
}


# ----------------------------------------------------------------------------- construction


def _eur(amount: Decimal, currency: str, rate: Decimal) -> Decimal:
    """Document currency into EUR at the document's rate (the generator's own arithmetic)."""
    return amount if currency == FUNCTIONAL else money(amount * rate)


def _rate_for(day: date) -> Decimal:
    published = sorted(USD_RATES)
    usable = [d for d in published if d <= day]
    return USD_RATES[usable[-1]] if usable else USD_RATES[published[0]]


class _Numbering:
    """Identifier schemes, deliberately unlike Brightwater's."""

    def __init__(self) -> None:
        self.invoice = 0
        self.bill = 0
        self.journal = 0
        self.settlement = 0

    def next_invoice(self) -> str:
        self.invoice += 1
        return f"S-2026-{self.invoice:04d}"

    def next_bill(self) -> str:
        self.bill += 1
        return f"P-2026-{self.bill:04d}"

    def next_journal(self) -> str:
        self.journal += 1
        return f"JNL-{self.journal:05d}"

    def next_settlement(self) -> str:
        self.settlement += 1
        return f"Z-{self.settlement:04d}"


def _month_days(month: int) -> tuple[date, date]:
    first = date(2026, month, 1)
    last = PERIOD_ENDS[month - 1]
    return first, last


def build_books() -> Books:
    """Clean books: every control report agrees with the ledger, and no rule has anything to say."""
    books = Books(
        accounts=list(ACCOUNTS),
        target_accounts=list(TARGET_ACCOUNTS),
        mapping=list(MAPPING),
        customers=list(CUSTOMERS),
        suppliers=list(SUPPLIERS),
    )
    numbering = _Numbering()
    books.fx = [(day, "USD", FUNCTIONAL, rate) for day, rate in sorted(USD_RATES.items())]

    carried = _opening_documents(books)
    _opening_balances(books, carried)
    for month in range(1, 7):
        _trading_month(books, numbering, month)
    _scrap_recovery(books, numbering)
    _accruals(books, numbering)
    _bank_statement(books)
    return books


def _opening_documents(books: Books) -> tuple[Decimal, Decimal]:
    """Invoices and bills still open at the opening date, carried into the window (SC-04)."""
    receivable = Decimal(0)
    payable = Decimal(0)
    for index, (customer, amount, day) in enumerate(
        (
            (CUSTOMERS[0], money("18450.00"), date(2025, 11, 18)),
            (CUSTOMERS[2], money("9120.50"), date(2025, 12, 3)),
            (CUSTOMERS[5], money("24780.00"), date(2025, 12, 19)),
        )
    ):
        number = f"S-2025-{index + 41:04d}"
        books.invoices.append(
            Document(
                number=number,
                party=customer.code,
                doc_date=day,
                due_date=day + timedelta(days=customer.terms),
                currency=FUNCTIONAL,
                total=amount,
                functional_total=amount,
                fx_rate=Decimal("1"),
                open_amount=amount,
            )
        )
        receivable += amount
    for index, (supplier, amount, day) in enumerate(
        (
            (SUPPLIERS[0], money("7310.00"), date(2025, 12, 8)),
            (SUPPLIERS[2], money("3985.40"), date(2025, 12, 22)),
        )
    ):
        number = f"P-2025-{index + 17:04d}"
        books.bills.append(
            Document(
                number=number,
                party=supplier.code,
                doc_date=day,
                due_date=day + timedelta(days=supplier.terms),
                currency=FUNCTIONAL,
                total=amount,
                functional_total=amount,
                fx_rate=Decimal("1"),
                open_amount=amount,
            )
        )
        payable += amount
    return money(receivable), money(payable)


def _opening_balances(books: Books, carried: tuple[Decimal, Decimal]) -> None:
    receivable, payable = carried
    cash = money("214380.65")
    inventory = money("86500.00")
    prepaid = money("4200.00")
    deposits = money("6500.00")
    vat = money("11840.25")
    capital = money("50000.00")
    assets = cash + receivable + inventory + prepaid
    liabilities = payable + deposits + vat + capital
    books.opening = {
        CASH: cash,
        RECEIVABLES: receivable,
        INVENTORY: inventory,
        PREPAID: prepaid,
        PAYABLES: -payable,
        DEPOSITS: -deposits,
        VAT_PAYABLE: -vat,
        EQUITY: -capital,
        RETAINED: -(assets - liabilities),
    }


_SALES: Final = (
    # (customer index, net amount, cost, service revenue share, day of month, currency)
    (0, "21400.00", "12840.00", "0.00", 7, FUNCTIONAL),
    (1, "13980.50", "8388.30", "1250.00", 11, FUNCTIONAL),
    (4, "17600.00", "10560.00", "0.00", 15, "USD"),
    (2, "9450.75", "5670.45", "0.00", 19, FUNCTIONAL),
    (6, "26310.00", "15786.00", "2400.00", 23, FUNCTIONAL),
)
_PURCHASES: Final = (
    (0, "8420.00", 5, FUNCTIONAL),
    (3, "6150.00", 12, "USD"),
    (1, "4980.25", 17, FUNCTIONAL),
    (5, "2310.00", 26, FUNCTIONAL),
)


def _trading_month(books: Books, numbering: _Numbering, month: int) -> None:
    first, last = _month_days(month)
    for customer_index, net, cost, service, day, currency in _SALES:
        customer = CUSTOMERS[customer_index]
        doc_date = date(2026, month, day)
        rate = _rate_for(doc_date) if currency != FUNCTIONAL else Decimal("1")
        total = money(net)
        functional = _eur(total, currency, rate)
        number = numbering.next_invoice()
        paid = month <= 4  # invoices of the last two months stay open at cutover
        books.invoices.append(
            Document(
                number=number,
                party=customer.code,
                doc_date=doc_date,
                due_date=doc_date + timedelta(days=customer.terms),
                currency=currency,
                total=total,
                functional_total=functional,
                fx_rate=rate,
                open_amount=Decimal("0.00") if paid else total,
            )
        )
        service_part = _eur(money(service), currency, rate)
        product_part = money(functional - service_part)
        lines = [
            Line(
                RECEIVABLES,
                functional,
                customer.code,
                number,
                "Invoice",
                total if currency != FUNCTIONAL else None,
                currency,
            ),
            Line(REVENUE, -product_part, customer.code, number, "Instrument sales"),
        ]
        if service_part:
            lines.append(Line(SERVICE_REVENUE, -service_part, customer.code, number, "Calibration"))
        books.entries.append(Entry(numbering.next_journal(), doc_date, "ar", tuple(lines)))
        cost_amount = _eur(money(cost), currency, rate)
        books.entries.append(
            Entry(
                numbering.next_journal(),
                doc_date,
                "manual",
                (
                    Line(COGS, cost_amount, None, number, "Cost of sale"),
                    Line(INVENTORY, -cost_amount, None, number, "Stock relief"),
                ),
            )
        )
        if paid:
            _receipt(books, numbering, customer, number, total, currency, doc_date, rate)

    for supplier_index, net, day, currency in _PURCHASES:
        supplier = SUPPLIERS[supplier_index]
        doc_date = date(2026, month, day)
        rate = _rate_for(doc_date) if currency != FUNCTIONAL else Decimal("1")
        total = money(net)
        functional = _eur(total, currency, rate)
        number = numbering.next_bill()
        settled = month <= 4
        books.bills.append(
            Document(
                number=number,
                party=supplier.code,
                doc_date=doc_date,
                due_date=doc_date + timedelta(days=supplier.terms),
                currency=currency,
                total=total,
                functional_total=functional,
                fx_rate=rate,
                open_amount=Decimal("0.00") if settled else total,
            )
        )
        books.entries.append(
            Entry(
                numbering.next_journal(),
                doc_date,
                "ap",
                (
                    Line(INVENTORY, functional, None, number, "Goods received"),
                    Line(
                        PAYABLES,
                        -functional,
                        supplier.code,
                        number,
                        "Purchase invoice",
                        -total if currency != FUNCTIONAL else None,
                        currency,
                    ),
                ),
            )
        )
        if settled:
            _disbursement(books, numbering, supplier, number, total, currency, doc_date, rate)

    # Recurring rent on the first of the month: identical amounts, never a duplicate (benign).
    books.entries.append(
        Entry(
            numbering.next_journal(),
            first,
            "manual",
            (
                Line(RENT, money("2400.00"), None, None, "Workshop rent"),
                Line(CASH, money("-2400.00"), None, None, "Workshop rent"),
            ),
        )
    )
    books.bank.append(
        BankLine(first, "Storvik Eiendom rent", money("-2400.00"), f"RENT-{month:02d}")
    )
    books.entries.append(
        Entry(
            numbering.next_journal(),
            last,
            "manual",
            (
                Line(SALARIES, money("18750.00"), None, None, "Payroll"),
                Line(CASH, money("-18750.00"), None, None, "Payroll"),
            ),
        )
    )
    books.bank.append(BankLine(last, "Payroll run", money("-18750.00"), f"PAY-{month:02d}"))


def _receipt(
    books: Books,
    numbering: _Numbering,
    customer: Party,
    document: str,
    amount: Decimal,
    currency: str,
    doc_date: date,
    doc_rate: Decimal,
) -> None:
    """A receipt settles the invoice at the invoice's rate and hits cash at the day's rate.

    The difference is an exchange gain or loss, which is what the ledger of a company that invoices
    in a foreign currency actually looks like.
    """
    paid_on = doc_date + timedelta(days=min(customer.terms, 20))
    pay_rate = _rate_for(paid_on) if currency != FUNCTIONAL else Decimal("1")
    cash_amount = _eur(amount, currency, pay_rate)
    relief = _eur(amount, currency, doc_rate)
    number = numbering.next_settlement()
    books.settlements.append(
        Settlement(
            number=number,
            direction="received",
            paid_on=paid_on,
            party=customer.code,
            method="wire" if currency != FUNCTIONAL else "ach",
            currency=currency,
            amount=amount,
            functional_amount=cash_amount,
            fx_rate=pay_rate,
            applied=((document, amount),),
            reference=f"REF{number[-4:]}",
        )
    )
    lines = [
        Line(CASH, cash_amount, customer.code, document, "Customer receipt"),
        Line(
            RECEIVABLES,
            -relief,
            customer.code,
            document,
            "Customer receipt",
            -amount if currency != FUNCTIONAL else None,
            currency,
        ),
    ]
    difference = money(relief - cash_amount)
    if difference:
        lines.append(Line(FX_LOSS, difference, None, document, "Exchange difference"))
    books.entries.append(Entry(numbering.next_journal(), paid_on, "cash_receipts", tuple(lines)))
    books.bank.append(
        BankLine(paid_on, f"{customer.name} receipt", cash_amount, f"REF{number[-4:]}")
    )


def _disbursement(
    books: Books,
    numbering: _Numbering,
    supplier: Party,
    document: str,
    amount: Decimal,
    currency: str,
    doc_date: date,
    doc_rate: Decimal,
) -> None:
    paid_on = doc_date + timedelta(days=min(supplier.terms, 25))
    pay_rate = _rate_for(paid_on) if currency != FUNCTIONAL else Decimal("1")
    cash_amount = _eur(amount, currency, pay_rate)
    relief = _eur(amount, currency, doc_rate)
    number = numbering.next_settlement()
    books.settlements.append(
        Settlement(
            number=number,
            direction="disbursed",
            paid_on=paid_on,
            party=supplier.code,
            method="wire" if currency != FUNCTIONAL else "check",
            currency=currency,
            amount=amount,
            functional_amount=cash_amount,
            fx_rate=pay_rate,
            applied=((document, amount),),
            reference=f"REF{number[-4:]}",
        )
    )
    lines = [
        Line(
            PAYABLES,
            relief,
            supplier.code,
            document,
            "Supplier payment",
            amount if currency != FUNCTIONAL else None,
            currency,
        ),
        Line(CASH, -cash_amount, supplier.code, document, "Supplier payment"),
    ]
    difference = money(cash_amount - relief)
    if difference:
        lines.append(Line(FX_LOSS, difference, None, document, "Exchange difference"))
    books.entries.append(
        Entry(numbering.next_journal(), paid_on, "cash_disbursements", tuple(lines))
    )
    books.bank.append(
        BankLine(paid_on, f"{supplier.name} payment", -cash_amount, f"REF{number[-4:]}")
    )


def _scrap_recovery(books: Books, numbering: _Numbering) -> None:
    """A small credit to an account nothing else touches, so a mapping gap has something to show."""
    books.entries.append(
        Entry(
            numbering.next_journal(),
            date(2026, 4, 14),
            "manual",
            (
                Line(CASH, money("320.00"), None, None, "Scrap recovery"),
                Line(UNMAPPED, money("-320.00"), None, None, "Scrap recovery"),
            ),
        )
    )
    books.bank.append(BankLine(date(2026, 4, 14), "Scrap merchant", money("320.00"), "SCRAP-04"))


def _accruals(books: Books, numbering: _Numbering) -> None:
    """A reversal pair (benign look-alike) and the insurance release."""
    accrual_date = date(2026, 3, 31)
    accrued = Entry(
        numbering.next_journal(),
        accrual_date,
        "manual",
        (
            Line(RENT, money("1150.00"), None, None, "March accrual"),
            Line(VAT_PAYABLE, money("-1150.00"), None, None, "March accrual"),
        ),
    )
    books.entries.append(accrued)
    books.entries.append(
        Entry(
            numbering.next_journal(),
            date(2026, 4, 1),
            "manual",
            (
                Line(RENT, money("-1150.00"), None, None, "Reversal of March accrual"),
                Line(VAT_PAYABLE, money("1150.00"), None, None, "Reversal of March accrual"),
            ),
            reverses=accrued.number,
        )
    )
    for month in range(1, 7):
        _, last = _month_days(month)
        books.entries.append(
            Entry(
                numbering.next_journal(),
                last,
                "manual",
                (
                    Line(RENT, money("700.00"), None, None, "Insurance release"),
                    Line(PREPAID, money("-700.00"), None, None, "Insurance release"),
                ),
            )
        )


def _bank_statement(books: Books) -> None:
    """The statement mirrors every cash movement, ordered by date, with a running balance."""
    opening = books.opening[CASH]
    books.bank.sort(key=lambda line: (line.posted, line.reference))
    running = opening
    ordered: list[BankLine] = []
    for line in books.bank:
        running = money(running + line.amount)
        ordered.append(line)
    books.bank = ordered
