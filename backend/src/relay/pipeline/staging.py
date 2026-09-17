"""Staged records: one row per canonical record of a run, with lineage to the source row. Pure."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from relay.canonical import natural_keys as nk
from relay.canonical.enums import DocumentType, PartyType
from relay.canonical.lineage import SourceLocation
from relay.core.currency import Currency
from relay.core.hashing import to_canonical
from relay.core.money import Money
from relay.engine.snapshot import RunSnapshot


def plain(value: object) -> Any:
    """Canonical JSON form of a canonical record (Money as amount/currency, Currency as code)."""
    if isinstance(value, Money):
        return value.to_json()
    if isinstance(value, Currency):
        return value.code
    if is_dataclass(value) and not isinstance(value, type):
        return {spec.name: plain(getattr(value, spec.name)) for spec in fields(value)}
    if isinstance(value, tuple | list):
        return [plain(item) for item in value]
    return to_canonical(value)


def _lineage(snapshot: RunSnapshot, key: str) -> dict[str, Any]:
    location: SourceLocation | None = snapshot.locations.get(key)
    if location is None:
        return {}
    try:
        import_id = uuid.UUID(location.file_name)
    except ValueError:
        return {}
    return {
        "source_import_id": import_id,
        "source_row_number": location.row_number,
        "line_start": location.line_start,
        "line_end": location.line_end,
    }


def _row(
    snapshot: RunSnapshot,
    run_id: uuid.UUID,
    record_type: str,
    key: str,
    data: object,
    *,
    account_code: str | None = None,
    party_code: str | None = None,
    document_number: str | None = None,
    entry_number: str | None = None,
    record_date: date | None = None,
    posting_period: str | None = None,
    functional_amount: Decimal | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "record_type": record_type,
        "natural_key": key,
        "account_code": account_code,
        "party_code": party_code,
        "document_number": document_number,
        "entry_number": entry_number,
        "record_date": record_date,
        "posting_period": posting_period,
        "functional_amount": functional_amount,
        "source_import_id": None,
        "source_row_number": None,
        "line_start": None,
        "line_end": None,
        **_lineage(snapshot, key),
        "data": plain(data),
    }


def staged_rows(snapshot: RunSnapshot, run_id: uuid.UUID) -> Iterator[dict[str, Any]]:
    """Rows in a stable order; a repeated natural key gets a ``#n`` suffix so nothing is dropped."""
    seen: dict[str, int] = {}
    for row in _rows(snapshot, run_id):
        key = row["natural_key"]
        count = seen.get(key, 0)
        seen[key] = count + 1
        if count:
            row["natural_key"] = f"{key}#{count + 1}"
        yield row


def _rows(  # noqa: PLR0912 - one block per record type
    snapshot: RunSnapshot, run_id: uuid.UUID
) -> Iterator[dict[str, Any]]:
    for code, account in sorted(snapshot.legacy_accounts.items()):
        yield _row(
            snapshot, run_id, "legacy_account", nk.legacy_account(code), account, account_code=code
        )
    for code, account in sorted(snapshot.target_accounts.items()):
        yield _row(
            snapshot, run_id, "target_account", nk.target_account(code), account, account_code=code
        )
    for legacy, target in sorted(snapshot.account_mapping.items()):
        yield _row(
            snapshot,
            run_id,
            "account_mapping",
            f"mapping:{legacy}",
            {"legacy_account_code": legacy, "target_account_code": target},
            account_code=legacy,
        )
    for (code, period_end), balance in sorted(snapshot.trial_balance.items()):
        yield _row(
            snapshot,
            run_id,
            "trial_balance",
            nk.trial_balance(code, period_end.isoformat()),
            {"account_code": code, "period_end": period_end, "balance": balance},
            account_code=code,
            record_date=period_end,
            functional_amount=balance,
        )
    for number, entry in sorted(snapshot.journal_entries.items()):
        yield _row(
            snapshot,
            run_id,
            "journal_entry",
            nk.journal_entry(number),
            {
                "entry_number": number,
                "entry_date": entry.entry_date,
                "posting_period": entry.posting_period,
                "source_module": entry.source_module,
                "memo": entry.memo,
                "reversal_of": entry.reversal_of,
                "line_count": len(entry.lines),
            },
            entry_number=number,
            record_date=entry.entry_date,
            posting_period=entry.posting_period,
        )
        for line in entry.lines:
            yield _row(
                snapshot,
                run_id,
                "journal_line",
                nk.journal_line(number, line.line_number),
                line,
                account_code=line.account_code,
                party_code=line.party.code if line.party else None,
                document_number=line.document_number,
                entry_number=number,
                record_date=entry.entry_date,
                posting_period=entry.posting_period,
                functional_amount=line.functional_amount.amount,
            )
    for party_type, parties in (
        (PartyType.CUSTOMER, snapshot.customers),
        (PartyType.VENDOR, snapshot.vendors),
    ):
        for code, party in sorted(parties.items()):
            yield _row(
                snapshot,
                run_id,
                party_type.value,
                nk.party(party_type, code),
                party,
                party_code=code,
            )
    for document_type, documents in (
        (DocumentType.INVOICE, snapshot.invoices),
        (DocumentType.BILL, snapshot.bills),
    ):
        for number, od in sorted(documents.items()):
            document = od.document
            yield _row(
                snapshot,
                run_id,
                document_type.value,
                nk.document(document_type, number),
                {**plain(document), "open_amount": od.open_amount},
                party_code=document.party_code,
                document_number=number,
                record_date=document.document_date,
                functional_amount=document.functional_total.amount,
            )
    for (direction, number), payment in sorted(
        snapshot.payments.items(), key=lambda i: (i[0][0].value, i[0][1])
    ):
        yield _row(
            snapshot,
            run_id,
            "payment",
            nk.payment(direction, number),
            payment,
            party_code=payment.party_code,
            document_number=number,
            record_date=payment.payment_date,
            functional_amount=payment.functional_amount.amount,
        )
        for application in payment.applications:
            key = nk.application(number, application.document_number)
            row = _row(
                snapshot,
                run_id,
                "payment_application",
                key,
                {"payment_key": nk.payment(direction, number), **plain(application)},
                party_code=payment.party_code,
                document_number=application.document_number,
                record_date=payment.payment_date,
                functional_amount=application.applied_functional_amount.amount,
            )
            row.update(_lineage(snapshot, nk.payment(direction, number)))
            yield row
    for (_, _), items in sorted(snapshot.agings.items(), key=lambda i: (i[0][0].value, i[0][1])):
        for item in items:
            yield _row(
                snapshot,
                run_id,
                "aging_item",
                nk.aging_item(item.aging_type, item.as_of, item.reference),
                item,
                party_code=item.party_code,
                document_number=item.reference,
                record_date=item.as_of,
                functional_amount=item.functional_open_amount.amount,
            )
    for records in snapshot.bank.values():
        for record in records:
            yield _row(
                snapshot,
                run_id,
                "bank_transaction",
                record.natural_key,
                {**plain(record.transaction), "running_balance": record.running_balance},
                record_date=record.transaction.posted_date,
                functional_amount=record.transaction.amount.amount,
            )
