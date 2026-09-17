"""Clean Brightwater books: a complete, internally consistent LedgerPro universe with no defects.

The builder simulates the legacy half-year (plus carried-forward open items from 2025) as drafts,
assigns identifiers, then materializes canonical records. Invariants are verified by ``checks.py``;
``build_clean_universe`` refuses to return books that violate them.

The clean books include the legitimate patterns that later serve as false-positive traps
(TN-01 to TN-05); they are ordinary business activity, not defects.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Final

from relay.canonical.enums import (
    DocumentType,
    PartyType,
    PaymentDirection,
    PaymentMethod,
    SourceModule,
)
from relay.canonical.records import (
    Account,
    BankTransaction,
    Document,
    FxRate,
    JournalEntry,
    JournalLine,
    Party,
    PartyKey,
    Payment,
    PaymentApplication,
    period_of,
)
from relay.core.currency import Currency
from relay.core.money import Money, convert
from relay_scenarios.brightwater import constants as k
from relay_scenarios.brightwater import numbering
from relay_scenarios.brightwater.chart import (
    LEGACY_ACCOUNTS,
    TARGET_ACCOUNTS,
    correct_account_mapping,
)
from relay_scenarios.brightwater.parties import (
    CLERKS,
    CustomerProfile,
    Segment,
    VendorCategory,
    VendorProfile,
    Warehouse,
    build_customers,
    build_vendors,
)
from relay_scenarios.brightwater.postings import (
    CASH,
    INVENTORY,
    post_bill,
    post_disbursement,
    post_invoice,
    post_receipt,
)
from relay_scenarios.brightwater.universe import (
    BankLine,
    BillInfo,
    CustomerInfo,
    InvoiceInfo,
    JournalInfo,
    LegacyAccountInfo,
    LegacyUniverse,
    VendorInfo,
)
from relay_scenarios.calendar import (
    add_business_days,
    days,
    is_business_day,
    last_business_day,
    month_end,
    next_business_day,
    previous_business_day,
)
from relay_scenarios.errors import ScenarioConsistencyError
from relay_scenarios.rng import ScenarioRng

USD: Final = Currency.of("USD")
EUR: Final = Currency.of("EUR")
ONE: Final = Decimal(1)
CENT: Final = Decimal("0.01")
H1_START: Final = k.PLAN.history_start_date
CUTOVER: Final = k.PLAN.cutover_date
MONTHS: Final = (1, 2, 3, 4, 5, 6)

REVENUE_ACCOUNT: Final = {
    Segment.GROCER: "4000",
    Segment.RESTAURANT: "4010",
    Segment.EXPORT: "4100",
}

ALPENKOST_DATES: Final = (
    date(2026, 1, 8),
    date(2026, 1, 20),
    date(2026, 1, 30),
    date(2026, 2, 9),
    date(2026, 2, 19),
    date(2026, 3, 2),
    date(2026, 3, 12),
    date(2026, 3, 23),
    date(2026, 4, 1),
    date(2026, 4, 9),
    date(2026, 4, 22),
    date(2026, 5, 1),
    date(2026, 5, 14),
    date(2026, 5, 26),
    date(2026, 6, 5),
    date(2026, 6, 16),
    date(2026, 6, 26),
)
ALPENKOST_PAYS_DUE_UNTIL: Final = date(2026, 6, 5)

LOC_MONTHLY_RATE: Final = Decimal("0.00575")
EQUIPMENT_LOAN_RATE: Final = Decimal("0.0055")
EQUIPMENT_LOAN_PRINCIPAL: Final = Decimal("4850.00")
DEPRECIATION: Final = Decimal("11850.00")
AMORTIZATION: Final = Decimal("500.00")
PREPAID_INSURANCE_AMORTIZATION: Final = Decimal("3275.00")
DEC_FREIGHT_ACCRUAL: Final = Decimal("10860.00")
DEC_COMMISSION_ACCRUAL: Final = Decimal("16920.00")
DESIRED_OPENING_CASH: Final = Decimal("465000.00")
PAYROLL_TAX_RATE_BP: Final = 765


def _floor_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding="ROUND_FLOOR")


def _bp(amount: Decimal, basis_points: int) -> Decimal:
    return _floor_cents(amount * basis_points / 10000)


# =============================================================================================
# Drafts
# =============================================================================================


@dataclass
class InvoiceDraft:
    key: int
    customer: str
    invoice_date: date
    due_date: date
    currency: Currency
    subtotal: Decimal
    fx_rate: Decimal
    functional_total: Decimal
    cost: Decimal
    warehouse: Warehouse
    order_entered_on: date
    carried_forward: bool
    number: str | None = None


@dataclass
class BillDraft:
    key: int
    vendor: str
    bill_date: date
    due_date: date
    amount: Decimal
    expense_account: str
    reference: str
    entered_by: str
    carried_forward: bool
    number: str | None = None
    paid: bool = False


@dataclass
class ReceiptDraft:
    key: int
    customer: str
    receipt_date: date
    method: PaymentMethod
    currency: Currency
    applications: list[tuple[int, Decimal]]
    fx_rate: Decimal
    functional_amount: Decimal
    reference: str
    bank_posted_on: date
    number: str | None = None

    @property
    def amount(self) -> Decimal:
        return sum((amount for _, amount in self.applications), Decimal(0))


@dataclass
class DisbursementDraft:
    key: int
    vendor: str
    payment_date: date
    method: PaymentMethod
    applications: list[tuple[int, Decimal]]
    bank_posted_on: date
    pinned_check: str | None = None
    pinned_number: str | None = None
    number: str | None = None
    check_number: str | None = None
    trace: str = ""

    @property
    def amount(self) -> Decimal:
        return sum((amount for _, amount in self.applications), Decimal(0))


@dataclass
class ManualDraft:
    key: int
    created_on: date
    order: int
    entry_date: date
    posting_period: str
    memo: str
    lines: list[tuple[str, Decimal, str]]
    """(account, signed functional USD amount, line memo)."""
    created_by: str = "mreyes"
    pinned_number: str | None = None
    reversal_of_key: int | None = None
    series: str = "2026"
    bank_description: str | None = None
    number: str | None = None

    def cash_amount(self) -> Decimal:
        return sum((amount for account, amount, _ in self.lines if account == CASH), Decimal(0))


@dataclass
class Drafts:
    invoices: list[InvoiceDraft] = field(default_factory=list)
    bills: list[BillDraft] = field(default_factory=list)
    receipts: list[ReceiptDraft] = field(default_factory=list)
    disbursements: list[DisbursementDraft] = field(default_factory=list)
    manual: list[ManualDraft] = field(default_factory=list)
    bank_only: list[tuple[date, str, Decimal, str | None]] = field(default_factory=list)
    _next_key: int = 0

    def key(self) -> int:
        self._next_key += 1
        return self._next_key


# =============================================================================================
# Builder
# =============================================================================================


class _CleanBuilder:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = ScenarioRng(seed, "brightwater")
        self.d = Drafts()
        self.customers = {p.party.code: p for p in build_customers(self.rng.child("customers"))}
        self.vendors = {p.party.code: p for p in build_vendors(self.rng.child("vendors"))}
        self.vendor_by_name = {p.party.name: p for p in self.vendors.values()}
        self.fx = self._build_fx_rates()
        self.invoice_by_key: dict[int, InvoiceDraft] = {}
        self.bill_by_key: dict[int, BillDraft] = {}

    # ------------------------------------------------------------------ FX
    def _build_fx_rates(self) -> dict[date, Decimal]:
        rng = self.rng.child("fx")
        anchors = {
            date(2026, 1, 1): Decimal("1.0735"),
            **k.EUR_ANCHOR_RATES,
            date(2026, 7, 15): Decimal("1.1045"),
        }
        points = sorted(anchors.items())
        rates: dict[date, Decimal] = {}
        for (start, start_rate), (end, end_rate) in pairwise(points):
            span = (end - start).days
            start_units = int(start_rate.scaleb(4))
            end_units = int(end_rate.scaleb(4))
            for offset in range(span + 1):
                day = start + timedelta(days=offset)
                base = start_units + (end_units - start_units) * offset // span
                noise = 0 if day in anchors else rng.integer(-11, 11)
                rates[day] = Decimal(base + noise).scaleb(-4)
        return rates | anchors

    # ------------------------------------------------------------------ helpers
    def _customer(self, code: str) -> CustomerProfile:
        return self.customers[code]

    def _vendor(self, name: str) -> VendorProfile:
        return self.vendor_by_name[name]

    def _add_invoice(
        self,
        customer: CustomerProfile,
        invoice_date: date,
        subtotal: Decimal,
        *,
        rng: ScenarioRng,
        carried_forward: bool = False,
        number: str | None = None,
        lead_days: int | None = None,
    ) -> InvoiceDraft:
        party = customer.party
        currency = party.default_currency
        if currency == USD:
            rate = ONE
            functional = subtotal
        else:
            rate = self.fx[invoice_date]
            functional = convert(Money(subtotal, currency), rate, USD).converted.amount
        ratio = rng.integer(6900, 7600)
        cost = _bp(functional, ratio)
        if lead_days is None:
            lead_days = {
                Segment.GROCER: rng.integer(0, 9),
                Segment.RESTAURANT: rng.integer(0, 2),
                Segment.EXPORT: rng.integer(25, 60),
            }[customer.segment]
        draft = InvoiceDraft(
            key=self.d.key(),
            customer=party.code,
            invoice_date=invoice_date,
            due_date=invoice_date + timedelta(days=party.payment_terms_days),
            currency=currency,
            subtotal=subtotal,
            fx_rate=rate,
            functional_total=functional,
            cost=cost,
            warehouse=customer.warehouse,
            order_entered_on=invoice_date - timedelta(days=lead_days),
            carried_forward=carried_forward,
            number=number,
        )
        self.d.invoices.append(draft)
        self.invoice_by_key[draft.key] = draft
        return draft

    def _add_bill(
        self,
        vendor: VendorProfile,
        bill_date: date,
        amount: Decimal,
        *,
        reference: str,
        due_date: date | None = None,
        carried_forward: bool = False,
        number: str | None = None,
        expense_account: str | None = None,
    ) -> BillDraft:
        draft = BillDraft(
            key=self.d.key(),
            vendor=vendor.party.code,
            bill_date=bill_date,
            due_date=due_date or bill_date + timedelta(days=vendor.party.payment_terms_days),
            amount=amount,
            expense_account=expense_account or vendor.expense_account,
            reference=reference,
            entered_by=vendor.created_by,
            carried_forward=carried_forward,
            number=number,
        )
        self.d.bills.append(draft)
        self.bill_by_key[draft.key] = draft
        return draft

    # ------------------------------------------------------------------ sales
    def build_sales(self) -> None:
        rng = self.rng.child("sales")
        dit_customer = next(
            p
            for p in sorted(self.customers.values(), key=lambda c: c.party.code)
            if p.segment is Segment.GROCER
            and p.receipt_method is PaymentMethod.CHECK
            and p.party.code not in {k.GREEN_VALLEY, k.GREEN_VALLEY_STORE_2}
        )
        disputed = [
            p
            for p in sorted(self.customers.values(), key=lambda c: c.party.code)
            if p.segment is Segment.RESTAURANT
            and p.party.code not in {k.TN05_CUSTOMER, k.CEDAR_AND_SALT}
        ][5:7]
        self.disputed_customers = {p.party.code for p in disputed}
        self.dit_customer = dit_customer.party.code

        for customer in sorted(self.customers.values(), key=lambda c: c.party.code):
            code = customer.party.code
            crng = rng.child(code)
            if customer.segment is Segment.GROCER:
                self._grocer_invoices(customer, crng)
            elif customer.segment is Segment.RESTAURANT:
                self._restaurant_invoices(customer, crng, disputed=code in self.disputed_customers)
            elif customer.segment is Segment.EXPORT:
                self._export_invoices(customer, crng)

        # Deposit-in-transit invoice: paid early by check on the cutover date (DS-10 fact).
        self.dit_invoice = self._add_invoice(
            dit_customer, date(2026, 6, 5), k.DEPOSIT_IN_TRANSIT[2], rng=rng.child("dit")
        )
        # Green Valley small fill-in order still open at cutover (DS-06 fact).
        self.green_valley_open = self._add_invoice(
            self._customer(k.GREEN_VALLEY),
            date(2026, 6, 19),
            k.DS06_OPEN_AMOUNT,
            rng=rng.child("gv"),
        )

    def _grocer_invoices(self, customer: CustomerProfile, rng: ScenarioRng) -> None:
        # Carried forward: two December deliveries open at year end.
        for day in (rng.integer(4, 10), rng.integer(16, 23)):
            invoice_date = next_business_day(date(2025, 12, day))
            self._add_invoice(
                customer,
                invoice_date,
                rng.cents(Decimal("11000"), Decimal("29000")),
                rng=rng,
                carried_forward=True,
            )
        blocked: set[date] = set()
        if customer.party.code == k.ROSE_CITY:
            self._add_invoice(
                customer, k.DS04_INVOICE_DATE, k.DS04_AMOUNT, rng=rng, number=k.DS04_INVOICE
            )
            blocked = {k.DS04_INVOICE_DATE + timedelta(days=o) for o in range(-4, 5)}
        current = next_business_day(date(2026, 1, rng.integer(2, 13)))
        while current <= CUTOVER:
            if current not in blocked:
                self._add_invoice(
                    customer, current, rng.cents(Decimal("11000"), Decimal("29000")), rng=rng
                )
            current = next_business_day(current + timedelta(days=rng.integer(12, 16)))

    def _restaurant_invoices(
        self, customer: CustomerProfile, rng: ScenarioRng, *, disputed: bool
    ) -> None:
        code = customer.party.code
        if disputed:
            self._add_invoice(
                customer,
                next_business_day(date(2025, 10, rng.integer(6, 24))),
                rng.cents(Decimal("900"), Decimal("2400")),
                rng=rng,
                carried_forward=True,
            )
        elif rng.chance(60, 100):
            self._add_invoice(
                customer,
                next_business_day(date(2025, 12, rng.integer(8, 29))),
                rng.cents(Decimal("700"), Decimal("4200")),
                rng=rng,
                carried_forward=True,
            )
        if code == k.CEDAR_AND_SALT:
            for invoice_date, amount_text in (
                (date(2026, 1, 9), "2215.60"),
                (date(2026, 1, 23), "1948.25"),
            ):
                self._add_invoice(customer, invoice_date, Decimal(amount_text), rng=rng)
            self._add_invoice(
                customer, k.DS09_INVOICE_DATE, k.DS09_AMOUNT, rng=rng, number=k.DS09_INVOICE
            )
            return
        if code == k.TN05_CUSTOMER:
            self.tn05_invoices = [
                self._add_invoice(customer, date(2026, 3, 3), k.TN05_AMOUNT, rng=rng),
                self._add_invoice(customer, date(2026, 3, 10), k.TN05_AMOUNT, rng=rng),
            ]
            for month in (1, 5):
                invoice_date = next_business_day(date(2026, month, rng.integer(5, 20)))
                self._add_invoice(
                    customer, invoice_date, rng.cents(Decimal("1310"), Decimal("3900")), rng=rng
                )
            return
        count = rng.integer(2, 4)
        chosen = sorted(
            {next_business_day(rng.date_between(H1_START, date(2026, 6, 26))) for _ in range(count)}
        )
        for invoice_date in chosen:
            amount = rng.cents(Decimal("700"), Decimal("4200"))
            if amount == k.TN05_AMOUNT:
                amount += CENT
            self._add_invoice(customer, invoice_date, amount, rng=rng)

    def _export_invoices(self, customer: CustomerProfile, rng: ScenarioRng) -> None:
        pinned = {
            invoice_date: (number, amount) for number, invoice_date, amount in k.DS07_INVOICES
        }
        self.alpenkost_invoices: list[InvoiceDraft] = []
        for invoice_date in ALPENKOST_DATES:
            if invoice_date in pinned:
                number, amount = pinned[invoice_date]
                draft = self._add_invoice(customer, invoice_date, amount, rng=rng, number=number)
            else:
                draft = self._add_invoice(
                    customer, invoice_date, rng.cents(Decimal("4200"), Decimal("12400")), rng=rng
                )
            self.alpenkost_invoices.append(draft)

    # ------------------------------------------------------------------ collections
    def build_receipts(self) -> None:
        rng = self.rng.child("receipts")
        by_customer: dict[str, list[InvoiceDraft]] = defaultdict(list)
        for invoice in self.d.invoices:
            by_customer[invoice.customer].append(invoice)
        for code in sorted(by_customer):
            customer = self._customer(code)
            crng = rng.child(code)
            invoices = sorted(by_customer[code], key=lambda i: (i.invoice_date, i.key))
            if customer.segment is Segment.EXPORT:
                self._export_receipts(customer, invoices, crng)
                continue
            planned: list[tuple[date, InvoiceDraft]] = []
            for invoice in invoices:
                if invoice is self.dit_invoice:
                    self._receipt(
                        customer,
                        k.DEPOSIT_IN_TRANSIT[0],
                        [(invoice, invoice.subtotal)],
                        crng,
                        method=PaymentMethod.CHECK,
                        bank_posted_on=k.DEPOSIT_IN_TRANSIT[1],
                    )
                    continue
                if invoice is self.green_valley_open or (
                    code in self.disputed_customers and invoice.carried_forward
                ):
                    continue
                if invoice.number == k.DS09_INVOICE:
                    self._receipt(
                        customer,
                        k.DS09_RECEIPT_DATE,
                        [(invoice, invoice.subtotal)],
                        crng,
                        method=PaymentMethod.CHECK,
                        number=k.DS09_RECEIPT,
                    )
                    continue
                if code == k.TN05_CUSTOMER and invoice in self.tn05_invoices:
                    continue
                if customer.segment is Segment.GROCER:
                    delay = crng.integer(-4, 9)
                else:
                    delay = crng.integer(-3, 12)
                pay_date = next_business_day(invoice.due_date + timedelta(days=delay))
                if pay_date < invoice.invoice_date:
                    pay_date = next_business_day(invoice.invoice_date + timedelta(days=1))
                if pay_date < H1_START:
                    # A carried-forward item was open at year end, so it is collected in January.
                    pay_date = next_business_day(
                        date(2026, 1, 2) + timedelta(days=crng.integer(0, 12))
                    )
                if pay_date >= CUTOVER:
                    continue  # still open at cutover
                planned.append((pay_date, invoice))
            if code == k.TN05_CUSTOMER:
                for invoice in self.tn05_invoices:
                    self._receipt(
                        customer,
                        date(2026, 3, 24),
                        [(invoice, invoice.subtotal)],
                        crng,
                        method=PaymentMethod.CHECK,
                    )
            combine = (
                customer.segment is Segment.RESTAURANT
                and customer.receipt_method is PaymentMethod.CHECK
            )
            if combine:
                groups: dict[tuple[int, int], list[tuple[date, InvoiceDraft]]] = defaultdict(list)
                for pay_date, invoice in planned:
                    groups[pay_date.isocalendar()[:2]].append((pay_date, invoice))
                for group in groups.values():
                    pay_date = max(p for p, _ in group)
                    self._receipt(customer, pay_date, [(i, i.subtotal) for _, i in group], crng)
            else:
                for pay_date, invoice in planned:
                    self._receipt(customer, pay_date, [(invoice, invoice.subtotal)], crng)

    def _export_receipts(
        self, customer: CustomerProfile, invoices: list[InvoiceDraft], rng: ScenarioRng
    ) -> None:
        for invoice in invoices:
            if invoice.number == k.DS07_PAID_INVOICE:
                self._receipt(customer, k.DS07_PAYMENT_DATE, [(invoice, invoice.subtotal)], rng)
            elif invoice.number is None and invoice.due_date <= ALPENKOST_PAYS_DUE_UNTIL:
                pay_date = next_business_day(invoice.due_date + timedelta(days=rng.integer(1, 6)))
                self._receipt(customer, pay_date, [(invoice, invoice.subtotal)], rng)

    def _receipt(
        self,
        customer: CustomerProfile,
        receipt_date: date,
        applications: list[tuple[InvoiceDraft, Decimal]],
        rng: ScenarioRng,
        *,
        method: PaymentMethod | None = None,
        number: str | None = None,
        bank_posted_on: date | None = None,
    ) -> ReceiptDraft:
        party = customer.party
        method = method or customer.receipt_method
        currency = party.default_currency
        total = sum((amount for _, amount in applications), Decimal(0))
        if currency == USD:
            rate = ONE
            functional = total
        else:
            rate = self.fx[receipt_date]
            functional = convert(Money(total, currency), rate, USD).converted.amount
        reference = {
            PaymentMethod.CHECK: rng.digits(4).lstrip("0") or "1001",
            PaymentMethod.ACH: rng.digits(15),
            PaymentMethod.WIRE: f"FT{rng.digits(10)}",
        }[method]
        draft = ReceiptDraft(
            key=self.d.key(),
            customer=party.code,
            receipt_date=receipt_date,
            method=method,
            currency=currency,
            applications=[(invoice.key, amount) for invoice, amount in applications],
            fx_rate=rate,
            functional_amount=functional,
            reference=reference,
            bank_posted_on=bank_posted_on or receipt_date,
            number=number,
        )
        self.d.receipts.append(draft)
        return draft

    # ------------------------------------------------------------------ purchasing
    def build_purchases(self) -> None:
        rng = self.rng.child("purchases")
        for vendor in sorted(self.vendors.values(), key=lambda v: v.party.code):
            vrng = rng.child(vendor.party.code)
            prefix = "".join(
                word[0] for word in vendor.party.name.replace("&", "").split()[:3]
            ).upper()
            references = _References(prefix, vrng)
            name = vendor.party.name
            if vendor.category is VendorCategory.PRODUCER:
                self._producer_bills(vendor, vrng, references)
            elif name == "Pacific Coast Packaging LLC":
                self._pcp_bills(vendor, vrng, references)
            elif vendor.category is VendorCategory.LANDLORD:
                for month in MONTHS:
                    bill_date = date(2026, month, 1)
                    self._add_bill(
                        vendor,
                        bill_date,
                        vendor.min_amount,
                        reference=f"RENT-2026-{month:02d}",
                        due_date=bill_date,
                    )
            elif name == "Portland General Utilities":
                for month, day in zip(MONTHS, (13, 12, 14, 14, 13, 12), strict=True):
                    bill_date = date(2026, month, day)
                    if month == 3:
                        self._add_bill(
                            vendor,
                            bill_date,
                            k.DS11_AMOUNT,
                            reference=references.take(),
                            number=k.DS11_BILL,
                        )
                    else:
                        self._add_bill(
                            vendor,
                            bill_date,
                            vrng.cents(vendor.min_amount, vendor.max_amount),
                            reference=references.take(),
                        )
            else:
                self._periodic_bills(vendor, vrng, references)
            if vendor.category in {VendorCategory.PRODUCER, VendorCategory.FREIGHT}:
                for _ in range(vrng.integer(1, 2)):
                    bill_date = next_business_day(date(2025, 12, vrng.integer(8, 29)))
                    self._add_bill(
                        vendor,
                        bill_date,
                        vrng.cents(vendor.min_amount, vendor.max_amount),
                        reference=references.take(),
                        carried_forward=True,
                    )

        # Off-cycle checks written at quarter close that clear after cutover (DS-10 facts).
        self.outstanding_check_bills: list[tuple[BillDraft, tuple[date, date, Decimal]]] = []
        for vendor_name, facts, bill_day in zip(
            (
                "Willamette Valley Creamery",
                "Columbia Gorge Orchards",
                "Cascade Coldchain Logistics",
            ),
            k.OUTSTANDING_CHECKS,
            (5, 8, 10),
            strict=True,
        ):
            vendor = self._vendor(vendor_name)
            bill_date = date(2026, 6, bill_day)
            bill = self._add_bill(
                vendor,
                bill_date,
                facts[2],
                reference=f"{vendor_name[:3].upper()}-{facts[2]}",
                due_date=bill_date + timedelta(days=30),
            )
            bill.reference = _References(vendor_name[:3].upper(), rng.child(vendor_name)).take()
            self.outstanding_check_bills.append((bill, facts))

    def _spread_dates(self, rng: ScenarioRng, count: int) -> list[date]:
        span = (CUTOVER - H1_START).days
        result = []
        for index in range(count):
            base = H1_START + timedelta(
                days=span * index // count + rng.integer(0, max(1, span // count - 2))
            )
            result.append(next_business_day(min(base, date(2026, 6, 26))))
        return sorted(set(result))

    def _producer_bills(
        self, vendor: VendorProfile, rng: ScenarioRng, references: _References
    ) -> None:
        amounts: list[tuple[date, Decimal]] = []
        for bill_date in self._spread_dates(rng, vendor.bills_per_half_year):
            amount = rng.cents(vendor.min_amount, vendor.max_amount)
            if vendor.party.name in {
                "Willamette Valley Creamery",
                "Columbia Gorge Orchards",
            } and amount in {facts[2] for facts in k.OUTSTANDING_CHECKS}:
                amount += CENT
            amounts.append((bill_date, amount))
        for bill_date, amount in amounts:
            self._add_bill(vendor, bill_date, amount, reference=references.take())

    def _periodic_bills(
        self, vendor: VendorProfile, rng: ScenarioRng, references: _References
    ) -> None:
        for bill_date in self._spread_dates(rng, vendor.bills_per_half_year):
            amount = rng.cents(vendor.min_amount, vendor.max_amount)
            if (
                vendor.party.name == "Cascade Coldchain Logistics"
                and amount == k.OUTSTANDING_CHECKS[2][2]
            ):
                amount += CENT
            self._add_bill(vendor, bill_date, amount, reference=references.take())

    def _pcp_bills(self, vendor: VendorProfile, rng: ScenarioRng, references: _References) -> None:
        self.pcp_bills: list[BillDraft] = []
        dates = self._spread_dates(rng, 26)
        dates = [
            d
            for d in dates
            if abs((d - k.PCP_DUPLICATED_BILL_DATE).days) > 3
            and abs((d - date(2026, 6, 18)).days) > 3
        ]
        while len(dates) < 24:
            candidate = next_business_day(rng.date_between(H1_START, date(2026, 6, 26)))
            if all(
                abs((candidate - d).days) > 3
                for d in [*dates, k.PCP_DUPLICATED_BILL_DATE, date(2026, 6, 18)]
            ):
                dates.append(candidate)
        dates = sorted(dates)[:24]
        for bill_date in dates:
            self.pcp_bills.append(
                self._add_bill(
                    vendor,
                    bill_date,
                    rng.cents(vendor.min_amount, vendor.max_amount),
                    reference=references.take(),
                )
            )
        self.pcp_bills.append(
            self._add_bill(
                vendor,
                k.PCP_DUPLICATED_BILL_DATE,
                k.PCP_DUPLICATED_AMOUNT,
                reference=k.PCP_DUPLICATED_REFERENCE,
                number=k.PCP_ORIGINAL_BILL,
            )
        )
        self.pcp_bills.append(
            self._add_bill(
                vendor,
                date(2026, 6, 18),
                k.PCP_OPEN_BILL_AMOUNT,
                reference=references.take(),
                number=k.PCP_OPEN_BILL,
            )
        )
        references.reserve(k.PCP_DUPLICATED_REFERENCE)

    # ------------------------------------------------------------------ bill payments
    def build_disbursements(self) -> None:
        rng = self.rng.child("disbursements")
        special = {b.key for b, _ in self.outstanding_check_bills}
        pcp_original = next(b for b in self.pcp_bills if b.number == k.PCP_ORIGINAL_BILL)
        special.add(pcp_original.key)

        # Rent: paid by ACH on the 1st of each month (TN-01).
        for bill in self.d.bills:
            vendor = self.vendors[bill.vendor]
            if vendor.category is VendorCategory.LANDLORD:
                self._pay(vendor, bill.bill_date, [bill], rng, method=PaymentMethod.ACH)
                special.add(bill.key)

        # Off-cycle check for the original Pacific Coast Packaging invoice (DS-01/DS-02 facts).
        self._pay(
            self.vendors[k.PCP_VENDOR],
            k.PCP_ORIGINAL_CHECK_DATE,
            [pcp_original],
            rng,
            method=PaymentMethod.CHECK,
            check=k.PCP_ORIGINAL_CHECK,
        )

        run = date(2026, 1, 8)
        while run <= CUTOVER:
            due = [
                b
                for b in self.d.bills
                if not b.paid
                and b.key not in special
                and b.bill_date <= run
                and b.due_date <= run + timedelta(days=6)
            ]
            by_vendor: dict[str, list[BillDraft]] = defaultdict(list)
            for bill in due:
                by_vendor[bill.vendor].append(bill)
            for code in sorted(by_vendor):
                vendor = self.vendors[code]
                bills = sorted(by_vendor[code], key=lambda b: (b.bill_date, b.key))
                if code == k.PCP_VENDOR:
                    for bill in bills:
                        self._pay(vendor, run, [bill], rng)
                else:
                    self._pay(vendor, run, bills, rng)
            run += timedelta(days=7)

        for bill, (issued, clears, _) in self.outstanding_check_bills:
            self._pay(
                self.vendors[bill.vendor],
                issued,
                [bill],
                rng,
                method=PaymentMethod.CHECK,
                clears_on=clears,
            )

    def _pay(
        self,
        vendor: VendorProfile,
        payment_date: date,
        bills: list[BillDraft],
        rng: ScenarioRng,
        *,
        method: PaymentMethod | None = None,
        check: str | None = None,
        clears_on: date | None = None,
    ) -> None:
        method = method or vendor.payment_method
        if method is PaymentMethod.CHECK:
            posted = clears_on or min(add_business_days(payment_date, rng.integer(2, 6)), CUTOVER)
        else:
            posted = next_business_day(payment_date)
        draft = DisbursementDraft(
            key=self.d.key(),
            vendor=vendor.party.code,
            payment_date=payment_date,
            method=method,
            applications=[(bill.key, bill.amount) for bill in bills],
            bank_posted_on=posted,
            pinned_check=check,
            trace=rng.digits(15),
        )
        for bill in bills:
            if bill.paid:
                raise ScenarioConsistencyError(f"bill {bill.key} paid twice")
            bill.paid = True
        self.d.disbursements.append(draft)

    # ------------------------------------------------------------------ manual journals
    def build_manual_journals(self) -> None:
        rng = self.rng.child("manual")
        d = self.d

        def add(
            created_on: date,
            order: int,
            entry_date: date,
            memo: str,
            lines: list[tuple[str, Decimal, str]],
            *,
            created_by: str = "mreyes",
            pinned_number: str | None = None,
            reversal_of_key: int | None = None,
            series: str = "2026",
            bank_description: str | None = None,
        ) -> ManualDraft:
            draft = ManualDraft(
                key=d.key(),
                created_on=created_on,
                order=order,
                entry_date=entry_date,
                posting_period=period_of(entry_date),
                memo=memo,
                lines=lines,
                created_by=created_by,
                pinned_number=pinned_number,
                reversal_of_key=reversal_of_key,
                series=series,
                bank_description=bank_description,
            )
            d.manual.append(draft)
            return draft

        def accrual_pair(
            month_end_date: date,
            order: int,
            memo: str,
            lines: list[tuple[str, Decimal, str]],
            *,
            pinned: tuple[str, str | None] | None = None,
        ) -> None:
            accrual = add(
                month_end_date,
                order,
                month_end_date,
                memo,
                lines,
                pinned_number=pinned[0] if pinned else None,
            )
            reversal_date = month_end_date + timedelta(days=1)
            add(
                month_end_date,
                order + 1,
                reversal_date,
                f"Reverse: {memo}",
                [(account, -amount, line_memo) for account, amount, line_memo in lines],
                reversal_of_key=accrual.key,
                pinned_number=pinned[1] if pinned else None,
            )

        # Reversals of December 2025 accruals, created in 2025 (2025 journal series).
        opening_freight = add(
            date(2025, 12, 31),
            0,
            date(2025, 12, 31),
            "Accrued freight - December 2025",
            [("6400", DEC_FREIGHT_ACCRUAL, ""), ("2100", -DEC_FREIGHT_ACCRUAL, "")],
            series="2025",
            pinned_number="JE-2025-0916",
        )
        opening_commissions = add(
            date(2025, 12, 31),
            1,
            date(2025, 12, 31),
            "Accrued commissions - December 2025",
            [("6150", DEC_COMMISSION_ACCRUAL, ""), ("2160", -DEC_COMMISSION_ACCRUAL, "")],
            series="2025",
            pinned_number="JE-2025-0917",
        )
        add(
            date(2025, 12, 31),
            2,
            date(2026, 1, 1),
            "Reverse: Accrued freight - December 2025",
            [("6400", -DEC_FREIGHT_ACCRUAL, ""), ("2100", DEC_FREIGHT_ACCRUAL, "")],
            series="2025",
            pinned_number="JE-2025-0918",
            reversal_of_key=opening_freight.key,
        )
        add(
            date(2025, 12, 31),
            3,
            date(2026, 1, 1),
            "Reverse: Accrued commissions - December 2025",
            [("6150", -DEC_COMMISSION_ACCRUAL, ""), ("2160", DEC_COMMISSION_ACCRUAL, "")],
            series="2025",
            pinned_number="JE-2025-0919",
            reversal_of_key=opening_commissions.key,
        )
        self.opening_accrual_keys = {opening_freight.key, opening_commissions.key}

        # Q1 daily COGS relief by warehouse (before perpetual inventory, SC-06).
        cost_by_day: dict[tuple[date, Warehouse], Decimal] = defaultdict(Decimal)
        for invoice in d.invoices:
            if not invoice.carried_forward and invoice.invoice_date < k.PERPETUAL_INVENTORY_START:
                cost_by_day[(invoice.invoice_date, invoice.warehouse)] += invoice.cost
        for (day, warehouse), cost in sorted(
            cost_by_day.items(), key=lambda item: (item[0][0], item[0][1].value)
        ):
            add(
                day,
                10,
                day,
                f"Daily COGS relief - {warehouse.value} warehouse",
                [("5000", cost, ""), (INVENTORY, -cost, "")],
                created_by="warehouse.ops",
            )

        # Suspense activity (legitimate in the clean books; DS-12 concerns its later export).
        for number, entry_date, suspense_amount, counter, memo in k.SUSPENSE_ENTRIES:
            add(
                entry_date,
                20,
                entry_date,
                memo,
                [(k.SUSPENSE_ACCOUNT, suspense_amount, memo), (counter, -suspense_amount, memo)],
                pinned_number=number,
            )

        # Payroll (15th and last business day) and commissions paid mid-month.
        commissions_due = DEC_COMMISSION_ACCRUAL
        self.commission_accruals: dict[int, Decimal] = {}
        for month in MONTHS:
            mrng = rng.child(f"month-{month}")
            for pay_day, includes_commissions in (
                (previous_business_day(date(2026, month, 15)), True),
                (last_business_day(2026, month), False),
            ):
                wages = [
                    ("6100", mrng.cents(Decimal("60000"), Decimal("64500")), "Warehouse wages"),
                    ("6105", mrng.cents(Decimal("36000"), Decimal("39800")), "Driver wages"),
                    ("6110", mrng.cents(Decimal("33000"), Decimal("35200")), "Office wages"),
                ]
                if includes_commissions:
                    wages.append(("6150", commissions_due, "Sales commissions"))
                gross = sum((amount for _, amount, _ in wages), Decimal(0))
                taxes = _bp(gross, PAYROLL_TAX_RATE_BP)
                lines = [
                    *wages,
                    ("6120", taxes, "Employer payroll taxes"),
                    (CASH, -(gross + taxes), "Payroll funding"),
                ]
                add(
                    pay_day,
                    30,
                    pay_day,
                    f"Payroll {pay_day.isoformat()} - Pinnacle Payroll Services",
                    lines,
                    created_by="payroll.admin",
                    bank_description="PINNACLE PAYROLL SVCS PAYROLL DD",
                )

            # Month-end close, created on the last calendar day.
            end = month_end(2026, month)
            add(
                end,
                40,
                end,
                "Monthly depreciation",
                [("6700", DEPRECIATION, ""), ("1590", -DEPRECIATION, "")],
            )
            add(
                end,
                41,
                end,
                "Monthly amortization - customer lists",
                [("6710", AMORTIZATION, ""), ("1790", -AMORTIZATION, "")],
            )
            add(
                end,
                42,
                end,
                "Prepaid insurance amortization",
                [
                    ("6500", PREPAID_INSURANCE_AMORTIZATION, ""),
                    ("1400", -PREPAID_INSURANCE_AMORTIZATION, ""),
                ],
            )
            if month in (3, 6):
                add(
                    end,
                    43,
                    end,
                    f"Allowance provision - Q{month // 3}",
                    [
                        ("6800", k.ALLOWANCE_QUARTERLY_PROVISION, ""),
                        (k.ALLOWANCE_ACCOUNT, -k.ALLOWANCE_QUARTERLY_PROVISION, ""),
                    ],
                )
            if month == 4:
                accrual_pair(
                    end,
                    50,
                    "Accrued freight — April",
                    [
                        ("6400", k.DS05_FREIGHT, "Accrued freight — April"),
                        ("2100", -k.DS05_ACCRUED, "Accrued freight — April"),
                        ("6410", -k.DS05_REBATE, k.DS05_CLEAN_MEMO),
                    ],
                    pinned=(k.DS05_ENTRY, None),
                )
            else:
                freight = mrng.cents(Decimal("9000"), Decimal("14000"))
                label = end.strftime("%B")
                accrual_pair(
                    end,
                    50,
                    f"Accrued freight — {label}",
                    [("6400", freight, ""), ("2100", -freight, "")],
                )
            commissions = (
                k.TN04_AMOUNT if month == 5 else mrng.cents(Decimal("15000"), Decimal("19500"))
            )
            label = end.strftime("%B")
            accrual_pair(
                end,
                90,
                f"Accrued commissions — {label}",
                [("6150", commissions, ""), ("2160", -commissions, "")],
                pinned=(k.TN04_ACCRUAL_ENTRY, k.TN04_REVERSAL_ENTRY) if month == 5 else None,
            )
            self.commission_accruals[month] = commissions
            commissions_due = commissions

        # Inventory count adjustment for the March close, entered 2 April (DS-08 fact; clean date).
        add(
            k.DS08_ENTERED_DATE,
            5,
            k.DS08_CLEAN_DATE,
            "March inventory count adjustment",
            [("5000", k.DS08_AMOUNT, ""), (INVENTORY, -k.DS08_AMOUNT, "")],
            pinned_number=k.DS08_ENTRY,
        )

    def build_financing(self) -> None:
        """Debt service and line-of-credit activity, calibrated so opening cash is plausible."""
        rng = self.rng.child("financing")
        operating = self._operating_cash_flow_through_cutover()
        loan_balance = Decimal("268400.00")
        loan_lines: list[tuple[date, Decimal, Decimal]] = []
        for month in MONTHS:
            interest = _floor_cents(loan_balance * EQUIPMENT_LOAN_RATE)
            loan_lines.append(
                (previous_business_day(date(2026, month, 10)), EQUIPMENT_LOAN_PRINCIPAL, interest)
            )
            loan_balance -= EQUIPMENT_LOAN_PRINCIPAL
        loan_total = sum((p + i for _, p, i in loan_lines), Decimal(0))

        repayments = [Decimal(0)] * 6
        for _ in range(8):
            loc_balance = Decimal("900000.00")
            interest_total = Decimal(0)
            for month in MONTHS:
                interest_total += _floor_cents(loc_balance * LOC_MONTHLY_RATE)
                loc_balance -= repayments[month - 1]
            net = operating - loan_total - interest_total - sum(repayments, Decimal(0))
            opening = k.CLEAN_GL_CASH_AT_CUTOVER - net
            adjustment = opening - DESIRED_OPENING_CASH
            per_month = (-adjustment / 30000).quantize(ONE, rounding="ROUND_HALF_EVEN") * 5000
            repayments = [r + per_month for r in repayments]
        if any(abs(r) > Decimal("150000") for r in repayments):
            raise ScenarioConsistencyError("line-of-credit calibration out of range")

        loc_balance = Decimal("900000.00")
        for month in MONTHS:
            day = previous_business_day(date(2026, month, 25))
            interest = _floor_cents(loc_balance * LOC_MONTHLY_RATE)
            self.d.manual.append(
                ManualDraft(
                    key=self.d.key(),
                    created_on=day,
                    order=60,
                    entry_date=day,
                    posting_period=period_of(day),
                    memo="Line of credit interest",
                    lines=[("7200", interest, ""), (CASH, -interest, "")],
                    bank_description="FIRST CASCADE LOC INTEREST 5512",
                )
            )
            amount = repayments[month - 1]
            if amount != 0:
                memo = "Line of credit repayment" if amount > 0 else "Line of credit advance"
                description = (
                    "FIRST CASCADE LOC PAYMENT 5512"
                    if amount > 0
                    else "FIRST CASCADE LOC ADVANCE 5512"
                )
                self.d.manual.append(
                    ManualDraft(
                        key=self.d.key(),
                        created_on=day,
                        order=61,
                        entry_date=day,
                        posting_period=period_of(day),
                        memo=memo,
                        lines=[("2500", amount, ""), (CASH, -amount, "")],
                        bank_description=description,
                    )
                )
            loc_balance -= amount
        for day, principal, interest in loan_lines:
            self.d.manual.append(
                ManualDraft(
                    key=self.d.key(),
                    created_on=day,
                    order=62,
                    entry_date=day,
                    posting_period=period_of(day),
                    memo="Equipment loan payment",
                    lines=[
                        ("2700", principal, "Principal"),
                        ("7200", interest, "Interest"),
                        (CASH, -(principal + interest), ""),
                    ],
                    bank_description="FIRST CASCADE LOAN PMT 7719",
                )
            )
        self.loc_repayments = repayments
        del rng

    def _operating_cash_flow_through_cutover(self) -> Decimal:
        total = Decimal(0)
        for receipt in self.d.receipts:
            total += receipt.functional_amount
        for payment in self.d.disbursements:
            total -= payment.amount
        for manual in self.d.manual:
            if manual.entry_date <= CUTOVER and manual.entry_date >= H1_START:
                total += manual.cash_amount()
        return total

    # ------------------------------------------------------------------ bank-only July activity
    def build_post_cutover_bank_activity(self) -> None:
        rng = self.rng.child("july")
        self.d.bank_only.append(
            (
                date(2026, 7, 15),
                "PINNACLE PAYROLL SVCS PAYROLL DD",
                -rng.cents(Decimal("141000"), Decimal("149000")),
                None,
            )
        )
        open_invoices = sorted(
            (
                i
                for i in self.d.invoices
                if i.customer in self.customers
                and self.customers[i.customer].receipt_method is PaymentMethod.ACH
                and i.currency == USD
                and not self._invoice_paid(i)
                and i.due_date <= date(2026, 7, 15)
                and self.customers[i.customer].segment is Segment.GROCER
            ),
            key=lambda i: (i.due_date, i.key),
        )[:9]
        for invoice in open_invoices:
            posted = next_business_day(max(invoice.due_date, date(2026, 7, 1)))
            name = self.customers[invoice.customer].party.name.upper()[:16]
            self.d.bank_only.append(
                (posted, f"ACH CREDIT {name} PPD", invoice.subtotal, rng.digits(15))
            )
        for posted in (date(2026, 7, 2), date(2026, 7, 9)):
            self.d.bank_only.append(
                (
                    posted,
                    "ACH DEBIT VENDOR PAYMENT RUN CCD",
                    -rng.cents(Decimal("48000"), Decimal("96000")),
                    rng.digits(15),
                )
            )

    def _invoice_paid(self, invoice: InvoiceDraft) -> bool:
        return any(
            key == invoice.key for receipt in self.d.receipts for key, _ in receipt.applications
        )

    # ------------------------------------------------------------------ numbering
    def assign_numbers(self) -> None:
        rng = self.rng.child("numbering")
        d = self.d

        # Invoices: reserved at sales-order entry (SC-05).
        invoice_anchors = {int(i.number.split("-")[1]) for i in d.invoices if i.number}
        unpinned = sorted(
            (i for i in d.invoices if not i.number),
            key=lambda i: (i.order_entered_on, i.invoice_date, i.customer, i.key),
        )
        number = 9851
        for invoice in unpinned:
            while number in invoice_anchors:
                number += 1
            invoice.number = f"INV-{number}"
            number += 1

        # Bills: reference numbers assigned independently of date (SC-03).
        bill_anchors = {k.DS11_BILL, k.PCP_ORIGINAL_BILL, k.PCP_DUPLICATE_BILL, k.PCP_OPEN_BILL}
        reserved = {int(n.split("-")[1]) for n in bill_anchors}
        unpinned_bills = [b for b in d.bills if not b.number]
        pool_end = max(20001 + len(d.bills) + 190, max(reserved) + 41)
        pool = numbering.shuffled_pool(
            rng.child("bills"), len(unpinned_bills), 20001, pool_end, reserved
        )
        for bill, value in zip(unpinned_bills, pool, strict=True):
            bill.number = f"B-{value}"

        # Receipts: chronological, anchored.
        receipts = sorted(d.receipts, key=lambda r: (r.receipt_date, r.customer, r.key))
        anchor = next(i for i, r in enumerate(receipts) if r.number == k.DS09_RECEIPT)
        for receipt, value in zip(
            receipts, numbering.sequential_with_anchor(len(receipts), anchor, 31877), strict=True
        ):
            receipt.number = f"PMT-{value}"

        # Bill payments: chronological; DS-02's duplicate payment later uses a reserved number.
        disbursements = sorted(d.disbursements, key=lambda p: (p.payment_date, p.vendor, p.key))
        before_gap = sum(1 for p in disbursements if p.payment_date <= k.PCP_DUPLICATE_PAYMENT_DATE)
        for payment, value in zip(
            disbursements,
            numbering.sequential_with_reserved_gap(len(disbursements), 7730, before_gap),
            strict=True,
        ):
            payment.number = f"PAY-D-{value}"

        checks = [p for p in disbursements if p.method is PaymentMethod.CHECK]
        anchor = next(i for i, p in enumerate(checks) if p.pinned_check == k.PCP_ORIGINAL_CHECK)
        for payment, value in zip(
            checks,
            numbering.sequential_with_anchor(len(checks), anchor, int(k.PCP_ORIGINAL_CHECK)),
            strict=True,
        ):
            payment.check_number = str(value)

        # Manual journals: creation order, pinned numbers, gaps from abandoned drafts (SC-06).
        manual_2026 = sorted(
            (m for m in d.manual if m.series == "2026"),
            key=lambda m: (m.created_on, m.order, m.key),
        )
        slots = [
            int(m.pinned_number.rsplit("-", 1)[1]) if m.pinned_number else None for m in manual_2026
        ]
        for draft, value in zip(
            manual_2026,
            numbering.numbers_between_anchors(rng.child("journals"), slots, first_number=1),
            strict=True,
        ):
            draft.number = f"JE-2026-{value:04d}"
        for draft in d.manual:
            if draft.series == "2025":
                draft.number = draft.pinned_number

    # ------------------------------------------------------------------ materialize
    def materialize(self) -> LegacyUniverse:
        d = self.d
        accounts = {
            spec.code: LegacyAccountInfo(
                Account(
                    code=spec.code, name=spec.name, subtype=spec.subtype, is_active=spec.active
                ),
                spec.ledgerpro_type,
                spec.detail_type,
            )
            for spec in LEGACY_ACCOUNTS
        }
        targets = {
            spec.code: Account(code=spec.code, name=spec.name, subtype=spec.subtype)
            for spec in TARGET_ACCOUNTS
        }
        customers = {code: p.party for code, p in sorted(self.customers.items())}
        customer_info = {
            code: CustomerInfo(p.segment, p.warehouse) for code, p in sorted(self.customers.items())
        }
        vendors = {code: p.party for code, p in sorted(self.vendors.items())}
        vendor_info = {
            code: VendorInfo(p.category, p.created_by) for code, p in sorted(self.vendors.items())
        }

        invoices: dict[str, Document] = {}
        invoice_info: dict[str, InvoiceInfo] = {}
        journals: dict[str, JournalEntry] = {}
        journal_info: dict[str, JournalInfo] = {}
        booked: dict[str, Money] = {}
        for invoice_draft in sorted(d.invoices, key=lambda i: i.number or ""):
            number = _require(invoice_draft.number)
            document = Document(
                document_type=DocumentType.INVOICE,
                number=number,
                party_code=invoice_draft.customer,
                party_reference=None,
                document_date=invoice_draft.invoice_date,
                due_date=invoice_draft.due_date,
                currency=invoice_draft.currency,
                subtotal=Money(invoice_draft.subtotal, invoice_draft.currency),
                tax=Money(0, invoice_draft.currency),
                total=Money(invoice_draft.subtotal, invoice_draft.currency),
                fx_rate=invoice_draft.fx_rate,
                functional_total=Money(invoice_draft.functional_total, USD),
            )
            invoices[number] = document
            invoice_info[number] = InvoiceInfo(
                printed=True,
                warehouse=invoice_draft.warehouse,
                order_entered_on=invoice_draft.order_entered_on,
                cost=invoice_draft.cost,
                carried_forward=invoice_draft.carried_forward,
            )
            booked[number] = document.functional_total
            if not invoice_draft.carried_forward:
                segment = self.customers[invoice_draft.customer].segment
                entry = post_invoice(document, REVENUE_ACCOUNT[segment], invoice_draft.cost)
                journals[entry.entry_number] = entry
                journal_info[entry.entry_number] = JournalInfo(
                    created_on=invoice_draft.invoice_date, created_by="ar.clerk"
                )

        bills: dict[str, Document] = {}
        bill_info: dict[str, BillInfo] = {}
        for bill_draft in sorted(d.bills, key=lambda b: b.number or ""):
            number = _require(bill_draft.number)
            document = Document(
                document_type=DocumentType.BILL,
                number=number,
                party_code=bill_draft.vendor,
                party_reference=bill_draft.reference,
                document_date=bill_draft.bill_date,
                due_date=bill_draft.due_date,
                currency=USD,
                subtotal=Money(bill_draft.amount, USD),
                tax=Money(0, USD),
                total=Money(bill_draft.amount, USD),
                fx_rate=ONE,
                functional_total=Money(bill_draft.amount, USD),
            )
            bills[number] = document
            bill_info[number] = BillInfo(
                entered_by=bill_draft.entered_by,
                expense_account=bill_draft.expense_account,
                carried_forward=bill_draft.carried_forward,
            )
            if not bill_draft.carried_forward:
                entry = post_bill(document, bill_draft.expense_account)
                journals[entry.entry_number] = entry
                journal_info[entry.entry_number] = JournalInfo(
                    created_on=bill_draft.bill_date, created_by=bill_draft.entered_by
                )

        payments: dict[str, Payment] = {}
        bank: list[tuple[date, int, BankTransaction]] = []
        order = 0
        for receipt in sorted(d.receipts, key=lambda r: r.number or ""):
            number = _require(receipt.number)
            applications = tuple(
                PaymentApplication(
                    document_number=_require(self.invoice_by_key[key].number),
                    applied_amount=Money(amount, receipt.currency),
                    applied_functional_amount=booked[_require(self.invoice_by_key[key].number)],
                )
                for key, amount in receipt.applications
            )
            payment = Payment(
                number=number,
                direction=PaymentDirection.RECEIVED,
                method=receipt.method,
                reference=receipt.reference,
                party_code=receipt.customer,
                payment_date=receipt.receipt_date,
                currency=receipt.currency,
                amount=Money(receipt.amount, receipt.currency),
                fx_rate=receipt.fx_rate,
                functional_amount=Money(receipt.functional_amount, USD),
                applications=applications,
                unapplied_amount=Money(0, receipt.currency),
                bank_account=k.COMPANY.bank_account,
            )
            payments[payment.number] = payment
            entry = post_receipt(payment, booked)
            journals[entry.entry_number] = entry
            journal_info[entry.entry_number] = JournalInfo(
                created_on=receipt.receipt_date, created_by="ar.clerk"
            )
            name = self.customers[receipt.customer].party.name.upper()
            description = {
                PaymentMethod.CHECK: "REMOTE DEPOSIT CAPTURE",
                PaymentMethod.ACH: f"ACH CREDIT {name[:16]} PPD",
                PaymentMethod.WIRE: f"INCOMING WIRE {name[:20]} EUR {receipt.amount:,.2f}",
            }[receipt.method]
            order += 1
            bank.append(
                (
                    receipt.bank_posted_on,
                    order,
                    BankTransaction(
                        bank_account=k.COMPANY.bank_account,
                        posted_date=receipt.bank_posted_on,
                        description=description,
                        amount=Money(receipt.functional_amount, USD),
                        reference=receipt.reference,
                    ),
                )
            )

        for payment_draft in sorted(d.disbursements, key=lambda p: p.number or ""):
            number = _require(payment_draft.number)
            reference = (
                payment_draft.check_number
                if payment_draft.method is PaymentMethod.CHECK
                else payment_draft.trace
            )
            payment = Payment(
                number=number,
                direction=PaymentDirection.DISBURSED,
                method=payment_draft.method,
                reference=reference,
                party_code=payment_draft.vendor,
                payment_date=payment_draft.payment_date,
                currency=USD,
                amount=Money(payment_draft.amount, USD),
                fx_rate=ONE,
                functional_amount=Money(payment_draft.amount, USD),
                applications=tuple(
                    PaymentApplication(
                        document_number=_require(self.bill_by_key[key].number),
                        applied_amount=Money(amount, USD),
                        applied_functional_amount=Money(amount, USD),
                    )
                    for key, amount in payment_draft.applications
                ),
                unapplied_amount=Money(0, USD),
                bank_account=k.COMPANY.bank_account,
            )
            payments[payment.number] = payment
            entry = post_disbursement(payment)
            journals[entry.entry_number] = entry
            journal_info[entry.entry_number] = JournalInfo(
                created_on=payment_draft.payment_date, created_by="ap.clerk"
            )
            vendor_name = self.vendors[payment_draft.vendor].party.name.upper()
            description = (
                f"CHECK {reference}"
                if payment_draft.method is PaymentMethod.CHECK
                else f"ACH DEBIT {vendor_name[:18]} CCD"
            )
            order += 1
            bank.append(
                (
                    payment_draft.bank_posted_on,
                    order,
                    BankTransaction(
                        bank_account=k.COMPANY.bank_account,
                        posted_date=payment_draft.bank_posted_on,
                        description=description,
                        amount=Money(-payment_draft.amount, USD),
                        reference=reference,
                    ),
                )
            )

        number_by_key = {m.key: m.number for m in d.manual}
        for manual_draft in d.manual:
            number = _require(manual_draft.number)
            lines = tuple(
                JournalLine(
                    line_number=index + 1,
                    account_code=account,
                    amount=Money(amount, USD),
                    functional_amount=Money(amount, USD),
                    memo=memo,
                )
                for index, (account, amount, memo) in enumerate(manual_draft.lines)
            )
            entry = JournalEntry(
                entry_number=number,
                entry_date=manual_draft.entry_date,
                posting_period=manual_draft.posting_period,
                source_module=SourceModule.MANUAL,
                memo=manual_draft.memo,
                lines=lines,
                reversal_of=number_by_key[manual_draft.reversal_of_key]
                if manual_draft.reversal_of_key
                else None,
            )
            journals[entry.entry_number] = entry
            journal_info[entry.entry_number] = JournalInfo(
                created_on=manual_draft.created_on, created_by=manual_draft.created_by
            )
            cash = manual_draft.cash_amount()
            if cash != 0 and H1_START <= manual_draft.entry_date <= CUTOVER:
                posted = next_business_day(manual_draft.entry_date)
                order += 1
                bank.append(
                    (
                        posted,
                        order,
                        BankTransaction(
                            bank_account=k.COMPANY.bank_account,
                            posted_date=posted,
                            description=manual_draft.bank_description or manual_draft.memo.upper(),
                            amount=Money(cash, USD),
                        ),
                    )
                )

        for posted, description, amount, reference in d.bank_only:
            order += 1
            bank.append(
                (
                    posted,
                    order,
                    BankTransaction(
                        bank_account=k.COMPANY.bank_account,
                        posted_date=posted,
                        description=description,
                        amount=Money(amount, USD),
                        reference=reference,
                    ),
                )
            )

        bank.sort(key=lambda item: (item[0], item[1]))
        bank_lines = [
            BankLine(transaction, sequence)
            for sequence, (_, _, transaction) in enumerate(bank, start=1)
        ]

        # Opening trial balance.
        opening = {spec.code: spec.opening_balance for spec in LEGACY_ACCOUNTS}
        opening["1200"] = sum(
            (i.functional_total for i in d.invoices if i.carried_forward), Decimal(0)
        )
        opening["2000"] = -sum((b.amount for b in d.bills if b.carried_forward), Decimal(0))
        opening["2100"] = -DEC_FREIGHT_ACCRUAL
        opening["2160"] = -DEC_COMMISSION_ACCRUAL
        h1_cash = sum(
            (
                line.functional_amount.amount
                for entry in journals.values()
                for line in entry.lines
                if line.account_code == CASH and H1_START <= entry.entry_date <= CUTOVER
            ),
            Decimal(0),
        )
        opening[CASH] = k.CLEAN_GL_CASH_AT_CUTOVER - h1_cash
        opening["3900"] = Decimal(0)
        opening["3900"] = -sum(opening.values(), Decimal(0))

        fx_rates = {
            day: FxRate(rate_date=day, base_currency=EUR, quote_currency=USD, rate=rate)
            for day, rate in sorted(self.fx.items())
        }
        return LegacyUniverse(
            company=k.COMPANY,
            plan=k.PLAN,
            seed=self.seed,
            accounts=accounts,
            target_accounts=targets,
            account_mapping=correct_account_mapping(),
            customers=customers,
            customer_info=customer_info,
            vendors=vendors,
            vendor_info=vendor_info,
            invoices=invoices,
            invoice_info=invoice_info,
            bills=bills,
            bill_info=bill_info,
            payments=payments,
            journals=dict(sorted(journals.items())),
            journal_info=dict(sorted(journal_info.items())),
            bank_lines=bank_lines,
            fx_rates=fx_rates,
            opening_balances=opening,
        )

    def build(self) -> LegacyUniverse:
        self.build_sales()
        self.build_receipts()
        self.build_purchases()
        self.build_disbursements()
        self.build_manual_journals()
        self.build_financing()
        self.build_post_cutover_bank_activity()
        self.assign_numbers()
        return self.materialize()


class _References:
    """Unique vendor invoice references per vendor."""

    def __init__(self, prefix: str, rng: ScenarioRng) -> None:
        self.prefix = prefix or "INV"
        self.rng = rng
        self.used: set[str] = set()
        self.next = rng.integer(10000, 80000)

    def reserve(self, reference: str) -> None:
        self.used.add(reference)

    def take(self) -> str:
        while True:
            self.next += self.rng.integer(3, 40)
            reference = f"{self.prefix}-{self.next}"
            if reference not in self.used and reference != k.PCP_DUPLICATED_REFERENCE:
                self.used.add(reference)
                return reference


def _require(value: str | None) -> str:
    if value is None:
        raise ScenarioConsistencyError("identifier not assigned")
    return value


def build_clean_universe(seed: int = k.DEFAULT_SEED, *, verify: bool = True) -> LegacyUniverse:
    """Build the clean books. With ``verify`` (default), raise if any invariant is violated."""
    universe = _CleanBuilder(seed).build()
    if verify:
        from relay_scenarios.brightwater.checks import verify_clean_books  # noqa: PLC0415 - cycle

        verify_clean_books(universe)
    return universe


__all__ = ["build_clean_universe"]

# Silence unused-import warnings for names used only in type positions.
_ = (Party, PartyKey, PartyType, CLERKS, days, is_business_day)
