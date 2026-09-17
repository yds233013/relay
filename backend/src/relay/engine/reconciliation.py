"""Reconciliations R1-R6 (docs/validation-and-reconciliation.md Part B, SC-02, SC-04).

Every amount is signed in the canonical convention (debit positive) and every difference is
``left - right``. Explainers may only explain timing items backed by matched records; anything that
indicates an error remains unexplained.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final

from relay.canonical import natural_keys as nk
from relay.canonical.enums import (
    AccountSubtype,
    AgingItemKind,
    AgingType,
    DocumentType,
    PaymentDirection,
)
from relay.canonical.records import JournalEntry
from relay.core.errors import InvalidInputError
from relay.engine.exceptions import Category, Nature, RuleException, Severity, make_exception
from relay.engine.policy import Policy
from relay.engine.snapshot import BankRecord, RunSnapshot
from relay.ingestion.csv_reader import QuarantinedRow, RawTable, reconstruct_quarantined
from relay.mapping.transforms import FieldMapping, TransformError

RECONCILIATION_VERSION: Final = 1
UNASSIGNED: Final = "unassigned"
UNMAPPED: Final = "unmapped"


class LineStatus(StrEnum):
    TIED = "tied"
    WITHIN_TOLERANCE = "within_tolerance"
    EXPLAINED = "explained"
    DISCREPANCY = "discrepancy"


@dataclass(frozen=True, slots=True)
class ReconcilingItem:
    classification: str
    amount: Decimal
    """Contribution to ``left - right``."""
    record_keys: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class ReconLine:
    grain: tuple[tuple[str, str], ...]
    left: Decimal
    right: Decimal
    explained: Decimal = Decimal(0)
    items: tuple[ReconcilingItem, ...] = ()
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def difference(self) -> Decimal:
        return self.left - self.right

    @property
    def unexplained(self) -> Decimal:
        return self.difference - self.explained

    def other_differences(self) -> bool:
        """Secondary measures (``*_difference`` in extra), e.g. R6 debit and credit totals."""
        return any(key.endswith("_difference") and value != 0 for key, value in self.extra.items())

    def status(self, tolerance: Decimal) -> LineStatus:
        if self.other_differences():
            return LineStatus.DISCREPANCY
        if self.difference == 0:
            return LineStatus.TIED
        if self.unexplained == 0:
            return LineStatus.EXPLAINED
        if abs(self.unexplained) <= tolerance:
            return LineStatus.WITHIN_TOLERANCE
        return LineStatus.DISCREPANCY


@dataclass(frozen=True, slots=True)
class ReconResult:
    recon_id: str
    title: str
    purpose: str
    left_label: str
    right_label: str
    tolerance: Decimal
    lines: tuple[ReconLine, ...]
    applicable: bool = True
    note: str = ""

    def discrepancies(self) -> list[ReconLine]:
        return [
            line for line in self.lines if line.status(self.tolerance) is LineStatus.DISCREPANCY
        ]

    @property
    def status(self) -> str:
        if not self.applicable:
            return "not_applicable"
        if self.discrepancies():
            return "discrepancy"
        if any(line.difference != 0 for line in self.lines):
            return "tied_with_explained_items"
        return "tied"


def grain_key(recon_id: str, grain: tuple[tuple[str, str], ...]) -> str:
    return f"recon:{recon_id}:" + ",".join(f"{k}={v}" for k, v in grain)


def _in_window(snapshot: RunSnapshot, value: date, until: date | None = None) -> bool:
    return snapshot.plan.history_start_date <= value <= (until or snapshot.plan.cutover_date)


def period_ends(snapshot: RunSnapshot) -> list[date]:
    return sorted(
        {end for _, end in snapshot.trial_balance if end > snapshot.plan.opening_balance_date}
    )


def _activity_to(
    snapshot: RunSnapshot, account_filter: set[str] | None, ends: list[date]
) -> dict[tuple[str, date], Decimal]:
    """Cumulative GL detail from history start to each period end, by account (entry date basis)."""
    result: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for entry in snapshot.journal_entries.values():
        if entry.entry_date < snapshot.plan.history_start_date:
            continue
        applicable = [end for end in ends if entry.entry_date <= end]
        if not applicable:
            continue
        for line in entry.lines:
            if account_filter is not None and line.account_code not in account_filter:
                continue
            for end in applicable:
                result[(line.account_code, end)] += line.functional_amount.amount
    return result


# ======================================================================================= R1
def r1_tb_vs_gl_detail(snapshot: RunSnapshot, policy: Policy) -> ReconResult:
    ends = period_ends(snapshot)
    applicable = bool(snapshot.trial_balance) and "gl_detail" in snapshot.datasets_present
    detail = _activity_to(snapshot, None, ends)
    opening = snapshot.plan.opening_balance_date
    accounts = sorted({code for code, _ in snapshot.trial_balance} | {code for code, _ in detail})
    lines = []
    for account in accounts:
        for end in ends:
            left = snapshot.trial_balance.get((account, end), Decimal(0))
            right = snapshot.trial_balance.get((account, opening), Decimal(0)) + detail.get(
                (account, end), Decimal(0)
            )
            lines.append(
                ReconLine((("account", account), ("period_end", end.isoformat())), left, right)
            )
    return ReconResult(
        "R1",
        "Trial balance control vs GL detail",
        "completeness",
        "Control trial balance",
        "Opening balance + GL detail (entry date)",
        policy.reconciliation_tolerance,
        tuple(lines),
        applicable,
    )


# ======================================================================================= R2
def r2_legacy_vs_staged(snapshot: RunSnapshot, policy: Policy) -> ReconResult:
    ends = period_ends(snapshot)
    mapping = snapshot.account_mapping
    opening = snapshot.plan.opening_balance_date
    applicable = bool(snapshot.trial_balance) and bool(mapping)
    left: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    right: dict[tuple[str, date], Decimal] = defaultdict(Decimal)
    for (account, end), balance in snapshot.trial_balance.items():
        if end == opening:
            continue
        left[(mapping.get(account, UNMAPPED), end)] += balance
        if account in mapping:
            right[(mapping[account], end)] += snapshot.trial_balance.get(
                (account, opening), Decimal(0)
            )
    for (account, end), amount in _activity_to(snapshot, set(mapping), ends).items():
        right[(mapping[account], end)] += amount
    lines = [
        ReconLine(
            (("target_account", target), ("period_end", end.isoformat())),
            left.get((target, end), Decimal(0)),
            right.get((target, end), Decimal(0)),
        )
        for target, end in sorted(set(left) | set(right))
    ]
    return ReconResult(
        "R2",
        "Legacy balances through the mapping vs staged balances",
        "fidelity",
        "Control trial balance mapped to target accounts",
        "Staged opening + mapped GL detail",
        policy.reconciliation_tolerance,
        tuple(lines),
        applicable,
    )


# ======================================================================================= R3 / R4
@dataclass(frozen=True, slots=True)
class _SubledgerSide:
    recon: str
    aging_type: AgingType
    document_type: DocumentType
    direction: PaymentDirection
    subtype: AccountSubtype
    sign: int


_AR = _SubledgerSide(
    "R3",
    AgingType.AR,
    DocumentType.INVOICE,
    PaymentDirection.RECEIVED,
    AccountSubtype.ACCOUNTS_RECEIVABLE,
    1,
)
_AP = _SubledgerSide(
    "R4",
    AgingType.AP,
    DocumentType.BILL,
    PaymentDirection.DISBURSED,
    AccountSubtype.ACCOUNTS_PAYABLE,
    -1,
)


def _open_items(
    snapshot: RunSnapshot, side: _SubledgerSide
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """Staged open items at cutover in the ledger sign: by party and by document."""
    documents = snapshot.invoices if side.document_type is DocumentType.INVOICE else snapshot.bills
    by_party: dict[str, Decimal] = defaultdict(Decimal)
    by_document: dict[str, Decimal] = {}
    for number, od in documents.items():
        if od.open_amount == 0:
            continue
        document = od.document
        if od.open_amount == document.total.amount:
            functional = document.functional_total.amount
        else:
            functional = (od.open_amount * document.fx_rate).quantize(Decimal("0.01"))
        value = side.sign * functional
        by_party[document.party_code] += value
        by_document[number] = value
    for (direction, _), payment in snapshot.payments.items():
        if direction is side.direction and not payment.unapplied_amount.is_zero():
            unapplied = (payment.unapplied_amount.amount * payment.fx_rate).quantize(
                Decimal("0.01")
            )
            by_party[payment.party_code] -= side.sign * unapplied
    return by_party, by_document


def _subledger(snapshot: RunSnapshot, policy: Policy, side: _SubledgerSide) -> list[ReconResult]:
    plan = snapshot.plan
    mapped_legacy = {
        legacy
        for legacy, target in snapshot.account_mapping.items()
        if (account := snapshot.target_accounts.get(target)) is not None
        and account.subtype is side.subtype
    }
    opening_items = snapshot.agings.get((side.aging_type, plan.opening_balance_date))
    cutover_items = snapshot.agings.get((side.aging_type, plan.cutover_date))
    documents_present = (
        "invoices" if side.document_type is DocumentType.INVOICE else "bills"
    ) in snapshot.datasets_present
    applicable = bool(mapped_legacy) and opening_items is not None and documents_present

    left: dict[str, Decimal] = defaultdict(Decimal)
    opening_total = Decimal(0)
    for item in opening_items or []:
        value = side.sign * (
            item.functional_open_amount.amount
            if item.kind is AgingItemKind.DOCUMENT
            else -item.functional_open_amount.amount
        )
        left[item.party_code] += value
        opening_total += value
    opening_tb = sum(
        (
            snapshot.trial_balance.get((code, plan.opening_balance_date), Decimal(0))
            for code in mapped_legacy
        ),
        Decimal(0),
    )
    left[UNASSIGNED] += opening_tb - opening_total
    for entry in snapshot.journal_entries.values():
        if not _in_window(snapshot, entry.entry_date):
            continue
        for line in entry.lines:
            if line.account_code in mapped_legacy:
                left[line.party.code if line.party else UNASSIGNED] += line.functional_amount.amount
    right, by_document = _open_items(snapshot, side)
    party_lines = tuple(
        ReconLine((("party", party),), left.get(party, Decimal(0)), right.get(party, Decimal(0)))
        for party in sorted(set(left) | set(right))
    )
    main = ReconResult(
        side.recon,
        f"{'AR' if side is _AR else 'AP'} subledger vs GL control accounts",
        "fidelity",
        "Opening aging + GL control-account activity",
        "Staged open items at cutover",
        policy.reconciliation_tolerance,
        party_lines,
        applicable,
    )

    aging_documents: dict[str, Decimal] = {}
    for item in cutover_items or []:
        if item.kind is AgingItemKind.DOCUMENT:
            aging_documents[item.reference] = side.sign * item.functional_open_amount.amount
    document_lines = tuple(
        ReconLine(
            (("document", number),),
            aging_documents.get(number, Decimal(0)),
            by_document.get(number, Decimal(0)),
        )
        for number in sorted(set(aging_documents) | set(by_document))
    )
    companion = ReconResult(
        f"{side.recon}b",
        "Control aging vs staged open items",
        "completeness",
        "Control aging at cutover",
        "Staged open items",
        policy.reconciliation_tolerance,
        document_lines,
        cutover_items is not None and documents_present,
    )

    legacy_control = {
        code
        for code, account in snapshot.legacy_accounts.items()
        if account.subtype is side.subtype
    }
    opening_control = sum(
        (
            snapshot.trial_balance.get((code, plan.opening_balance_date), Decimal(0))
            for code in legacy_control
        ),
        Decimal(0),
    )
    opening_line = ReconLine(
        (("as_of", plan.opening_balance_date.isoformat()),), opening_control, opening_total
    )
    opening = ReconResult(
        f"{side.recon}o",
        "Opening aging vs opening trial balance",
        "completeness",
        "Opening trial balance (control accounts)",
        "Opening aging total",
        policy.reconciliation_tolerance,
        (opening_line,),
        opening_items is not None and bool(legacy_control),
    )
    return [main, companion, opening]


# ======================================================================================= R5
@dataclass(frozen=True, slots=True)
class _CashMovement:
    entry_number: str
    entry_date: date
    amount: Decimal
    references: frozenset[str]


def _cash_movements(snapshot: RunSnapshot, gl_account: str) -> list[_CashMovement]:
    payment_references = {
        number: payment.reference
        for (_, number), payment in snapshot.payments.items()
        if payment.reference
    }
    movements = []
    for number, entry in sorted(snapshot.journal_entries.items()):
        if not _in_window(snapshot, entry.entry_date):
            continue
        amount = sum(
            (ln.functional_amount.amount for ln in entry.lines if ln.account_code == gl_account),
            Decimal(0),
        )
        if amount == 0:
            continue
        references = {
            payment_references[ln.document_number]
            for ln in entry.lines
            if ln.document_number in payment_references
        }
        movements.append(
            _CashMovement(number, entry.entry_date, amount, frozenset(r for r in references if r))
        )
    return movements


def _match(
    movement: _CashMovement,
    candidates: list[BankRecord],
    used: set[str],
    earliest: date,
    latest: date,
) -> BankRecord | None:
    best: tuple[int, int, str] | None = None
    chosen: BankRecord | None = None
    for record in candidates:
        if record.natural_key in used or record.transaction.amount.amount != movement.amount:
            continue
        posted = record.transaction.posted_date
        if not earliest <= posted <= latest:
            continue
        reference_rank = (
            0
            if record.transaction.reference and record.transaction.reference in movement.references
            else 1
        )
        rank = (reference_rank, abs((posted - movement.entry_date).days), record.natural_key)
        if best is None or rank < best:
            best, chosen = rank, record
    return chosen


def r5_cash_vs_bank(
    snapshot: RunSnapshot, policy: Policy
) -> tuple[list[ReconResult], list[RuleException]]:
    plan = snapshot.plan
    results: list[ReconResult] = []
    exceptions: list[RuleException] = []
    for link in snapshot.bank_links:
        records = snapshot.bank.get(link.bank_account)
        if records is None or not snapshot.trial_balance:
            results.append(
                ReconResult(
                    "R5",
                    "GL cash vs bank statement",
                    "completeness",
                    "GL cash",
                    "Bank statement",
                    policy.cash_unexplained_tolerance,
                    (),
                    applicable=False,
                )
            )
            continue
        gl_balance = snapshot.trial_balance.get(
            (link.gl_account, plan.opening_balance_date), Decimal(0)
        )
        movements = _cash_movements(snapshot, link.gl_account)
        gl_balance += sum((m.amount for m in movements), Decimal(0))
        through = [r for r in records if r.transaction.posted_date <= plan.cutover_date]
        after = [r for r in records if r.transaction.posted_date > plan.cutover_date]
        bank_balance = next(
            (r.running_balance for r in reversed(through) if r.running_balance is not None), None
        )
        if bank_balance is None:
            bank_balance = sum((r.transaction.amount.amount for r in through), Decimal(0))
        by_amount: dict[Decimal, list[BankRecord]] = defaultdict(list)
        for record in through:
            by_amount[record.transaction.amount.amount].append(record)
        after_by_amount: dict[Decimal, list[BankRecord]] = defaultdict(list)
        for record in after:
            after_by_amount[record.transaction.amount.amount].append(record)
        used: set[str] = set()
        unmatched: list[_CashMovement] = []
        # Reference-bearing movements first, so a reference match is never taken by a lookalike.
        for movement in sorted(
            movements, key=lambda m: (not m.references, m.entry_date, m.entry_number)
        ):
            match = _match(
                movement,
                by_amount[movement.amount],
                used,
                movement.entry_date - timedelta(days=policy.bank_match_days_before),
                movement.entry_date + timedelta(days=policy.bank_match_days_after),
            )
            if match is None:
                unmatched.append(movement)
            else:
                used.add(match.natural_key)
        items: list[ReconcilingItem] = []
        window_end = plan.cutover_date + timedelta(days=plan.bank_clearing_window_days)
        for movement in unmatched:
            clearing = _match(
                movement,
                after_by_amount[movement.amount],
                used,
                plan.cutover_date + timedelta(days=1),
                window_end,
            )
            if clearing is None:
                continue
            used.add(clearing.natural_key)
            classification = "outstanding_check" if movement.amount < 0 else "deposit_in_transit"
            items.append(
                ReconcilingItem(
                    classification,
                    movement.amount,
                    (nk.journal_entry(movement.entry_number), clearing.natural_key),
                    f"{movement.entry_number} clears the bank on "
                    f"{clearing.transaction.posted_date}",
                )
            )
        for record in through:
            if record.natural_key in used:
                continue
            items.append(
                ReconcilingItem(
                    "bank_only_activity",
                    -record.transaction.amount.amount,
                    (record.natural_key,),
                    f"bank activity on {record.transaction.posted_date} has no ledger counterpart",
                )
            )
            exceptions.append(
                make_exception(
                    rule_id="BANK.UNRECORDED_ACTIVITY",
                    rule_version=RECONCILIATION_VERSION,
                    severity=Severity.MEDIUM,
                    nature=Nature.SOURCE_ANOMALY,
                    category=Category.CASH,
                    subjects=[record.natural_key],
                    message=(
                        f"{record.transaction.description} {record.transaction.amount} on "
                        f"{record.transaction.posted_date} is not recorded in the ledger"
                    ),
                    amount_at_risk=record.transaction.amount.amount,
                    lineage=[record.location],
                    details={
                        "posted_date": record.transaction.posted_date.isoformat(),
                        "amount": record.transaction.amount.amount_str,
                        "description": record.transaction.description,
                    },
                )
            )
        explained = sum((item.amount for item in items), Decimal(0))
        line = ReconLine(
            (("bank_account", link.bank_account),),
            gl_balance,
            bank_balance,
            explained,
            tuple(items),
            {
                "unmatched_ledger_movements": len(unmatched)
                - sum(1 for i in items if i.classification != "bank_only_activity")
            },
        )
        results.append(
            ReconResult(
                "R5",
                "GL cash vs bank statement",
                "completeness",
                f"GL {link.gl_account}",
                f"Bank account {link.bank_account}",
                policy.cash_unexplained_tolerance,
                (line,),
            )
        )
    return results, exceptions


# ======================================================================================= R6
def _reconstruct_amount(
    table: RawTable, row: QuarantinedRow, fields: dict[str, FieldMapping], delimiter: str
) -> tuple[str, Decimal] | None:
    """Period and signed amount of a quarantined GL record, or None when it cannot be read."""
    record = reconstruct_quarantined(table, row, delimiter=delimiter)
    if record is None or "posting_period" not in fields or "functional_amount" not in fields:
        return None
    try:
        period = fields["posting_period"].apply(record)
        amount = fields["functional_amount"].apply(record)
    except (TransformError, InvalidInputError):
        return None
    if not isinstance(period, str) or not isinstance(amount, Decimal):
        return None
    return period, amount


def r6_activity_totals(snapshot: RunSnapshot) -> ReconResult:
    """Source GL rows (quarantined records reconstructed provisionally) vs staged lines, by period.

    Both sides use the posting period as exported, so approved period overrides do not create R6
    differences.
    """
    zero = (0, Decimal(0), Decimal(0))
    staged: dict[str, tuple[int, Decimal, Decimal]] = defaultdict(lambda: zero)
    for number, entry in snapshot.journal_entries.items():
        period = snapshot.source_posting_periods.get(number, entry.posting_period)
        count, debits, credit_total = staged[period]
        for line in entry.lines:
            amount = line.functional_amount.amount
            count, debits, credit_total = (
                count + 1,
                debits + max(amount, Decimal(0)),
                credit_total + max(-amount, Decimal(0)),
            )
        staged[period] = (count, debits, credit_total)
    source = dict(staged)
    unreconstructable = 0
    for file_name in snapshot.quarantined_files("gl_detail"):
        table = snapshot.raw_tables[file_name]
        mapping = snapshot.dataset_mappings[file_name]
        fields = {f.target: f for f in mapping.fields}
        for spec, row in snapshot.quarantined[file_name]:
            reconstructed = _reconstruct_amount(table, row, fields, spec.delimiter)
            if reconstructed is None:
                unreconstructable += 1
                continue
            period, amount = reconstructed
            count, debits, credit_total = source.get(period, zero)
            source[period] = (
                count + 1,
                debits + max(amount, Decimal(0)),
                credit_total + max(-amount, Decimal(0)),
            )
    lines = []
    for period in sorted(set(source) | set(staged)):
        s_count, s_debits, s_credits = source.get(period, zero)
        t_count, t_debits, t_credits = staged.get(period, zero)
        count_difference = s_count - t_count
        lines.append(
            ReconLine(
                (("period", period),),
                Decimal(s_count),
                Decimal(t_count),
                extra={
                    "count_difference": count_difference,
                    "debit_difference": s_debits - t_debits,
                    "credit_difference": s_credits - t_credits,
                },
            )
        )
    return ReconResult(
        "R6",
        "Source GL rows vs staged journal lines",
        "completeness",
        "Source rows (incl. quarantined)",
        "Staged lines",
        Decimal(0),
        tuple(lines),
        "gl_detail" in snapshot.datasets_present,
        note=f"{unreconstructable} quarantined records could not be reconstructed"
        if unreconstructable
        else "",
    )


# ======================================================================================= run all
RECONCILIATIONS: Final = ("R1", "R2", "R3", "R3b", "R3o", "R4", "R4b", "R4o", "R5", "R6")


def reconcile(
    snapshot: RunSnapshot, policy: Policy
) -> tuple[list[ReconResult], list[RuleException]]:
    results = [r1_tb_vs_gl_detail(snapshot, policy), r2_legacy_vs_staged(snapshot, policy)]
    results += _subledger(snapshot, policy, _AR)
    results += _subledger(snapshot, policy, _AP)
    cash_results, exceptions = r5_cash_vs_bank(snapshot, policy)
    results += cash_results
    results.append(r6_activity_totals(snapshot))
    results = [_with_hints(snapshot, result) for result in results]
    for result in results:
        if not result.applicable:
            continue
        severity = Severity.HIGH if result.recon_id == "R6" else Severity.CRITICAL
        for line in result.discrepancies():
            key = grain_key(result.recon_id, line.grain)
            exceptions.append(
                make_exception(
                    rule_id=f"RECON.{result.recon_id}",
                    rule_version=RECONCILIATION_VERSION,
                    severity=severity,
                    nature=Nature.MIGRATION_DEFECT,
                    category=Category.COMPLETENESS
                    if result.purpose == "completeness"
                    else Category.SUBLEDGER,
                    subjects=[key],
                    message=f"{result.title}: {dict(line.grain)} differs by {line.unexplained}",
                    expected=str(line.right),
                    observed=str(line.left),
                    amount_at_risk=line.unexplained
                    if result.recon_id != "R6"
                    else _r6_amount(line),
                    details={
                        "recon_id": result.recon_id,
                        "grain": dict(line.grain),
                        **{k: str(v) for k, v in line.extra.items()},
                    },
                )
            )
    return results, exceptions


def _r6_amount(line: ReconLine) -> Decimal:
    debit, credit = line.extra["debit_difference"], line.extra["credit_difference"]
    if not isinstance(debit, Decimal) or not isinstance(credit, Decimal):
        raise TypeError("R6 lines carry decimal differences")
    return max(abs(debit), abs(credit))


def reconciliation_set_version() -> list[str]:
    return [f"{recon}@{RECONCILIATION_VERSION}" for recon in RECONCILIATIONS]


def drilldown(snapshot: RunSnapshot, recon_id: str, grain: dict[str, str]) -> dict[str, object]:
    """Contributors on each side of a reconciliation line, with source lineage where available."""
    locations = snapshot.locations

    def located(key: str) -> dict[str, object]:
        location = locations.get(key)
        return (
            {
                "record": key,
                "file": location.file_name,
                "line_start": location.line_start,
                "line_end": location.line_end,
            }
            if location
            else {"record": key}
        )

    if recon_id in {"R1", "R2"}:
        end = date.fromisoformat(grain["period_end"])
        accounts = (
            {grain["account"]}
            if recon_id == "R1"
            else (
                {
                    legacy
                    for legacy, target in snapshot.account_mapping.items()
                    if target == grain["target_account"]
                }
                if grain["target_account"] != UNMAPPED
                else {c for c, _ in snapshot.trial_balance if c not in snapshot.account_mapping}
            )
        )
        detail = []
        for number, entry in sorted(snapshot.journal_entries.items()):
            if not (_dated_through(snapshot, entry, end) or _posted_through(snapshot, entry, end)):
                continue
            for line in entry.lines:
                if line.account_code in accounts:
                    key = nk.journal_line(number, line.line_number)
                    detail.append(
                        {
                            **located(key),
                            "account": line.account_code,
                            "entry_date": entry.entry_date.isoformat(),
                            "posting_period": entry.posting_period,
                            "amount": line.functional_amount.amount_str,
                            "in_right_side": _dated_through(snapshot, entry, end),
                        }
                    )
        controls = [
            {
                **located(nk.trial_balance(code, end.isoformat())),
                "account": code,
                "balance": str(snapshot.trial_balance.get((code, end), Decimal(0))),
            }
            for code in sorted(accounts)
        ]
        quarantined = [
            {
                "file": file_name,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "raw_text": row.raw_text,
            }
            for file_name, rows in snapshot.quarantined.items()
            for _, row in rows
        ]
        return {
            "left": controls,
            "right": detail,
            "quarantined": quarantined,
            "limits": (
                "The control side is an aggregate report, so record-level matching is not "
                "possible. Detail lines counted by posting period but not by entry date are marked."
            ),
        }
    if recon_id in {"R3", "R4", "R3b", "R4b"}:
        side = _AR if recon_id.startswith("R3") else _AP
        documents = snapshot.invoices if side is _AR else snapshot.bills
        target_party = grain.get("party")
        document_filter = grain.get("document")
        mapped_legacy = {
            legacy
            for legacy, t in snapshot.account_mapping.items()
            if (a := snapshot.target_accounts.get(t)) and a.subtype is side.subtype
        }
        gl = []
        for number, entry in sorted(snapshot.journal_entries.items()):
            for line in entry.lines:
                if line.account_code not in mapped_legacy:
                    continue
                party = line.party.code if line.party else UNASSIGNED
                if (target_party and party != target_party) or (
                    document_filter and line.document_number != document_filter
                ):
                    continue
                key = nk.journal_line(number, line.line_number)
                gl.append(
                    {
                        **located(key),
                        "account": line.account_code,
                        "entry_date": entry.entry_date.isoformat(),
                        "document": line.document_number,
                        "amount": line.functional_amount.amount_str,
                        "in_window": _in_window(snapshot, entry.entry_date),
                    }
                )
        items = [
            {
                **located(nk.document(side.document_type, number)),
                "document": number,
                "open_amount": str(od.open_amount),
            }
            for number, od in sorted(documents.items())
            if od.open_amount != 0
            and (not target_party or od.document.party_code == target_party)
            and (not document_filter or number == document_filter)
        ]
        aging = [
            {
                **located(nk.aging_item(side.aging_type, i.as_of, i.reference)),
                "as_of": i.as_of.isoformat(),
                "reference": i.reference,
                "open_amount": i.functional_open_amount.amount_str,
                "kind": i.kind.value,
            }
            for (aging_type, _), agings in snapshot.agings.items()
            if aging_type is side.aging_type
            for i in agings
            if (not target_party or i.party_code == target_party)
            and (not document_filter or i.reference == document_filter)
        ]
        gl_documents = {str(row["document"]) for row in gl if row["document"]}
        item_documents = {str(row["document"]) for row in items}
        aging_references = {str(row["reference"]) for row in aging}
        return {
            "ledger": gl,
            "open_items": items,
            "aging": aging,
            "ledger_documents_without_open_item": sorted(
                (gl_documents - item_documents) & aging_references
            ),
            "limits": "Opening balances by party come from the opening aging report.",
        }
    return {"limits": f"no drill-down for {recon_id}"}


def _dated_through(snapshot: RunSnapshot, entry: JournalEntry, end: date) -> bool:
    return snapshot.plan.history_start_date <= entry.entry_date <= end


def _posted_through(snapshot: RunSnapshot, entry: JournalEntry, end: date) -> bool:
    start = snapshot.plan.history_start_date
    first, last = f"{start.year:04d}-{start.month:02d}", f"{end.year:04d}-{end.month:02d}"
    return first <= entry.posting_period <= last


# ======================================================================================= hints
def _with_hints(snapshot: RunSnapshot, result: ReconResult) -> ReconResult:
    """Attach documented hint items. Hints never change ``explained``: no line passes by a hint."""
    if result.recon_id not in {"R2", "R3", "R4"} or not result.applicable:
        return result
    lines = []
    for line in result.lines:
        hints = (
            _hints(snapshot, result.recon_id, line)
            if line.status(result.tolerance) is LineStatus.DISCREPANCY
            else []
        )
        lines.append(replace(line, items=(*line.items, *hints)) if hints else line)
    return replace(result, lines=tuple(lines))


def _hints(snapshot: RunSnapshot, recon_id: str, line: ReconLine) -> list[ReconcilingItem]:
    grain = dict(line.grain)
    if recon_id == "R2" and grain.get("target_account") == UNMAPPED:
        end = date.fromisoformat(grain["period_end"])
        return [
            ReconcilingItem(
                "unmapped_source_account",
                balance,
                (nk.legacy_account(code),),
                f"legacy account {code} has no target account mapping",
            )
            for (code, period_end), balance in sorted(snapshot.trial_balance.items())
            if period_end == end and code not in snapshot.account_mapping and balance != 0
        ]
    if recon_id not in {"R3", "R4"}:
        return []
    side = _AR if recon_id == "R3" else _AP
    hints = []
    for legacy, target in sorted(snapshot.account_mapping.items()):
        account = snapshot.target_accounts.get(target)
        if account is None or account.subtype is not side.subtype:
            continue
        balance = snapshot.trial_balance.get((legacy, snapshot.plan.cutover_date))
        if balance and balance == line.unexplained:
            hints.append(
                ReconcilingItem(
                    "single_account_contribution",
                    balance,
                    (nk.legacy_account(legacy),),
                    f"the difference equals the balance of legacy account {legacy}",
                )
            )
    return hints


__all__ = [
    "ReconLine",
    "ReconResult",
    "drilldown",
    "grain_key",
    "reconcile",
    "reconciliation_set_version",
]
