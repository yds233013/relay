"""Dataset profiling: per-column shape statistics without storing any data values (SEC-21).

Pure: operates on raw row values. The profile helps an operator choose column mappings (for example
which date format a column uses) and never feeds validation results.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict

PROFILER_VERSION: Final = 1
_DISTINCT_CAP: Final = 10_000
_PATTERNS: Final = {
    "date_mm_dd_yyyy": re.compile(r"\d{2}/\d{2}/\d{4}"),
    "date_yyyy_mm_dd": re.compile(r"\d{4}-\d{2}-\d{2}"),
    "period_mm_yyyy": re.compile(r"\d{2}/\d{4}"),
    "amount_grouped": re.compile(r"-?\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?"),
    "decimal": re.compile(r"-?\(?\d+\.\d+\)?"),
    "integer": re.compile(r"-?\d+"),
}


class ColumnProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    blank_count: int
    distinct_count: int
    distinct_count_capped: bool
    max_length: int
    pattern_counts: dict[str, int]
    ambiguous_date_count: int
    """MM/DD vs DD/MM ambiguity: both leading parts are 12 or below."""


class DatasetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profiler_version: int
    row_count: int
    quarantined_count: int
    columns: list[ColumnProfile]


def profile_rows(
    header: Sequence[str], rows: Iterable[Mapping[str, str]], quarantined_count: int
) -> DatasetProfile:
    blanks = dict.fromkeys(header, 0)
    distinct: dict[str, set[str]] = {name: set() for name in header}
    capped = dict.fromkeys(header, False)
    lengths = dict.fromkeys(header, 0)
    patterns: dict[str, dict[str, int]] = {name: dict.fromkeys(_PATTERNS, 0) for name in header}
    ambiguous = dict.fromkeys(header, 0)
    count = 0
    for row in rows:
        count += 1
        for name in header:
            value = row.get(name, "").strip()
            if not value:
                blanks[name] += 1
                continue
            lengths[name] = max(lengths[name], len(value))
            if len(distinct[name]) < _DISTINCT_CAP:
                distinct[name].add(value)
            else:
                capped[name] = True
            for label, pattern in _PATTERNS.items():
                if pattern.fullmatch(value):
                    patterns[name][label] += 1
            if _PATTERNS["date_mm_dd_yyyy"].fullmatch(value):
                first, second = int(value[:2]), int(value[3:5])
                if first <= 12 and second <= 12 and first != second:
                    ambiguous[name] += 1
    return DatasetProfile(
        profiler_version=PROFILER_VERSION,
        row_count=count,
        quarantined_count=quarantined_count,
        columns=[
            ColumnProfile(
                name=name,
                blank_count=blanks[name],
                distinct_count=len(distinct[name]),
                distinct_count_capped=capped[name],
                max_length=lengths[name],
                pattern_counts={k: v for k, v in patterns[name].items() if v},
                ambiguous_date_count=ambiguous[name],
            )
            for name in header
        ],
    )
