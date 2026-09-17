"""Enumerations of the canonical accounting model."""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class NormalBalance(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class AccountSubtype(StrEnum):
    CASH = "cash"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    CONTRA_ASSET = "contra_asset"
    INVENTORY = "inventory"
    PREPAID = "prepaid"
    OTHER_CURRENT_ASSET = "other_current_asset"
    FIXED_ASSET = "fixed_asset"
    ACCUMULATED_DEPRECIATION = "accumulated_depreciation"
    ACCOUNTS_PAYABLE = "accounts_payable"
    ACCRUED_LIABILITY = "accrued_liability"
    PAYROLL_LIABILITY = "payroll_liability"
    LINE_OF_CREDIT = "line_of_credit"
    LONG_TERM_DEBT = "long_term_debt"
    COMMON_STOCK = "common_stock"
    RETAINED_EARNINGS = "retained_earnings"
    OPERATING_REVENUE = "operating_revenue"
    COST_OF_GOODS_SOLD = "cost_of_goods_sold"
    OPERATING_EXPENSE = "operating_expense"
    OTHER_INCOME = "other_income"
    OTHER_EXPENSE = "other_expense"
    SUSPENSE = "suspense"


_SUBTYPE_TYPE: dict[AccountSubtype, AccountType] = {
    AccountSubtype.CASH: AccountType.ASSET,
    AccountSubtype.ACCOUNTS_RECEIVABLE: AccountType.ASSET,
    AccountSubtype.CONTRA_ASSET: AccountType.ASSET,
    AccountSubtype.INVENTORY: AccountType.ASSET,
    AccountSubtype.PREPAID: AccountType.ASSET,
    AccountSubtype.OTHER_CURRENT_ASSET: AccountType.ASSET,
    AccountSubtype.FIXED_ASSET: AccountType.ASSET,
    AccountSubtype.ACCUMULATED_DEPRECIATION: AccountType.ASSET,
    AccountSubtype.SUSPENSE: AccountType.ASSET,
    AccountSubtype.ACCOUNTS_PAYABLE: AccountType.LIABILITY,
    AccountSubtype.ACCRUED_LIABILITY: AccountType.LIABILITY,
    AccountSubtype.PAYROLL_LIABILITY: AccountType.LIABILITY,
    AccountSubtype.LINE_OF_CREDIT: AccountType.LIABILITY,
    AccountSubtype.LONG_TERM_DEBT: AccountType.LIABILITY,
    AccountSubtype.COMMON_STOCK: AccountType.EQUITY,
    AccountSubtype.RETAINED_EARNINGS: AccountType.EQUITY,
    AccountSubtype.OPERATING_REVENUE: AccountType.REVENUE,
    AccountSubtype.OTHER_INCOME: AccountType.REVENUE,
    AccountSubtype.COST_OF_GOODS_SOLD: AccountType.EXPENSE,
    AccountSubtype.OPERATING_EXPENSE: AccountType.EXPENSE,
    AccountSubtype.OTHER_EXPENSE: AccountType.EXPENSE,
}

_CREDIT_NORMAL_SUBTYPES = frozenset(
    {
        AccountSubtype.CONTRA_ASSET,
        AccountSubtype.ACCUMULATED_DEPRECIATION,
        AccountSubtype.ACCOUNTS_PAYABLE,
        AccountSubtype.ACCRUED_LIABILITY,
        AccountSubtype.PAYROLL_LIABILITY,
        AccountSubtype.LINE_OF_CREDIT,
        AccountSubtype.LONG_TERM_DEBT,
        AccountSubtype.COMMON_STOCK,
        AccountSubtype.RETAINED_EARNINGS,
        AccountSubtype.OPERATING_REVENUE,
        AccountSubtype.OTHER_INCOME,
    }
)


def account_type_of(subtype: AccountSubtype) -> AccountType:
    return _SUBTYPE_TYPE[subtype]


def normal_balance_of(subtype: AccountSubtype) -> NormalBalance:
    return NormalBalance.CREDIT if subtype in _CREDIT_NORMAL_SUBTYPES else NormalBalance.DEBIT


class PartyType(StrEnum):
    CUSTOMER = "customer"
    VENDOR = "vendor"


class DocumentType(StrEnum):
    INVOICE = "invoice"
    BILL = "bill"


class PaymentDirection(StrEnum):
    RECEIVED = "received"
    DISBURSED = "disbursed"


class PaymentMethod(StrEnum):
    CHECK = "check"
    ACH = "ach"
    WIRE = "wire"


class SourceModule(StrEnum):
    ACCOUNTS_RECEIVABLE = "ar"
    ACCOUNTS_PAYABLE = "ap"
    CASH_RECEIPTS = "cash_receipts"
    CASH_DISBURSEMENTS = "cash_disbursements"
    MANUAL = "manual"


class AgingType(StrEnum):
    AR = "ar"
    AP = "ap"


class AgingItemKind(StrEnum):
    DOCUMENT = "document"
    UNAPPLIED_PAYMENT = "unapplied_payment"
