"""Normalization: source files + column mapping set + overlays → a RunSnapshot.

Every canonical record keeps its source location. Rows that cannot be normalized produce ``NORM.*``
exceptions instead of being dropped silently.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from relay.canonical import natural_keys as nk
from relay.canonical.enums import (
    AccountSubtype,
    AgingItemKind,
    AgingType,
    DocumentType,
    PartyType,
    PaymentDirection,
    PaymentMethod,
    SourceModule,
)
from relay.canonical.lineage import SourceLocation
from relay.canonical.records import (
    Account,
    AgingItem,
    BankTransaction,
    Document,
    JournalEntry,
    JournalLine,
    Party,
    PartyKey,
    Payment,
    PaymentApplication,
)
from relay.core.currency import Currency
from relay.core.dates import parse_iso_business_date
from relay.core.errors import InvalidInputError
from relay.core.money import Money
from relay.engine.exceptions import Category, Nature, RuleException, Severity, make_exception
from relay.engine.inputs import BankAccountLink, ConversionPlan, DatasetSpec, MigrationInputs
from relay.engine.overlays import Overlays
from relay.ingestion.csv_reader import (
    QuarantinedRow,
    RawTable,
    SourceFileError,
    read_csv,
    repair_quarantined,
)
from relay.mapping.transforms import DatasetMapping, MappingConfigError, TransformError

NORM_VERSION = 1


@dataclass(frozen=True, slots=True)
class BankRecord:
    transaction: BankTransaction
    running_balance: Decimal | None
    natural_key: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class OpenDocument:
    document: Document
    open_amount: Decimal
    """Open amount at the cutover date, in the document currency (as reported by the source)."""


@dataclass
class RunSnapshot:
    plan: ConversionPlan
    functional_currency: Currency
    fiscal_year_start_month: int
    datasets_present: set[str] = field(default_factory=set)
    legacy_accounts: dict[str, Account] = field(default_factory=dict)
    target_accounts: dict[str, Account] = field(default_factory=dict)
    account_mapping: dict[str, str] = field(default_factory=dict)
    trial_balance: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    journal_entries: dict[str, JournalEntry] = field(default_factory=dict)
    customers: dict[str, Party] = field(default_factory=dict)
    vendors: dict[str, Party] = field(default_factory=dict)
    invoices: dict[str, OpenDocument] = field(default_factory=dict)
    bills: dict[str, OpenDocument] = field(default_factory=dict)
    payments: dict[tuple[PaymentDirection, str], Payment] = field(default_factory=dict)
    agings: dict[tuple[AgingType, date], list[AgingItem]] = field(default_factory=dict)
    bank: dict[str, list[BankRecord]] = field(default_factory=dict)
    bank_links: tuple[BankAccountLink, ...] = ()
    fx_rates: dict[tuple[str, str, date], Decimal] = field(default_factory=dict)
    raw_tables: dict[str, RawTable] = field(default_factory=dict)
    quarantined: dict[str, list[tuple[DatasetSpec, QuarantinedRow]]] = field(default_factory=dict)
    locations: dict[str, SourceLocation] = field(default_factory=dict)
    dataset_mappings: dict[str, DatasetMapping] = field(default_factory=dict)
    source_posting_periods: dict[str, str] = field(default_factory=dict)
    """Posting period as exported, for entries whose period an approved override changed."""
    exceptions: list[RuleException] = field(default_factory=list)
    applied_overrides: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ helpers
    def party(self, key: PartyKey) -> Party | None:
        return (self.customers if key.party_type is PartyType.CUSTOMER else self.vendors).get(
            key.code
        )

    def gl_file(self) -> str | None:
        return next(iter(self.quarantined_files("gl_detail")), None)

    def quarantined_files(self, dataset_type: str) -> list[str]:
        return [
            f
            for f, items in self.quarantined.items()
            if items and items[0][0].dataset_type == dataset_type
        ]

    def mapped_target(self, legacy_code: str) -> str | None:
        return self.account_mapping.get(legacy_code)

    def legacy_account_codes(self) -> set[str]:
        codes = set(self.legacy_accounts) | {code for code, _ in self.trial_balance}
        for entry in self.journal_entries.values():
            codes.update(line.account_code for line in entry.lines)
        return codes


class _Normalizer:
    def __init__(self, inputs: MigrationInputs, overlays: Overlays) -> None:
        self.inputs = inputs
        self.overlays = overlays
        self.snapshot = RunSnapshot(
            plan=inputs.plan,
            functional_currency=inputs.functional_currency,
            fiscal_year_start_month=inputs.fiscal_year_start_month,
            bank_links=inputs.bank_links,
        )
        self.mapping_configs: dict[str, Any] = dict(inputs.mapping_set.get("datasets", {}))

    # ------------------------------------------------------------------ exceptions
    def _norm(  # noqa: PLR0917 - one call per normalization finding
        self,
        rule: str,
        severity: Severity,
        spec: DatasetSpec,
        subject: str,
        message: str,
        location: SourceLocation | None,
        discriminator: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.snapshot.exceptions.append(
            make_exception(
                rule_id=rule,
                rule_version=NORM_VERSION,
                severity=severity,
                nature=Nature.MIGRATION_DEFECT,
                category=Category.COMPLETENESS,
                subjects=[subject],
                message=message,
                discriminator=discriminator,
                details={"dataset_type": spec.dataset_type, "file": spec.file, **(details or {})},
                lineage=[location] if location else [],
            )
        )

    # ------------------------------------------------------------------ staging
    def stage(self, spec: DatasetSpec) -> list[tuple[dict[str, Any], SourceLocation]]:
        config = self.mapping_configs.get(spec.file)
        if config is None:
            raise MappingConfigError(f"no column mapping for {spec.file}")
        if config.get("dataset_type") != spec.dataset_type:
            raise MappingConfigError(f"column mapping for {spec.file} is for another dataset type")
        try:
            table = read_csv(
                spec.file,
                self.inputs.files[spec.file],
                encoding=spec.encoding,
                delimiter=spec.delimiter,
            )
        except SourceFileError as exc:
            self._norm(
                "NORM.UNREADABLE_FILE",
                Severity.CRITICAL,
                spec,
                f"file:{spec.file}",
                exc.detail,
                None,
            )
            return []
        mapping = DatasetMapping.parse(spec.dataset_type, config, table.header)
        self.snapshot.raw_tables[spec.file] = table
        self.snapshot.dataset_mappings[spec.file] = mapping
        self.snapshot.datasets_present.add(spec.dataset_type)
        quarantined = list(table.quarantined)
        repairs = {
            r.quarantine_key: r for r in self.overlays.quarantine_repairs if r.file == spec.file
        }
        repaired_rows: list[tuple[dict[str, str], SourceLocation]] = []
        remaining: list[tuple[DatasetSpec, QuarantinedRow]] = []
        for row in quarantined:
            repair = repairs.pop(row.key, None)
            location = SourceLocation(
                dataset=spec.dataset_type,
                file_name=spec.file,
                row_number=1,
                line_start=row.line_start,
                line_end=row.line_end,
            )
            if repair is not None:
                repaired_rows.append(
                    (
                        repair_quarantined(
                            table, repair.replacement_text, delimiter=spec.delimiter
                        ),
                        location,
                    )
                )
                self.snapshot.applied_overrides.append(repair.id)
                continue
            remaining.append((spec, row))
            self._norm(
                "NORM.MALFORMED_ROW",
                Severity.CRITICAL,
                spec,
                f"quarantine:{spec.dataset_type}:{row.key}",
                f"{spec.file} lines {row.line_start}-{row.line_end} could not be parsed "
                f"({row.reason})",
                location,
                details={
                    "line_start": row.line_start,
                    "line_end": row.line_end,
                    "raw_text": row.raw_text,
                    "reason": row.reason,
                },
            )
        for repair in repairs.values():
            self._norm(
                "OVERRIDE.STALE",
                Severity.HIGH,
                spec,
                f"override:{repair.id}",
                f"quarantine repair {repair.id} no longer matches a quarantined record",
                None,
            )
        self.snapshot.quarantined[spec.file] = remaining

        staged: list[tuple[dict[str, Any], SourceLocation]] = []
        sources = [
            (
                r.values,
                SourceLocation(
                    dataset=spec.dataset_type,
                    file_name=spec.file,
                    row_number=r.row_number,
                    line_start=r.line_start,
                    line_end=r.line_end,
                ),
            )
            for r in table.rows
        ]
        for values, location in [*sources, *repaired_rows]:
            if mapping.excludes(values):
                continue
            record: dict[str, Any] = {}
            ok = True
            for field_mapping in mapping.fields:
                try:
                    value = field_mapping.apply(values)
                except (TransformError, InvalidInputError) as exc:
                    ok = False
                    self._norm(
                        "NORM.PARSE_FAILURE",
                        Severity.HIGH,
                        spec,
                        f"row:{spec.file}:{location.line_start}",
                        f"{field_mapping.target}: {exc.detail}",
                        location,
                        discriminator=field_mapping.target,
                    )
                    continue
                if value is None and field_mapping.required:
                    ok = False
                    self._norm(
                        "NORM.REQUIRED_FIELD_MISSING",
                        Severity.HIGH,
                        spec,
                        f"row:{spec.file}:{location.line_start}",
                        f"required field {field_mapping.target} is empty",
                        location,
                        discriminator=field_mapping.target,
                    )
                    continue
                record[field_mapping.target] = value
            if ok:
                staged.append((record, location))
        return staged

    def _duplicate(self, spec: DatasetSpec, key: str, location: SourceLocation) -> None:
        self._norm(
            "NORM.DUPLICATE_NATURAL_KEY",
            Severity.HIGH,
            spec,
            key,
            f"{key} appears more than once",
            location,
        )

    def _record_error(
        self, spec: DatasetSpec, location: SourceLocation, exc: InvalidInputError
    ) -> None:
        self._norm(
            "NORM.PARSE_FAILURE",
            Severity.HIGH,
            spec,
            f"row:{spec.file}:{location.line_start}",
            exc.detail,
            location,
            discriminator="record",
        )

    # ------------------------------------------------------------------ datasets
    def run(self) -> RunSnapshot:
        order = [
            "legacy_coa",
            "target_coa",
            "account_mapping",
            "trial_balance",
            "customers",
            "vendors",
            "fx_rates",
            "invoices",
            "bills",
            "payments",
            "ar_aging",
            "ap_aging",
            "gl_detail",
            "bank_transactions",
        ]
        known = set(order)
        for spec in self.inputs.datasets:
            if spec.dataset_type not in known:
                raise MappingConfigError(f"unsupported dataset type {spec.dataset_type}")
        for dataset_type in order:
            for spec in self.inputs.datasets_of(dataset_type):
                getattr(self, f"_load_{dataset_type}")(spec)
        for change in self.overlays.account_mapping_changes:
            self.snapshot.account_mapping[change.legacy_account] = change.target_account
            self.snapshot.applied_overrides.append(change.id)
        self._apply_record_overrides()
        return self.snapshot

    def _load_legacy_coa(self, spec: DatasetSpec) -> None:
        for record, location in self.stage(spec):
            code = record["account_code"]
            try:
                account = Account(
                    code=code,
                    name=record["name"],
                    subtype=AccountSubtype(record["subtype"]),
                    is_active=bool(record["is_active"]),
                )
            except (ValueError, InvalidInputError) as exc:
                self._norm(
                    "COA.TYPE_VALID",
                    Severity.HIGH,
                    spec,
                    nk.legacy_account(code),
                    f"invalid account type: {exc}",
                    location,
                )
                continue
            if code in self.snapshot.legacy_accounts:
                self._norm(
                    "COA.CODE_UNIQUE",
                    Severity.CRITICAL,
                    spec,
                    nk.legacy_account(code),
                    f"account {code} is duplicated",
                    location,
                )
                continue
            self.snapshot.legacy_accounts[code] = account
            self.snapshot.locations[nk.legacy_account(code)] = location

    def _load_target_coa(self, spec: DatasetSpec) -> None:
        for record, location in self.stage(spec):
            code = record["account_code"]
            try:
                account = Account(
                    code=code, name=record["name"], subtype=AccountSubtype(record["subtype"])
                )
            except (ValueError, InvalidInputError) as exc:
                self._norm(
                    "COA.TYPE_VALID",
                    Severity.HIGH,
                    spec,
                    nk.target_account(code),
                    f"invalid account type: {exc}",
                    location,
                )
                continue
            if code in self.snapshot.target_accounts:
                self._duplicate(spec, nk.target_account(code), location)
                continue
            self.snapshot.target_accounts[code] = account
            self.snapshot.locations[nk.target_account(code)] = location

    def _load_account_mapping(self, spec: DatasetSpec) -> None:
        for record, location in self.stage(spec):
            legacy = record["legacy_account_code"]
            if legacy in self.snapshot.account_mapping:
                self._duplicate(spec, f"mapping:{legacy}", location)
                continue
            self.snapshot.account_mapping[legacy] = record["target_account_code"]
            self.snapshot.locations[f"mapping:{legacy}"] = location

    def _load_trial_balance(self, spec: DatasetSpec) -> None:
        for record, location in self.stage(spec):
            key = (record["account_code"], record["period_end"])
            natural = nk.trial_balance(record["account_code"], record["period_end"].isoformat())
            if key in self.snapshot.trial_balance:
                self._duplicate(spec, natural, location)
                continue
            self.snapshot.trial_balance[key] = record["balance"]
            self.snapshot.locations[natural] = location

    def _load_parties(
        self, spec: DatasetSpec, party_type: PartyType, target: dict[str, Party]
    ) -> None:
        for record, location in self.stage(spec):
            code = record["party_code"]
            key = nk.party(party_type, code)
            email = record.get("email")
            try:
                party = Party(
                    party_type=party_type,
                    code=code,
                    name=record["name"],
                    address_line1=record.get("address_line1") or "",
                    city=record.get("city") or "",
                    region=record.get("region") or "",
                    postal_code=record.get("postal_code") or "",
                    country=record.get("country") or "",
                    email=email,
                    tax_id_last4=record.get("tax_id_last4"),
                    default_currency=record.get("default_currency")
                    or self.snapshot.functional_currency,
                    payment_terms_days=record.get("payment_terms_days") or 0,
                    is_active=bool(record.get("is_active", True)),
                    created_on=record.get("created_on") or self.snapshot.plan.opening_balance_date,
                    notes=record.get("notes") or "",
                )
            except InvalidInputError as exc:
                self._record_error(spec, location, exc)
                continue
            if code in target:
                self._duplicate(spec, key, location)
                continue
            target[code] = party
            self.snapshot.locations[key] = location

    def _load_customers(self, spec: DatasetSpec) -> None:
        self._load_parties(spec, PartyType.CUSTOMER, self.snapshot.customers)

    def _load_vendors(self, spec: DatasetSpec) -> None:
        self._load_parties(spec, PartyType.VENDOR, self.snapshot.vendors)

    def _load_fx_rates(self, spec: DatasetSpec) -> None:
        for record, location in self.stage(spec):
            key = (record["base_currency"].code, record["quote_currency"].code, record["rate_date"])
            if key in self.snapshot.fx_rates:
                self._duplicate(spec, f"fx:{key[0]}{key[1]}:{key[2].isoformat()}", location)
                continue
            self.snapshot.fx_rates[key] = record["rate"]

    def _load_documents(
        self, spec: DatasetSpec, document_type: DocumentType, target: dict[str, OpenDocument]
    ) -> None:
        for record, location in self.stage(spec):
            number = record["document_number"]
            key = nk.document(document_type, number)
            currency: Currency = record["currency"]
            total = record["total"]
            functional_total = record.get(
                "functional_total", total if currency == self.snapshot.functional_currency else None
            )
            rate = record.get("fx_rate", Decimal(1))
            try:
                if functional_total is None:
                    raise TransformError(
                        "functional total is required for foreign-currency documents"
                    )
                document = Document(
                    document_type=document_type,
                    number=number,
                    party_code=record["party_code"],
                    party_reference=record.get("party_reference"),
                    document_date=record["document_date"],
                    due_date=record["due_date"],
                    currency=currency,
                    subtotal=Money(record.get("subtotal", total), currency),
                    tax=Money(record.get("tax", Decimal(0)), currency),
                    total=Money(total, currency),
                    fx_rate=rate,
                    functional_total=Money(functional_total, self.snapshot.functional_currency),
                )
            except InvalidInputError as exc:
                self._record_error(spec, location, exc)
                continue
            if number in target:
                self._duplicate(spec, key, location)
                continue
            target[number] = OpenDocument(document=document, open_amount=record["open_amount"])
            self.snapshot.locations[key] = location

    def _load_invoices(self, spec: DatasetSpec) -> None:
        self._load_documents(spec, DocumentType.INVOICE, self.snapshot.invoices)

    def _load_bills(self, spec: DatasetSpec) -> None:
        self._load_documents(spec, DocumentType.BILL, self.snapshot.bills)

    def _load_payments(self, spec: DatasetSpec) -> None:
        groups: dict[tuple[str, str], list[tuple[dict[str, Any], SourceLocation]]] = defaultdict(
            list
        )
        for record, location in self.stage(spec):
            groups[(record["direction"], record["payment_number"])].append((record, location))
        for (direction_text, number), rows in groups.items():
            direction = PaymentDirection(direction_text)
            first, location = rows[0]
            key = nk.payment(direction, number)
            currency: Currency = first["currency"]
            applied_documents = [
                r["applied_document"] for r, _ in rows if r.get("applied_document")
            ]
            if len(applied_documents) != len(set(applied_documents)):
                self._duplicate(spec, key, location)
                continue
            try:
                rate = first["fx_rate"]
                applications = tuple(
                    PaymentApplication(
                        document_number=r["applied_document"],
                        applied_amount=Money(r["applied_amount"], currency),
                        applied_functional_amount=Money(
                            (r["applied_amount"] * rate).quantize(Decimal("0.01")),
                            self.snapshot.functional_currency,
                        ),
                    )
                    for r, _ in rows
                    if r.get("applied_document")
                )
                unapplied = max(
                    (r.get("unapplied_amount") or Decimal(0) for r, _ in rows), default=Decimal(0)
                )
                payment = Payment(
                    number=number,
                    direction=direction,
                    method=PaymentMethod(first["method"]),
                    reference=first.get("reference"),
                    party_code=first["party_code"],
                    payment_date=first["payment_date"],
                    currency=currency,
                    amount=Money(first["amount"], currency),
                    fx_rate=rate,
                    functional_amount=Money(
                        first["functional_amount"], self.snapshot.functional_currency
                    ),
                    applications=applications,
                    unapplied_amount=Money(unapplied, currency),
                    bank_account=self._default_bank_account(),
                )
            except (InvalidInputError, ValueError) as exc:
                detail = exc.detail if isinstance(exc, InvalidInputError) else str(exc)
                self._norm(
                    "NORM.PARSE_FAILURE",
                    Severity.HIGH,
                    spec,
                    key,
                    detail,
                    location,
                    discriminator="record",
                )
                continue
            self.snapshot.payments[(direction, number)] = payment
            self.snapshot.locations[key] = location

    def _default_bank_account(self) -> str:
        links = self.snapshot.bank_links
        return links[0].bank_account if len(links) == 1 else "unassigned"

    def _load_aging(self, spec: DatasetSpec, aging_type: AgingType) -> None:
        if spec.as_of is None:
            raise MappingConfigError(f"{spec.file}: aging datasets need an as_of date")
        items: list[AgingItem] = []
        for record, location in self.stage(spec):
            value: Decimal = record["functional_open_amount"]
            kind = AgingItemKind(record["kind"])
            try:
                item = AgingItem(
                    aging_type=aging_type,
                    as_of=spec.as_of,
                    party_code=record["party_code"],
                    kind=kind,
                    reference=record["reference"],
                    item_date=record["item_date"],
                    due_date=record.get("due_date"),
                    currency=self.snapshot.functional_currency,
                    open_amount=Money(abs(value), self.snapshot.functional_currency),
                    functional_open_amount=Money(abs(value), self.snapshot.functional_currency),
                    extra=(("document_currency", record["currency"].code),),
                )
            except InvalidInputError as exc:
                self._record_error(spec, location, exc)
                continue
            items.append(item)
            self.snapshot.locations[nk.aging_item(aging_type, spec.as_of, item.reference)] = (
                location
            )
        self.snapshot.agings[(aging_type, spec.as_of)] = items

    def _load_ar_aging(self, spec: DatasetSpec) -> None:
        self._load_aging(spec, AgingType.AR)

    def _load_ap_aging(self, spec: DatasetSpec) -> None:
        self._load_aging(spec, AgingType.AP)

    def _load_bank_transactions(self, spec: DatasetSpec) -> None:
        link = next((link for link in self.snapshot.bank_links if link.file == spec.file), None)
        if link is None:
            raise MappingConfigError(f"{spec.file}: no bank account link configured")
        records: list[BankRecord] = []
        ordinals: dict[tuple[Any, ...], int] = defaultdict(int)
        for record, location in self.stage(spec):
            try:
                amount = Money(record["amount"], self.snapshot.functional_currency)
                transaction = BankTransaction(
                    bank_account=link.bank_account,
                    posted_date=record["posted_date"],
                    description=record["description"],
                    amount=amount,
                    reference=record.get("reference"),
                )
            except InvalidInputError as exc:
                self._record_error(spec, location, exc)
                continue
            identity = (
                transaction.posted_date,
                transaction.description,
                amount.amount_str,
                transaction.reference,
            )
            ordinal = ordinals[identity]
            ordinals[identity] += 1
            natural = nk.bank_transaction(
                link.bank_account,
                transaction.posted_date,
                description=transaction.description,
                amount=amount,
                reference=transaction.reference,
                ordinal=ordinal,
            )
            records.append(
                BankRecord(transaction, record.get("running_balance"), natural, location)
            )
            self.snapshot.locations[natural] = location
        self.snapshot.bank[link.bank_account] = records

    def _load_gl_detail(self, spec: DatasetSpec) -> None:
        by_entry: dict[str, list[tuple[dict[str, Any], SourceLocation]]] = defaultdict(list)
        for record, location in self.stage(spec):
            by_entry[record["entry_number"]].append((record, location))
        functional = self.snapshot.functional_currency
        for number, rows in by_entry.items():
            rows.sort(key=lambda item: item[0]["line_number"])
            head = rows[0][0]
            headers = {
                (r["entry_date"], r["posting_period"], r["source_module"], r.get("reversal_of"))
                for r, _ in rows
            }
            entry_key = nk.journal_entry(number)
            if len(headers) != 1:
                self._norm(
                    "NORM.PARSE_FAILURE",
                    Severity.HIGH,
                    spec,
                    entry_key,
                    "lines of one entry disagree on date, period or type",
                    rows[0][1],
                    discriminator="entry_header",
                )
                continue
            module = SourceModule(head["source_module"])
            lines: list[JournalLine] = []
            seen: set[int] = set()
            for record, location in rows:
                line_number = record["line_number"]
                line_key = nk.journal_line(number, line_number)
                if line_number in seen:
                    self._duplicate(spec, line_key, location)
                    continue
                seen.add(line_number)
                currency: Currency = record["currency"]
                functional_amount = Money(record["functional_amount"], functional)
                try:
                    if currency == functional:
                        amount = functional_amount
                    elif record.get("foreign_amount") is None:
                        raise TransformError("foreign-currency line without a foreign amount")
                    else:
                        amount = Money(record["foreign_amount"], currency)
                    party = None
                    if record.get("party_code"):
                        party_type = (
                            PartyType.VENDOR
                            if module
                            in {SourceModule.ACCOUNTS_PAYABLE, SourceModule.CASH_DISBURSEMENTS}
                            else PartyType.CUSTOMER
                        )
                        party = PartyKey(party_type=party_type, code=record["party_code"])
                    line = JournalLine(
                        line_number=line_number,
                        account_code=record["account_code"],
                        amount=amount,
                        functional_amount=functional_amount,
                        party=party,
                        document_number=record.get("document_number"),
                        memo=record.get("memo") or "",
                    )
                except InvalidInputError as exc:
                    self._record_error(spec, location, exc)
                    continue
                lines.append(line)
                self.snapshot.locations[line_key] = location
            if not lines:
                continue
            try:
                entry = JournalEntry(
                    entry_number=number,
                    entry_date=head["entry_date"],
                    posting_period=head["posting_period"],
                    source_module=module,
                    memo="",
                    lines=tuple(lines),
                    reversal_of=head.get("reversal_of"),
                )
            except InvalidInputError as exc:
                self._record_error(spec, rows[0][1], exc)
                continue
            self.snapshot.journal_entries[number] = entry
            self.snapshot.locations[entry_key] = rows[0][1]

    # ------------------------------------------------------------------ overrides
    def _apply_record_overrides(self) -> None:
        snapshot = self.snapshot
        for override in self.overlays.record_overrides:
            prefix, _, identifier = override.record.partition(":")
            stale = False
            if prefix == "je" and identifier in snapshot.journal_entries:
                entry = snapshot.journal_entries[identifier]
                if override.field == "entry_date":
                    current = entry.entry_date.isoformat()
                    if current != override.expected_current:
                        stale = True
                    else:
                        snapshot.journal_entries[identifier] = dataclasses.replace(
                            entry, entry_date=parse_iso_business_date(override.new_value)
                        )
                elif override.field == "posting_period":
                    if entry.posting_period != override.expected_current:
                        stale = True
                    else:
                        snapshot.source_posting_periods.setdefault(identifier, entry.posting_period)
                        snapshot.journal_entries[identifier] = dataclasses.replace(
                            entry, posting_period=override.new_value
                        )
                else:
                    raise MappingConfigError(
                        f"override field {override.field} is not supported for journal entries"
                    )
            else:
                stale = True
            if stale:
                snapshot.exceptions.append(
                    make_exception(
                        rule_id="OVERRIDE.STALE",
                        rule_version=NORM_VERSION,
                        severity=Severity.HIGH,
                        nature=Nature.MIGRATION_DEFECT,
                        category=Category.OTHER,
                        subjects=[f"override:{override.id}"],
                        message=(
                            f"override {override.id} no longer matches "
                            f"{override.record}.{override.field}"
                        ),
                        expected=override.expected_current,
                    )
                )
            else:
                snapshot.applied_overrides.append(override.id)


def normalize(inputs: MigrationInputs, overlays: Overlays) -> RunSnapshot:
    return _Normalizer(inputs, overlays).run()
