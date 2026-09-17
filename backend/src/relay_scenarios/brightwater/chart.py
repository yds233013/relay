"""Brightwater charts of accounts and the implementation team's account mapping table.

Legacy accounts carry LedgerPro's own type and detail-type labels (what the export shows); the
canonical subtype is what a correct column mapping would derive from those labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from relay.canonical.enums import AccountSubtype as S


@dataclass(frozen=True, slots=True)
class LegacyAccountSpec:
    code: str
    name: str
    subtype: S
    ledgerpro_type: str
    detail_type: str
    active: bool = True
    opening_balance: Decimal = Decimal(0)
    target: str | None = None


def _a(
    code: str,
    name: str,
    subtype: S,
    lp_type: str,
    detail: str,
    target: str,
    opening: str = "0",
    *,
    active: bool = True,
) -> LegacyAccountSpec:
    return LegacyAccountSpec(code, name, subtype, lp_type, detail, active, Decimal(opening), target)


BANK = "Bank"
AR = "Accounts Receivable"
OCA = "Other Current Asset"
FA = "Fixed Asset"
OA = "Other Asset"
AP = "Accounts Payable"
CC = "Credit Card"
OCL = "Other Current Liability"
LTL = "Long Term Liability"
EQ = "Equity"
INC = "Income"
COGS = "Cost of Goods Sold"
EXP = "Expense"
OI = "Other Income"
OE = "Other Expense"

# Opening balances marked here are static balances at 2025-12-31. Balances derived from other data
# (cash, receivables, payables, accruals, retained earnings) are computed by the clean builder.
LEGACY_ACCOUNTS: Final[tuple[LegacyAccountSpec, ...]] = (
    _a("1000", "Petty Cash", S.CASH, BANK, "Cash on Hand", "1015", "400.00"),
    _a("1010", "Operating Account - First Cascade 4471", S.CASH, BANK, "Checking", "1000"),
    _a("1015", "Payroll Account - First Cascade 4488", S.CASH, BANK, "Checking", "1005", "5000.00"),
    _a("1020", "Money Market - First Cascade 4490", S.CASH, BANK, "Money Market", "1010", "250000.00"),
    _a("1030", "Savings - Umpqua (closed)", S.CASH, BANK, "Savings", "1010", active=False),
    _a("1100", "Undeposited Funds", S.CASH, OCA, "Undeposited Funds", "1015"),
    _a("1110", "Returned Checks", S.OTHER_CURRENT_ASSET, OCA, "Other Current Assets", "1250"),
    _a("1200", "Accounts Receivable", S.ACCOUNTS_RECEIVABLE, AR, "Accounts Receivable (A/R)", "1200"),
    _a("1205", "Allowance for Doubtful Accounts", S.CONTRA_ASSET, OCA, "Allowance for Bad Debts", "1210", "-35000.00"),
    _a("1215", "Employee Advances", S.OTHER_CURRENT_ASSET, OCA, "Employee Cash Advances", "1250"),
    _a("1250", "Other Receivables", S.OTHER_CURRENT_ASSET, OCA, "Other Current Assets", "1250", "3150.00"),
    _a("1260", "Notes Receivable", S.OTHER_CURRENT_ASSET, OCA, "Loans to Others", "1250"),
    _a("1300", "Inventory - Finished Goods", S.INVENTORY, OCA, "Inventory", "1300", "1418250.00"),
    _a("1310", "Inventory in Transit", S.INVENTORY, OCA, "Inventory", "1300"),
    _a("1320", "Inventory - Samples", S.INVENTORY, OCA, "Inventory", "1300"),
    _a("1400", "Prepaid Insurance", S.PREPAID, OCA, "Prepaid Expenses", "1400", "39300.00"),
    _a("1410", "Prepaid Expenses - Other", S.PREPAID, OCA, "Prepaid Expenses", "1400", "18400.00"),
    _a("1420", "Security Deposits", S.OTHER_CURRENT_ASSET, OCA, "Other Current Assets", "1450", "42500.00"),
    _a("1500", "Warehouse Equipment", S.FIXED_ASSET, FA, "Machinery & Equipment", "1500", "1182400.00"),
    _a("1510", "Vehicles", S.FIXED_ASSET, FA, "Vehicles", "1500", "486300.00"),
    _a("1520", "Leasehold Improvements", S.FIXED_ASSET, FA, "Leasehold Improvements", "1500", "211750.00"),
    _a("1530", "Office Furniture & Equipment", S.FIXED_ASSET, FA, "Furniture & Fixtures", "1500", "38620.00"),
    _a("1540", "Computer Equipment", S.FIXED_ASSET, FA, "Machinery & Equipment", "1500", "52980.00"),
    _a("1590", "Accumulated Depreciation", S.ACCUMULATED_DEPRECIATION, FA, "Accumulated Depreciation", "1590", "-412640.00"),
    _a("1600", "Utility Deposits", S.OTHER_CURRENT_ASSET, OA, "Security Deposits", "1450", "6200.00"),
    _a("1700", "Customer Lists", S.FIXED_ASSET, OA, "Intangible Assets", "1700", "60000.00"),
    _a("1790", "Accumulated Amortization", S.ACCUMULATED_DEPRECIATION, OA, "Accumulated Amortization", "1590", "-36000.00"),
    _a("2000", "Accounts Payable", S.ACCOUNTS_PAYABLE, AP, "Accounts Payable (A/P)", "2000"),
    _a("2050", "Cascade Visa Business", S.ACCRUED_LIABILITY, CC, "Credit Card", "2050"),
    _a("2060", "Amex Corporate (closed)", S.ACCRUED_LIABILITY, CC, "Credit Card", "2050", active=False),
    _a("2100", "Accrued Liabilities", S.ACCRUED_LIABILITY, OCL, "Accrued Liabilities", "2100"),
    _a("2150", "Payroll Liabilities", S.PAYROLL_LIABILITY, OCL, "Payroll Tax Payable", "2150"),
    _a("2160", "Accrued Commissions", S.ACCRUED_LIABILITY, OCL, "Accrued Liabilities", "2100"),
    _a("2170", "Accrued Vacation", S.ACCRUED_LIABILITY, OCL, "Accrued Liabilities", "2100", "-48620.00"),
    _a("2200", "Sales Tax Payable", S.ACCRUED_LIABILITY, OCL, "Sales Tax Payable", "2200"),
    _a("2210", "Use Tax Payable", S.ACCRUED_LIABILITY, OCL, "Sales Tax Payable", "2200"),
    _a("2220", "Oregon CAT Payable", S.ACCRUED_LIABILITY, OCL, "Federal Income Tax Payable", "2200", "-7840.00"),
    _a("2300", "Customer Deposits", S.ACCRUED_LIABILITY, OCL, "Other Current Liabilities", "2300"),
    _a("2400", "Deferred Revenue", S.ACCRUED_LIABILITY, OCL, "Deferred Revenue", "2300"),
    _a("2500", "Line of Credit - First Cascade", S.LINE_OF_CREDIT, OCL, "Line of Credit", "2500", "-900000.00"),
    _a("2700", "Equipment Loan - First Cascade", S.LONG_TERM_DEBT, LTL, "Notes Payable", "2700", "-268400.00"),
    _a("2710", "Vehicle Loans", S.LONG_TERM_DEBT, LTL, "Notes Payable", "2700", "-94200.00"),
    _a("2800", "Due to Shareholder", S.LONG_TERM_DEBT, LTL, "Shareholder Notes Payable", "2800"),
    _a("3000", "Common Stock", S.COMMON_STOCK, EQ, "Common Stock", "3000", "-50000.00"),
    _a("3100", "Additional Paid-In Capital", S.COMMON_STOCK, EQ, "Paid-In Capital or Surplus", "3000", "-150000.00"),
    _a("3900", "Retained Earnings", S.RETAINED_EARNINGS, EQ, "Retained Earnings", "3900"),
    _a("3950", "Shareholder Distributions", S.RETAINED_EARNINGS, EQ, "Partner Distributions", "3900"),
    _a("4000", "Sales - Wholesale Grocery", S.OPERATING_REVENUE, INC, "Sales of Product Income", "4000"),
    _a("4010", "Sales - Foodservice", S.OPERATING_REVENUE, INC, "Sales of Product Income", "4010"),
    _a("4100", "Sales - Export", S.OPERATING_REVENUE, INC, "Sales of Product Income", "4020"),
    _a("4200", "Freight Income", S.OPERATING_REVENUE, INC, "Service/Fee Income", "4100"),
    _a("4300", "Rebate Income", S.OTHER_INCOME, OI, "Other Miscellaneous Income", "4100"),
    _a("4400", "Miscellaneous Income", S.OTHER_INCOME, OI, "Other Miscellaneous Income", "4100"),
    _a("4900", "Sales Discounts", S.OPERATING_REVENUE, INC, "Discounts/Refunds Given", "4900"),
    _a("4950", "Returns & Allowances", S.OPERATING_REVENUE, INC, "Discounts/Refunds Given", "4900"),
    _a("5000", "Cost of Goods Sold", S.COST_OF_GOODS_SOLD, COGS, "Supplies & Materials - COGS", "5000"),
    _a("5010", "Inventory Adjustments", S.COST_OF_GOODS_SOLD, COGS, "Supplies & Materials - COGS", "5000"),
    _a("5020", "Purchase Price Variance", S.COST_OF_GOODS_SOLD, COGS, "Other Costs of Services - COS", "5000"),
    _a("5030", "Samples & Demos", S.COST_OF_GOODS_SOLD, COGS, "Other Costs of Services - COS", "5000"),
    _a("5100", "Inbound Freight - COGS", S.COST_OF_GOODS_SOLD, COGS, "Shipping, Freight & Delivery - COS", "5100"),
    _a("5150", "Packaging Materials", S.COST_OF_GOODS_SOLD, COGS, "Supplies & Materials - COGS", "5150"),
    _a("5200", "Spoilage & Shrink", S.COST_OF_GOODS_SOLD, COGS, "Other Costs of Services - COS", "5000"),
    _a("5300", "Co-Packing Fees", S.COST_OF_GOODS_SOLD, COGS, "Other Costs of Services - COS", "5100"),
    _a("6000", "Advertising & Marketing", S.OPERATING_EXPENSE, EXP, "Advertising/Promotional", "6000"),
    _a("6010", "Trade Shows", S.OPERATING_EXPENSE, EXP, "Advertising/Promotional", "6000"),
    _a("6020", "Website", S.OPERATING_EXPENSE, EXP, "Advertising/Promotional", "6000"),
    _a("6030", "Meals & Entertainment", S.OPERATING_EXPENSE, EXP, "Entertainment Meals", "6900"),
    _a("6040", "Travel", S.OPERATING_EXPENSE, EXP, "Travel", "6900"),
    _a("6050", "Donations", S.OPERATING_EXPENSE, EXP, "Charitable Contributions", "6900"),
    _a("6060", "Licenses & Permits", S.OPERATING_EXPENSE, EXP, "Taxes Paid", "6980"),
    _a("6070", "Property Taxes", S.OPERATING_EXPENSE, EXP, "Taxes Paid", "6980"),
    _a("6080", "Business Taxes", S.OPERATING_EXPENSE, EXP, "Taxes Paid", "6980"),
    _a("6090", "Recruiting", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6190"),
    _a("6100", "Wages - Warehouse", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6100"),
    _a("6105", "Wages - Drivers", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6100"),
    _a("6110", "Wages - Office", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6100"),
    _a("6120", "Payroll Taxes", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6120"),
    _a("6130", "Employee Benefits", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6120"),
    _a("6140", "Workers Compensation", S.OPERATING_EXPENSE, EXP, "Insurance", "6120"),
    _a("6150", "Sales Commissions", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6150"),
    _a("6160", "Temporary Labor", S.OPERATING_EXPENSE, EXP, "Payroll Expenses", "6100"),
    _a("6170", "Training", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6190"),
    _a("6180", "Employee Relations", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6190"),
    _a("6190", "Payroll Processing Fees", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6190"),
    _a("6200", "Utilities - Electric", S.OPERATING_EXPENSE, EXP, "Utilities", "6200"),
    _a("6210", "Utilities - Water & Sewer", S.OPERATING_EXPENSE, EXP, "Utilities", "6200"),
    _a("6220", "Telephone & Internet", S.OPERATING_EXPENSE, EXP, "Utilities", "6220"),
    _a("6230", "Utilities - Gas", S.OPERATING_EXPENSE, EXP, "Utilities", "6200"),
    _a("6240", "Waste Removal", S.OPERATING_EXPENSE, EXP, "Utilities", "6200"),
    _a("6300", "Rent - Portland Warehouse", S.OPERATING_EXPENSE, EXP, "Rent or Lease of Buildings", "6300"),
    _a("6310", "Rent - Seattle Warehouse", S.OPERATING_EXPENSE, EXP, "Rent or Lease of Buildings", "6300"),
    _a("6320", "Rent - Boise Warehouse", S.OPERATING_EXPENSE, EXP, "Rent or Lease of Buildings", "6300"),
    _a("6330", "Third-Party Storage", S.OPERATING_EXPENSE, EXP, "Rent or Lease of Buildings", "6300"),
    _a("6400", "Freight-In", S.OPERATING_EXPENSE, EXP, "Shipping, Freight & Delivery", "5100"),
    _a("6410", "Freight Rebates", S.OPERATING_EXPENSE, EXP, "Shipping, Freight & Delivery", "5100"),
    _a("6420", "Delivery Fuel", S.OPERATING_EXPENSE, EXP, "Auto", "6420"),
    _a("6430", "Vehicle Repairs & Maintenance", S.OPERATING_EXPENSE, EXP, "Auto", "6420"),
    _a("6440", "Tolls & Parking", S.OPERATING_EXPENSE, EXP, "Auto", "6420"),
    _a("6450", "Vehicle Registration", S.OPERATING_EXPENSE, EXP, "Auto", "6420"),
    _a("6460", "Vehicle Leases", S.OPERATING_EXPENSE, EXP, "Auto", "6420"),
    _a("6500", "Insurance - General", S.OPERATING_EXPENSE, EXP, "Insurance", "6500"),
    _a("6510", "Insurance - Vehicles", S.OPERATING_EXPENSE, EXP, "Insurance", "6500"),
    _a("6520", "Insurance - Product Liability", S.OPERATING_EXPENSE, EXP, "Insurance", "6500"),
    _a("6600", "Repairs - Refrigeration & Equipment", S.OPERATING_EXPENSE, EXP, "Repair & Maintenance", "6600"),
    _a("6610", "Forklift Lease", S.OPERATING_EXPENSE, EXP, "Equipment Rental", "6610"),
    _a("6620", "Building Repairs", S.OPERATING_EXPENSE, EXP, "Repair & Maintenance", "6300"),
    _a("6630", "Small Tools & Equipment", S.OPERATING_EXPENSE, EXP, "Supplies", "6600"),
    _a("6700", "Depreciation Expense", S.OPERATING_EXPENSE, EXP, "Depreciation", "6700"),
    _a("6710", "Amortization Expense", S.OPERATING_EXPENSE, EXP, "Amortization", "6700"),
    _a("6800", "Bad Debt Expense", S.OPERATING_EXPENSE, EXP, "Bad Debts", "6800"),
    _a("6810", "Collection Fees", S.OPERATING_EXPENSE, EXP, "Bad Debts", "6800"),
    _a("6900", "Office Supplies", S.OPERATING_EXPENSE, EXP, "Office/General Administrative Expenses", "6900"),
    _a("6910", "Postage & Delivery", S.OPERATING_EXPENSE, EXP, "Office/General Administrative Expenses", "6900"),
    _a("6920", "Bank Service Charges", S.OPERATING_EXPENSE, EXP, "Bank Charges", "6920"),
    _a("6925", "Merchant Fees", S.OPERATING_EXPENSE, EXP, "Bank Charges", "6920"),
    _a("6930", "Dues & Subscriptions", S.OPERATING_EXPENSE, EXP, "Dues & subscriptions", "6900"),
    _a("6935", "Software Subscriptions", S.OPERATING_EXPENSE, EXP, "Dues & subscriptions", "6960"),
    _a("6940", "Accounting Fees", S.OPERATING_EXPENSE, EXP, "Legal & Professional Fees", "6940"),
    _a("6945", "Consulting Fees", S.OPERATING_EXPENSE, EXP, "Legal & Professional Fees", "6940"),
    _a("6950", "Legal Fees", S.OPERATING_EXPENSE, EXP, "Legal & Professional Fees", "6940"),
    _a("6960", "IT Services", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6960"),
    _a("6970", "Janitorial", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6970"),
    _a("6980", "Pest Control", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6970"),
    _a("6990", "Uniforms & Laundry", S.OPERATING_EXPENSE, EXP, "Other Business Expenses", "6970"),
    _a("6995", "Miscellaneous Expense (old)", S.OPERATING_EXPENSE, EXP, "Other Miscellaneous Service Cost", "7300", active=False),
    _a("6999", "Suspense – Clearing", S.SUSPENSE, OCA, "Other Current Assets", "1999"),
    _a("7100", "Foreign Exchange Gain/Loss", S.OTHER_EXPENSE, OE, "Exchange Gain or Loss", "7100"),
    _a("7200", "Interest Expense", S.OTHER_EXPENSE, OE, "Interest Paid", "7200"),
    _a("7300", "Interest Income", S.OTHER_INCOME, OI, "Interest Earned", "4100"),
    _a("7400", "Gain/Loss on Asset Disposal", S.OTHER_EXPENSE, OE, "Other Miscellaneous Expense", "7300"),
    _a("7900", "Other Expense", S.OTHER_EXPENSE, OE, "Other Miscellaneous Expense", "7300"),
    _a("8000", "Owner Draw (old)", S.RETAINED_EARNINGS, EQ, "Owner's Equity", "3900", active=False),
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class TargetAccountSpec:
    code: str
    name: str
    subtype: S


def _t(code: str, name: str, subtype: S) -> TargetAccountSpec:
    return TargetAccountSpec(code, name, subtype)


# The new ERP's chart, designed by the implementation team. It includes template accounts that
# Brightwater does not use yet.
TARGET_ACCOUNTS: Final[tuple[TargetAccountSpec, ...]] = (
    _t("1000", "Cash - Operating", S.CASH),
    _t("1005", "Cash - Payroll", S.CASH),
    _t("1010", "Cash - Savings & Money Market", S.CASH),
    _t("1015", "Cash on Hand & Undeposited", S.CASH),
    _t("1100", "Short-Term Investments", S.OTHER_CURRENT_ASSET),
    _t("1200", "Accounts Receivable", S.ACCOUNTS_RECEIVABLE),
    _t("1210", "Allowance for Credit Losses", S.CONTRA_ASSET),
    _t("1220", "Unbilled Receivables", S.OTHER_CURRENT_ASSET),
    _t("1250", "Other Receivables", S.OTHER_CURRENT_ASSET),
    _t("1300", "Inventory", S.INVENTORY),
    _t("1310", "Inventory Reserve", S.CONTRA_ASSET),
    _t("1400", "Prepaid Expenses", S.PREPAID),
    _t("1450", "Deposits", S.OTHER_CURRENT_ASSET),
    _t("1500", "Property & Equipment", S.FIXED_ASSET),
    _t("1590", "Accumulated Depreciation", S.ACCUMULATED_DEPRECIATION),
    _t("1600", "Right-of-Use Assets", S.FIXED_ASSET),
    _t("1700", "Intangible Assets, Net", S.FIXED_ASSET),
    _t("1800", "Deferred Tax Assets", S.OTHER_CURRENT_ASSET),
    _t("1999", "Suspense", S.SUSPENSE),
    _t("2000", "Accounts Payable", S.ACCOUNTS_PAYABLE),
    _t("2010", "Accounts Payable - Intercompany", S.ACCOUNTS_PAYABLE),
    _t("2050", "Credit Cards Payable", S.ACCRUED_LIABILITY),
    _t("2100", "Accrued Expenses", S.ACCRUED_LIABILITY),
    _t("2150", "Payroll Liabilities", S.PAYROLL_LIABILITY),
    _t("2200", "Taxes Payable", S.ACCRUED_LIABILITY),
    _t("2300", "Customer Deposits & Deferred Revenue", S.ACCRUED_LIABILITY),
    _t("2350", "Lease Liabilities - Current", S.ACCRUED_LIABILITY),
    _t("2500", "Line of Credit", S.LINE_OF_CREDIT),
    _t("2700", "Long-Term Debt", S.LONG_TERM_DEBT),
    _t("2750", "Lease Liabilities - Non-Current", S.LONG_TERM_DEBT),
    _t("2800", "Related Party Payables", S.LONG_TERM_DEBT),
    _t("2900", "Deferred Tax Liabilities", S.LONG_TERM_DEBT),
    _t("3000", "Common Stock & Paid-In Capital", S.COMMON_STOCK),
    _t("3900", "Retained Earnings", S.RETAINED_EARNINGS),
    _t("4000", "Revenue - Wholesale", S.OPERATING_REVENUE),
    _t("4010", "Revenue - Foodservice", S.OPERATING_REVENUE),
    _t("4020", "Revenue - Export", S.OPERATING_REVENUE),
    _t("4030", "Revenue - E-Commerce", S.OPERATING_REVENUE),
    _t("4100", "Other Revenue", S.OTHER_INCOME),
    _t("4900", "Contra Revenue", S.OPERATING_REVENUE),
    _t("5000", "Cost of Goods Sold", S.COST_OF_GOODS_SOLD),
    _t("5100", "Freight & Fulfillment", S.COST_OF_GOODS_SOLD),
    _t("5150", "Packaging", S.COST_OF_GOODS_SOLD),
    _t("5200", "Landed Cost Variance", S.COST_OF_GOODS_SOLD),
    _t("6000", "Marketing", S.OPERATING_EXPENSE),
    _t("6100", "Salaries & Wages", S.OPERATING_EXPENSE),
    _t("6120", "Payroll Taxes & Benefits", S.OPERATING_EXPENSE),
    _t("6150", "Commissions", S.OPERATING_EXPENSE),
    _t("6190", "Other Personnel Costs", S.OPERATING_EXPENSE),
    _t("6200", "Utilities", S.OPERATING_EXPENSE),
    _t("6220", "Telecommunications", S.OPERATING_EXPENSE),
    _t("6300", "Rent & Occupancy", S.OPERATING_EXPENSE),
    _t("6420", "Vehicle & Delivery", S.OPERATING_EXPENSE),
    _t("6500", "Insurance", S.OPERATING_EXPENSE),
    _t("6600", "Repairs & Maintenance", S.OPERATING_EXPENSE),
    _t("6610", "Equipment Leases", S.OPERATING_EXPENSE),
    _t("6700", "Depreciation & Amortization", S.OPERATING_EXPENSE),
    _t("6800", "Bad Debt", S.OPERATING_EXPENSE),
    _t("6900", "Office & Administrative", S.OPERATING_EXPENSE),
    _t("6920", "Bank & Merchant Fees", S.OPERATING_EXPENSE),
    _t("6940", "Professional Services", S.OPERATING_EXPENSE),
    _t("6960", "Software & IT", S.OPERATING_EXPENSE),
    _t("6970", "Facilities Services", S.OPERATING_EXPENSE),
    _t("6980", "Taxes & Licenses", S.OPERATING_EXPENSE),
    _t("6990", "Research & Development", S.OPERATING_EXPENSE),
    _t("7100", "Foreign Exchange Gain/Loss", S.OTHER_EXPENSE),
    _t("7200", "Interest Expense", S.OTHER_EXPENSE),
    _t("7300", "Other Income & Expense", S.OTHER_EXPENSE),
    _t("7500", "Income Tax Expense", S.OTHER_EXPENSE),
)  # fmt: skip

TARGET_BY_CODE: Final = {account.code: account for account in TARGET_ACCOUNTS}
LEGACY_BY_CODE: Final = {account.code: account for account in LEGACY_ACCOUNTS}


def correct_account_mapping() -> dict[str, str]:
    """The implementation team's legacy → target mapping table, before any mapping error."""
    return {
        account.code: account.target for account in LEGACY_ACCOUNTS if account.target is not None
    }
