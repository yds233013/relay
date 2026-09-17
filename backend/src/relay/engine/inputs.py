"""Engine inputs: the migration descriptor, source files, and the approved column mapping set."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

from relay.core.currency import Currency
from relay.core.dates import parse_iso_business_date
from relay.core.errors import InvalidInputError
from relay.core.hashing import sha256_hex

DESCRIPTOR_FILE = "migration.json"


class EngineInputError(InvalidInputError):
    code: ClassVar[str] = "engine.invalid_inputs"
    title: ClassVar[str] = "Invalid engine inputs"


@dataclass(frozen=True, slots=True)
class ConversionPlan:
    opening_balance_date: date
    history_start_date: date
    cutover_date: date
    go_live_date: date
    bank_clearing_window_days: int

    def __post_init__(self) -> None:
        if not (
            self.opening_balance_date
            < self.history_start_date
            <= self.cutover_date
            < self.go_live_date
        ):
            raise EngineInputError(
                "conversion plan dates must satisfy opening < history start <= cutover < go-live"
            )


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    file: str
    dataset_type: str
    source_system: str
    encoding: str
    as_of: date | None
    delimiter: str = ","


@dataclass(frozen=True, slots=True)
class BankAccountLink:
    file: str
    bank_account: str
    gl_account: str


@dataclass(frozen=True, slots=True)
class MigrationInputs:
    plan: ConversionPlan
    functional_currency: Currency
    fiscal_year_start_month: int
    datasets: tuple[DatasetSpec, ...]
    files: Mapping[str, bytes]
    mapping_set: Mapping[str, Any]
    bank_links: tuple[BankAccountLink, ...]
    file_hashes: Mapping[str, str] = field(default_factory=dict)
    governed_account_mapping: Mapping[str, str] | None = None
    """An approved account mapping set (legacy code → target code).

    When present it replaces the pairs read from ``account_mapping`` files, which are still staged
    so their rows stay inspectable and duplicate keys are still reported.
    """

    def datasets_of(self, dataset_type: str) -> list[DatasetSpec]:
        return [spec for spec in self.datasets if spec.dataset_type == dataset_type]


def _date(raw: Mapping[str, Any], key: str) -> date:
    try:
        return parse_iso_business_date(raw[key])
    except KeyError as exc:
        raise EngineInputError(f"descriptor is missing {key}") from exc


def build_inputs(
    descriptor: Mapping[str, Any], files: Mapping[str, bytes], mapping_set: Mapping[str, Any]
) -> MigrationInputs:
    plan_raw = descriptor.get("conversion_plan", {})
    plan = ConversionPlan(
        opening_balance_date=_date(plan_raw, "opening_balance_date"),
        history_start_date=_date(plan_raw, "history_start_date"),
        cutover_date=_date(plan_raw, "cutover_date"),
        go_live_date=_date(plan_raw, "go_live_date"),
        bank_clearing_window_days=int(plan_raw.get("bank_clearing_window_days", 15)),
    )
    company = descriptor.get("company", {})
    datasets = []
    for item in descriptor.get("datasets", []):
        path = item["file"]
        if path not in files:
            raise EngineInputError(f"descriptor lists {path} but the file was not provided")
        datasets.append(
            DatasetSpec(
                file=path,
                dataset_type=item["dataset_type"],
                source_system=item.get("source_system", ""),
                encoding=item.get("encoding", "utf-8"),
                as_of=parse_iso_business_date(item["as_of"]) if item.get("as_of") else None,
                delimiter=item.get("delimiter", ","),
            )
        )
    links = tuple(
        BankAccountLink(
            file=link["file"], bank_account=link["bank_account"], gl_account=link["gl_account"]
        )
        for link in mapping_set.get("bank_account_links", [])
    )
    return MigrationInputs(
        plan=plan,
        functional_currency=Currency.of(company.get("functional_currency", "USD")),
        fiscal_year_start_month=int(company.get("fiscal_year_start_month", 1)),
        datasets=tuple(datasets),
        files=dict(files),
        mapping_set=mapping_set,
        bank_links=links,
        file_hashes={spec.file: sha256_hex(files[spec.file]) for spec in datasets},
    )


def load_inputs(migration_dir: Path, mapping_set_path: Path) -> MigrationInputs:
    """Read a migration directory (descriptor plus files) and an approved column mapping set."""
    descriptor = json.loads((migration_dir / DESCRIPTOR_FILE).read_text(encoding="utf-8"))
    files = {
        item["file"]: (migration_dir / item["file"]).read_bytes()
        for item in descriptor.get("datasets", [])
    }
    mapping_set = json.loads(mapping_set_path.read_text(encoding="utf-8"))
    return build_inputs(descriptor, files, mapping_set)
