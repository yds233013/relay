"""Source-style exports: the files Relay will ingest (docs/demo-scenario.md §2).

LedgerPro Desktop exports (Windows-1252, CRLF, ``MM/DD/YYYY`` dates, thousands separators).
LedgerPro's CSV writer quotes fields containing commas or quotes but **not** line breaks.
Export filters are LedgerPro's defaults:

* chart of accounts: active accounts only
* customers: active customers only (vendors: all)
* invoices: printed invoices only; history window plus documents open at the opening date
* bills: history window plus documents open at the opening date
* GL detail and payments: postings in the history window's periods

First Cascade Bank exports: UTF-8 with BOM, CRLF, ISO dates, single signed amount column.
Implementation-team artifacts: UTF-8, LF.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal
from typing import Final

from relay.canonical.enums import (
    AgingItemKind,
    AgingType,
    PaymentDirection,
    PaymentMethod,
    SourceModule,
)
from relay.canonical.records import AgingItem, period_of
from relay_scenarios.brightwater import controls
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.errors import ScenarioConsistencyError

LEDGERPRO_DIR: Final = "ledgerpro"
BANK_DIR: Final = "firstcascade"
IMPLEMENTATION_DIR: Final = "implementation"


# ------------------------------------------------------------------------------------ formatting
def lp_date(value: date) -> str:
    return value.strftime("%m/%d/%Y")


def lp_amount(value: Decimal) -> str:
    return f"{value:,.2f}"


def lp_optional_amount(value: Decimal) -> str:
    return "" if value == 0 else lp_amount(value)


def _lp_field(value: str) -> str:
    if "," in value or '"' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def ledgerpro_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    lines = [",".join(_lp_field(h) for h in header)]
    lines.extend(",".join(_lp_field(value) for value in row) for row in rows)
    text = "\r\n".join(lines) + "\r\n"
    try:
        return text.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise ScenarioConsistencyError(
            f"LedgerPro export text is not Windows-1252 encodable: {exc}"
        ) from exc


def bank_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def implementation_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


# ------------------------------------------------------------------------------------ LedgerPro
def export_chart_of_accounts(u: LegacyUniverse) -> bytes:
    rows = [
        (code, info.account.name, info.ledgerpro_type, info.detail_type, "Yes")
        for code, info in sorted(u.accounts.items())
        if info.account.is_active
    ]
    return ledgerpro_csv(("Account", "Description", "Type", "Detail Type", "Active"), rows)


def export_trial_balance(u: LegacyUniverse) -> bytes:
    rows = []
    for line in controls.trial_balance(u):
        balance = line.balance.amount
        debit = lp_amount(balance) if balance >= 0 else ""
        credit = lp_amount(-balance) if balance < 0 else ""
        rows.append(
            (
                line.account_code,
                u.accounts[line.account_code].account.name,
                lp_date(line.period_end),
                debit,
                credit,
            )
        )
    rows.sort(key=lambda r: (r[2][6:] + r[2][:2] + r[2][3:5], r[0]))
    return ledgerpro_csv(("Account", "Description", "Period Ending", "Debit", "Credit"), rows)


_ENTRY_TYPES: Final = {
    SourceModule.ACCOUNTS_RECEIVABLE: "Invoice",
    SourceModule.ACCOUNTS_PAYABLE: "Bill",
    SourceModule.CASH_RECEIPTS: "Payment",
    SourceModule.MANUAL: "General Journal",
}


def _history_periods(u: LegacyUniverse) -> tuple[str, str]:
    return period_of(u.plan.history_start_date), period_of(u.plan.cutover_date)


def export_gl_detail(u: LegacyUniverse) -> bytes:
    first, last = _history_periods(u)
    rows = []
    for entry in u.journals.values():
        if not first <= entry.posting_period <= last:
            continue
        if entry.source_module is SourceModule.CASH_DISBURSEMENTS:
            payment = u.payments[entry.lines[-1].document_number or ""]
            kind = "Bill Pmt -Check" if payment.method is PaymentMethod.CHECK else "Bill Pmt -ACH"
        else:
            kind = _ENTRY_TYPES[entry.source_module]
        for line in entry.lines:
            amount = line.functional_amount.amount
            party_name = ""
            party_id = ""
            if line.party is not None:
                party_id = line.party.code
                parties = u.customers if line.party.party_type.value == "customer" else u.vendors
                party_name = parties[line.party.code].name
            foreign = ""
            currency = line.amount.currency.code
            if currency != "USD":
                foreign = lp_amount(line.amount.amount)
            rows.append(
                (
                    line.account_code,
                    u.accounts[line.account_code].account.name,
                    lp_date(entry.entry_date),
                    entry.posting_period[5:] + "/" + entry.posting_period[:4],
                    kind,
                    entry.entry_number,
                    str(line.line_number),
                    line.document_number or "",
                    party_id,
                    party_name,
                    line.memo,
                    lp_optional_amount(amount if amount > 0 else Decimal(0)),
                    lp_optional_amount(-amount if amount < 0 else Decimal(0)),
                    currency,
                    foreign,
                    entry.reversal_of or "",
                )
            )
    rows.sort(key=lambda r: (r[0], r[2][6:] + r[2][:2] + r[2][3:5], r[5], int(r[6])))
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def export_customers(u: LegacyUniverse) -> bytes:
    rows = [
        (
            p.code,
            p.name,
            p.address_line1,
            p.city,
            p.region,
            p.postal_code,
            p.country,
            p.email or "",
            f"XX-XXX{p.tax_id_last4}" if p.tax_id_last4 else "",
            p.default_currency.code,
            f"Net {p.payment_terms_days}",
            "Active",
            lp_date(p.created_on),
        )
        for p in u.customers.values()
        if p.is_active
    ]
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def export_vendors(u: LegacyUniverse) -> bytes:
    rows = [
        (
            p.code,
            p.name,
            p.address_line1,
            p.city,
            p.region,
            p.postal_code,
            f"XX-XXX{p.tax_id_last4}" if p.tax_id_last4 else "",
            "Due on receipt" if p.payment_terms_days == 0 else f"Net {p.payment_terms_days}",
            "Active" if p.is_active else "Inactive",
            lp_date(p.created_on),
            u.vendor_info[p.code].created_by,
            p.notes,
        )
        for p in u.vendors.values()
    ]
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def _in_scope(u: LegacyUniverse, number: str, document_date: date, is_invoice: bool) -> bool:
    if u.plan.history_start_date <= document_date <= u.plan.cutover_date:
        return True
    if document_date <= u.plan.opening_balance_date:
        document = u.invoices[number] if is_invoice else u.bills[number]
        return controls.open_amount(u, document, u.plan.opening_balance_date) > 0
    return False


def export_invoices(u: LegacyUniverse) -> bytes:
    rows = []
    for number, invoice in u.invoices.items():
        if not u.invoice_info[number].printed or not _in_scope(
            u, number, invoice.document_date, True
        ):
            continue
        balance = controls.open_amount(u, invoice, u.plan.cutover_date)
        rows.append(
            (
                number,
                invoice.party_code,
                u.customers[invoice.party_code].name,
                lp_date(invoice.document_date),
                lp_date(invoice.due_date),
                f"Net {(invoice.due_date - invoice.document_date).days}",
                invoice.currency.code,
                lp_amount(invoice.subtotal.amount),
                lp_amount(invoice.tax.amount),
                lp_amount(invoice.total.amount),
                f"{invoice.fx_rate:.4f}",
                lp_amount(invoice.functional_total.amount),
                lp_amount(balance),
                "Open" if balance > 0 else "Paid",
            )
        )
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def export_bills(u: LegacyUniverse) -> bytes:
    rows = []
    for number, bill in u.bills.items():
        if not _in_scope(u, number, bill.document_date, False):
            continue
        balance = controls.open_amount(u, bill, u.plan.cutover_date)
        rows.append(
            (
                number,
                bill.party_code,
                u.vendors[bill.party_code].name,
                bill.party_reference or "",
                lp_date(bill.document_date),
                lp_date(bill.due_date),
                bill.currency.code,
                lp_amount(bill.total.amount),
                lp_amount(balance),
                "Open" if balance > 0 else "Paid",
            )
        )
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def export_payments(u: LegacyUniverse) -> bytes:
    rows = []
    for payment in u.payments.values():
        if not u.plan.history_start_date <= payment.payment_date <= u.plan.cutover_date:
            continue
        received = payment.direction is PaymentDirection.RECEIVED
        name = (u.customers if received else u.vendors)[payment.party_code].name
        common = (
            payment.number,
            "Receipt" if received else "Bill Payment",
            lp_date(payment.payment_date),
            payment.party_code,
            name,
            payment.method.value.upper(),
            payment.reference or "",
            payment.currency.code,
            lp_amount(payment.amount.amount),
            f"{payment.fx_rate:.4f}",
            lp_amount(payment.functional_amount.amount),
        )
        for index, application in enumerate(payment.applications):
            rows.append(
                (
                    *common,
                    application.document_number,
                    lp_amount(application.applied_amount.amount),
                    lp_amount(payment.unapplied_amount.amount) if index == 0 else "",
                )
            )
        if not payment.applications:
            rows.append((*common, "", "", lp_amount(payment.unapplied_amount.amount)))
    header = (
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
    )
    return ledgerpro_csv(header, rows)


def _bucket(item: AgingItem) -> int:
    if item.kind is AgingItemKind.UNAPPLIED_PAYMENT or item.due_date is None:
        return 0
    days_past_due = (item.as_of - item.due_date).days
    if days_past_due <= 0:
        return 0
    if days_past_due <= 30:
        return 1
    if days_past_due <= 60:
        return 2
    if days_past_due <= 90:
        return 3
    return 4


def export_aging(u: LegacyUniverse, aging_type: AgingType, as_of: date) -> bytes:
    items = controls.aging(u, aging_type, as_of)
    parties = u.customers if aging_type is AgingType.AR else u.vendors
    totals = [Decimal(0)] * 5
    rows = []
    for item in items:
        sign = 1 if item.kind is AgingItemKind.DOCUMENT else -1
        amount = sign * item.functional_open_amount.amount
        buckets = [""] * 5
        index = _bucket(item)
        buckets[index] = lp_amount(amount)
        totals[index] += amount
        kind = (
            ("Invoice" if aging_type is AgingType.AR else "Bill")
            if item.kind is AgingItemKind.DOCUMENT
            else "Payment"
        )
        rows.append(
            (
                item.party_code,
                parties[item.party_code].name,
                kind,
                item.reference,
                lp_date(item.item_date),
                lp_date(item.due_date) if item.due_date else "",
                item.currency.code,
                *buckets,
                lp_amount(amount),
            )
        )
    rows.append(
        (
            "",
            "TOTAL",
            "",
            "",
            "",
            "",
            "",
            *(lp_amount(t) for t in totals),
            lp_amount(sum(totals, Decimal(0))),
        )
    )
    label = "Customer" if aging_type is AgingType.AR else "Vendor"
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
    return ledgerpro_csv(header, rows)


# ------------------------------------------------------------------------------------ bank
def export_bank_statement(u: LegacyUniverse) -> bytes:
    lines = controls.bank_statement(u, controls.bank_opening_balance(u), u.plan.bank_export_end)
    rows = [
        (
            line.posted_date.isoformat(),
            line.description,
            f"{line.amount:.2f}",
            f"{line.running_balance:.2f}",
            line.reference or "",
        )
        for line in lines
    ]
    return bank_csv(("Posted Date", "Description", "Amount", "Balance", "Reference"), rows)


def export_fx_rates(u: LegacyUniverse) -> bytes:
    rows = [
        (day.isoformat(), "EUR/USD", f"{rate.rate:.4f}") for day, rate in sorted(u.fx_rates.items())
    ]
    return bank_csv(("Date", "Currency Pair", "Rate"), rows)


# ------------------------------------------------------------------------- implementation team
def export_target_chart(u: LegacyUniverse) -> bytes:
    rows = [
        (code, account.name, account.account_type.value.title(), account.subtype.value)
        for code, account in sorted(u.target_accounts.items())
    ]
    return implementation_csv(
        ("Account Number", "Account Name", "Account Type", "Account Subtype"), rows
    )


def export_account_mapping(u: LegacyUniverse) -> bytes:
    """Mapping table as approved (version 2), for the legacy accounts in the CoA export."""
    rows = []
    for code, info in sorted(u.accounts.items()):
        if not info.account.is_active:
            continue
        target_code = u.account_mapping[code]
        rows.append((code, info.account.name, target_code, u.target_accounts[target_code].name))
    return implementation_csv(
        ("Legacy Account", "Legacy Description", "Target Account", "Target Description"), rows
    )


def migration_descriptor(u: LegacyUniverse, files: dict[str, bytes]) -> bytes:
    company = u.company
    plan = u.plan
    datasets = [
        ("legacy_coa", "ledgerpro", "ledgerpro/ledgerpro_chart_of_accounts.csv", "cp1252", None),
        (
            "trial_balance",
            "ledgerpro",
            "ledgerpro/ledgerpro_trial_balance_by_period.csv",
            "cp1252",
            None,
        ),
        ("gl_detail", "ledgerpro", "ledgerpro/ledgerpro_gl_detail_2026H1.csv", "cp1252", None),
        ("customers", "ledgerpro", "ledgerpro/ledgerpro_customers.csv", "cp1252", None),
        ("vendors", "ledgerpro", "ledgerpro/ledgerpro_vendors.csv", "cp1252", None),
        ("invoices", "ledgerpro", "ledgerpro/ledgerpro_invoices.csv", "cp1252", None),
        ("bills", "ledgerpro", "ledgerpro/ledgerpro_bills.csv", "cp1252", None),
        ("payments", "ledgerpro", "ledgerpro/ledgerpro_payments.csv", "cp1252", None),
        (
            "ar_aging",
            "ledgerpro",
            "ledgerpro/ledgerpro_ar_aging_20251231.csv",
            "cp1252",
            plan.opening_balance_date,
        ),
        (
            "ar_aging",
            "ledgerpro",
            "ledgerpro/ledgerpro_ar_aging_20260630.csv",
            "cp1252",
            plan.cutover_date,
        ),
        (
            "ap_aging",
            "ledgerpro",
            "ledgerpro/ledgerpro_ap_aging_20251231.csv",
            "cp1252",
            plan.opening_balance_date,
        ),
        (
            "ap_aging",
            "ledgerpro",
            "ledgerpro/ledgerpro_ap_aging_20260630.csv",
            "cp1252",
            plan.cutover_date,
        ),
        (
            "bank_transactions",
            "first_cascade_bank",
            "firstcascade/firstcascade_4471_statement.csv",
            "utf-8-sig",
            None,
        ),
        (
            "fx_rates",
            "first_cascade_bank",
            "firstcascade/firstcascade_fx_eurusd.csv",
            "utf-8-sig",
            None,
        ),
        (
            "target_coa",
            "implementation_team",
            "implementation/target_chart_of_accounts.csv",
            "utf-8",
            None,
        ),
        (
            "account_mapping",
            "implementation_team",
            "implementation/account_mapping_v2.csv",
            "utf-8",
            None,
        ),
    ]
    for _, _, path, _, _ in datasets:
        if path not in files:
            raise ScenarioConsistencyError(f"descriptor references missing file {path}")
    descriptor = {
        "fictional": True,
        "notice": "Fictional sample data. All companies, people and figures are invented.",
        "company": {
            "name": company.name,
            "functional_currency": company.functional_currency,
            "fiscal_year_start_month": company.fiscal_year_start_month,
        },
        "conversion_plan": {
            "opening_balance_date": plan.opening_balance_date.isoformat(),
            "history_start_date": plan.history_start_date.isoformat(),
            "cutover_date": plan.cutover_date.isoformat(),
            "go_live_date": plan.go_live_date.isoformat(),
            "bank_clearing_window_days": plan.bank_clearing_window_days,
        },
        "source_systems": [
            {"id": "ledgerpro", "name": company.legacy_system, "kind": "legacy_erp"},
            {
                "id": "first_cascade_bank",
                "name": f"{company.bank_name} (account ending {company.bank_account})",
                "kind": "bank",
            },
            {"id": "implementation_team", "name": "Implementation team", "kind": "other"},
        ],
        "datasets": [
            {
                "dataset_type": kind,
                "source_system": source,
                "file": path,
                "encoding": encoding,
                **({"as_of": as_of.isoformat()} if as_of else {}),
            }
            for kind, source, path, encoding, as_of in datasets
        ],
    }
    return (json.dumps(descriptor, indent=2, sort_keys=False) + "\n").encode("utf-8")


def export_all(u: LegacyUniverse) -> dict[str, bytes]:
    plan = u.plan
    files = {
        "ledgerpro/ledgerpro_chart_of_accounts.csv": export_chart_of_accounts(u),
        "ledgerpro/ledgerpro_trial_balance_by_period.csv": export_trial_balance(u),
        "ledgerpro/ledgerpro_gl_detail_2026H1.csv": export_gl_detail(u),
        "ledgerpro/ledgerpro_customers.csv": export_customers(u),
        "ledgerpro/ledgerpro_vendors.csv": export_vendors(u),
        "ledgerpro/ledgerpro_invoices.csv": export_invoices(u),
        "ledgerpro/ledgerpro_bills.csv": export_bills(u),
        "ledgerpro/ledgerpro_payments.csv": export_payments(u),
        "ledgerpro/ledgerpro_ar_aging_20251231.csv": export_aging(
            u, AgingType.AR, plan.opening_balance_date
        ),
        "ledgerpro/ledgerpro_ar_aging_20260630.csv": export_aging(
            u, AgingType.AR, plan.cutover_date
        ),
        "ledgerpro/ledgerpro_ap_aging_20251231.csv": export_aging(
            u, AgingType.AP, plan.opening_balance_date
        ),
        "ledgerpro/ledgerpro_ap_aging_20260630.csv": export_aging(
            u, AgingType.AP, plan.cutover_date
        ),
        "firstcascade/firstcascade_4471_statement.csv": export_bank_statement(u),
        "firstcascade/firstcascade_fx_eurusd.csv": export_fx_rates(u),
        "implementation/target_chart_of_accounts.csv": export_target_chart(u),
        "implementation/account_mapping_v2.csv": export_account_mapping(u),
    }
    files["migration.json"] = migration_descriptor(u, files)
    return dict(sorted(files.items()))
