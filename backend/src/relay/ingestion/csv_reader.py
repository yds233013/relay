"""CSV reading with physical-line lineage and quarantine.

Rows are returned exactly as read: every value is the raw string. A physical row whose field count
does not match the header is **quarantined**, never guessed at. Consecutive malformed physical lines
are grouped into one quarantined record, because a line break inside an unquoted field splits a
single logical row across lines.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from typing import ClassVar, Final

from relay.core.errors import InvalidInputError

MAX_FIELD_CHARS: Final = 10_000
MAX_ROWS: Final = 2_000_000
MAX_COLUMNS: Final = 512
MAX_RECORD_LINES: Final = 20
QUARANTINE_TEXT_LIMIT: Final = 4_000


class SourceFileError(InvalidInputError):
    code: ClassVar[str] = "ingestion.unreadable_file"
    title: ClassVar[str] = "Source file cannot be read"


@dataclass(frozen=True, slots=True)
class SourceRow:
    row_number: int
    """1-based data row number (header excluded, quarantined rows not counted)."""
    line_start: int
    line_end: int
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class QuarantinedRow:
    line_start: int
    line_end: int
    raw_text: str
    field_counts: tuple[int, ...]
    reason: str

    @property
    def key(self) -> str:
        """Stable identity of the quarantined content (independent of line position)."""
        return hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RawTable:
    file_name: str
    header: tuple[str, ...]
    rows: tuple[SourceRow, ...]
    quarantined: tuple[QuarantinedRow, ...]
    physical_lines: int


def decode(content: bytes, encoding: str) -> str:
    try:
        return content.decode(encoding)
    except UnicodeDecodeError as exc:
        raise SourceFileError(f"file is not valid {encoding}: byte {exc.start}") from exc


def _read_record(physical: list[str], index: int, delimiter: str) -> tuple[list[str] | None, int]:
    """Parse one logical record starting at ``physical[index]``.

    A quoted field may legitimately span lines, up to ``MAX_RECORD_LINES``. A quote that is still
    open after that is treated as an unterminated quote on the first line only, so one stray quote
    cannot swallow the rest of the file.
    """
    limit = min(len(physical) - index, MAX_RECORD_LINES)
    for consumed in range(1, limit + 1):
        chunk = "".join(physical[index : index + consumed])
        if chunk.count('"') % 2:
            continue
        parsed = list(csv.reader(io.StringIO(chunk, newline=""), delimiter=delimiter))
        return (parsed[0], consumed) if len(parsed) == 1 else (None, consumed)
    return None, 1


def _read_header(line: str, delimiter: str) -> tuple[str, ...]:
    header = tuple(field.strip() for field in next(csv.reader([line], delimiter=delimiter)))
    if len(set(header)) != len(header) or any(not h for h in header):
        raise SourceFileError("header has blank or duplicate column names")
    if len(header) > MAX_COLUMNS:
        # SEC-01: a pathological header would otherwise size every row's dict and every profile.
        raise SourceFileError(f"file has {len(header)} columns; at most {MAX_COLUMNS} are read")
    return header


def read_csv(file_name: str, content: bytes, *, encoding: str, delimiter: str = ",") -> RawTable:
    text = decode(content, encoding)
    if "\x00" in text:
        raise SourceFileError("file contains NUL bytes; not a text CSV")
    physical = text.splitlines(keepends=True)
    if not physical:
        raise SourceFileError("file is empty")
    header = _read_header(physical[0], delimiter)

    rows: list[SourceRow] = []
    quarantined: list[QuarantinedRow] = []
    pending_lines: list[str] = []
    pending_counts: list[int] = []
    pending_start = 0

    def flush_pending() -> None:
        nonlocal pending_lines, pending_counts
        if pending_lines:
            raw = "".join(pending_lines)[:QUARANTINE_TEXT_LIMIT]
            quarantined.append(
                QuarantinedRow(
                    line_start=pending_start,
                    line_end=pending_start + len(pending_lines) - 1,
                    raw_text=raw,
                    field_counts=tuple(pending_counts),
                    reason="field_count_mismatch",
                )
            )
        pending_lines, pending_counts = [], []

    line_index = 1
    while line_index < len(physical):
        start = line_index + 1  # 1-based physical line number
        record, consumed = _read_record(physical, line_index, delimiter)
        if record is None:
            flush_pending()
            chunk = "".join(physical[line_index : line_index + consumed])
            quarantined.append(
                QuarantinedRow(
                    start,
                    start + consumed - 1,
                    chunk[:QUARANTINE_TEXT_LIMIT],
                    (),
                    "unterminated_quote",
                )
            )
            line_index += consumed
            continue
        if any(len(value) > MAX_FIELD_CHARS for value in record):
            flush_pending()
            quarantined.append(
                QuarantinedRow(
                    start,
                    start + consumed - 1,
                    "".join(physical[line_index : line_index + consumed])[:QUARANTINE_TEXT_LIMIT],
                    (len(record),),
                    "field_too_long",
                )
            )
            line_index += consumed
            continue
        if len(record) != len(header):
            if not pending_lines:
                pending_start = start
            pending_lines.append("".join(physical[line_index : line_index + consumed]))
            pending_counts.append(len(record))
            line_index += consumed
            continue
        flush_pending()
        if len(rows) >= MAX_ROWS:
            raise SourceFileError(f"file exceeds {MAX_ROWS} rows")
        rows.append(
            SourceRow(
                row_number=len(rows) + 1,
                line_start=start,
                line_end=start + consumed - 1,
                values=dict(zip(header, record, strict=True)),
            )
        )
        line_index += consumed
    flush_pending()
    return RawTable(
        file_name=file_name,
        header=header,
        rows=tuple(rows),
        quarantined=tuple(quarantined),
        physical_lines=len(physical),
    )


def repair_quarantined(
    table: RawTable, replacement_text: str, *, delimiter: str = ","
) -> dict[str, str]:
    """Parse operator-supplied repaired text for a quarantined record (one logical row)."""
    parsed = list(csv.reader(io.StringIO(replacement_text, newline=""), delimiter=delimiter))
    if len(parsed) != 1 or len(parsed[0]) != len(table.header):
        raise SourceFileError("repaired text must be exactly one row matching the header")
    return dict(zip(table.header, parsed[0], strict=True))


def reconstruct_quarantined(
    table: RawTable, row: QuarantinedRow, *, delimiter: str = ","
) -> dict[str, str] | None:
    """Best-effort provisional record: join the physical lines, replacing line breaks with spaces.

    Used only for control totals (activity reconciliation). Never used as staged data.
    """
    joined = row.raw_text.replace("\r\n", " ").replace("\n", " ").rstrip()
    parsed = list(csv.reader(io.StringIO(joined, newline=""), delimiter=delimiter))
    if len(parsed) == 1 and len(parsed[0]) == len(table.header):
        return dict(zip(table.header, parsed[0], strict=True))
    return None
