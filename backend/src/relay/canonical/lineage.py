"""Lineage: where a canonical record came from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from relay.core.errors import InvalidInputError


class LineageError(InvalidInputError):
    code: ClassVar[str] = "canonical.invalid_lineage"
    title: ClassVar[str] = "Invalid lineage"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceLocation:
    """A row in a source file: 1-based data row number and the physical lines it spans."""

    dataset: str
    file_name: str
    row_number: int
    line_start: int
    line_end: int

    def __post_init__(self) -> None:
        if not self.dataset or not self.file_name:
            raise LineageError("dataset and file name are required")
        if self.row_number < 1 or self.line_start < 1 or self.line_end < self.line_start:
            raise LineageError("row and line numbers must be positive and ordered")
