"""Assemble the Kestrel scenario: clean books, the defects, and the migration descriptor.

Evaluation truth lives in ``evaluation/kestrel/`` and is never read here. This module knows which
defects it plants; it does not know what the engine is supposed to report about them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from relay_scenarios.kestrel.books import (
    CUTOVER,
    FISCAL_YEAR_START_MONTH,
    FUNCTIONAL,
    GO_LIVE,
    HISTORY_START,
    OPENING,
    Books,
    build_books,
)
from relay_scenarios.kestrel.defects import ALL_DEFECTS, apply_defects
from relay_scenarios.kestrel.exports import export_books

COMPANY: Final = "Kestrel Instruments Ltd"
CHECKSUM_FILE: Final = "checksums.sha256"

_DATASETS: Final = (
    ("legacy_coa", "tallyworks/accounts.csv", None),
    ("trial_balance", "tallyworks/balances.csv", None),
    ("gl_detail", "tallyworks/journal.csv", None),
    ("customers", "tallyworks/customers.csv", None),
    ("vendors", "tallyworks/suppliers.csv", None),
    ("invoices", "tallyworks/sales_invoices.csv", None),
    ("bills", "tallyworks/purchase_invoices.csv", None),
    ("payments", "tallyworks/settlements.csv", None),
    ("ar_aging", "tallyworks/debtors_ageing_20251231.csv", "2025-12-31"),
    ("ar_aging", "tallyworks/debtors_ageing_20260630.csv", "2026-06-30"),
    ("ap_aging", "tallyworks/creditors_ageing_20251231.csv", "2025-12-31"),
    ("ap_aging", "tallyworks/creditors_ageing_20260630.csv", "2026-06-30"),
    ("bank_transactions", "nordbank/statement.csv", None),
    ("fx_rates", "nordbank/fx_usd_eur.csv", None),
    ("target_coa", "implementation/target_accounts.csv", None),
    ("account_mapping", "implementation/mapping.csv", None),
)


@dataclass(frozen=True, slots=True)
class Scenario:
    files: dict[str, bytes]
    planted: tuple[str, ...]
    books: Books
    """The clean books the exports were written from — for summaries, never for expectations."""


def descriptor() -> dict[str, Any]:
    """The migration descriptor Relay reads: plan, source systems, datasets and their formats."""
    return {
        "fictional": True,
        "notice": "Fictional sample data. All companies, people and figures are invented.",
        "company": {
            "name": COMPANY,
            "functional_currency": FUNCTIONAL,
            "fiscal_year_start_month": FISCAL_YEAR_START_MONTH,
        },
        "conversion_plan": {
            "opening_balance_date": OPENING.isoformat(),
            "history_start_date": HISTORY_START.isoformat(),
            "cutover_date": CUTOVER.isoformat(),
            "go_live_date": GO_LIVE.isoformat(),
            "bank_clearing_window_days": 10,
        },
        "source_systems": [
            {"id": "tallyworks", "name": "Tallyworks 9", "kind": "legacy_erp"},
            {"id": "nordbank", "name": "Nordbank (account NB-8842)", "kind": "bank"},
            {"id": "implementation", "name": "Implementation team", "kind": "other"},
        ],
        "datasets": [
            {
                "dataset_type": dataset_type,
                "source_system": path.split("/", 1)[0],
                "file": path,
                "encoding": "utf-8-sig",
                "delimiter": ";",
                **({"as_of": as_of} if as_of else {}),
            }
            for dataset_type, path, as_of in _DATASETS
        ],
    }


def build_scenario(*, defects: tuple[str, ...] = ALL_DEFECTS) -> Scenario:
    books = build_books()
    files = export_books(books)
    planted = apply_defects(files, defects)
    files["migration.json"] = (json.dumps(descriptor(), indent=2) + "\n").encode("utf-8")
    return Scenario(files=dict(sorted(files.items())), planted=planted, books=books)


def checksum_manifest(files: dict[str, bytes]) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {name}"
        for name, content in sorted(files.items())
        if name != CHECKSUM_FILE
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_fixtures(scenario: Scenario, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, content in scenario.files.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (out / CHECKSUM_FILE).write_bytes(checksum_manifest(scenario.files))
