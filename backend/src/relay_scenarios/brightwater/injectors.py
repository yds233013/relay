"""Defect injectors DS-01 to DS-13 (docs/demo-scenario.md §4).

EVALUATION/DEMO-ONLY. Each injector performs one bounded mutation of the LedgerPro universe (or of
the implementation team's mapping table), checks its preconditions, and fails loudly if they do not
hold. Injectors never add flags or labels to records: results must look like ordinary legacy data.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from relay.canonical.enums import PartyType, PaymentDirection, PaymentMethod
from relay.canonical.records import (
    BankTransaction,
    Document,
    JournalEntry,
    Party,
    PartyKey,
    Payment,
    PaymentApplication,
)
from relay.core.currency import Currency
from relay.core.money import Money
from relay_scenarios.brightwater import constants as k
from relay_scenarios.brightwater.parties import VendorCategory
from relay_scenarios.brightwater.postings import (
    bill_entry_number,
    disbursement_entry_number,
    invoice_entry_number,
    post_bill,
    post_disbursement,
    post_invoice,
    post_receipt,
    receipt_entry_number,
)
from relay_scenarios.brightwater.universe import (
    BankLine,
    BillInfo,
    CustomerInfo,
    JournalInfo,
    LegacyUniverse,
    VendorInfo,
)
from relay_scenarios.calendar import last_business_day
from relay_scenarios.errors import ScenarioConsistencyError

USD = Currency.of("USD")


@dataclass(frozen=True, slots=True)
class Injector:
    id: str
    title: str
    depends_on: tuple[str, ...]
    apply: Callable[[LegacyUniverse], None]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioConsistencyError(message)


def _reparty_entry(entry: JournalEntry, old: PartyKey, new: PartyKey) -> JournalEntry:
    lines = tuple(
        dataclasses.replace(line, party=new) if line.party == old else line for line in entry.lines
    )
    return dataclasses.replace(entry, lines=lines)


def _payments_applying(
    universe: LegacyUniverse, document_number: str, direction: PaymentDirection
) -> list[Payment]:
    return [
        p
        for p in universe.payments.values()
        if p.direction is direction
        and any(a.document_number == document_number for a in p.applications)
    ]


def _move_documents(
    universe: LegacyUniverse,
    documents: dict[str, Document],
    numbers: Sequence[str],
    old_code: str,
    new_code: str,
    party_type: PartyType,
) -> None:
    direction = (
        PaymentDirection.RECEIVED
        if party_type is PartyType.CUSTOMER
        else PaymentDirection.DISBURSED
    )
    old = PartyKey(party_type=party_type, code=old_code)
    new = PartyKey(party_type=party_type, code=new_code)
    for number in numbers:
        document = documents[number]
        _require(document.party_code == old_code, f"{number} does not belong to {old_code}")
        documents[number] = dataclasses.replace(document, party_code=new_code)
        entry_number = (
            invoice_entry_number(number)
            if party_type is PartyType.CUSTOMER
            else bill_entry_number(number)
        )
        universe.journals[entry_number] = _reparty_entry(universe.journals[entry_number], old, new)
        for payment in _payments_applying(universe, number, direction):
            _require(len(payment.applications) == 1, f"{payment.number} pays more than {number}")
            universe.payments[payment.number] = dataclasses.replace(payment, party_code=new_code)
            payment_entry = (
                receipt_entry_number(payment.number)
                if direction is PaymentDirection.RECEIVED
                else disbursement_entry_number(payment.number)
            )
            universe.journals[payment_entry] = _reparty_entry(
                universe.journals[payment_entry], old, new
            )


# ------------------------------------------------------------------------------------ DS-01
def ds01_duplicate_vendor(universe: LegacyUniverse) -> None:
    _require(k.PCP_DUPLICATE_VENDOR not in universe.vendors, "duplicate vendor already exists")
    original = universe.vendors[k.PCP_VENDOR]
    universe.vendors[k.PCP_DUPLICATE_VENDOR] = Party(
        party_type=PartyType.VENDOR,
        code=k.PCP_DUPLICATE_VENDOR,
        name="Pacific Coast Packaging, L.L.C.",
        address_line1="4410 N.W. Front Avenue, Suite 200",
        city="Portland",
        region="OR",
        postal_code="97209",
        country="US",
        email=original.email,
        tax_id_last4="7781",
        default_currency=USD,
        payment_terms_days=original.payment_terms_days,
        is_active=True,
        created_on=k.PCP_DUPLICATE_CREATED,
    )
    universe.vendor_info[k.PCP_DUPLICATE_VENDOR] = VendorInfo(
        VendorCategory.PACKAGING, "temp.apclerk"
    )
    universe.vendors = dict(sorted(universe.vendors.items()))
    universe.vendor_info = dict(sorted(universe.vendor_info.items()))

    candidates = sorted(
        (
            b
            for b in universe.bills.values()
            if b.party_code == k.PCP_VENDOR
            and b.document_date >= date(2026, 4, 1)
            and b.number != k.PCP_OPEN_BILL
            and _payments_applying(universe, b.number, PaymentDirection.DISBURSED)
        ),
        key=lambda b: (b.document_date, b.number),
    )
    _require(len(candidates) >= 2, "not enough Pacific Coast Packaging bills to re-key")
    _require(k.PCP_OPEN_BILL in universe.bills, "open Pacific Coast Packaging bill missing")
    moved = [k.PCP_OPEN_BILL, candidates[0].number, candidates[1].number]
    _move_documents(
        universe, universe.bills, moved, k.PCP_VENDOR, k.PCP_DUPLICATE_VENDOR, PartyType.VENDOR
    )


# ------------------------------------------------------------------------------------ DS-02
def ds02_duplicate_bill_and_payment(universe: LegacyUniverse) -> None:
    _require(
        k.PCP_DUPLICATE_VENDOR in universe.vendors, "DS-02 requires the duplicate vendor (DS-01)"
    )
    _require(k.PCP_DUPLICATE_BILL not in universe.bills, "duplicate bill already exists")
    _require(k.PCP_DUPLICATE_PAYMENT not in universe.payments, "duplicate payment already exists")
    original = universe.bills[k.PCP_ORIGINAL_BILL]
    _require(
        original.party_reference == k.PCP_DUPLICATED_REFERENCE, "original bill reference changed"
    )
    bill = dataclasses.replace(
        original, number=k.PCP_DUPLICATE_BILL, party_code=k.PCP_DUPLICATE_VENDOR
    )
    universe.bills[bill.number] = bill
    universe.bill_info[bill.number] = BillInfo(
        entered_by="temp.apclerk", expense_account="5150", carried_forward=False
    )
    universe.bills = dict(sorted(universe.bills.items()))
    universe.bill_info = dict(sorted(universe.bill_info.items()))
    entry = post_bill(bill, "5150")
    universe.journals[entry.entry_number] = entry
    universe.journal_info[entry.entry_number] = JournalInfo(
        created_on=date(2026, 2, 26), created_by="temp.apclerk"
    )

    payment = Payment(
        number=k.PCP_DUPLICATE_PAYMENT,
        direction=PaymentDirection.DISBURSED,
        method=PaymentMethod.ACH,
        reference="021000089773052",
        party_code=k.PCP_DUPLICATE_VENDOR,
        payment_date=k.PCP_DUPLICATE_PAYMENT_DATE,
        currency=USD,
        amount=bill.total,
        fx_rate=Decimal(1),
        functional_amount=bill.total,
        applications=(
            PaymentApplication(
                document_number=bill.number,
                applied_amount=bill.total,
                applied_functional_amount=bill.total,
            ),
        ),
        unapplied_amount=Money(0, USD),
        bank_account=k.COMPANY.bank_account,
    )
    universe.payments[payment.number] = payment
    universe.payments = dict(sorted(universe.payments.items()))
    payment_entry = post_disbursement(payment)
    universe.journals[payment_entry.entry_number] = payment_entry
    universe.journal_info[payment_entry.entry_number] = JournalInfo(
        created_on=payment.payment_date, created_by="ap.clerk"
    )
    universe.journals = dict(sorted(universe.journals.items()))
    universe.journal_info = dict(sorted(universe.journal_info.items()))
    universe.bank_lines.append(
        BankLine(
            BankTransaction(
                bank_account=k.COMPANY.bank_account,
                posted_date=k.PCP_DUPLICATE_PAYMENT_DATE,
                description="ACH DEBIT PACIFIC COAST PACKAG CCD",
                amount=-bill.total,
                reference=payment.reference,
            ),
            universe.next_bank_sequence(),
        )
    )


# ------------------------------------------------------------------------------------ DS-03
def ds03_allowance_mapped_to_receivables(universe: LegacyUniverse) -> None:
    _require(
        universe.account_mapping.get(k.ALLOWANCE_ACCOUNT) == "1210",
        "allowance mapping already altered",
    )
    universe.account_mapping[k.ALLOWANCE_ACCOUNT] = "1200"


# ------------------------------------------------------------------------------------ DS-04
def ds04_invoice_emailed_not_printed(universe: LegacyUniverse) -> None:
    info = universe.invoice_info[k.DS04_INVOICE]
    _require(info.printed, "invoice already unprinted")
    universe.invoice_info[k.DS04_INVOICE] = dataclasses.replace(info, printed=False)


# ------------------------------------------------------------------------------------ DS-05
def ds05_multiline_memo(universe: LegacyUniverse) -> None:
    entry = universe.journals[k.DS05_ENTRY]
    targets = [line for line in entry.lines if line.account_code == "6410"]
    _require(
        len(targets) == 1 and targets[0].memo == k.DS05_CLEAN_MEMO,
        "rebate line not in expected state",
    )
    lines = tuple(
        dataclasses.replace(line, memo=k.DS05_BROKEN_MEMO) if line.account_code == "6410" else line
        for line in entry.lines
    )
    universe.journals[k.DS05_ENTRY] = dataclasses.replace(entry, lines=lines)


# ------------------------------------------------------------------------------------ DS-06
def ds06_duplicate_customer(universe: LegacyUniverse) -> None:
    _require(
        k.GREEN_VALLEY_DUPLICATE not in universe.customers, "duplicate customer already exists"
    )
    original = universe.customers[k.GREEN_VALLEY]
    tax = original.tax_id_last4  # same legal entity, entered again by another clerk
    universe.customers[k.GREEN_VALLEY_DUPLICATE] = Party(
        party_type=PartyType.CUSTOMER,
        code=k.GREEN_VALLEY_DUPLICATE,
        name="Green Valley Cooperative Market",
        address_line1="1220 S.E. Hawthorne Boulevard",
        city="Portland",
        region="OR",
        postal_code="97214",
        country="US",
        email="accounts@greenvalley.coop",
        tax_id_last4=tax,
        default_currency=USD,
        payment_terms_days=original.payment_terms_days,
        is_active=True,
        created_on=date(2025, 9, 18),
    )
    universe.customer_info[k.GREEN_VALLEY_DUPLICATE] = universe.customer_info[k.GREEN_VALLEY]
    universe.customers = dict(sorted(universe.customers.items()))
    universe.customer_info = dict(sorted(universe.customer_info.items()))

    invoices = [i for i in universe.invoices.values() if i.party_code == k.GREEN_VALLEY]
    open_invoice = [
        i
        for i in invoices
        if i.total.amount == k.DS06_OPEN_AMOUNT and i.document_date == date(2026, 6, 19)
    ]
    _require(len(open_invoice) == 1, "Green Valley open fill-in invoice not found")
    paid_may = sorted(
        (
            i
            for i in invoices
            if date(2026, 4, 1) <= i.document_date <= date(2026, 6, 30)
            and _payments_applying(universe, i.number, PaymentDirection.RECEIVED)
        ),
        key=lambda i: (i.document_date, i.number),
    )
    _require(len(paid_may) >= 2, "Green Valley has fewer than two paid second-quarter invoices")
    moved = [open_invoice[0].number, paid_may[0].number, paid_may[1].number]
    _move_documents(
        universe,
        universe.invoices,
        moved,
        k.GREEN_VALLEY,
        k.GREEN_VALLEY_DUPLICATE,
        PartyType.CUSTOMER,
    )


# ------------------------------------------------------------------------------------ DS-07
def ds07_eur_invoices_keyed_as_usd(universe: LegacyUniverse) -> None:
    for number, invoice_date, face in k.DS07_INVOICES:
        invoice = universe.invoices[number]
        _require(
            invoice.currency.code == "EUR"
            and invoice.total.amount == face
            and invoice.document_date == invoice_date,
            f"{number} not in expected EUR state",
        )
        rekeyed = dataclasses.replace(
            invoice,
            currency=USD,
            subtotal=Money(face, USD),
            tax=Money(0, USD),
            total=Money(face, USD),
            fx_rate=Decimal(1),
            functional_total=Money(face, USD),
        )
        universe.invoices[number] = rekeyed
        cost = universe.invoice_info[number].cost
        universe.journals[invoice_entry_number(number)] = post_invoice(rekeyed, "4100", cost)

    receipts = _payments_applying(universe, k.DS07_PAID_INVOICE, PaymentDirection.RECEIVED)
    _require(
        len(receipts) == 1 and len(receipts[0].applications) == 1,
        "EUR wire receipt not in expected state",
    )
    receipt = receipts[0]
    received = receipt.functional_amount
    face = next(face for number, _, face in k.DS07_INVOICES if number == k.DS07_PAID_INVOICE)
    rekeyed_receipt = dataclasses.replace(
        receipt,
        currency=USD,
        amount=received,
        fx_rate=Decimal(1),
        functional_amount=received,
        applications=(
            PaymentApplication(
                document_number=k.DS07_PAID_INVOICE,
                applied_amount=Money(face, USD),
                applied_functional_amount=Money(face, USD),
            ),
        ),
        unapplied_amount=Money(received.amount - face, USD),
    )
    universe.payments[receipt.number] = rekeyed_receipt
    universe.journals[receipt_entry_number(receipt.number)] = post_receipt(
        rekeyed_receipt, {k.DS07_PAID_INVOICE: Money(face, USD)}
    )


# ------------------------------------------------------------------------------------ DS-08
def ds08_backdated_period(universe: LegacyUniverse) -> None:
    entry = universe.journals[k.DS08_ENTRY]
    _require(
        entry.entry_date == k.DS08_CLEAN_DATE and entry.posting_period == "2026-03",
        "count adjustment altered",
    )
    universe.journals[k.DS08_ENTRY] = dataclasses.replace(entry, entry_date=k.DS08_ENTERED_DATE)


# ------------------------------------------------------------------------------------ DS-09
def ds09_customer_closed(universe: LegacyUniverse) -> None:
    customer = universe.customers[k.CEDAR_AND_SALT]
    _require(customer.is_active, "customer already inactive")
    universe.customers[k.CEDAR_AND_SALT] = dataclasses.replace(customer, is_active=False)
    info = universe.customer_info[k.CEDAR_AND_SALT]
    universe.customer_info[k.CEDAR_AND_SALT] = CustomerInfo(
        info.segment, info.warehouse, closed_on=k.DS09_CLOSED_ON
    )


# ------------------------------------------------------------------------------------ DS-10
def ds10_unrecorded_bank_fees(universe: LegacyUniverse) -> None:
    existing = [
        b for b in universe.bank_lines if b.transaction.description == "MONTHLY MAINTENANCE FEE"
    ]
    _require(not existing, "bank fees already present")
    for month in range(1, 7):
        posted = last_business_day(2026, month)
        universe.bank_lines.append(
            BankLine(
                BankTransaction(
                    bank_account=k.COMPANY.bank_account,
                    posted_date=posted,
                    description="MONTHLY MAINTENANCE FEE",
                    amount=Money(-k.MONTHLY_BANK_FEE, USD),
                ),
                universe.next_bank_sequence(),
            )
        )


# ------------------------------------------------------------------------------------ DS-11
def ds11_impossible_entry_date(universe: LegacyUniverse) -> None:
    entry = universe.journals[k.DS11_ENTRY]
    _require(
        entry.entry_date == k.DS11_BILL_DATE and entry.posting_period == "2026-03",
        "bill posting altered",
    )
    _require(
        universe.bills[k.DS11_BILL].total.amount == k.DS11_AMOUNT, "utility bill amount altered"
    )
    universe.journals[k.DS11_ENTRY] = dataclasses.replace(entry, entry_date=k.DS11_KEYED_DATE)


# ------------------------------------------------------------------------------------ DS-12
def ds12_suspense_account_inactivated(universe: LegacyUniverse) -> None:
    info = universe.accounts[k.SUSPENSE_ACCOUNT]
    _require(info.account.is_active, "suspense account already inactive")
    universe.accounts[k.SUSPENSE_ACCOUNT] = dataclasses.replace(
        info, account=dataclasses.replace(info.account, is_active=False)
    )


# ------------------------------------------------------------------------------------ DS-13
def ds13_instruction_text_in_vendor_notes(universe: LegacyUniverse) -> None:
    vendor = universe.vendors[k.SUMMIT_VENDOR]
    _require(vendor.notes == "", "vendor notes already populated")
    universe.vendors[k.SUMMIT_VENDOR] = dataclasses.replace(vendor, notes=k.DS13_NOTE)


INJECTORS: tuple[Injector, ...] = (
    Injector("DS-01", "Duplicate vendor", (), ds01_duplicate_vendor),
    Injector(
        "DS-02", "Duplicate bill and double payment", ("DS-01",), ds02_duplicate_bill_and_payment
    ),
    Injector(
        "DS-03",
        "Contra-asset mapped into Accounts Receivable",
        (),
        ds03_allowance_mapped_to_receivables,
    ),
    Injector("DS-04", "Invoice missing from invoice export", (), ds04_invoice_emailed_not_printed),
    Injector("DS-05", "Journal line broken by an unquoted newline", (), ds05_multiline_memo),
    Injector("DS-06", "Duplicate customer record", (), ds06_duplicate_customer),
    Injector("DS-07", "EUR invoices keyed as USD", (), ds07_eur_invoices_keyed_as_usd),
    Injector("DS-08", "Backdated period posting", (), ds08_backdated_period),
    Injector("DS-09", "Customer excluded from export while referenced", (), ds09_customer_closed),
    Injector("DS-10", "Unrecorded bank fees", (), ds10_unrecorded_bank_fees),
    Injector("DS-11", "Impossible entry date", (), ds11_impossible_entry_date),
    Injector(
        "DS-12",
        "Inactive suspense account excluded from CoA export",
        (),
        ds12_suspense_account_inactivated,
    ),
    Injector(
        "DS-13", "Instruction-like text in vendor notes", (), ds13_instruction_text_in_vendor_notes
    ),
)
INJECTORS_BY_ID: dict[str, Injector] = {injector.id: injector for injector in INJECTORS}
ALL_DEFECTS: tuple[str, ...] = tuple(injector.id for injector in INJECTORS)


def apply_defects(universe: LegacyUniverse, defect_ids: Sequence[str]) -> LegacyUniverse:
    """Apply injectors in order, enforcing dependencies. Mutates and returns ``universe``."""
    for defect_id in defect_ids:
        injector = INJECTORS_BY_ID.get(defect_id)
        if injector is None:
            raise ScenarioConsistencyError(f"unknown defect {defect_id}")
        missing = [d for d in injector.depends_on if d not in universe.applied_injectors]
        if missing:
            raise ScenarioConsistencyError(f"{defect_id} requires {missing} to be applied first")
        if defect_id in universe.applied_injectors:
            raise ScenarioConsistencyError(f"{defect_id} already applied")
        injector.apply(universe)
        universe.applied_injectors.append(defect_id)
    return universe
