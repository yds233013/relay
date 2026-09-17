"""Natural keys: stable business identity of records across runs (docs/data-model.md §8.1).

Natural keys are identifiers, not orderings: never infer chronology from them.
"""

from __future__ import annotations

from datetime import date

from relay.canonical.enums import AgingType, DocumentType, PartyType, PaymentDirection
from relay.core.dates import format_business_date
from relay.core.hashing import fingerprint
from relay.core.money import Money


def legacy_account(code: str) -> str:
    return f"acct:legacy:{code}"


def target_account(code: str) -> str:
    return f"acct:target:{code}"


def party(party_type: PartyType, code: str) -> str:
    return f"party:{party_type.value}:{code}"


def journal_entry(entry_number: str) -> str:
    return f"je:{entry_number}"


def journal_line(entry_number: str, line_number: int) -> str:
    return f"jl:{entry_number}:{line_number}"


def trial_balance(account_code: str, period: str) -> str:
    return f"tb:{account_code}:{period}"


def document(document_type: DocumentType, number: str) -> str:
    return f"doc:{document_type.value}:{number}"


def payment(direction: PaymentDirection, number: str) -> str:
    return f"pay:{direction.value}:{number}"


def application(payment_number: str, document_number: str) -> str:
    return f"app:{payment_number}:{document_number}"


def aging_item(aging_type: AgingType, as_of: date, reference: str) -> str:
    return f"aging:{aging_type.value}:{format_business_date(as_of)}:{reference}"


def bank_transaction(
    bank_account: str,
    posted_date: date,
    *,
    description: str,
    amount: Money,
    reference: str | None,
    ordinal: int,
) -> str:
    """Identity of a bank line: content plus an ordinal among otherwise equal lines."""
    digest = fingerprint([description, amount, reference, ordinal])[:12]
    return f"bank:{bank_account}:{format_business_date(posted_date)}:{digest}"
