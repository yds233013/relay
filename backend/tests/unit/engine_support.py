"""Helpers for engine tests: a small clean synthetic migration and targeted edits to its files.

The synthetic company is unrelated to Brightwater, so these tests exercise the rules as general
accounting checks rather than as answers to one scenario.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from decimal import Decimal
from functools import cache
from typing import Any

from relay.engine.inputs import MigrationInputs, build_inputs
from relay.engine.overlays import Overlays
from relay.engine.pipeline import EngineResult, run_engine
from relay.engine.policy import Policy
from relay_evaluation.paths import FIXTURES_DIR
from relay_scenarios.brightwater.exports import bank_csv, implementation_csv, ledgerpro_csv
from relay_scenarios.volume import build_volume_migration, export_volume_migration

GL = "ledgerpro/ledgerpro_gl_detail_2026H1.csv"
TRIAL_BALANCE = "ledgerpro/ledgerpro_trial_balance_by_period.csv"
CUSTOMERS = "ledgerpro/ledgerpro_customers.csv"
VENDORS = "ledgerpro/ledgerpro_vendors.csv"
INVOICES = "ledgerpro/ledgerpro_invoices.csv"
BILLS = "ledgerpro/ledgerpro_bills.csv"
PAYMENTS = "ledgerpro/ledgerpro_payments.csv"
BANK = "firstcascade/firstcascade_4471_statement.csv"
MAPPING = "implementation/account_mapping_v2.csv"
TARGET_CHART = "implementation/target_chart_of_accounts.csv"

Rows = list[dict[str, str]]


@cache
def _mapping_set_text() -> str:
    path = FIXTURES_DIR / "demo" / "brightwater_config" / "column_mapping_set_v1.json"
    return path.read_text(encoding="utf-8")


@cache
def _base_files() -> tuple[tuple[str, bytes], ...]:
    return tuple(export_volume_migration(build_volume_migration(400, seed=7)).items())


def base_files() -> dict[str, bytes]:
    return dict(_base_files())


def inputs(files: dict[str, bytes]) -> MigrationInputs:
    mapping: dict[str, Any] = json.loads(_mapping_set_text())
    return build_inputs(json.loads(files["migration.json"]), files, mapping)


def run(
    files: dict[str, bytes], overlays: Overlays | None = None, policy: Policy | None = None
) -> EngineResult:
    return run_engine(inputs(files), overlays, policy)


def _encoding(path: str) -> str:
    if path.startswith("ledgerpro/"):
        return "cp1252"
    if path.startswith("firstcascade/"):
        return "utf-8-sig"
    return "utf-8"


def read_rows(files: dict[str, bytes], path: str) -> tuple[list[str], Rows]:
    reader = csv.DictReader(io.StringIO(files[path].decode(_encoding(path)), newline=""))
    return list(reader.fieldnames or []), list(reader)


def write_rows(files: dict[str, bytes], path: str, header: list[str], rows: Rows) -> None:
    values = [[row[column] for column in header] for row in rows]
    if path.startswith("ledgerpro/"):
        files[path] = ledgerpro_csv(header, values)
    elif path.startswith("firstcascade/"):
        files[path] = bank_csv(header, values)
    else:
        files[path] = implementation_csv(header, values)


def edit(files: dict[str, bytes], path: str, change: Callable[[Rows], Rows]) -> dict[str, bytes]:
    header, rows = read_rows(files, path)
    write_rows(files, path, header, change(rows))
    return files


def recompute_bank_balances(files: dict[str, bytes], opening: Decimal) -> None:
    header, rows = read_rows(files, BANK)
    rows.sort(key=lambda r: r["Posted Date"])
    balance = opening
    for row in rows:
        balance += Decimal(row["Amount"])
        row["Balance"] = f"{balance:.2f}"
    write_rows(files, BANK, header, rows)


def rules_fired(result: EngineResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in result.exceptions:
        counts[finding.rule_id] = counts.get(finding.rule_id, 0) + 1
    return counts
