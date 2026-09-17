"""Deterministic column mapping suggestions and previews. Pure.

Suggestions match file headers to canonical fields by normalized name or a general synonym list, and
pick parsing steps from the column profile. They are proposals: an operator reviews and edits them,
and an approved change request makes them effective. Nothing here knows any particular company.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from relay.core.errors import InvalidInputError
from relay.mapping.registry import CanonicalField, FieldKind, fields_for
from relay.mapping.transforms import DatasetMapping, FieldMapping, MappingConfigError, Value
from relay.profiling.domain import ColumnProfile, DatasetProfile

MAX_PREVIEW_ROWS: Final = 50


def normalize_header(text: str) -> str:
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())


@dataclass(frozen=True, slots=True)
class FieldSuggestion:
    field: str
    kind: str
    required: bool
    specification: dict[str, Any] | None
    """The FieldMapping specification, or ``None`` when no column matched."""
    basis: str | None
    """``exact`` (header equals the field name) or ``synonym``."""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    dataset_type: str
    fields: tuple[FieldSuggestion, ...]
    unmatched_columns: tuple[str, ...]

    def config(self) -> dict[str, Any]:
        return {
            "fields": {f.field: f.specification for f in self.fields if f.specification},
            "exclude_rows_where_blank": [],
        }


@dataclass(slots=True)
class _Columns:
    by_normal: dict[str, str]
    used: set[str] = field(default_factory=set)

    def take(self, names: Sequence[str]) -> str | None:
        for name in names:
            column = self.by_normal.get(normalize_header(name))
            if column is not None and column not in self.used:
                self.used.add(column)
                return column
        return None


def _dominant(profile: ColumnProfile | None, label: str) -> bool:
    """The pattern matches some values and no other pattern matches more."""
    if profile is None:
        return False
    count = profile.pattern_counts.get(label, 0)
    return count > 0 and count >= max(profile.pattern_counts.values())


def _steps(  # noqa: PLR0912 - one branch per field kind
    spec: CanonicalField, profile: ColumnProfile | None
) -> tuple[list[dict[str, Any]], list[str]]:
    steps: list[dict[str, Any]] = [{"step": "trim"}]
    notes: list[str] = []
    if not spec.required and spec.kind not in {FieldKind.CODE, FieldKind.TEXT}:
        steps.append({"step": "empty_to_null"})
    if spec.kind is FieldKind.DATE:
        if _dominant(profile, "date_mm_dd_yyyy"):
            steps.append({"step": "parse_date", "format": "MM/DD/YYYY"})
            if profile is not None and profile.ambiguous_date_count:
                notes.append(
                    f"{profile.ambiguous_date_count} values also read as DD/MM/YYYY; confirm"
                )
        elif _dominant(profile, "date_yyyy_mm_dd"):
            steps.append({"step": "parse_date", "format": "YYYY-MM-DD"})
        else:
            notes.append("choose the date format")
    elif spec.kind is FieldKind.PERIOD:
        if _dominant(profile, "period_mm_yyyy"):
            steps.append({"step": "parse_period", "format": "MM/YYYY"})
        else:
            notes.append("choose the period format")
    elif spec.kind in {FieldKind.AMOUNT, FieldKind.RATE}:
        grouped = profile is not None and profile.pattern_counts.get("amount_grouped", 0) > 0
        steps.append(
            {"step": "parse_decimal", "thousands_separator": ","}
            if grouped
            else {"step": "parse_decimal"}
        )
    elif spec.kind is FieldKind.INTEGER:
        steps.append({"step": "parse_integer"})
    elif spec.kind is FieldKind.CURRENCY:
        steps.append({"step": "currency"})
    elif spec.kind is FieldKind.BOOLEAN:
        notes.append("map the column's values to true and false")
    elif spec.kind is FieldKind.ENUM:
        notes.append("map the column's values to: " + ", ".join(spec.values))
    return steps, notes


def suggest(
    dataset_type: str, header: Sequence[str], profile: DatasetProfile | None = None
) -> MappingSuggestion:
    columns = _Columns({normalize_header(h): h for h in reversed(header)})
    profiles = {c.name: c for c in profile.columns} if profile else {}
    suggestions = []
    # Required fields choose first, so an optional field cannot take a required field's column.
    ordered = sorted(fields_for(dataset_type), key=lambda f: not f.required)
    for spec in ordered:
        basis: str | None = None
        specification: dict[str, Any] | None = None
        notes: list[str] = []
        if spec.kind is FieldKind.SIGNED_AMOUNT:
            debit = columns.take(["debit", "debit amount", "dr"])
            credit = columns.take(["credit", "credit amount", "cr"]) if debit else None
            if debit and credit:
                grouped = any(
                    profiles.get(c) is not None
                    and profiles[c].pattern_counts.get("amount_grouped", 0) > 0
                    for c in (debit, credit)
                )
                specification = {
                    "debit_credit": {
                        "debit": debit,
                        "credit": credit,
                        **({"thousands_separator": ","} if grouped else {}),
                    }
                }
                basis = "synonym"
            elif debit:
                columns.used.discard(debit)
        if specification is None:
            exact = columns.take([spec.name])
            column = exact or columns.take(spec.synonyms)
            if column is not None:
                basis = "exact" if exact else "synonym"
                steps, notes = _steps(spec, profiles.get(column))
                specification = {"source": column, "steps": steps}
                if not spec.required:
                    specification["required"] = False
        suggestions.append(
            FieldSuggestion(
                spec.name,
                spec.kind.value,
                spec.required,
                specification,
                basis,
                tuple(notes),
            )
        )
    by_name = {s.field: s for s in suggestions}
    return MappingSuggestion(
        dataset_type=dataset_type,
        fields=tuple(by_name[f.name] for f in fields_for(dataset_type)),
        unmatched_columns=tuple(h for h in header if h not in columns.used),
    )


def _text(value: Value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass(frozen=True, slots=True)
class PreviewRow:
    row_number: int
    values: dict[str, Any]
    errors: dict[str, str]
    excluded: bool


def preview(
    dataset_type: str,
    config: Mapping[str, Any],
    header: Sequence[str],
    rows: Sequence[tuple[int, Mapping[str, str]]],
) -> list[PreviewRow]:
    """Apply a mapping configuration to sample rows, reporting per-field errors instead of raising.

    Raises ``MappingConfigError`` when the configuration itself is invalid.
    """
    mapping = DatasetMapping.parse(dataset_type, config, header)
    output = []
    for row_number, row in rows[:MAX_PREVIEW_ROWS]:
        values: dict[str, Any] = {}
        errors: dict[str, str] = {}
        field_mapping: FieldMapping
        for field_mapping in mapping.fields:
            try:
                value = field_mapping.apply(row)
            except (InvalidInputError, MappingConfigError) as exc:
                errors[field_mapping.target] = exc.detail
                continue
            if value is None and field_mapping.required:
                errors[field_mapping.target] = "required value is blank"
            values[field_mapping.target] = _text(value)
        output.append(PreviewRow(row_number, values, errors, mapping.excludes(row)))
    return output
