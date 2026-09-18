"""Column transforms: a closed set of typed steps (docs/data-model.md §6).

A field mapping reads one or more source columns and applies steps in order. There is no expression
language: every step is declared data and validated when the mapping set is loaded. A step that
cannot convert a value raises :class:`TransformError`, which normalization records as an exception
for that row and field. Nothing is guessed.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from relay.core.currency import Currency
from relay.core.dates import DateFormat, parse_business_date
from relay.core.errors import InvalidInputError, RelayError
from relay.core.money import AmountFormat, parse_amount_text, signed_ledger_amount


class TransformError(InvalidInputError):
    code: ClassVar[str] = "mapping.transform_failed"
    title: ClassVar[str] = "Value could not be transformed"


class MappingConfigError(RelayError):
    code: ClassVar[str] = "mapping.invalid_configuration"
    title: ClassVar[str] = "Invalid mapping configuration"
    http_status: ClassVar[int] = 422


type Value = str | Decimal | date | int | bool | Currency | None

# ASCII digits only, for the reason in core.money: a number must read as itself.
_PERIOD_FORMATS = {
    "MM/YYYY": re.compile(r"([0-9]{2})/([0-9]{4})"),
    "MM.YYYY": re.compile(r"([0-9]{2})\.([0-9]{4})"),
    "YYYY-MM": re.compile(r"([0-9]{4})-([0-9]{2})"),
    "YYYY/MM": re.compile(r"([0-9]{4})/([0-9]{2})"),
}


def _require_keys(step: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(step) - allowed - {"step"}
    if unknown:
        raise MappingConfigError(f"step {step['step']!r} has unknown options {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    options: Mapping[str, Any]

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> Step:
        name = raw.get("step")
        allowed = _STEP_OPTIONS.get(name) if isinstance(name, str) else None
        if allowed is None:
            raise MappingConfigError(f"unknown transform step {name!r}")
        _require_keys(raw, allowed)
        step = cls(name=str(name), options={k: v for k, v in raw.items() if k != "step"})
        if name == "parse_date":
            try:
                DateFormat(step.options["format"])
            except (KeyError, ValueError) as exc:
                raise MappingConfigError("parse_date requires a supported explicit format") from exc
        if name == "parse_period" and step.options.get("format") not in _PERIOD_FORMATS:
            raise MappingConfigError(
                "parse_period format must be one of " + ", ".join(sorted(_PERIOD_FORMATS))
            )
        if name == "regex_extract":
            try:
                re.compile(str(step.options["pattern"]))
            except (KeyError, re.error) as exc:
                raise MappingConfigError("regex_extract requires a valid pattern") from exc
        if name == "parse_decimal":
            _amount_format(step.options)
        return step


_STEP_OPTIONS: dict[str, set[str]] = {
    "trim": set(),
    "upper": set(),
    "empty_to_null": set(),
    "parse_decimal": {
        "decimal_separator",
        "thousands_separator",
        "parentheses_negative",
        "currency_symbols",
        "empty_as_zero",
    },
    "parse_date": {"format"},
    "parse_period": {"format"},
    "parse_integer": set(),
    "parse_boolean": {"true", "false"},
    "value_map": {"mapping", "default", "passthrough"},
    "regex_extract": {"pattern", "group"},
    "currency": set(),
    "constant": {"value"},
}


def _amount_format(options: Mapping[str, Any]) -> AmountFormat:
    symbols = options.get("currency_symbols", ())
    if isinstance(symbols, str) or not all(isinstance(symbol, str) for symbol in symbols):
        raise MappingConfigError("currency_symbols must be a list of strings")
    return _cached_amount_format(
        options.get("decimal_separator", "."),
        options.get("thousands_separator"),
        bool(options.get("parentheses_negative", False)),
        tuple(sorted(symbols)),
    )


@functools.cache
def _cached_amount_format(
    decimal_separator: str,
    thousands_separator: str | None,
    parentheses_negative: bool,
    currency_symbols: tuple[str, ...],
) -> AmountFormat:
    try:
        return AmountFormat(
            decimal_separator=decimal_separator,
            thousands_separator=thousands_separator,
            parentheses_negative=parentheses_negative,
            currency_symbols=frozenset(currency_symbols),
        )
    except InvalidInputError as exc:
        raise MappingConfigError(f"invalid amount format: {exc.detail}") from exc


def apply_step(step: Step, value: Value) -> Value:  # noqa: PLR0911, PLR0912 - one branch per step
    name, options = step.name, step.options
    if value is None and name not in {"constant"}:
        return None
    if name == "trim":
        return value.strip() if isinstance(value, str) else value
    if name == "upper":
        return value.upper() if isinstance(value, str) else value
    if name == "empty_to_null":
        return None if isinstance(value, str) and not value.strip() else value
    if name == "constant":
        return str(options["value"])
    text = _as_text(value, name)
    if name == "parse_decimal":
        if not text.strip():
            if options.get("empty_as_zero"):
                return Decimal(0)
            raise TransformError("amount is empty")
        return parse_amount_text(text, _amount_format(options))
    if name == "parse_date":
        return parse_business_date(text, DateFormat(options["format"]))
    if name == "parse_period":
        match = _PERIOD_FORMATS[options["format"]].fullmatch(text.strip())
        if match is None:
            raise TransformError(f"period does not match {options['format']}")
        month_first = options["format"].startswith("MM")
        month, year = (
            (match.group(1), match.group(2)) if month_first else (match.group(2), match.group(1))
        )
        if not 1 <= int(month) <= 12:
            raise TransformError("period month out of range")
        return f"{year}-{month}"
    if name == "parse_integer":
        if not re.fullmatch(r"-?\d+", text.strip()):
            raise TransformError("not an integer")
        return int(text.strip())
    if name == "parse_boolean":
        if text in options.get("true", ()):
            return True
        if text in options.get("false", ()):
            return False
        raise TransformError("value is not a declared boolean literal")
    if name == "value_map":
        mapping = options["mapping"]
        if text in mapping:
            return str(mapping[text])
        if options.get("passthrough"):
            return text
        if "default" in options:
            return None if options["default"] is None else str(options["default"])
        raise TransformError("value is not in the declared value map")
    if name == "regex_extract":
        match = re.search(str(options["pattern"]), text)
        if match is None:
            raise TransformError("value does not match the declared pattern")
        return match.group(int(options.get("group", 0)))
    if name == "currency":
        return Currency.of(text.strip())
    raise MappingConfigError(f"unhandled step {name}")  # pragma: no cover - guarded by Step.parse


def _as_text(value: Value, step: str) -> str:
    if not isinstance(value, str):
        raise TransformError(f"step {step} expects text")
    return value


@dataclass(frozen=True, slots=True)
class FieldMapping:
    target: str
    source: str | None
    steps: tuple[Step, ...]
    required: bool
    debit_credit: tuple[str, str] | None = None
    """For signed ledger amounts from separate debit and credit columns."""
    amount_format: Mapping[str, Any] | None = None

    @classmethod
    def parse(cls, target: str, raw: Mapping[str, Any]) -> FieldMapping:
        allowed = {"source", "steps", "required", "debit_credit"}
        if set(raw) - allowed:
            raise MappingConfigError(
                f"field {target!r} has unknown keys {sorted(set(raw) - allowed)}"
            )
        debit_credit = raw.get("debit_credit")
        if debit_credit is not None:
            if not isinstance(debit_credit, Mapping) or not {"debit", "credit"} <= set(
                debit_credit
            ):
                raise MappingConfigError(
                    f"field {target!r}: debit_credit needs debit and credit columns"
                )
            fmt = {k: v for k, v in debit_credit.items() if k not in {"debit", "credit"}}
            _amount_format(fmt)
            return cls(
                target,
                None,
                (),
                bool(raw.get("required", True)),
                (debit_credit["debit"], debit_credit["credit"]),
                fmt,
            )
        source = raw.get("source")
        steps = tuple(Step.parse(step) for step in raw.get("steps", []))
        if source is None and not any(step.name == "constant" for step in steps):
            raise MappingConfigError(f"field {target!r} needs a source column or a constant")
        return cls(target, source, steps, bool(raw.get("required", True)))

    def source_columns(self) -> tuple[str, ...]:
        if self.debit_credit:
            return self.debit_credit
        return (self.source,) if self.source else ()

    def apply(self, row: Mapping[str, str]) -> Value:
        if self.debit_credit is not None:
            fmt = _amount_format(self.amount_format or {})
            debit_text, credit_text = (row.get(c, "") for c in self.debit_credit)
            debit = parse_amount_text(debit_text, fmt) if debit_text.strip() else None
            credit = parse_amount_text(credit_text, fmt) if credit_text.strip() else None
            return signed_ledger_amount(debit, credit)
        value: Value = row.get(self.source, "") if self.source else ""
        for step in self.steps:
            value = apply_step(step, value)
        if (
            isinstance(value, str)
            and not value.strip()
            and not any(s.name == "constant" for s in self.steps)
        ):
            value = None
        return value


@dataclass(frozen=True, slots=True)
class DatasetMapping:
    dataset_type: str
    fields: tuple[FieldMapping, ...]
    exclude_rows_where_blank: tuple[str, ...]

    @classmethod
    def parse(
        cls, dataset_type: str, raw: Mapping[str, Any], header: Sequence[str] | None = None
    ) -> DatasetMapping:
        fields = tuple(
            FieldMapping.parse(target, spec) for target, spec in raw.get("fields", {}).items()
        )
        exclude = tuple(raw.get("exclude_rows_where_blank", ()))
        mapping = cls(dataset_type, fields, exclude)
        if header is not None:
            missing = sorted(
                {c for f in fields for c in f.source_columns()} - set(header)
                | set(exclude) - set(header)
            )
            if missing:
                raise MappingConfigError(f"{dataset_type}: columns not in file header: {missing}")
        return mapping

    def excludes(self, row: Mapping[str, str]) -> bool:
        return any(not row.get(column, "").strip() for column in self.exclude_rows_where_blank)
