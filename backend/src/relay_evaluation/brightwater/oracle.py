"""Reference reconciliations over fixture files (evaluation oracle).

An intentionally direct implementation of the documented reconciliation definitions
(docs/validation-and-reconciliation.md, SC-02, SC-04), computed from the source-style files only. It
exists to verify that generated fixtures carry exactly the effects the golden manifest states. It is
not Relay's reconciliation engine and knows nothing about which defects were injected.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from relay.core.dates import DateFormat, parse_business_date, parse_iso_business_date
from relay_evaluation.brightwater.fixtures import Table, amount, read_table

GL = "ledgerpro/ledgerpro_gl_detail_2026H1.csv"
TB = "ledgerpro/ledgerpro_trial_balance_by_period.csv"
MAPPING = "implementation/account_mapping_v2.csv"
TARGETS = "implementation/target_chart_of_accounts.csv"
COA = "ledgerpro/ledgerpro_chart_of_accounts.csv"
INVOICES = "ledgerpro/ledgerpro_invoices.csv"
BILLS = "ledgerpro/ledgerpro_bills.csv"
PAYMENTS = "ledgerpro/ledgerpro_payments.csv"
VENDORS = "ledgerpro/ledgerpro_vendors.csv"
BANK = "firstcascade/firstcascade_4471_statement.csv"
OPENING_DATE = date(2025, 12, 31)
HISTORY_START = date(2026, 1, 1)
CUTOVER = date(2026, 6, 30)


def _us(value: str) -> date:
    return parse_business_date(value, DateFormat.US_PADDED)


@dataclass(frozen=True, slots=True)
class Line:
    recon: str
    grain: tuple[tuple[str, str], ...]
    values: dict[str, object]


class Oracle:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.tables: dict[str, Table] = {
            path: read_table(path, content)
            for path, content in files.items()
            if path.endswith(".csv")
        }

    # ------------------------------------------------------------------ building blocks
    def tb(self) -> dict[tuple[str, date], Decimal]:
        balances: dict[tuple[str, date], Decimal] = {}
        for row in self.tables[TB].rows:
            balances[(row["Account"], _us(row["Period Ending"]))] = amount(row["Debit"]) - amount(
                row["Credit"]
            )
        return balances

    def period_ends(self) -> list[date]:
        return sorted({end for _, end in self.tb()})

    def gl_lines(self) -> list[dict[str, str]]:
        return list(self.tables[GL].rows)

    @staticmethod
    def signed(row: dict[str, str]) -> Decimal:
        return amount(row["Debit"]) - amount(row["Credit"])

    def mapping(self) -> dict[str, str]:
        return {row["Legacy Account"]: row["Target Account"] for row in self.tables[MAPPING].rows}

    def target_subtypes(self) -> dict[str, str]:
        return {row["Account Number"]: row["Account Subtype"] for row in self.tables[TARGETS].rows}

    # ------------------------------------------------------------------ R1
    def r1(self) -> list[Line]:
        tb = self.tb()
        detail: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
        ends = [e for e in self.period_ends() if e > OPENING_DATE]
        for row in self.gl_lines():
            entry_date = _us(row["Date"])
            for end in ends:
                if HISTORY_START <= entry_date <= end:
                    detail[(row["Account"], end)] += self.signed(row)
        lines = []
        for (account, end), balance in sorted(tb.items()):
            if end == OPENING_DATE:
                continue
            right = tb.get((account, OPENING_DATE), Decimal(0)) + detail.get(
                (account, end), Decimal(0)
            )
            if balance != right:
                lines.append(
                    Line(
                        "R1",
                        (("account", account), ("period_end", end.isoformat())),
                        {"difference": balance - right},
                    )
                )
        return lines

    # ------------------------------------------------------------------ R2
    def r2(self) -> list[Line]:
        tb = self.tb()
        mapping = self.mapping()
        ends = [e for e in self.period_ends() if e > OPENING_DATE]
        left: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
        right: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
        for (account, end), balance in tb.items():
            if end == OPENING_DATE:
                continue
            left[(mapping.get(account, "unmapped"), end)] += balance
            if account in mapping:
                right[(mapping[account], end)] += tb.get((account, OPENING_DATE), Decimal(0))
        for row in self.gl_lines():
            target = mapping.get(row["Account"])
            if target is None:
                continue
            entry_date = _us(row["Date"])
            for end in ends:
                if HISTORY_START <= entry_date <= end:
                    right[(target, end)] += self.signed(row)
        lines = []
        for key in sorted(set(left) | set(right)):
            difference = left.get(key, Decimal(0)) - right.get(key, Decimal(0))
            if difference != 0:
                lines.append(
                    Line(
                        "R2",
                        (("target_account", key[0]), ("period_end", key[1].isoformat())),
                        {"difference": difference},
                    )
                )
        return lines

    # ------------------------------------------------------------------ R3 / R4 and companions
    def _subledger(
        self, recon: str, subtype: str, aging_opening: str, aging_cutover: str, sign: int
    ) -> list[Line]:
        mapping = self.mapping()
        subtypes = self.target_subtypes()
        mapped_legacy = {
            legacy for legacy, target in mapping.items() if subtypes.get(target) == subtype
        }
        tb = self.tb()
        opening_aging = self.tables[aging_opening]
        party_column = next(c for c in opening_aging.header if c.endswith(" ID"))
        left: dict[str, Decimal] = defaultdict(Decimal)
        opening_total = Decimal(0)
        for row in opening_aging.rows:
            if row[party_column]:
                value = sign * amount(row["Open Balance (USD)"])
                left[row[party_column]] += value
                opening_total += value
        opening_tb = sum((tb.get((a, OPENING_DATE), Decimal(0)) for a in mapped_legacy), Decimal(0))
        left["unassigned"] += opening_tb - opening_total
        for row in self.gl_lines():
            if row["Account"] in mapped_legacy and HISTORY_START <= _us(row["Date"]) <= CUTOVER:
                left[row["Name ID"] or "unassigned"] += self.signed(row)
        right: dict[str, Decimal] = defaultdict(Decimal)
        documents = self.tables[INVOICES if recon == "R3" else BILLS]
        number_column = "Invoice No" if recon == "R3" else "Bill No"
        party_id = "Customer ID" if recon == "R3" else "Vendor ID"
        document_items: dict[str, Decimal] = {}
        for row in documents.rows:
            balance = amount(row["Balance Due"])
            if balance == 0:
                continue
            total = amount(row["Total"] if recon == "R3" else row["Amount"])
            functional_total = amount(row["Total (USD)"]) if recon == "R3" else total
            functional = functional_total if balance == total else balance
            right[row[party_id]] += sign * functional
            document_items[row[number_column]] = sign * functional
        direction = "Receipt" if recon == "R3" else "Bill Payment"
        for row in self.tables[PAYMENTS].rows:
            if row["Type"] == direction and row["Unapplied"] and amount(row["Unapplied"]) != 0:
                right[row["Name ID"]] -= sign * amount(row["Unapplied"])
        lines = []
        names = {row["Vendor ID"]: row["Vendor Name"] for row in self.tables[VENDORS].rows}
        for party in sorted(set(left) | set(right)):
            difference = left.get(party, Decimal(0)) - right.get(party, Decimal(0))
            if difference != 0:
                grain = (
                    (("party", party),)
                    if recon == "R3"
                    else (("party_name", names.get(party, party)),)
                )
                lines.append(Line(recon, grain, {"difference": difference}))
        # Companion b: cutover aging vs staged items, by document.
        aging_items: dict[str, Decimal] = {}
        for row in self.tables[aging_cutover].rows:
            if row[party_column] and row["Type"] != "Payment":
                aging_items[row["Num"]] = sign * amount(row["Open Balance (USD)"])
        for document in sorted(set(aging_items) | set(document_items)):
            difference = aging_items.get(document, Decimal(0)) - document_items.get(
                document, Decimal(0)
            )
            if difference != 0:
                lines.append(
                    Line(f"{recon}b", (("document", document),), {"difference": sign * difference})
                )
        # Companion o: opening aging total vs opening TB of legacy accounts of that subtype.
        coa_subtype_accounts = {
            row["Account"]
            for row in self.tables[COA].rows
            if row["Type"] == ("Accounts Receivable" if recon == "R3" else "Accounts Payable")
        }
        opening_control = sum(
            (tb.get((a, OPENING_DATE), Decimal(0)) for a in coa_subtype_accounts), Decimal(0)
        )
        if opening_control != opening_total:
            lines.append(Line(f"{recon}o", (), {"difference": opening_control - opening_total}))
        return lines

    def r3(self) -> list[Line]:
        return self._subledger(
            "R3",
            "accounts_receivable",
            "ledgerpro/ledgerpro_ar_aging_20251231.csv",
            "ledgerpro/ledgerpro_ar_aging_20260630.csv",
            1,
        )

    def r4(self) -> list[Line]:
        return self._subledger(
            "R4",
            "accounts_payable",
            "ledgerpro/ledgerpro_ap_aging_20251231.csv",
            "ledgerpro/ledgerpro_ap_aging_20260630.csv",
            -1,
        )

    # ------------------------------------------------------------------ R5
    def r5(self) -> dict[str, object]:
        tb = self.tb()
        gl_cash = tb.get(("1010", OPENING_DATE), Decimal(0))
        gl_movements: list[tuple[date, Decimal, str]] = []
        by_entry: dict[str, Decimal] = defaultdict(Decimal)
        entry_meta: dict[str, tuple[date, str]] = {}
        for row in self.gl_lines():
            if row["Account"] == "1010" and HISTORY_START <= _us(row["Date"]) <= CUTOVER:
                gl_cash += self.signed(row)
                by_entry[row["Num"]] += self.signed(row)
                entry_meta[row["Num"]] = (_us(row["Date"]), row["Memo"])
        for number, value in by_entry.items():
            gl_movements.append((entry_meta[number][0], value, entry_meta[number][1]))
        bank_rows = [
            (
                parse_iso_business_date(r["Posted Date"]),
                Decimal(r["Amount"]),
                r["Description"],
                Decimal(r["Balance"]),
            )
            for r in self.tables[BANK].rows
        ]
        through_cutover = [r for r in bank_rows if r[0] <= CUTOVER]
        after = [r for r in bank_rows if r[0] > CUTOVER]
        bank_balance = through_cutover[-1][3]
        remaining_bank: dict[Decimal, int] = defaultdict(int)
        for _, value, _, _ in through_cutover:
            remaining_bank[value] += 1
        unmatched_gl: list[Decimal] = []
        for _, value, _ in gl_movements:
            if remaining_bank[value] > 0:
                remaining_bank[value] -= 1
            else:
                unmatched_gl.append(value)
        after_pool: dict[Decimal, int] = defaultdict(int)
        for _, value, _, _ in after:
            after_pool[value] += 1
        outstanding: list[Decimal] = []
        in_transit: list[Decimal] = []
        unexplained_gl: list[Decimal] = []
        for value in unmatched_gl:
            if after_pool[value] > 0:
                after_pool[value] -= 1
                (outstanding if value < 0 else in_transit).append(value)
            else:
                unexplained_gl.append(value)
        bank_only = [value for value, count in remaining_bank.items() for _ in range(count)]
        difference = gl_cash - bank_balance
        explained = (
            sum(outstanding, Decimal(0)) + sum(in_transit, Decimal(0)) - sum(bank_only, Decimal(0))
        )
        return {
            "gl_balance": gl_cash,
            "bank_balance": bank_balance,
            "difference": difference,
            "outstanding_checks": {
                "count": len(outstanding),
                "total": sum(outstanding, Decimal(0)),
            },
            "deposits_in_transit": {"count": len(in_transit), "total": sum(in_transit, Decimal(0))},
            "bank_only_activity": {"count": len(bank_only), "total": -sum(bank_only, Decimal(0))},
            "unexplained": difference - explained,
            "unexplained_gl_movements": len(unexplained_gl),
        }

    # ------------------------------------------------------------------ R6
    def r6(self) -> list[Line]:
        table = self.tables[GL]
        staged: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
        for row in table.rows:
            period = row["Period"][3:] + "-" + row["Period"][:2]
            bucket = staged[period]
            bucket[0] += 1
            bucket[1] += amount(row["Debit"])
            bucket[2] += amount(row["Credit"])
        source = {period: list(values) for period, values in staged.items()}
        for record in reconstruct_quarantined(table):
            period = record["Period"][3:] + "-" + record["Period"][:2]
            bucket = source.setdefault(period, [Decimal(0), Decimal(0), Decimal(0)])
            bucket[0] += 1
            bucket[1] += amount(record["Debit"])
            bucket[2] += amount(record["Credit"])
        lines = []
        for period in sorted(set(source) | set(staged)):
            s = source.get(period, [Decimal(0)] * 3)
            t = staged.get(period, [Decimal(0)] * 3)
            if s != t:
                lines.append(
                    Line(
                        "R6",
                        (("period", period),),
                        {
                            "count_difference": int(s[0] - t[0]),
                            "debit_difference": s[1] - t[1],
                            "credit_difference": s[2] - t[2],
                        },
                    )
                )
        return lines

    def all_lines(self) -> list[Line]:
        return [*self.r1(), *self.r2(), *self.r3(), *self.r4(), *self.r6()]


def reconstruct_quarantined(table: Table) -> list[dict[str, str]]:
    """Join consecutive malformed physical lines whose field counts combine into one record."""
    import csv  # noqa: PLC0415
    import io  # noqa: PLC0415

    records: list[dict[str, str]] = []
    pending: list[str] = []
    for malformed in table.malformed:
        pending.append(malformed.raw_text)
        joined = "\n".join(pending)
        fields = next(csv.reader(io.StringIO(joined.replace("\n", " "))))
        if len(fields) == len(table.header):
            records.append(dict(zip(table.header, fields, strict=True)))
            pending = []
    return records
