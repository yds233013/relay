"""Kestrel's source exports: a different legacy system, so a different shape on disk.

Everything here differs from the Brightwater exports on purpose, because the point of this company
is to find out whether the engine was overfitted to those files:

- **semicolon**-delimited, UTF-8 with a byte-order mark (Brightwater: comma, cp1252);
- dates written ``DD.MM.YYYY`` (Brightwater: ``MM/DD/YYYY``);
- amounts written ``1.234,56`` with a leading ``-`` for negatives (Brightwater: ``1,234.56`` and
  parentheses);
- the general ledger carries **one signed amount** per line (Brightwater: separate debit and credit
  columns);
- the trial balance is a signed balance per account and period (Brightwater: debit and credit);
- receipts and payments share one file with a ``Type`` column, applications inline;
- rows are ordered by account and then date, and documents descending by number — never the order a
  person would guess.
"""

from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from relay_scenarios.kestrel.books import (
    CUTOVER,
    FUNCTIONAL,
    OPENING,
    PERIOD_ENDS,
    Books,
    Document,
    money,
)

BOM = "﻿"
DELIMITER = ";"


def fmt_date(value: date) -> str:
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def fmt_amount(value: Decimal) -> str:
    """European convention: ``.`` groups thousands, ``,`` is the decimal separator."""
    quantized = money(value)
    sign = "-" if quantized < 0 else ""
    digits = f"{abs(quantized):,.2f}"
    return sign + digits.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_rate(value: Decimal) -> str:
    return f"{value:.4f}".replace(".", ",")


