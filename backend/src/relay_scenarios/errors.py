"""Scenario generation errors. Generation fails loudly instead of producing invalid books."""

from __future__ import annotations


class ScenarioError(Exception):
    """Base class for generator failures."""


class ScenarioConsistencyError(ScenarioError):
    """The scenario cannot be generated consistently (a precondition or invariant does not hold)."""


class BooksInvariantError(ScenarioError):
    """Generated books violate an accounting invariant."""

    def __init__(self, violations: list[str]) -> None:
        preview = "; ".join(violations[:10])
        more = f" (+{len(violations) - 10} more)" if len(violations) > 10 else ""
        super().__init__(f"{len(violations)} invariant violation(s): {preview}{more}")
        self.violations = violations
