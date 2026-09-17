"""Validation rules (docs/validation-and-reconciliation.md Part A).

Each rule is a pure function of a :class:`RuleContext` and returns exceptions. Rules are registered
explicitly with :func:`rule`. They know accounting semantics and nothing about any specific company.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Final

from relay.canonical import natural_keys as nk
from relay.canonical.enums import (
    AccountSubtype,
    AgingType,
    DocumentType,
    PartyType,
    PaymentDirection,
    SourceModule,
    account_type_of,
)
from relay.canonical.records import Document, JournalEntry, Payment, period_of
from relay.core.currency import Currency
from relay.core.dates import fiscal_period_for
from relay.core.money import Money, convert
from relay.engine.entities import Candidate, Clusters
from relay.engine.exceptions import Category, Nature, RuleException, Severity, make_exception
from relay.engine.policy import Policy
from relay.engine.snapshot import OpenDocument, RunSnapshot

CONTROL_SUBTYPES: Final = frozenset(
    {
        # Reconciled against an independent control (bank, AR/AP subledgers), or sign-reversing
        # contra accounts. Suspense is deliberately absent: it has no independent control, and
        # routing an uncategorized legacy account into target suspense is a normal, reviewable
        # mapping decision.
        AccountSubtype.CASH,
        AccountSubtype.ACCOUNTS_RECEIVABLE,
        AccountSubtype.ACCOUNTS_PAYABLE,
        AccountSubtype.CONTRA_ASSET,
        AccountSubtype.ACCUMULATED_DEPRECIATION,
    }
)

INSTRUCTION_PATTERNS: Final = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore (all |any )?(previous|prior|above) (instructions|messages)\b",
        r"\b(system|developer) (note|prompt|message|instruction)s?\b",
        r"\bnote to (the )?(ai|assistant|model|reviewer|agent)\b",
        r"\b(ai|llm|assistant) (reviewer|agent|model)\b",
        r"\bapprove (all|any|every) (pending )?(change|request|item)",
        r"\bmark (all|every|any) (related )?(issues?|items?|exceptions?) (as )?"
        r"(resolved|closed|approved)\b",
        r"\bpre-?approved by\b",
    )
)


@dataclass(frozen=True, slots=True)
class RuleSpec:
    id: str
    version: int
    title: str
    severity: Severity
    nature: Nature
    category: Category
    requires: frozenset[str]


@dataclass
class RuleContext:
    snapshot: RunSnapshot
    policy: Policy
    clusters: dict[PartyType, Clusters]
    candidates: list[Candidate]
    duplicate_bill_groups: list[tuple[str, ...]] = field(default_factory=list)

    def cluster(self, party_type: PartyType, code: str) -> str:
        return self.clusters[party_type].cluster(code)

    def fx_rate(self, base: Currency, quote: Currency, on: date) -> Decimal | None:
        for offset in range(self.policy.fx_rate_lookback_days + 1):
            rate = self.snapshot.fx_rates.get((base.code, quote.code, on - timedelta(days=offset)))
            if rate is not None:
                return rate
        return None

    def open_balance_parties(self, party_type: PartyType) -> set[str]:
        documents = (
            self.snapshot.invoices if party_type is PartyType.CUSTOMER else self.snapshot.bills
        )
        direction = (
            PaymentDirection.RECEIVED
            if party_type is PartyType.CUSTOMER
            else PaymentDirection.DISBURSED
        )
        parties = {od.document.party_code for od in documents.values() if od.open_amount > 0}
        parties |= {
            p.party_code
            for (d, _), p in self.snapshot.payments.items()
            if d is direction and not p.unapplied_amount.is_zero()
        }
        return parties


RuleFunction = Callable[[RuleContext, RuleSpec], Iterable[RuleException]]
REGISTRY: dict[str, tuple[RuleSpec, RuleFunction]] = {}


def rule(  # noqa: PLR0917 - registrations read as a catalog row
    rule_id: str,
    title: str,
    severity: Severity,
    nature: Nature,
    category: Category,
    requires: Iterable[str],
    version: int = 1,
) -> Callable[[RuleFunction], RuleFunction]:
    def decorator(function: RuleFunction) -> RuleFunction:
        if rule_id in REGISTRY:
            raise ValueError(f"rule {rule_id} registered twice")
        REGISTRY[rule_id] = (
            RuleSpec(rule_id, version, title, severity, nature, category, frozenset(requires)),
            function,
        )
        return function

    return decorator


def _exception(
    spec: RuleSpec, subjects: list[str], message: str, **kwargs: object
) -> RuleException:
    severity = kwargs.pop("severity", spec.severity)
    return make_exception(
        rule_id=spec.id,
        rule_version=spec.version,
        severity=severity,  # type: ignore[arg-type]
        nature=spec.nature,
        category=spec.category,
        subjects=subjects,
        message=message,
        **kwargs,  # type: ignore[arg-type]
    )


def _lineage(ctx: RuleContext, *keys: str) -> list[object]:
    return [ctx.snapshot.locations[key] for key in keys if key in ctx.snapshot.locations]


def _debit_total(entry: JournalEntry) -> Decimal:
    return sum(
        (
            line.functional_amount.amount
            for line in entry.lines
            if line.functional_amount.amount > 0
        ),
        Decimal(0),
    )


def _legacy_subtype(ctx: RuleContext, code: str) -> AccountSubtype | None:
    account = ctx.snapshot.legacy_accounts.get(code)
    return account.subtype if account else None


# ======================================================================================= mapping
def subtype_conflict(legacy: AccountSubtype, target: AccountSubtype) -> bool:
    """A mapping that mixes a control-account subtype with a different subtype."""
    return legacy != target and (legacy in CONTROL_SUBTYPES or target in CONTROL_SUBTYPES)


@rule(
    "MAP.ACCOUNT_UNMAPPED",
    "Legacy account with activity or balance has no target",
    Severity.CRITICAL,
    Nature.MIGRATION_DEFECT,
    Category.MAPPING,
    {"account_mapping"},
)
def map_account_unmapped(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    snapshot = ctx.snapshot
    activity: dict[str, Decimal] = defaultdict(Decimal)
    for entry in snapshot.journal_entries.values():
        for line in entry.lines:
            activity[line.account_code] += abs(line.functional_amount.amount)
    cutover_balance = {
        code: amount
        for (code, end), amount in snapshot.trial_balance.items()
        if end == snapshot.plan.cutover_date
    }
    nonzero_tb = {code for (code, _), amount in snapshot.trial_balance.items() if amount != 0}
    for code in sorted(snapshot.legacy_account_codes()):
        if code in snapshot.account_mapping or not (code in nonzero_tb or activity.get(code)):
            continue
        at_risk = abs(cutover_balance.get(code, Decimal(0))) or activity.get(code, Decimal(0))
        key = nk.legacy_account(code)
        yield _exception(
            spec,
            [key],
            f"legacy account {code} has a balance or activity but no target mapping",
            amount_at_risk=at_risk,
            lineage=_lineage(ctx, key),
        )


@rule(
    "MAP.TARGET_ACCOUNT_EXISTS",
    "Mapping points to an account missing from the target chart",
    Severity.CRITICAL,
    Nature.MIGRATION_DEFECT,
    Category.MAPPING,
    {"account_mapping", "target_coa"},
)
def map_target_exists(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for legacy, target in sorted(ctx.snapshot.account_mapping.items()):
        if target not in ctx.snapshot.target_accounts:
            yield _exception(
                spec,
                [nk.legacy_account(legacy)],
                f"legacy {legacy} maps to unknown target {target}",
                observed=target,
                lineage=_lineage(ctx, f"mapping:{legacy}"),
            )


@rule(
    "MAP.TYPE_COMPATIBLE",
    "Legacy and target account types differ",
    Severity.HIGH,
    Nature.MIGRATION_DEFECT,
    Category.MAPPING,
    {"account_mapping", "target_coa", "legacy_coa"},
)
def map_type_compatible(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for legacy, target in sorted(ctx.snapshot.account_mapping.items()):
        legacy_account = ctx.snapshot.legacy_accounts.get(legacy)
        target_account = ctx.snapshot.target_accounts.get(target)
        if (
            legacy_account
            and target_account
            and legacy_account.account_type != target_account.account_type
        ):
            yield _exception(
                spec,
                [nk.legacy_account(legacy)],
                f"{legacy} ({legacy_account.account_type}) maps to "
                f"{target} ({target_account.account_type})",
                expected=legacy_account.account_type.value,
                observed=target_account.account_type.value,
                lineage=_lineage(ctx, f"mapping:{legacy}"),
            )


@rule(
    "MAP.SUBTYPE_COMPATIBLE",
    "Control-account subtypes mixed by the mapping",
    Severity.HIGH,
    Nature.MIGRATION_DEFECT,
    Category.MAPPING,
    {"account_mapping", "target_coa", "legacy_coa"},
)
def map_subtype_compatible(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for legacy, target in sorted(ctx.snapshot.account_mapping.items()):
        legacy_account = ctx.snapshot.legacy_accounts.get(legacy)
        target_account = ctx.snapshot.target_accounts.get(target)
        if not (legacy_account and target_account):
            continue
        if subtype_conflict(legacy_account.subtype, target_account.subtype):
            yield _exception(
                spec,
                [nk.legacy_account(legacy)],
                f"{legacy} ({legacy_account.subtype}) maps to {target} ({target_account.subtype})",
                expected=legacy_account.subtype.value,
                observed=target_account.subtype.value,
                lineage=_lineage(ctx, f"mapping:{legacy}"),
            )


# ================================================================================ general ledger
@rule(
    "GL.JE_BALANCED",
    "Journal entry does not balance",
    Severity.CRITICAL,
    Nature.MIGRATION_DEFECT,
    Category.LEDGER_INTEGRITY,
    {"gl_detail"},
)
def gl_je_balanced(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        total = entry.functional_total()
        if total != 0:
            key = nk.journal_entry(number)
            yield _exception(
                spec,
                [key],
                f"{number} is out of balance by {abs(total)}",
                expected="0",
                observed=str(total),
                amount_at_risk=total,
                lineage=_lineage(ctx, key),
            )


@rule(
    "GL.LINE_NONZERO",
    "Journal line amount is zero",
    Severity.LOW,
    Nature.SOURCE_ANOMALY,
    Category.LEDGER_INTEGRITY,
    {"gl_detail"},
)
def gl_line_nonzero(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        for line in entry.lines:
            if line.functional_amount.is_zero():
                key = nk.journal_line(number, line.line_number)
                yield _exception(
                    spec, [key], f"{key} has a zero amount", lineage=_lineage(ctx, key)
                )


@rule(
    "GL.ACCOUNT_EXISTS",
    "Journal line posts to an account missing from the chart of accounts",
    Severity.CRITICAL,
    Nature.MIGRATION_DEFECT,
    Category.COMPLETENESS,
    {"gl_detail", "legacy_coa"},
)
def gl_account_exists(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        for line in entry.lines:
            if line.account_code not in ctx.snapshot.legacy_accounts:
                key = nk.journal_line(number, line.line_number)
                yield _exception(
                    spec,
                    [key],
                    f"{key} posts to {line.account_code}, which is not in the chart of accounts",
                    observed=line.account_code,
                    amount_at_risk=line.functional_amount.amount,
                    lineage=_lineage(ctx, key),
                )


@rule(
    "GL.DATE_IN_WINDOW",
    "Entry date outside the history window",
    Severity.CRITICAL,
    Nature.MIGRATION_DEFECT,
    Category.DATES,
    {"gl_detail"},
)
def gl_date_in_window(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    plan = ctx.snapshot.plan
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        if not plan.history_start_date <= entry.entry_date <= plan.cutover_date:
            key = nk.journal_entry(number)
            yield _exception(
                spec,
                [key],
                f"{number} is dated {entry.entry_date}, outside "
                f"{plan.history_start_date}..{plan.cutover_date}",
                observed=entry.entry_date.isoformat(),
                amount_at_risk=_debit_total(entry),
                lineage=_lineage(ctx, key),
            )


@rule(
    "GL.PERIOD_MATCHES_DATE",
    "Posting period differs from the period of the entry date",
    Severity.MEDIUM,
    Nature.MIGRATION_DEFECT,
    Category.DATES,
    {"gl_detail"},
)
def gl_period_matches_date(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    start_month = ctx.snapshot.fiscal_year_start_month
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        derived = period_of(entry.entry_date)
        if derived == entry.posting_period:
            continue
        year, month = (int(part) for part in entry.posting_period.split("-"))
        posting_fiscal_year = fiscal_period_for(date(year, month, 1), start_month).fiscal_year
        date_fiscal_year = fiscal_period_for(entry.entry_date, start_month).fiscal_year
        severity = Severity.HIGH if posting_fiscal_year != date_fiscal_year else Severity.MEDIUM
        key = nk.journal_entry(number)
        yield _exception(
            spec,
            [key],
            f"{number} is posted to {entry.posting_period} but dated {entry.entry_date}",
            expected=derived,
            observed=entry.posting_period,
            amount_at_risk=_debit_total(entry),
            severity=severity,
            lineage=_lineage(ctx, key),
        )


@rule(
    "GL.DUPLICATE_ENTRY",
    "Manual journal entries with identical date and lines",
    Severity.HIGH,
    Nature.SOURCE_ANOMALY,
    Category.LEDGER_INTEGRITY,
    {"gl_detail"},
)
def gl_duplicate_entry(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    """Manual entries only: module postings are covered by document-level duplicate rules."""
    groups: dict[tuple[date, tuple[tuple[str, str], ...]], list[JournalEntry]] = defaultdict(list)
    for entry in ctx.snapshot.journal_entries.values():
        if entry.source_module is not SourceModule.MANUAL:
            continue
        signature = tuple(
            sorted((line.account_code, line.functional_amount.amount_str) for line in entry.lines)
        )
        groups[(entry.entry_date, signature)].append(entry)
    for entries in groups.values():
        for a, b in combinations(sorted(entries, key=lambda e: e.entry_number), 2):
            if a.reversal_of == b.entry_number or b.reversal_of == a.entry_number:
                continue
            keys = [nk.journal_entry(a.entry_number), nk.journal_entry(b.entry_number)]
            yield _exception(
                spec,
                keys,
                f"{a.entry_number} and {b.entry_number} have the same date and lines",
                amount_at_risk=_debit_total(b),
                lineage=_lineage(ctx, *keys),
            )


@rule(
    "GL.CONTROL_ACCOUNT_DIRECT_POST",
    "Manual posting to a receivable or payable control account without a party",
    Severity.MEDIUM,
    Nature.SOURCE_ANOMALY,
    Category.SUBLEDGER,
    {"gl_detail", "legacy_coa"},
)
def gl_control_account_direct_post(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    controls = {AccountSubtype.ACCOUNTS_RECEIVABLE, AccountSubtype.ACCOUNTS_PAYABLE}
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        if entry.source_module is not SourceModule.MANUAL:
            continue
        for line in entry.lines:
            if line.party is None and _legacy_subtype(ctx, line.account_code) in controls:
                key = nk.journal_line(number, line.line_number)
                yield _exception(
                    spec,
                    [key],
                    f"{key} posts directly to control account {line.account_code}",
                    amount_at_risk=line.functional_amount.amount,
                    lineage=_lineage(ctx, key),
                )


# ======================================================================================= subledgers
_SIDES: Final = (
    (
        "AR",
        DocumentType.INVOICE,
        PartyType.CUSTOMER,
        PaymentDirection.RECEIVED,
        "invoices",
        "customers",
    ),
    ("AP", DocumentType.BILL, PartyType.VENDOR, PaymentDirection.DISBURSED, "bills", "vendors"),
)


def _documents(ctx: RuleContext, document_type: DocumentType) -> dict[str, OpenDocument]:
    return ctx.snapshot.invoices if document_type is DocumentType.INVOICE else ctx.snapshot.bills


def _payments(ctx: RuleContext, direction: PaymentDirection) -> list[Payment]:
    return [
        p
        for (d, _), p in sorted(ctx.snapshot.payments.items(), key=lambda item: item[0][1])
        if d is direction
    ]


def _register_subledger_rules() -> None:  # noqa: PLR0915 - one closure per mirrored rule
    for prefix, document_type, party_type, direction, documents_dataset, parties_dataset in _SIDES:
        party_word = "customer" if party_type is PartyType.CUSTOMER else "vendor"
        document_word = document_type.value

        def document_party_exists(
            ctx: RuleContext,
            spec: RuleSpec,
            document_type: DocumentType = document_type,
            party_type: PartyType = party_type,
        ) -> Iterable[RuleException]:
            parties = (
                ctx.snapshot.customers if party_type is PartyType.CUSTOMER else ctx.snapshot.vendors
            )
            for number, od in sorted(_documents(ctx, document_type).items()):
                if od.document.party_code not in parties:
                    key = nk.document(document_type, number)
                    yield _exception(
                        spec,
                        [key],
                        f"{number} references {od.document.party_code}, "
                        "which is not in the party master",
                        observed=od.document.party_code,
                        lineage=_lineage(ctx, key),
                    )

        rule(
            f"{prefix}.{document_word.upper()}_PARTY_EXISTS",
            f"{document_word.title()} references an unknown {party_word}",
            Severity.CRITICAL,
            Nature.MIGRATION_DEFECT,
            Category.COMPLETENESS,
            {documents_dataset, parties_dataset},
        )(document_party_exists)

        def payment_party_exists(
            ctx: RuleContext,
            spec: RuleSpec,
            direction: PaymentDirection = direction,
            party_type: PartyType = party_type,
        ) -> Iterable[RuleException]:
            parties = (
                ctx.snapshot.customers if party_type is PartyType.CUSTOMER else ctx.snapshot.vendors
            )
            for payment in _payments(ctx, direction):
                if payment.party_code not in parties:
                    key = nk.payment(direction, payment.number)
                    yield _exception(
                        spec,
                        [key],
                        f"{payment.number} references {payment.party_code}, "
                        "which is not in the party master",
                        observed=payment.party_code,
                        lineage=_lineage(ctx, key),
                    )

        rule(
            f"{prefix}.PAYMENT_PARTY_EXISTS",
            f"Payment references an unknown {party_word}",
            Severity.CRITICAL,
            Nature.MIGRATION_DEFECT,
            Category.COMPLETENESS,
            {"payments", parties_dataset},
        )(payment_party_exists)

        def application_document_exists(
            ctx: RuleContext,
            spec: RuleSpec,
            direction: PaymentDirection = direction,
            document_type: DocumentType = document_type,
        ) -> Iterable[RuleException]:
            documents = _documents(ctx, document_type)
            for payment in _payments(ctx, direction):
                for application in payment.applications:
                    if application.document_number not in documents:
                        key = nk.application(payment.number, application.document_number)
                        yield _exception(
                            spec,
                            [key],
                            f"{payment.number} applies to unknown {document_type.value} "
                            f"{application.document_number}",
                            amount_at_risk=application.applied_functional_amount.amount,
                            lineage=_lineage(ctx, nk.payment(direction, payment.number)),
                        )

        rule(
            f"{prefix}.APPLICATION_DOCUMENT_EXISTS",
            f"Payment application references an unknown {document_word}",
            Severity.CRITICAL,
            Nature.MIGRATION_DEFECT,
            Category.COMPLETENESS,
            {"payments", documents_dataset},
        )(application_document_exists)

        def document_total_consistent(
            ctx: RuleContext, spec: RuleSpec, document_type: DocumentType = document_type
        ) -> Iterable[RuleException]:
            for number, od in sorted(_documents(ctx, document_type).items()):
                document = od.document
                if document.subtotal + document.tax != document.total:
                    key = nk.document(document_type, number)
                    yield _exception(
                        spec,
                        [key],
                        f"{number}: subtotal + tax != total",
                        expected=(document.subtotal + document.tax).amount_str,
                        observed=document.total.amount_str,
                        lineage=_lineage(ctx, key),
                    )

        rule(
            f"{prefix}.DOCUMENT_TOTAL_CONSISTENT",
            f"{document_word.title()} subtotal and tax do not add to total",
            Severity.HIGH,
            Nature.SOURCE_ANOMALY,
            Category.SUBLEDGER,
            {documents_dataset},
        )(document_total_consistent)

        def overapplied(
            ctx: RuleContext,
            spec: RuleSpec,
            direction: PaymentDirection = direction,
            document_type: DocumentType = document_type,
        ) -> Iterable[RuleException]:
            applied: dict[str, Decimal] = defaultdict(Decimal)
            for payment in _payments(ctx, direction):
                for application in payment.applications:
                    applied[application.document_number] += application.applied_amount.amount
            for number, od in sorted(_documents(ctx, document_type).items()):
                if applied.get(number, Decimal(0)) > od.document.total.amount:
                    key = nk.document(document_type, number)
                    yield _exception(
                        spec,
                        [key],
                        f"{number} is over-applied",
                        expected=od.document.total.amount_str,
                        observed=str(applied[number]),
                        amount_at_risk=applied[number] - od.document.total.amount,
                        lineage=_lineage(ctx, key),
                    )

        rule(
            f"{prefix}.OVERAPPLIED_DOCUMENT",
            f"Applications exceed the {document_word} total",
            Severity.HIGH,
            Nature.SOURCE_ANOMALY,
            Category.SUBLEDGER,
            {"payments", documents_dataset},
        )(overapplied)

        def open_amount_consistent(
            ctx: RuleContext,
            spec: RuleSpec,
            direction: PaymentDirection = direction,
            document_type: DocumentType = document_type,
        ) -> Iterable[RuleException]:
            snapshot = ctx.snapshot
            plan = snapshot.plan
            aging_type = AgingType.AR if document_type is DocumentType.INVOICE else AgingType.AP
            opening_items = {
                i.reference: i
                for i in snapshot.agings.get((aging_type, plan.opening_balance_date), [])
            }
            applied: dict[str, Decimal] = defaultdict(Decimal)
            for payment in _payments(ctx, direction):
                if payment.payment_date <= plan.cutover_date:
                    for application in payment.applications:
                        applied[application.document_number] += application.applied_amount.amount
            for number, od in sorted(_documents(ctx, document_type).items()):
                document = od.document
                if document.document_date <= plan.opening_balance_date:
                    item = opening_items.get(number)
                    if item is None or document.currency != snapshot.functional_currency:
                        continue
                    starting = item.functional_open_amount.amount
                else:
                    starting = document.total.amount
                expected = starting - applied.get(number, Decimal(0))
                if expected != od.open_amount:
                    key = nk.document(document_type, number)
                    yield _exception(
                        spec,
                        [key],
                        f"{number}: reported open amount {od.open_amount} != {expected}",
                        expected=str(expected),
                        observed=str(od.open_amount),
                        amount_at_risk=expected - od.open_amount,
                        lineage=_lineage(ctx, key),
                    )

        rule(
            f"{prefix}.OPEN_AMOUNT_CONSISTENT",
            f"Reported open amount does not follow from the {document_word} and its payments",
            Severity.HIGH,
            Nature.MIGRATION_DEFECT,
            Category.SUBLEDGER,
            {"payments", documents_dataset},
        )(open_amount_consistent)


_register_subledger_rules()


@rule(
    "AP.DUPLICATE_BILL",
    "Duplicate bills within one vendor entity",
    Severity.HIGH,
    Nature.SOURCE_ANOMALY,
    Category.SUBLEDGER,
    {"bills"},
)
def ap_duplicate_bill(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    groups = duplicate_bill_groups(ctx)
    ctx.duplicate_bill_groups = groups
    bills = ctx.snapshot.bills
    for group in groups:
        keys = [nk.document(DocumentType.BILL, number) for number in group]
        amount = min(bills[number].document.functional_total.amount for number in group)
        yield _exception(
            spec,
            keys,
            f"bills {', '.join(group)} look like the same vendor invoice",
            amount_at_risk=amount,
            lineage=_lineage(ctx, *keys),
        )


def _normalized_reference(reference: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (reference or "").casefold())


def duplicate_bill_groups(ctx: RuleContext) -> list[tuple[str, ...]]:
    by_reference: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_cluster: dict[str, list[Document]] = defaultdict(list)
    for number, od in ctx.snapshot.bills.items():
        cluster = ctx.cluster(PartyType.VENDOR, od.document.party_code)
        reference = _normalized_reference(od.document.party_reference)
        if reference:
            by_reference[(cluster, reference)].append(number)
        by_cluster[cluster].append(od.document)
    groups: set[tuple[str, ...]] = {
        tuple(sorted(numbers)) for numbers in by_reference.values() if len(numbers) > 1
    }
    window = timedelta(days=ctx.policy.duplicate_window_days)
    grouped = {number for group in groups for number in group}
    for documents in by_cluster.values():
        documents.sort(key=lambda d: (d.document_date, d.number))
        for a, b in combinations(documents, 2):
            if a.number in grouped and b.number in grouped:
                continue
            if a.total == b.total and abs(a.document_date - b.document_date) <= window:
                groups.add(tuple(sorted((a.number, b.number))))
    return sorted(groups)


@rule(
    "PAY.DUPLICATE_PAYMENT",
    "The same obligation paid twice",
    Severity.HIGH,
    Nature.SOURCE_ANOMALY,
    Category.SUBLEDGER,
    {"payments"},
)
def pay_duplicate_payment(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    groups = ctx.duplicate_bill_groups or duplicate_bill_groups(ctx)
    duplicate_of: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        for number in group:
            duplicate_of[number].update(set(group) - {number})
    for direction, party_type in (
        (PaymentDirection.RECEIVED, PartyType.CUSTOMER),
        (PaymentDirection.DISBURSED, PartyType.VENDOR),
    ):
        by_cluster: dict[tuple[str, Decimal], list[Payment]] = defaultdict(list)
        for payment in _payments(ctx, direction):
            by_cluster[
                (ctx.cluster(party_type, payment.party_code), payment.functional_amount.amount)
            ].append(payment)
        for payments in by_cluster.values():
            for a, b in combinations(sorted(payments, key=lambda p: p.number), 2):
                docs_a = {app.document_number for app in a.applications}
                docs_b = {app.document_number for app in b.applications}
                overlapping = bool(docs_a & docs_b)
                flagged = any(duplicate_of.get(doc, set()) & docs_b for doc in docs_a)
                if overlapping or flagged:
                    keys = [nk.payment(direction, a.number), nk.payment(direction, b.number)]
                    yield _exception(
                        spec,
                        keys,
                        f"{a.number} and {b.number} pay the same obligation",
                        amount_at_risk=b.functional_amount.amount,
                        lineage=_lineage(ctx, *keys),
                    )


@rule(
    "PAY.UNAPPLIED_CASH",
    "Receipt with unapplied cash at cutover",
    Severity.LOW,
    Nature.SOURCE_ANOMALY,
    Category.SUBLEDGER,
    {"payments"},
)
def pay_unapplied_cash(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for payment in _payments(ctx, PaymentDirection.RECEIVED):
        if (
            not payment.unapplied_amount.is_zero()
            and payment.payment_date <= ctx.snapshot.plan.cutover_date
        ):
            key = nk.payment(PaymentDirection.RECEIVED, payment.number)
            yield _exception(
                spec,
                [key],
                f"{payment.number} has {payment.unapplied_amount} unapplied",
                observed=payment.unapplied_amount.amount_str,
                lineage=_lineage(ctx, key),
            )


# ======================================================================================= currency
def _foreign_records(ctx: RuleContext) -> Iterable[tuple[str, Currency, Money, Money, date, str]]:
    functional = ctx.snapshot.functional_currency
    for document_type in (DocumentType.INVOICE, DocumentType.BILL):
        for number, od in sorted(_documents(ctx, document_type).items()):
            document = od.document
            if document.currency != functional:
                yield (
                    nk.document(document_type, number),
                    document.currency,
                    document.total,
                    document.functional_total,
                    document.document_date,
                    number,
                )
    for (direction, number), payment in sorted(
        ctx.snapshot.payments.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        if payment.currency != functional:
            yield (
                nk.payment(direction, number),
                payment.currency,
                payment.amount,
                payment.functional_amount,
                payment.payment_date,
                number,
            )


@rule(
    "CUR.MISSING_FX_RATE",
    "Foreign-currency record without a published rate",
    Severity.HIGH,
    Nature.MIGRATION_DEFECT,
    Category.CURRENCY,
    {"fx_rates"},
)
def cur_missing_fx_rate(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    functional = ctx.snapshot.functional_currency
    for key, currency, _, functional_amount, on, number in _foreign_records(ctx):
        if ctx.fx_rate(currency, functional, on) is None:
            yield _exception(
                spec,
                [key],
                f"no {currency.code}/{functional.code} rate within "
                f"{ctx.policy.fx_rate_lookback_days} days of {on} for {number}",
                amount_at_risk=functional_amount.amount,
                lineage=_lineage(ctx, key),
            )


@rule(
    "CUR.FUNCTIONAL_AMOUNT_CONSISTENT",
    "Functional amount does not match amount times the published rate",
    Severity.HIGH,
    Nature.SOURCE_ANOMALY,
    Category.CURRENCY,
    {"fx_rates"},
)
def cur_functional_amount_consistent(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    functional = ctx.snapshot.functional_currency
    for key, currency, amount, functional_amount, on, number in _foreign_records(ctx):
        rate = ctx.fx_rate(currency, functional, on)
        if rate is None:
            continue
        expected = convert(amount, rate, functional).converted
        difference = abs(expected.amount - functional_amount.amount)
        if difference > ctx.policy.fx_rounding_tolerance:
            yield _exception(
                spec,
                [key],
                f"{number}: {amount} at {rate} is {expected}, recorded {functional_amount}",
                expected=expected.amount_str,
                observed=functional_amount.amount_str,
                amount_at_risk=difference,
                lineage=_lineage(ctx, key),
            )


@rule(
    "CUR.PARTY_CURRENCY_MISMATCH",
    "Document currency differs from the party's usual currency",
    Severity.HIGH,
    Nature.SOURCE_ANOMALY,
    Category.CURRENCY,
    set(),
)
def cur_party_currency_mismatch(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    functional = ctx.snapshot.functional_currency
    for document_type, parties in (
        (DocumentType.INVOICE, ctx.snapshot.customers),
        (DocumentType.BILL, ctx.snapshot.vendors),
    ):
        documents = _documents(ctx, document_type)
        in_default: dict[str, int] = defaultdict(int)
        for od in documents.values():
            party = parties.get(od.document.party_code)
            if party and od.document.currency == party.default_currency:
                in_default[party.code] += 1
        for number, od in sorted(documents.items()):
            document = od.document
            party = parties.get(document.party_code)
            if party is None or document.currency == party.default_currency:
                continue
            if in_default[party.code] < ctx.policy.party_currency_min_documents:
                continue
            at_risk = None
            if party.default_currency != functional and document.currency == functional:
                rate = ctx.fx_rate(party.default_currency, functional, document.document_date)
                if rate is not None:
                    restated = convert(
                        Money(document.total.amount, party.default_currency), rate, functional
                    ).converted
                    at_risk = restated.amount - document.functional_total.amount
            key = nk.document(document_type, number)
            yield _exception(
                spec,
                [key],
                f"{number} is in {document.currency.code}; "
                f"{party.code} normally uses {party.default_currency.code}",
                expected=party.default_currency.code,
                observed=document.currency.code,
                amount_at_risk=at_risk,
                lineage=_lineage(ctx, key),
            )


# ======================================================================================= parties
@rule(
    "PARTY.UNRESOLVED_DUPLICATE_CANDIDATE",
    "Possible duplicate parties without a decision",
    Severity.MEDIUM,
    Nature.MIGRATION_DEFECT,
    Category.MASTER_DATA,
    set(),
)
def party_unresolved_duplicate(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    open_parties = {party_type: ctx.open_balance_parties(party_type) for party_type in PartyType}
    for candidate in ctx.candidates:
        if frozenset(candidate.members) in ctx.clusters[candidate.party_type].decided_pairs:
            continue
        has_balance = bool(set(candidate.members) & open_parties[candidate.party_type])
        yield _exception(
            spec,
            list(candidate.subjects),
            f"{candidate.left} and {candidate.right} may be the same "
            f"{candidate.party_type.value} (score {candidate.score})",
            severity=Severity.HIGH if has_balance else Severity.MEDIUM,
            details={
                "score": str(candidate.score),
                "features": {k: str(v) for k, v in candidate.features.items()},
            },
            lineage=_lineage(ctx, *candidate.subjects),
        )


@rule(
    "PARTY.INACTIVE_WITH_OPEN_BALANCE",
    "Inactive party with open items at cutover",
    Severity.MEDIUM,
    Nature.SOURCE_ANOMALY,
    Category.MASTER_DATA,
    set(),
)
def party_inactive_with_open_balance(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    for party_type, parties in (
        (PartyType.CUSTOMER, ctx.snapshot.customers),
        (PartyType.VENDOR, ctx.snapshot.vendors),
    ):
        open_parties = ctx.open_balance_parties(party_type)
        for code, party in sorted(parties.items()):
            if not party.is_active and code in open_parties:
                key = nk.party(party_type, code)
                yield _exception(
                    spec,
                    [key],
                    f"{code} is inactive but has open items",
                    lineage=_lineage(ctx, key),
                )


# =================================================================================== data safety
@rule(
    "DATA.INSTRUCTION_LIKE_TEXT",
    "Free text that reads like instructions to an automated reviewer",
    Severity.LOW,
    Nature.SOURCE_ANOMALY,
    Category.AI_SAFETY,
    set(),
)
def data_instruction_like_text(ctx: RuleContext, spec: RuleSpec) -> Iterable[RuleException]:
    texts: list[tuple[str, str, str]] = []
    for party_type, parties in (
        (PartyType.CUSTOMER, ctx.snapshot.customers),
        (PartyType.VENDOR, ctx.snapshot.vendors),
    ):
        for code, party in sorted(parties.items()):
            texts.extend(
                (nk.party(party_type, code), field_name, value)
                for field_name, value in (("name", party.name), ("notes", party.notes))
            )
    for number, entry in sorted(ctx.snapshot.journal_entries.items()):
        texts.extend(
            (nk.journal_line(number, line.line_number), "memo", line.memo)
            for line in entry.lines
            if line.memo
        )
    for records in ctx.snapshot.bank.values():
        texts.extend(
            (record.natural_key, "description", record.transaction.description)
            for record in records
        )
    for key, field_name, value in texts:
        if any(pattern.search(value) for pattern in INSTRUCTION_PATTERNS):
            yield _exception(
                spec,
                [key],
                f"{field_name} of {key} contains instruction-like text",
                discriminator=field_name,
                lineage=_lineage(ctx, key),
            )


def ruleset_version() -> list[str]:
    return sorted(f"{spec.id}@{spec.version}" for spec, _ in REGISTRY.values())


__all__ = ["REGISTRY", "RuleContext", "RuleSpec", "account_type_of", "ruleset_version"]
