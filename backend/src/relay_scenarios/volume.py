"""Synthetic volume migration for performance measurement (not a demo, not evaluation truth).

Generates a clean, internally consistent half-year of a fictional wholesaler ("Harborline Supply
Co.") at a requested GL line count, in the same LedgerPro and bank export layouts as the Brightwater
fixtures, so the same approved column mapping set applies. Every party has a unique name, tax id,
address and email domain; amounts come from named deterministic streams (integer arithmetic only).

Because the books are clean and the bank export ends at cutover, a correct engine reports no
reconciliation discrepancies on this data. That makes the measurement a throughput check with a
built-in correctness check, not a synthetic benchmark of an empty workload.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from relay.canonical.enums import account_type_of
from relay_scenarios.brightwater.chart import LEGACY_BY_CODE, TARGET_BY_CODE
from relay_scenarios.brightwater.exports import (
    bank_csv,
    implementation_csv,
    ledgerpro_csv,
    lp_amount,
    lp_date,
    lp_optional_amount,
)
from relay_scenarios.calendar import next_business_day
from relay_scenarios.rng import ScenarioRng

VOLUME_SEED: Final = 424242
OPENING: Final = date(2025, 12, 31)
HISTORY_START: Final = date(2026, 1, 1)
CUTOVER: Final = date(2026, 6, 30)
OPENING_CASH: Final = Decimal("750000.00")
PERIOD_ENDS: Final = (
    date(2026, 1, 31),
    date(2026, 2, 28),
    date(2026, 3, 31),
    date(2026, 4, 30),
    date(2026, 5, 31),
    date(2026, 6, 30),
)

CASH, AR, INVENTORY, AP, EQUITY, REVENUE, COGS, UTILITIES = (
    "1010",
    "1200",
    "1300",
    "2000",
    "3000",
    "4000",
    "5000",
    "6200",
)
ACCOUNTS: Final = (CASH, AR, INVENTORY, AP, EQUITY, REVENUE, COGS, UTILITIES)

_FIRST: Final = (
    "Amber",
    "Basalt",
    "Cedar",
    "Driftwood",
    "Ember",
    "Fernbrook",
    "Granite",
    "Heron",
    "Ironwood",
    "Juniper",
    "Kestrel",
    "Larkspur",
    "Meridian",
    "Nettle",
    "Obsidian",
    "Pinecrest",
    "Quarry",
    "Riverstone",
    "Saltmarsh",
    "Tamarack",
    "Umber",
    "Vireo",
    "Willowmere",
    "Yarrow",
    "Zephyr",
    "Alder",
    "Bramble",
    "Coho",
    "Dunlin",
    "Estuary",
)
_SECOND: Final = (
    "Bay",
    "Bluff",
    "Canyon",
    "Cove",
    "Creek",
    "Crossing",
    "Delta",
    "Field",
    "Flats",
    "Gap",
    "Glen",
    "Grove",
    "Harbor",
    "Hollow",
    "Island",
    "Knoll",
    "Landing",
    "Ledge",
    "Meadow",
    "Mesa",
    "Point",
    "Prairie",
    "Ridge",
    "Shoals",
    "Spring",
    "Summit",
    "Terrace",
    "Vale",
    "View",
    "Wharf",
)
_KIND_CUSTOMER: Final = (
    "Market",
    "Grocers",
    "Kitchen",
    "Provisions",
    "Foods",
    "Cafe",
    "Co-op",
    "Deli",
    "Bistro",
    "Pantry",
)
_KIND_VENDOR: Final = (
    "Farms",
    "Packaging",
    "Logistics",
    "Mills",
    "Growers",
    "Supply",
    "Dairy",
    "Fisheries",
    "Orchards",
    "Services",
)
_STREETS: Final = (
    "Main St",
    "Oak Ave",
    "Front St",
    "Division St",
    "Harbor Way",
    "Mill Rd",
    "Park Blvd",
    "Lake Dr",
)
_CITIES: Final = (
    ("Salem", "OR"),
    ("Eugene", "OR"),
    ("Tacoma", "WA"),
    ("Spokane", "WA"),
    ("Boise", "ID"),
    ("Medford", "OR"),
)


@dataclass(frozen=True, slots=True)
class VolumeParty:
    code: str
    name: str
    address: str
    city: str
    region: str
    postal_code: str
    tax_last4: str
    domain: str


@dataclass(frozen=True, slots=True)
class _Line:
    account: str
    amount: Decimal
    party: VolumeParty | None = None
    document: str = ""


@dataclass(frozen=True, slots=True)
class _Entry:
    number: str
    kind: str
    entry_date: date
    lines: tuple[_Line, ...]


@dataclass(frozen=True, slots=True)
class _Document:
    number: str
    party: VolumeParty
    document_date: date
    amount: Decimal
    reference: str
    paid: bool


@dataclass(frozen=True, slots=True)
class _Payment:
    number: str
    received: bool
    party: VolumeParty
    payment_date: date
    amount: Decimal
    reference: str
    document: str


@dataclass
class VolumeMigration:
    target_lines: int
    customers: list[VolumeParty] = field(default_factory=list)
    vendors: list[VolumeParty] = field(default_factory=list)
    invoices: list[_Document] = field(default_factory=list)
    bills: list[_Document] = field(default_factory=list)
    payments: list[_Payment] = field(default_factory=list)
    entries: list[_Entry] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return sum(len(entry.lines) for entry in self.entries)


def _parties(
    rng: ScenarioRng, prefix: str, count: int, kinds: tuple[str, ...], offset: int
) -> list[VolumeParty]:
    if count > len(_FIRST) * len(_SECOND) * len(kinds):
        raise ValueError("too many parties for the name space")
    tax_ids = rng.sample(range(10000), count + offset)[offset:]
    names = rng.sample(range(len(_FIRST) * len(_SECOND) * len(kinds)), count)
    parties = []
    for index in range(count):
        combo = names[index]
        first = _FIRST[combo % len(_FIRST)]
        second = _SECOND[(combo // len(_FIRST)) % len(_SECOND)]
        kind = kinds[combo // (len(_FIRST) * len(_SECOND))]
        city, region = _CITIES[index % len(_CITIES)]
        name = f"{first} {second} {kind}"
        parties.append(
            VolumeParty(
                code=f"{prefix}-{index + 1:05d}",
                name=name,
                address=f"{100 + index * 7} {_STREETS[index % len(_STREETS)]}",
                city=city,
                region=region,
                postal_code=f"9{7000 + index % 2000:04d}",
                tax_last4=f"{tax_ids[index]:04d}",
                domain=f"{first}{second}{kind}{index}".lower().replace("-", ""),
            )
        )
    return parties


def build_volume_migration(target_lines: int, seed: int = VOLUME_SEED) -> VolumeMigration:
    """A clean migration with about ``target_lines`` GL detail lines (two lines per entry)."""
    rng = ScenarioRng(seed, "volume")
    migration = VolumeMigration(target_lines=target_lines)
    entries_wanted = max(target_lines // 2, 10)
    invoice_count = entries_wanted * 30 // 100
    bill_count = entries_wanted * 22 // 100
    migration.customers = _parties(
        rng.child("customers"), "K", max(invoice_count // 25, 20), _KIND_CUSTOMER, 0
    )
    migration.vendors = _parties(
        rng.child("vendors"), "W", max(bill_count // 30, 10), _KIND_VENDOR, 0
    )
    history_days = (CUTOVER - HISTORY_START).days

    def day(stream: ScenarioRng) -> date:
        return next_business_day(
            HISTORY_START + timedelta(days=stream.integer(0, history_days - 3))
        )

    documents = rng.child("documents")
    for kind, count, parties, target in (
        ("invoice", invoice_count, migration.customers, migration.invoices),
        ("bill", bill_count, migration.vendors, migration.bills),
    ):
        for index in range(count):
            party = parties[documents.integer(0, len(parties) - 1)]
            document_date = day(documents)
            settle = next_business_day(document_date + timedelta(days=documents.integer(5, 45)))
            number = f"{'S' if kind == 'invoice' else 'P'}-{index + 1:07d}"
            target.append(
                _Document(
                    number,
                    party,
                    document_date,
                    documents.cents(Decimal("150"), Decimal("25000")),
                    f"REF-{documents.digits(9)}",
                    settle <= CUTOVER,
                )
            )
            if settle <= CUTOVER:
                received = kind == "invoice"
                migration.payments.append(
                    _Payment(
                        f"{'R' if received else 'D'}-{len(migration.payments) + 1:07d}",
                        received,
                        party,
                        settle,
                        target[-1].amount,
                        documents.digits(12),
                        number,
                    )
                )

    entries = migration.entries
    for invoice in migration.invoices:
        entries.append(
            _Entry(
                f"JE-S-{invoice.number[2:]}",
                "Invoice",
                invoice.document_date,
                (
                    _Line(AR, invoice.amount, invoice.party, invoice.number),
                    _Line(REVENUE, -invoice.amount, None, invoice.number),
                ),
            )
        )
    for bill in migration.bills:
        expense = COGS if int(bill.number[2:]) % 5 else UTILITIES
        entries.append(
            _Entry(
                f"JE-P-{bill.number[2:]}",
                "Bill",
                bill.document_date,
                (
                    _Line(expense, bill.amount, None, bill.number),
                    _Line(AP, -bill.amount, bill.party, bill.number),
                ),
            )
        )
    for payment in migration.payments:
        if payment.received:
            lines = (
                _Line(CASH, payment.amount, None, payment.number),
                _Line(AR, -payment.amount, payment.party, payment.number),
            )
            kind = "Payment"
        else:
            lines = (
                _Line(AP, payment.amount, payment.party, payment.number),
                _Line(CASH, -payment.amount, None, payment.number),
            )
            kind = "Bill Pmt -ACH"
        entries.append(_Entry(f"JE-C-{payment.number}", kind, payment.payment_date, lines))
    manual = rng.child("manual")
    for index in range(max(entries_wanted - len(entries), 0)):
        amount = manual.cents(Decimal("50"), Decimal("4000"))
        entries.append(
            _Entry(
                f"JE-M-{index + 1:07d}",
                "General Journal",
                day(manual),
                (_Line(COGS, amount), _Line(INVENTORY, -amount)),
            )
        )
    return migration


def _period(value: date) -> str:
    return f"{value.month:02d}/{value.year:04d}"


def _account_row(code: str) -> tuple[str, str, str, str, str]:
    spec = LEGACY_BY_CODE[code]
    return (code, spec.name, spec.ledgerpro_type, spec.detail_type, "Yes")


def export_volume_migration(migration: VolumeMigration) -> dict[str, bytes]:
    lp = "ledgerpro/"
    files: dict[str, bytes] = {}
    files[lp + "ledgerpro_chart_of_accounts.csv"] = ledgerpro_csv(
        ("Account", "Description", "Type", "Detail Type", "Active"),
        [_account_row(code) for code in ACCOUNTS],
    )
    opening = {CASH: OPENING_CASH, EQUITY: -OPENING_CASH}
    activity: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    gl_rows = []
    for entry in migration.entries:
        period_end = next(end for end in PERIOD_ENDS if entry.entry_date <= end)
        for number, line in enumerate(entry.lines, start=1):
            activity[(line.account, period_end)] += line.amount
            gl_rows.append(
                (
                    line.account,
                    LEGACY_BY_CODE[line.account].name,
                    lp_date(entry.entry_date),
                    _period(entry.entry_date),
                    entry.kind,
                    entry.number,
                    str(number),
                    line.document,
                    line.party.code if line.party else "",
                    line.party.name if line.party else "",
                    "",
                    lp_optional_amount(max(line.amount, Decimal(0))),
                    lp_optional_amount(max(-line.amount, Decimal(0))),
                    "USD",
                    "",
                    "",
                )
            )
    gl_rows.sort(key=lambda r: (r[0], r[2][6:] + r[2][:2] + r[2][3:5], r[5], int(r[6])))
    files[lp + "ledgerpro_gl_detail_2026H1.csv"] = ledgerpro_csv(
        (
            "Account",
            "Account Description",
            "Date",
            "Period",
            "Type",
            "Num",
            "Line",
            "Doc No",
            "Name ID",
            "Name",
            "Memo",
            "Debit",
            "Credit",
            "Currency",
            "Foreign Amount",
            "Reversal Of",
        ),
        gl_rows,
    )

    tb_rows = []
    for code in ACCOUNTS:
        balance = opening.get(code, Decimal(0))
        for end in (OPENING, *PERIOD_ENDS):
            balance += activity.get((code, end), Decimal(0))
            tb_rows.append(
                (
                    code,
                    LEGACY_BY_CODE[code].name,
                    lp_date(end),
                    lp_amount(balance) if balance >= 0 else "",
                    lp_amount(-balance) if balance < 0 else "",
                )
            )
    files[lp + "ledgerpro_trial_balance_by_period.csv"] = ledgerpro_csv(
        ("Account", "Description", "Period Ending", "Debit", "Credit"), tb_rows
    )

    files[lp + "ledgerpro_customers.csv"] = ledgerpro_csv(
        (
            "Customer ID",
            "Customer Name",
            "Address",
            "City",
            "State",
            "Zip",
            "Country",
            "AP Email",
            "Tax ID",
            "Currency",
            "Terms",
            "Status",
            "Created",
        ),
        [
            (
                p.code,
                p.name,
                p.address,
                p.city,
                p.region,
                p.postal_code,
                "US",
                f"ap@{p.domain}.example",
                f"XX-XXX{p.tax_last4}",
                "USD",
                "Net 30",
                "Active",
                "03/01/2019",
            )
            for p in migration.customers
        ],
    )
    files[lp + "ledgerpro_vendors.csv"] = ledgerpro_csv(
        (
            "Vendor ID",
            "Vendor Name",
            "Address",
            "City",
            "State",
            "Zip",
            "Tax ID",
            "Terms",
            "Status",
            "Created",
            "Created By",
            "Notes",
        ),
        [
            (
                p.code,
                p.name,
                p.address,
                p.city,
                p.region,
                p.postal_code,
                f"XX-XXX{p.tax_last4}",
                "Net 30",
                "Active",
                "03/01/2019",
                "system",
                "",
            )
            for p in migration.vendors
        ],
    )
    files[lp + "ledgerpro_invoices.csv"] = ledgerpro_csv(
        (
            "Invoice No",
            "Customer ID",
            "Customer Name",
            "Invoice Date",
            "Due Date",
            "Terms",
            "Currency",
            "Subtotal",
            "Tax",
            "Total",
            "Exchange Rate",
            "Total (USD)",
            "Balance Due",
            "Status",
        ),
        [
            (
                d.number,
                d.party.code,
                d.party.name,
                lp_date(d.document_date),
                lp_date(d.document_date + timedelta(days=30)),
                "Net 30",
                "USD",
                lp_amount(d.amount),
                "0.00",
                lp_amount(d.amount),
                "1.0000",
                lp_amount(d.amount),
                "0.00" if d.paid else lp_amount(d.amount),
                "Paid" if d.paid else "Open",
            )
            for d in migration.invoices
        ],
    )
    files[lp + "ledgerpro_bills.csv"] = ledgerpro_csv(
        (
            "Bill No",
            "Vendor ID",
            "Vendor Name",
            "Vendor Ref",
            "Bill Date",
            "Due Date",
            "Currency",
            "Amount",
            "Balance Due",
            "Status",
        ),
        [
            (
                d.number,
                d.party.code,
                d.party.name,
                d.reference,
                lp_date(d.document_date),
                lp_date(d.document_date + timedelta(days=30)),
                "USD",
                lp_amount(d.amount),
                "0.00" if d.paid else lp_amount(d.amount),
                "Paid" if d.paid else "Open",
            )
            for d in migration.bills
        ],
    )
    files[lp + "ledgerpro_payments.csv"] = ledgerpro_csv(
        (
            "Payment No",
            "Type",
            "Date",
            "Name ID",
            "Name",
            "Method",
            "Check/Ref No",
            "Currency",
            "Amount",
            "Exchange Rate",
            "Amount (USD)",
            "Applied To",
            "Applied Amount",
            "Unapplied",
        ),
        [
            (
                p.number,
                "Receipt" if p.received else "Bill Payment",
                lp_date(p.payment_date),
                p.party.code,
                p.party.name,
                "ACH",
                p.reference,
                "USD",
                lp_amount(p.amount),
                "1.0000",
                lp_amount(p.amount),
                p.document,
                lp_amount(p.amount),
                "0.00",
            )
            for p in migration.payments
        ],
    )
    for kind, label, documents in (
        ("ar", "Customer", migration.invoices),
        ("ap", "Vendor", migration.bills),
    ):
        header = (
            f"{label} ID",
            label,
            "Type",
            "Num",
            "Date",
            "Due Date",
            "Currency",
            "Current",
            "1 - 30",
            "31 - 60",
            "61 - 90",
            "> 90",
            "Open Balance (USD)",
        )
        doc_label = "Invoice" if kind == "ar" else "Bill"
        files[lp + f"ledgerpro_{kind}_aging_20251231.csv"] = ledgerpro_csv(
            header, [("", "TOTAL", "", "", "", "", "", *(["0.00"] * 5), "0.00")]
        )
        open_documents = [d for d in documents if not d.paid]
        total = sum((d.amount for d in open_documents), Decimal(0))
        rows = [
            (
                d.party.code,
                d.party.name,
                doc_label,
                d.number,
                lp_date(d.document_date),
                lp_date(d.document_date + timedelta(days=30)),
                "USD",
                lp_amount(d.amount),
                "",
                "",
                "",
                "",
                lp_amount(d.amount),
            )
            for d in open_documents
        ]
        rows.append(
            (
                "",
                "TOTAL",
                "",
                "",
                "",
                "",
                "",
                lp_amount(total),
                "0.00",
                "0.00",
                "0.00",
                "0.00",
                lp_amount(total),
            )
        )
        files[lp + f"ledgerpro_{kind}_aging_20260630.csv"] = ledgerpro_csv(header, rows)

    bank_rows = []
    balance = OPENING_CASH
    for payment in sorted(migration.payments, key=lambda p: (p.payment_date, p.number)):
        amount = payment.amount if payment.received else -payment.amount
        balance += amount
        description = (
            f"ACH {'CREDIT' if payment.received else 'DEBIT'} {payment.party.name.upper()[:20]}"
        )
        bank_rows.append(
            (
                payment.payment_date.isoformat(),
                description,
                f"{amount:.2f}",
                f"{balance:.2f}",
                payment.reference,
            )
        )
    files["firstcascade/firstcascade_4471_statement.csv"] = bank_csv(
        ("Posted Date", "Description", "Amount", "Balance", "Reference"), bank_rows
    )
    files["firstcascade/firstcascade_fx_eurusd.csv"] = bank_csv(
        ("Date", "Currency Pair", "Rate"), [("2026-01-02", "EUR/USD", "1.0800")]
    )

    targets = sorted({LEGACY_BY_CODE[code].target or code for code in ACCOUNTS})
    files["implementation/target_chart_of_accounts.csv"] = implementation_csv(
        ("Account Number", "Account Name", "Account Type", "Account Subtype"),
        [
            (
                code,
                TARGET_BY_CODE[code].name,
                account_type_of(TARGET_BY_CODE[code].subtype).value.title(),
                TARGET_BY_CODE[code].subtype.value,
            )
            for code in targets
        ],
    )
    files["implementation/account_mapping_v2.csv"] = implementation_csv(
        ("Legacy Account", "Legacy Description", "Target Account", "Target Description"),
        [
            (
                code,
                LEGACY_BY_CODE[code].name,
                LEGACY_BY_CODE[code].target or code,
                TARGET_BY_CODE[LEGACY_BY_CODE[code].target or code].name,
            )
            for code in ACCOUNTS
        ],
    )
    files["migration.json"] = _descriptor()
    return dict(sorted(files.items()))


def _descriptor() -> bytes:
    lp, bank, impl = "ledgerpro/", "firstcascade/", "implementation/"
    datasets = [
        ("legacy_coa", lp + "ledgerpro_chart_of_accounts.csv", "cp1252", None),
        ("trial_balance", lp + "ledgerpro_trial_balance_by_period.csv", "cp1252", None),
        ("gl_detail", lp + "ledgerpro_gl_detail_2026H1.csv", "cp1252", None),
        ("customers", lp + "ledgerpro_customers.csv", "cp1252", None),
        ("vendors", lp + "ledgerpro_vendors.csv", "cp1252", None),
        ("invoices", lp + "ledgerpro_invoices.csv", "cp1252", None),
        ("bills", lp + "ledgerpro_bills.csv", "cp1252", None),
        ("payments", lp + "ledgerpro_payments.csv", "cp1252", None),
        ("ar_aging", lp + "ledgerpro_ar_aging_20251231.csv", "cp1252", OPENING),
        ("ar_aging", lp + "ledgerpro_ar_aging_20260630.csv", "cp1252", CUTOVER),
        ("ap_aging", lp + "ledgerpro_ap_aging_20251231.csv", "cp1252", OPENING),
        ("ap_aging", lp + "ledgerpro_ap_aging_20260630.csv", "cp1252", CUTOVER),
        ("bank_transactions", bank + "firstcascade_4471_statement.csv", "utf-8-sig", None),
        ("fx_rates", bank + "firstcascade_fx_eurusd.csv", "utf-8-sig", None),
        ("target_coa", impl + "target_chart_of_accounts.csv", "utf-8", None),
        ("account_mapping", impl + "account_mapping_v2.csv", "utf-8", None),
    ]
    descriptor = {
        "fictional": True,
        "notice": "Synthetic volume data for performance tests. Names and figures are invented.",
        "company": {
            "name": "Harborline Supply Co.",
            "functional_currency": "USD",
            "fiscal_year_start_month": 1,
        },
        "conversion_plan": {
            "opening_balance_date": OPENING.isoformat(),
            "history_start_date": HISTORY_START.isoformat(),
            "cutover_date": CUTOVER.isoformat(),
            "go_live_date": "2026-07-01",
            "bank_clearing_window_days": 15,
        },
        "datasets": [
            {"dataset_type": t, "file": f, "encoding": e, **({"as_of": a.isoformat()} if a else {})}
            for t, f, e, a in datasets
        ],
    }
    return (json.dumps(descriptor, indent=2) + "\n").encode("utf-8")
