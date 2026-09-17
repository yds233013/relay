"""Exceptions: deterministic rule and reconciliation failures within one run."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from relay.canonical.lineage import SourceLocation
from relay.core.hashing import fingerprint as content_fingerprint


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


class Nature(StrEnum):
    MIGRATION_DEFECT = "migration_defect"
    SOURCE_ANOMALY = "source_anomaly"


class Category(StrEnum):
    COMPLETENESS = "completeness"
    MAPPING = "mapping"
    LEDGER_INTEGRITY = "ledger_integrity"
    SUBLEDGER = "subledger"
    CASH = "cash"
    MASTER_DATA = "master_data"
    CURRENCY = "currency"
    DATES = "dates"
    AI_SAFETY = "ai_safety"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RuleException:
    rule_id: str
    rule_version: int
    severity: Severity
    nature: Nature
    category: Category
    subjects: tuple[str, ...]
    """Natural keys of the records the exception is about (sorted)."""
    message: str
    discriminator: str = ""
    expected: Any = None
    observed: Any = None
    amount_at_risk: Decimal | None = None
    details: dict[str, Any] = field(default_factory=dict)
    lineage: tuple[SourceLocation, ...] = ()

    @property
    def fingerprint(self) -> str:
        """Stable identity across runs: rule, subjects and discriminator (no amounts, no run)."""
        return content_fingerprint([self.rule_id, sorted(self.subjects), self.discriminator])


def make_exception(
    *,
    rule_id: str,
    rule_version: int,
    severity: Severity,
    nature: Nature,
    category: Category,
    subjects: list[str] | tuple[str, ...],
    message: str,
    discriminator: str = "",
    expected: Any = None,
    observed: Any = None,
    amount_at_risk: Decimal | None = None,
    details: dict[str, Any] | None = None,
    lineage: list[SourceLocation] | tuple[SourceLocation, ...] = (),
) -> RuleException:
    return RuleException(
        rule_id=rule_id,
        rule_version=rule_version,
        severity=severity,
        nature=nature,
        category=category,
        subjects=tuple(sorted(set(subjects))),
        message=message,
        discriminator=discriminator,
        expected=expected,
        observed=observed,
        amount_at_risk=abs(amount_at_risk) if amount_at_risk is not None else None,
        details=details or {},
        lineage=tuple(lineage),
    )
