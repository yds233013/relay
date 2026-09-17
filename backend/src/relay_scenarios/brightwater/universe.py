"""The LedgerPro universe: Brightwater's complete legacy database as canonical records.

This is *not* what Relay sees. Relay sees the exports produced from it (``exports.py``), which pass
through LedgerPro's export filters, and the control reports computed from it (``controls.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from relay.canonical.records import (
    Account,
    BankTransaction,
    Document,
    FxRate,
    JournalEntry,
    Party,
    Payment,
)
from relay_scenarios.brightwater.constants import CompanyProfile, ConversionPlan
from relay_scenarios.brightwater.parties import Segment, VendorCategory, Warehouse


@dataclass(frozen=True, slots=True)
class LegacyAccountInfo:
    account: Account
    ledgerpro_type: str
    detail_type: str


@dataclass(frozen=True, slots=True)
class CustomerInfo:
    segment: Segment
    warehouse: Warehouse
    closed_on: date | None = None


@dataclass(frozen=True, slots=True)
class VendorInfo:
    category: VendorCategory
    created_by: str


@dataclass(frozen=True, slots=True)
class InvoiceInfo:
    printed: bool
    warehouse: Warehouse
    order_entered_on: date
    cost: Decimal
    carried_forward: bool


@dataclass(frozen=True, slots=True)
class BillInfo:
    entered_by: str
    expense_account: str
    carried_forward: bool


@dataclass(frozen=True, slots=True)
class JournalInfo:
    created_on: date
    created_by: str


@dataclass(frozen=True, slots=True)
class BankLine:
    transaction: BankTransaction
    sequence: int
    """Stable tie-breaker among lines posted on the same date."""


@dataclass
class LegacyUniverse:
    company: CompanyProfile
    plan: ConversionPlan
    seed: int
    accounts: dict[str, LegacyAccountInfo]
    target_accounts: dict[str, Account]
    account_mapping: dict[str, str]
    """The implementation team's legacy → target mapping table (for every legacy account)."""
    customers: dict[str, Party]
    customer_info: dict[str, CustomerInfo]
    vendors: dict[str, Party]
    vendor_info: dict[str, VendorInfo]
    invoices: dict[str, Document]
    invoice_info: dict[str, InvoiceInfo]
    bills: dict[str, Document]
    bill_info: dict[str, BillInfo]
    payments: dict[str, Payment]
    journals: dict[str, JournalEntry]
    journal_info: dict[str, JournalInfo]
    bank_lines: list[BankLine]
    fx_rates: dict[date, FxRate]
    opening_balances: dict[str, Decimal]
    """Legacy trial balance at the opening balance date (signed, functional)."""
    applied_injectors: list[str] = field(default_factory=list)

    def next_bank_sequence(self) -> int:
        return max((line.sequence for line in self.bank_lines), default=0) + 1
