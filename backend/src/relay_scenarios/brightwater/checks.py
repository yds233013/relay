"""Accounting invariants of the clean Brightwater books.

Each check returns a list of human-readable violations. ``verify_clean_books`` raises
:class:`BooksInvariantError` if any check fails. Tests call the checks individually.

These checks are an independent reference for the *generator*. They are not Relay's validation or
reconciliation engine and must not be imported by runtime code.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from itertools import pairwise

from relay.canonical.enums import (
    AccountSubtype,
    AgingType,
    DocumentType,
    PartyType,
    PaymentDirection,
    SourceModule,
    account_type_of,
)
from relay.core.currency import Currency
from relay.core.money import Money, convert
from relay_scenarios.brightwater import controls
from relay_scenarios.brightwater.constants import (
    CLEAN_BANK_BALANCE_AT_CUTOVER,
    CLEAN_GL_CASH_AT_CUTOVER,
    DEPOSIT_IN_TRANSIT,
    OUTSTANDING_CHECKS,
)
from relay_scenarios.brightwater.postings import (
    bill_entry_number,
    disbursement_entry_number,
    invoice_entry_number,
    receipt_entry_number,
)
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.errors import BooksInvariantError

USD = Currency.of("USD")
CONTROL_SUBTYPES = frozenset(
    {
        AccountSubtype.CASH,
        AccountSubtype.ACCOUNTS_RECEIVABLE,
        AccountSubtype.ACCOUNTS_PAYABLE,
        AccountSubtype.CONTRA_ASSET,
        AccountSubtype.ACCUMULATED_DEPRECIATION,
        AccountSubtype.SUSPENSE,
    }
)

type Check = Callable[[LegacyUniverse], list[str]]


def _in_history(universe: LegacyUniverse, value: date) -> bool:
    return universe.plan.history_start_date <= value <= universe.plan.cutover_date


def check_entries_balance(universe: LegacyUniverse) -> list[str]:
    return [
        f"{entry.entry_number} does not balance ({entry.functional_total()})"
        for entry in universe.journals.values()
        if entry.functional_total() != 0
    ]


def check_total_debits_equal_credits(universe: LegacyUniverse) -> list[str]:
    debit_total = Decimal(0)
    credit_total = Decimal(0)
    for entry in universe.journals.values():
        for line in entry.lines:
            amount = line.functional_amount.amount
            if amount > 0:
                debit_total += amount
            else:
                credit_total -= amount
    if debit_total == credit_total:
        return []
    return [f"total debits {debit_total} != total credits {credit_total}"]


def check_line_references(universe: LegacyUniverse) -> list[str]:
    problems = []
    for entry in universe.journals.values():
        for line in entry.lines:
            info = universe.accounts.get(line.account_code)
            if info is None:
                problems.append(
                    f"{entry.entry_number}:{line.line_number} "
                    f"posts to unknown account {line.account_code}"
                )
                continue
            subtype = info.account.subtype
            if line.amount.is_zero():
                problems.append(f"{entry.entry_number}:{line.line_number} is a zero line")
            if subtype is AccountSubtype.ACCOUNTS_RECEIVABLE:
                if (
                    line.party is None
                    or line.party.party_type is not PartyType.CUSTOMER
                    or line.party.code not in universe.customers
                ):
                    problems.append(
                        f"{entry.entry_number}:{line.line_number} AR line without a known customer"
                    )
            elif subtype is AccountSubtype.ACCOUNTS_PAYABLE:
                if (
                    line.party is None
                    or line.party.party_type is not PartyType.VENDOR
                    or line.party.code not in universe.vendors
                ):
                    problems.append(
                        f"{entry.entry_number}:{line.line_number} AP line without a known vendor"
                    )
            elif line.party is not None:
                problems.append(
                    f"{entry.entry_number}:{line.line_number} non-control line carries a party"
                )
    return problems


def check_dates_and_periods(universe: LegacyUniverse) -> list[str]:
    problems = []
    opening = universe.plan.opening_balance_date
    for entry in universe.journals.values():
        if entry.posting_period != f"{entry.entry_date.year:04d}-{entry.entry_date.month:02d}":
            problems.append(
                f"{entry.entry_number} period {entry.posting_period} "
                f"does not match date {entry.entry_date}"
            )
        if entry.entry_date > opening and not _in_history(universe, entry.entry_date):
            is_post_cutover_reversal = (
                entry.reversal_of is not None and entry.entry_date == universe.plan.go_live_date
            )
            if not is_post_cutover_reversal:
                problems.append(
                    f"{entry.entry_number} dated {entry.entry_date} outside the history window"
                )
    return problems


def check_documents(universe: LegacyUniverse) -> list[str]:
    problems = []
    for collection, parties, doc_type in (
        (universe.invoices, universe.customers, DocumentType.INVOICE),
        (universe.bills, universe.vendors, DocumentType.BILL),
    ):
        for document in collection.values():
            if document.document_type is not doc_type:
                problems.append(f"{document.number} has the wrong document type")
            if document.party_code not in parties:
                problems.append(f"{document.number} references unknown party {document.party_code}")
            if document.subtotal + document.tax != document.total:
                problems.append(f"{document.number} subtotal + tax != total")
            if document.due_date < document.document_date:
                problems.append(f"{document.number} due before its date")
            if document.currency == USD:
                if (
                    document.functional_total != Money(document.total.amount, USD)
                    or document.fx_rate != 1
                ):
                    problems.append(
                        f"{document.number} USD document with inconsistent functional total"
                    )
            else:
                rate = universe.fx_rates.get(document.document_date)
                if rate is None or rate.rate != document.fx_rate:
                    problems.append(
                        f"{document.number} rate differs from the published rate on its date"
                    )
                elif (
                    convert(document.total, document.fx_rate, USD).converted
                    != document.functional_total
                ):
                    problems.append(f"{document.number} functional total is not total x rate")
            party = parties.get(document.party_code)
            if party is not None and party.default_currency != document.currency:
                problems.append(f"{document.number} currency differs from party default")
            if document.document_date > universe.plan.cutover_date:
                problems.append(f"{document.number} dated after cutover")
    references = Counter((b.party_code, b.party_reference) for b in universe.bills.values())
    problems += [
        f"vendor {v} reference {r} used {n} times" for (v, r), n in references.items() if n > 1
    ]
    return problems


def check_payments(universe: LegacyUniverse) -> list[str]:
    problems = []
    applied_total: dict[str, Decimal] = defaultdict(Decimal)
    checks: Counter[str | None] = Counter()
    for payment in universe.payments.values():
        documents, parties = (
            (universe.invoices, universe.customers)
            if payment.direction is PaymentDirection.RECEIVED
            else (universe.bills, universe.vendors)
        )
        if payment.party_code not in parties:
            problems.append(f"{payment.number} references unknown party")
        applied = sum((a.applied_amount.amount for a in payment.applications), Decimal(0))
        if applied + payment.unapplied_amount.amount != payment.amount.amount:
            problems.append(f"{payment.number} applications + unapplied != amount")
        if not _in_history(universe, payment.payment_date):
            problems.append(f"{payment.number} outside the history window")
        for application in payment.applications:
            document = documents.get(application.document_number)
            if document is None:
                problems.append(
                    f"{payment.number} applies to unknown document {application.document_number}"
                )
                continue
            if document.party_code != payment.party_code:
                problems.append(f"{payment.number} applies to another party's document")
            if document.document_date > payment.payment_date:
                problems.append(f"{payment.number} pays {document.number} before it was issued")
            applied_total[document.number] += application.applied_amount.amount
        if payment.direction is PaymentDirection.DISBURSED and payment.method.value == "check":
            checks[payment.reference] += 1
    for number, amount in applied_total.items():
        document = universe.invoices.get(number) or universe.bills[number]
        if amount > document.total.amount:
            problems.append(f"{number} over-applied")
    problems += [f"check number {c} used {n} times" for c, n in checks.items() if n > 1]
    return problems


def check_subledger_postings(universe: LegacyUniverse) -> list[str]:
    problems = []
    info = universe.invoice_info
    for number, invoice in universe.invoices.items():
        entry = universe.journals.get(invoice_entry_number(number))
        if info[number].carried_forward:
            if entry is not None:
                problems.append(f"carried-forward {number} has a 2026 posting")
            continue
        if entry is None or entry.source_module is not SourceModule.ACCOUNTS_RECEIVABLE:
            problems.append(f"{number} has no AR posting")
            continue
        ar = sum(
            (ln.functional_amount.amount for ln in entry.lines if ln.account_code == "1200"),
            Decimal(0),
        )
        if ar != invoice.functional_total.amount:
            problems.append(f"{number} AR posting {ar} != functional total")
    for number, bill in universe.bills.items():
        entry = universe.journals.get(bill_entry_number(number))
        if universe.bill_info[number].carried_forward:
            if entry is not None:
                problems.append(f"carried-forward {number} has a 2026 posting")
            continue
        if entry is None:
            problems.append(f"{number} has no AP posting")
            continue
        ap = sum(
            (ln.functional_amount.amount for ln in entry.lines if ln.account_code == "2000"),
            Decimal(0),
        )
        if ap != -bill.functional_total.amount:
            problems.append(f"{number} AP posting {ap} != -total")
    for payment in universe.payments.values():
        number = (
            receipt_entry_number(payment.number)
            if payment.direction is PaymentDirection.RECEIVED
            else disbursement_entry_number(payment.number)
        )
        entry = universe.journals.get(number)
        if entry is None:
            problems.append(f"{payment.number} has no cash posting")
            continue
        cash = sum(
            (ln.functional_amount.amount for ln in entry.lines if ln.account_code == "1010"),
            Decimal(0),
        )
        expected = payment.functional_amount.amount * (
            1 if payment.direction is PaymentDirection.RECEIVED else -1
        )
        if cash != expected:
            problems.append(f"{payment.number} cash posting {cash} != {expected}")
    return problems


def check_trial_balance(universe: LegacyUniverse) -> list[str]:
    problems = []
    by_end: dict[date, Decimal] = defaultdict(Decimal)
    for line in controls.trial_balance(universe):
        by_end[line.period_end] += line.balance.amount
    problems += [
        f"trial balance at {end} sums to {total}" for end, total in by_end.items() if total != 0
    ]
    # Detail by entry date agrees with the TB by posting period at every period end (clean books).
    for line in controls.trial_balance(universe):
        by_date = controls.gl_balance(universe, line.account_code, line.period_end)
        if line.period_end > universe.plan.opening_balance_date and by_date != line.balance.amount:
            problems.append(
                f"{line.account_code} at {line.period_end}: "
                f"TB {line.balance.amount} != detail {by_date}"
            )
    return problems


def _party_balances(
    universe: LegacyUniverse, aging_type: AgingType, as_of: date
) -> dict[str, Decimal]:
    balances: dict[str, Decimal] = defaultdict(Decimal)
    for item in controls.aging(universe, aging_type, as_of):
        sign = 1 if item.kind.value == "document" else -1
        balances[item.party_code] += sign * item.functional_open_amount.amount
    return balances


def check_agings(universe: LegacyUniverse) -> list[str]:
    problems = []
    plan = universe.plan
    for aging_type, account, sign in ((AgingType.AR, "1200", 1), (AgingType.AP, "2000", -1)):
        opening_items = controls.aging(universe, aging_type, plan.opening_balance_date)
        opening_total = controls.aging_total(opening_items)
        if sign * opening_total != universe.opening_balances[account]:
            problems.append(
                f"opening {aging_type.value} aging {opening_total} != opening TB {account}"
            )
        cutover_total = controls.aging_total(
            controls.aging(universe, aging_type, plan.cutover_date)
        )
        gl = controls.gl_balance(universe, account, plan.cutover_date)
        if sign * cutover_total != gl:
            problems.append(
                f"cutover {aging_type.value} aging {cutover_total} != GL {account} {gl}"
            )
        # Party level: opening aging(p) + H1 activity(p) == cutover aging(p).
        opening_party = _party_balances(universe, aging_type, plan.opening_balance_date)
        cutover_party = _party_balances(universe, aging_type, plan.cutover_date)
        activity: dict[str, Decimal] = defaultdict(Decimal)
        for entry in universe.journals.values():
            if not _in_history(universe, entry.entry_date):
                continue
            for line in entry.lines:
                if line.account_code == account and line.party is not None:
                    activity[line.party.code] += sign * line.functional_amount.amount
        zero = Decimal(0)
        problems.extend(
            f"{aging_type.value} party {party} does not roll forward to its cutover balance"
            for party in sorted(set(opening_party) | set(cutover_party) | set(activity))
            if opening_party.get(party, zero) + activity.get(party, zero)
            != cutover_party.get(party, zero)
        )
    return problems


def check_cash_and_bank(universe: LegacyUniverse) -> list[str]:
    problems = []
    cutover = universe.plan.cutover_date
    gl = controls.gl_balance(universe, "1010", cutover)
    bank = controls.bank_balance(universe, cutover)
    if gl != CLEAN_GL_CASH_AT_CUTOVER:
        problems.append(f"GL cash at cutover {gl} != {CLEAN_GL_CASH_AT_CUTOVER}")
    if bank != CLEAN_BANK_BALANCE_AT_CUTOVER:
        problems.append(f"bank balance at cutover {bank} != {CLEAN_BANK_BALANCE_AT_CUTOVER}")
    expected_timing = (
        sum((amount for _, _, amount in OUTSTANDING_CHECKS), Decimal(0)) - DEPOSIT_IN_TRANSIT[2]
    )
    if bank - gl != expected_timing:
        problems.append(f"bank - GL {bank - gl} != timing items {expected_timing}")

    # Every GL cash movement in the window appears exactly once in the bank, same amount.
    gl_movements: Counter[Decimal] = Counter()
    for entry in universe.journals.values():
        if _in_history(universe, entry.entry_date):
            amount = sum(
                (ln.functional_amount.amount for ln in entry.lines if ln.account_code == "1010"),
                Decimal(0),
            )
            if amount != 0:
                gl_movements[amount] += 1
    bank_movements = Counter(
        b.transaction.amount.amount
        for b in universe.bank_lines
        if b.transaction.posted_date <= cutover or _clears_timing_item(b.transaction.amount.amount)
    )
    missing = gl_movements - bank_movements
    if missing:
        problems.append(f"GL cash movements without bank lines: {dict(list(missing.items())[:5])}")
    pre_cutover_extra = (
        Counter(
            b.transaction.amount.amount
            for b in universe.bank_lines
            if b.transaction.posted_date <= cutover
        )
        - gl_movements
    )
    if pre_cutover_extra:
        problems.append(
            "bank lines through cutover without GL cash movements: "
            f"{dict(list(pre_cutover_extra.items())[:5])}"
        )
    problems.extend(
        "bank line after the bank export window"
        for bank_line in universe.bank_lines
        if bank_line.transaction.posted_date > universe.plan.bank_export_end
    )
    return problems


def _clears_timing_item(amount: Decimal) -> bool:
    return amount in {-a for _, _, a in OUTSTANDING_CHECKS} or amount == DEPOSIT_IN_TRANSIT[2]


def check_mapping(universe: LegacyUniverse) -> list[str]:
    problems = []
    for code, info in universe.accounts.items():
        target_code = universe.account_mapping.get(code)
        if target_code is None:
            problems.append(f"legacy {code} is unmapped")
            continue
        target = universe.target_accounts.get(target_code)
        if target is None:
            problems.append(f"legacy {code} maps to unknown target {target_code}")
            continue
        legacy_subtype = info.account.subtype
        if account_type_of(legacy_subtype) != account_type_of(target.subtype):
            problems.append(f"legacy {code} maps across account types")
        if (
            legacy_subtype in CONTROL_SUBTYPES or target.subtype in CONTROL_SUBTYPES
        ) and legacy_subtype != target.subtype:
            problems.append(
                f"legacy {code} ({legacy_subtype}) maps to {target_code} ({target.subtype})"
            )
    return problems


def check_parties(universe: LegacyUniverse) -> list[str]:
    problems = []
    for collection in (universe.customers, universe.vendors):
        taxes = Counter(p.tax_id_last4 for p in collection.values() if p.tax_id_last4)
        problems += [f"tax id suffix {t} shared by {n} parties" for t, n in taxes.items() if n > 1]
        names = Counter(p.name.casefold() for p in collection.values())
        problems += [f"party name {n} used {c} times" for n, c in names.items() if c > 1]
    active_documents = {d.party_code for d in universe.invoices.values()} | {
        p.party_code for p in universe.payments.values() if p.direction is PaymentDirection.RECEIVED
    }
    for code, party in universe.customers.items():
        if not party.is_active and code in active_documents:
            problems.append(f"inactive customer {code} has documents or receipts")
    return problems


def check_no_accidental_duplicates(universe: LegacyUniverse) -> list[str]:
    """Only the documented patterns may look like duplicates in the clean books."""
    problems = []
    by_vendor_amount: dict[tuple[str, Decimal], list[date]] = defaultdict(list)
    for bill in universe.bills.values():
        by_vendor_amount[(bill.party_code, bill.total.amount)].append(bill.document_date)
    for (vendor, amount), dates in by_vendor_amount.items():
        dates.sort()
        for earlier, later in pairwise(dates):
            if (later - earlier) <= timedelta(days=14):
                problems.append(f"vendor {vendor} has two bills of {amount} within 14 days")
    by_party_day: dict[tuple[str, date, Decimal], int] = Counter()
    for payment in universe.payments.values():
        by_party_day[(payment.party_code, payment.payment_date, payment.amount.amount)] += 1
    for (party, day, amount), count in by_party_day.items():
        if count > 1:
            allowed = party == "C-0120" and amount == Decimal("1250.00")
            if not allowed:
                problems.append(f"{party} has {count} payments of {amount} on {day}")
    return problems


def check_identifiers(universe: LegacyUniverse) -> list[str]:
    problems = []
    for name, keys in (
        ("invoice", [d.number for d in universe.invoices.values()]),
        ("bill", [d.number for d in universe.bills.values()]),
        ("payment", [p.number for p in universe.payments.values()]),
        ("journal", [e.entry_number for e in universe.journals.values()]),
    ):
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        if duplicates:
            problems.append(f"duplicate {name} identifiers: {duplicates[:5]}")
    for mapping_name, mapping, attr in (
        ("invoices", universe.invoices, "number"),
        ("bills", universe.bills, "number"),
        ("payments", universe.payments, "number"),
    ):
        for key, record in mapping.items():
            if getattr(record, attr) != key:
                problems.append(f"{mapping_name} key {key} does not match record identifier")
    for key, entry in universe.journals.items():
        if entry.entry_number != key:
            problems.append(f"journal key {key} does not match entry number")
    return problems


CLEAN_BOOK_CHECKS: dict[str, Check] = {
    "entries_balance": check_entries_balance,
    "total_debits_equal_credits": check_total_debits_equal_credits,
    "line_references": check_line_references,
    "dates_and_periods": check_dates_and_periods,
    "documents": check_documents,
    "payments": check_payments,
    "subledger_postings": check_subledger_postings,
    "trial_balance": check_trial_balance,
    "agings": check_agings,
    "cash_and_bank": check_cash_and_bank,
    "mapping": check_mapping,
    "parties": check_parties,
    "no_accidental_duplicates": check_no_accidental_duplicates,
    "identifiers": check_identifiers,
}


def run_clean_book_checks(universe: LegacyUniverse) -> dict[str, list[str]]:
    return {name: check(universe) for name, check in CLEAN_BOOK_CHECKS.items()}


def verify_clean_books(universe: LegacyUniverse) -> None:
    results = run_clean_book_checks(universe)
    violations = [
        f"[{name}] {problem}" for name, problems in results.items() for problem in problems
    ]
    if violations:
        raise BooksInvariantError(violations)