def write_csv(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    """No quoting: this legacy system writes plain fields, which is how a stray separator bites."""
    buffer = io.StringIO()
    buffer.write(BOM + DELIMITER.join(header) + "\r\n")
    for row in rows:
        buffer.write(DELIMITER.join(row) + "\r\n")
    return buffer.getvalue().encode("utf-8")


def _accounts(books: Books) -> bytes:
    return write_csv(
        ("Code", "Description", "Category", "Status"),
        [
            (a.code, a.name, a.subtype, "A" if a.active else "I")
            for a in sorted(books.accounts, key=lambda a: a.code)
        ],
    )


def _target_accounts(books: Books) -> bytes:
    return write_csv(
        ("Account", "Caption", "Class"),
        [(a.code, a.name, a.subtype) for a in books.target_accounts],
    )


def _mapping(books: Books) -> bytes:
    return write_csv(("Old", "New"), [(old, new) for old, new in books.mapping])


def _balances(books: Books) -> bytes:
    """Signed balance per account and period end, including the opening date."""
    rows = []
    for period_end in (OPENING, *PERIOD_ENDS):
        for account in sorted(books.accounts, key=lambda a: a.code):
            balance = books.balance_at(account.code, period_end)
            rows.append((account.code, account.name, fmt_date(period_end), fmt_amount(balance)))
    return write_csv(("Code", "Description", "Period End", "Balance"), rows)


def _journal(books: Books) -> bytes:
    """Ordered by account then date: a common export order, and not chronological."""
    rows = []
    for entry in books.entries:
        for number, line in enumerate(entry.lines, start=1):
            rows.append(
                (
                    line.account,
                    entry.entry_date,
                    entry.number,
                    str(number),
                    fmt_date(entry.entry_date),
                    f"{entry.entry_date:%m.%Y}",
                    entry.module,
                    line.document or "",
                    line.party or "",
                    line.memo,
                    fmt_amount(line.amount),
                    line.currency,
                    fmt_amount(line.foreign) if line.foreign is not None else "",
                    entry.reverses or "",
                )
            )
    rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    header = (
        "Code",
        "Entry",
        "Line",
        "Posted",
        "Period",
        "Module",
        "Document",
        "Party",
        "Text",
        "Amount",
        "Currency",
        "Foreign Amount",
        "Reverses",
    )
    # The sort key carries the entry date; the file itself shows the posted date and period.
    return write_csv(header, [(row[0], row[2], row[3], *row[4:]) for row in rows])


def _parties(parties: Iterable[object], *, notes: bool) -> bytes:
    header = ["Party", "Name", "City", "Country", "Currency", "Terms", "Email", "Tax Ref", "Status"]
    if notes:
        header.append("Remarks")
    rows = []
    for party in parties:
        row = [
            party.code,  # type: ignore[attr-defined]
            party.name,  # type: ignore[attr-defined]
            party.city,  # type: ignore[attr-defined]
            party.country,  # type: ignore[attr-defined]
            party.currency,  # type: ignore[attr-defined]
            str(party.terms),  # type: ignore[attr-defined]
            party.email,  # type: ignore[attr-defined]
            f"****{party.tax_last4}",  # type: ignore[attr-defined]
            "A" if party.active else "I",  # type: ignore[attr-defined]
        ]
        if notes:
            row.append("")
        rows.append(tuple(row))
    return write_csv(tuple(header), rows)


def _documents(documents: Sequence[Document], kind: str) -> bytes:
    """Descending by number: the newest first, as this system's browser shows them."""
    header = (
        f"{kind} No",
        "Party",
        "Issued",
        "Due",
        "Currency",
        "Gross",
        "Rate",
        "Gross (EUR)",
        "Outstanding",
        "State",
    )
    rows = [
        (
            d.number,
            d.party,
            fmt_date(d.doc_date),
            fmt_date(d.due_date),
            d.currency,
            fmt_amount(d.total),
            fmt_rate(d.fx_rate),
            fmt_amount(d.functional_total),
            fmt_amount(d.open_amount),
            "OPEN" if d.open_amount else "SETTLED",
        )
        for d in sorted(documents, key=lambda d: d.number, reverse=True)
    ]
    return write_csv(header, rows)


def _settlements(books: Books) -> bytes:
    header = (
        "Ref",
        "Type",
        "Value Date",
        "Party",
        "Method",
        "Currency",
        "Amount",
        "Rate",
        "Amount (EUR)",
        "Against",
        "Allocated",
        "On Account",
    )
    rows = []
    for settlement in books.settlements:
        for document, applied in settlement.applied or ((None, Decimal(0)),):
            rows.append(
                (
                    settlement.number,
                    "Receipt" if settlement.direction == "received" else "Payment",
                    fmt_date(settlement.paid_on),
                    settlement.party,
                    settlement.method,
                    settlement.currency,
                    fmt_amount(settlement.amount),
                    fmt_rate(settlement.fx_rate),
                    fmt_amount(settlement.functional_amount),
                    document or "",
                    fmt_amount(applied),
                    fmt_amount(settlement.unapplied),
                )
            )
    return write_csv(header, rows)


def _ageing(books: Books, documents: Sequence[Document], as_of: date) -> bytes:
    """Open items at a date, in EUR, with the ageing buckets this system prints."""
    header = ("Party", "Name", "Kind", "Reference", "Issued", "Due", "Currency", "Open (EUR)")
    names = {p.code: p.name for p in [*books.customers, *books.suppliers]}
    rows = []
    for document in sorted(documents, key=lambda d: (d.party, d.number)):
        open_at = _open_at(document, as_of)
        if open_at == 0:
            continue
        functional = (
            open_at if document.currency == FUNCTIONAL else money(open_at * document.fx_rate)
        )
        rows.append(
            (
                document.party,
                names.get(document.party, ""),
                "Invoice",
                document.number,
                fmt_date(document.doc_date),
                fmt_date(document.due_date),
                document.currency,
                fmt_amount(functional),
            )
        )
    return write_csv(header, rows)


def _open_at(document: Document, as_of: date) -> Decimal:
    """Open amount at a date: the whole document before the window, the recorded open at cutover."""
    if as_of >= CUTOVER:
        return document.open_amount
    return document.total if document.doc_date <= as_of else Decimal(0)


def _bank(books: Books) -> bytes:
    running = books.opening["1010"]
    rows = []
    for line in books.bank:
        running = money(running + line.amount)
        rows.append(
            (
                fmt_date(line.posted),
                line.description,
                line.reference,
                fmt_amount(line.amount),
                fmt_amount(running),
            )
        )
    return write_csv(("Booked", "Narrative", "Reference", "Movement", "Balance"), rows)


def _fx(books: Books) -> bytes:
    return write_csv(
        ("Date", "From", "To", "Rate"),
        [(fmt_date(day), base, quote, fmt_rate(rate)) for day, base, quote, rate in books.fx],
    )


def export_books(books: Books) -> dict[str, bytes]:
    """Every source file Kestrel hands over, keyed by the path Relay imports it under."""
    return {
        "tallyworks/accounts.csv": _accounts(books),
        "tallyworks/balances.csv": _balances(books),
        "tallyworks/journal.csv": _journal(books),
        "tallyworks/customers.csv": _parties(books.customers, notes=False),
        "tallyworks/suppliers.csv": _parties(books.suppliers, notes=True),
        "tallyworks/sales_invoices.csv": _documents(books.invoices, "Invoice"),
        "tallyworks/purchase_invoices.csv": _documents(books.bills, "Bill"),
        "tallyworks/settlements.csv": _settlements(books),
        "tallyworks/debtors_ageing_20251231.csv": _ageing(books, books.invoices, OPENING),
        "tallyworks/debtors_ageing_20260630.csv": _ageing(books, books.invoices, CUTOVER),
        "tallyworks/creditors_ageing_20251231.csv": _ageing(books, books.bills, OPENING),
        "tallyworks/creditors_ageing_20260630.csv": _ageing(books, books.bills, CUTOVER),
        "nordbank/statement.csv": _bank(books),
        "nordbank/fx_usd_eur.csv": _fx(books),
        "implementation/target_accounts.csv": _target_accounts(books),
        "implementation/mapping.csv": _mapping(books),
    }
