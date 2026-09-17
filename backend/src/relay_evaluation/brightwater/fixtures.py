"""Minimal, independent reader for Brightwater fixture files (evaluation oracle only).

Deliberately simple: Python's csv module, the documented encodings, and a field-count check that
quarantines malformed physical rows. It is a reference for verifying ground truth, not Relay's
ingestion pipeline.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from relay.core.dates import DateFormat, parse_business_date
from relay.core.money import AmountFormat, parse_amount_text

LEDGERPRO_AMOUNT: Final = AmountFormat(thousands_separator=",")
_US_DATE: Final = re.compile(r"\d{2}/\d{2}/\d{4}")
_NUMBER: Final = re.compile(r"-?[\d,]+\.\d+|-?\d+")


@dataclass(frozen=True, slots=True)
class MalformedRow:
    line_start: int
    line_end: int
    raw_text: str
    field_count: int


@dataclass(frozen=True, slots=True)
class Table:
    header: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    malformed: tuple[MalformedRow, ...]


def encoding_for(path: str) -> str:
    if path.startswith("ledgerpro/"):
        return "cp1252"
    if path.startswith("firstcascade/"):
        return "utf-8-sig"
    return "utf-8"


def read_table(path: str, content: bytes) -> Table:
    text = content.decode(encoding_for(path))
    physical = text.splitlines()
    reader = csv.reader(io.StringIO(text, newline=""))
    header = tuple(next(reader))
    rows: list[dict[str, str]] = []
    malformed: list[MalformedRow] = []
    line = 1
    for record in csv.reader(io.StringIO("\n".join(physical[1:]), newline="")):
        line += 1
        if len(record) != len(header):
            malformed.append(MalformedRow(line, line, physical[line - 1], len(record)))
            continue
        rows.append(dict(zip(header, record, strict=True)))
    return Table(header=header, rows=tuple(rows), malformed=tuple(malformed))


def normalize(value: str) -> str:
    """Canonical text for comparison: amounts as plain decimals, MM/DD/YYYY dates as ISO."""
    stripped = value.strip()
    if _US_DATE.fullmatch(stripped):
        return parse_business_date(stripped, DateFormat.US_PADDED).isoformat()
    if _NUMBER.fullmatch(stripped) and ("." in stripped or "," in stripped):
        try:
            return format(parse_amount_text(stripped, LEDGERPRO_AMOUNT).normalize(), "f")
        except ValueError:
            return stripped
    return stripped


def normalize_expected(value: object) -> str:
    text = str(value)
    if _NUMBER.fullmatch(text) and "." in text:
        return format(Decimal(text).normalize(), "f")
    return text


def amount(value: str) -> Decimal:
    if not value.strip():
        return Decimal(0)
    return parse_amount_text(value, LEDGERPRO_AMOUNT)
