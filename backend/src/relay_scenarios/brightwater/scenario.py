"""Brightwater scenario assembly: clean books → injected defects → source-style files."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from relay_scenarios.brightwater.clean import build_clean_universe
from relay_scenarios.brightwater.constants import DEFAULT_SEED
from relay_scenarios.brightwater.exports import ExportFilters, export_all
from relay_scenarios.brightwater.injectors import ALL_DEFECTS, apply_defects
from relay_scenarios.brightwater.universe import LegacyUniverse
from relay_scenarios.errors import ScenarioConsistencyError

CHECKSUM_FILE = "SHA256SUMS"


@dataclass(frozen=True, slots=True)
class Scenario:
    universe: LegacyUniverse
    files: dict[str, bytes]


_CLEAN_CACHE: dict[int, LegacyUniverse] = {}


def clean_universe(seed: int = DEFAULT_SEED) -> LegacyUniverse:
    """A private deep copy of the verified clean books (built once per seed per process)."""
    if seed not in _CLEAN_CACHE:
        _CLEAN_CACHE[seed] = build_clean_universe(seed)
    return copy.deepcopy(_CLEAN_CACHE[seed])


def build_scenario(seed: int = DEFAULT_SEED, defects: Sequence[str] = ALL_DEFECTS) -> Scenario:
    universe = apply_defects(clean_universe(seed), defects)
    return Scenario(universe=universe, files=export_all(universe))


def checksum_manifest(files: dict[str, bytes]) -> bytes:
    lines = [
        f"{hashlib.sha256(content).hexdigest()}  {path}" for path, content in sorted(files.items())
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_fixtures(scenario: Scenario, out_dir: Path) -> list[Path]:
    """Write files plus ``SHA256SUMS``; never writes outside ``out_dir`` or leaves stale files."""
    return write_files(scenario.files, out_dir)


def write_files(files: dict[str, bytes], out_dir: Path) -> list[Path]:
    """Write files plus ``SHA256SUMS``; never writes outside ``out_dir`` or leaves stale files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    root = out_dir.resolve()
    expected = {*files, CHECKSUM_FILE}
    stale = [
        p for p in root.rglob("*") if p.is_file() and p.relative_to(root).as_posix() not in expected
    ]
    for path in stale:
        path.unlink()
    written: list[Path] = []
    for relative, content in {**files, CHECKSUM_FILE: checksum_manifest(files)}.items():
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ScenarioConsistencyError(f"refusing to write outside {root}: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        written.append(target)
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return written


UNFILTERED_EXPORTS: Final = ExportFilters(
    include_inactive_accounts=True,
    include_inactive_customers=True,
    include_unprinted_invoices=True,
)
"""The export options a customer chooses when asked to export everything, without filters."""


def reexport_files(scenario: Scenario) -> dict[str, bytes]:
    """The files that change when the same books are exported without filters.

    These are the corrected exports a customer sends after the first imports; Relay ingests them
    as new imports of the existing datasets.
    """
    unfiltered = export_all(scenario.universe, UNFILTERED_EXPORTS)
    return {
        path: content
        for path, content in sorted(unfiltered.items())
        if path != "migration.json" and scenario.files.get(path) != content
    }
