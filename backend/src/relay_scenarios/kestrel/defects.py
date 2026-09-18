"""The problems planted in Kestrel's export, and the benign look-alikes left alone.

Six defects, chosen to be a different combination from Brightwater's thirteen and to break different
controls. Each one edits the exported files, never the books, so the clean books stay the reference.

| Id | What the legacy export does | What it should surface |
|---|---|---|
| KS-01 | A payroll entry's cash line is keyed 12,50 short | the entry does not balance |
| KS-02 | An account with a balance is missing from the mapping | an unmapped account |
| KS-03 | Customer deposits (liability) mapped to receivables (asset) | a type conflict |
| KS-04 | An open invoice is missing from the sales export | the subledger does not tie |
| KS-05 | A USD invoice is dated before any published rate | no usable FX rate |
| KS-06 | A memo contains an unquoted `;` | a quarantined row, and a count that does not tie |

Benign look-alikes that must stay silent: rent of the same amount every month (a schedule, not a
duplicate), a March accrual reversed on 1 April (a reversal pair, not a duplicate), and two receipts
from the same customer on one day against different invoices.
"""

from __future__ import annotations

from typing import Final

ALL_DEFECTS: Final = ("KS-01", "KS-02", "KS-03", "KS-04", "KS-05", "KS-06")

JOURNAL: Final = "tallyworks/journal.csv"
MAPPING: Final = "implementation/mapping.csv"
INVOICES: Final = "tallyworks/sales_invoices.csv"

KS01_PAYROLL_DATE: Final = "28.02.2026"
"""February's payroll: its cash line is keyed short, so the entry no longer balances."""
KS01_SHORTFALL: Final = "12,50"
KS02_ACCOUNT: Final = "4990"
KS03_LEGACY: Final = "2150"
KS03_WRONG_TARGET: Final = "11-1000"
KS04_ISSUED: Final = "23.06.2026"
"""June's largest sale, still open at cutover, and absent from the export."""
KS05_ISSUED: Final = "15.01.2026"
KS05_DATE: Final = "05.01.2026"
"""January's USD sale, re-dated before the first published rate."""
KS06_PAYROLL_DATE: Final = "31.01.2026"
KS06_TEXT: Final = "Payroll; January"


def _lines(files: dict[str, bytes], name: str) -> list[str]:
    return files[name].decode("utf-8").split("\r\n")


def _store(files: dict[str, bytes], name: str, lines: list[str]) -> None:
    files[name] = "\r\n".join(lines).encode("utf-8")


def _unbalanced_entry(files: dict[str, bytes]) -> bool:
    """KS-01: the cash side of February's payroll is keyed 12,50 short."""
    lines = _lines(files, JOURNAL)
    for index, line in enumerate(lines):
        fields = line.split(";")
        if len(fields) > 10 and fields[0] == "1010" and fields[3] == KS01_PAYROLL_DATE:
            amount = fields[9]
            if not amount.startswith("-"):  # the payroll credit is negative in clean books
                return False
            fields[9] = _short_by(amount, KS01_SHORTFALL)
            lines[index] = ";".join(fields)
            _store(files, JOURNAL, lines)
            return True
    return False


def _short_by(amount: str, shortfall: str) -> str:
    """Subtract from the magnitude of a European-formatted negative amount."""
    magnitude = amount.lstrip("-").replace(".", "").replace(",", ".")
    reduced = float(magnitude) - float(shortfall.replace(",", "."))
    formatted = f"{reduced:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return "-" + formatted


def _unmapped_account(files: dict[str, bytes]) -> bool:
    """KS-02: the mapping file never mentions one account that carries a balance."""
    lines = _lines(files, MAPPING)
    kept = [line for line in lines if not line.startswith(f"{KS02_ACCOUNT};")]
    if len(kept) == len(lines):
        return False
    _store(files, MAPPING, kept)
    return True


def _wrong_target(files: dict[str, bytes]) -> bool:
    """KS-03: customer deposits are mapped into trade receivables — a liability into an asset."""
    lines = _lines(files, MAPPING)
    for index, line in enumerate(lines):
        if line.startswith(f"{KS03_LEGACY};"):
            lines[index] = f"{KS03_LEGACY};{KS03_WRONG_TARGET}"
            _store(files, MAPPING, lines)
            return True
    return False


def _missing_invoice(files: dict[str, bytes]) -> bool:
    """KS-04: an open invoice never reached the sales export, but the ledger and ageing have it."""
    lines = _lines(files, INVOICES)
    kept = [line for line in lines if KS04_ISSUED not in line.split(";")[2:3]]
    if len(kept) == len(lines):
        return False
    _store(files, INVOICES, kept)
    return True


def _unrated_currency(files: dict[str, bytes]) -> bool:
    """KS-05: January's USD sale is re-dated before the first published rate."""
    lines = _lines(files, INVOICES)
    for index, line in enumerate(lines):
        fields = line.split(";")
        if len(fields) > 4 and fields[2] == KS05_ISSUED and fields[4] == "USD":
            fields[2] = KS05_DATE
            lines[index] = ";".join(fields)
            _store(files, INVOICES, lines)
            return True
    return False


def _split_row(files: dict[str, bytes]) -> bool:
    """KS-06: January's payroll memo contains the separator, so the row has a field too many."""
    lines = _lines(files, JOURNAL)
    for index, line in enumerate(lines):
        fields = line.split(";")
        if len(fields) > 8 and fields[3] == KS06_PAYROLL_DATE and fields[8] == "Payroll":
            fields[8] = KS06_TEXT
            lines[index] = ";".join(fields)
            _store(files, JOURNAL, lines)
            return True
    return False


_INJECTORS = {
    "KS-01": _unbalanced_entry,
    "KS-02": _unmapped_account,
    "KS-03": _wrong_target,
    "KS-04": _missing_invoice,
    "KS-05": _unrated_currency,
    "KS-06": _split_row,
}


def apply_defects(
    files: dict[str, bytes], defects: tuple[str, ...] = ALL_DEFECTS
) -> tuple[str, ...]:
    """Apply each defect to the exported files. A defect that cannot be applied is an error."""
    planted = []
    for defect in defects:
        if defect not in _INJECTORS:
            raise KeyError(f"unknown defect {defect}")
        if not _INJECTORS[defect](files):
            raise RuntimeError(f"{defect} did not match the export it edits")
        planted.append(defect)
    return tuple(planted)
