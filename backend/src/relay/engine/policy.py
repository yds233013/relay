"""Engine policy: rule parameters, tolerances and thresholds (docs/governance.md §2.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Policy:
    duplicate_window_days: int = 7
    party_currency_min_documents: int = 3
    fx_rounding_tolerance: Decimal = Decimal("0.01")
    fx_rate_lookback_days: int = 7
    entity_candidate_threshold: Decimal = Decimal("0.60")
    entity_strong_threshold: Decimal = Decimal("0.85")
    reconciliation_tolerance: Decimal = Decimal("0.00")
    cash_unexplained_tolerance: Decimal = Decimal("0.00")
    max_unresolved_exposure: Decimal = Decimal("1000.00")
    bank_match_days_before: int = 3
    bank_match_days_after: int = 10
    severity_overrides: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "duplicate_window_days": self.duplicate_window_days,
            "party_currency_min_documents": self.party_currency_min_documents,
            "fx_rounding_tolerance": self.fx_rounding_tolerance,
            "fx_rate_lookback_days": self.fx_rate_lookback_days,
            "entity_candidate_threshold": self.entity_candidate_threshold,
            "entity_strong_threshold": self.entity_strong_threshold,
            "reconciliation_tolerance": self.reconciliation_tolerance,
            "cash_unexplained_tolerance": self.cash_unexplained_tolerance,
            "max_unresolved_exposure": self.max_unresolved_exposure,
            "bank_match_days_before": self.bank_match_days_before,
            "bank_match_days_after": self.bank_match_days_after,
            "severity_overrides": dict(sorted(self.severity_overrides.items())),
        }
