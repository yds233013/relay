"""Existence checks for suggested actions, against the investigated run (read models only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from relay.ai.tools.registry import ToolContext
from relay.issues import read_model as issues_read
from relay.pipeline import read_model as runs_read
from relay.pipeline.read_model import ResourceNotFoundError
from relay.workspace import read_model as workspace_read


@dataclass(frozen=True, slots=True)
class RunReferences:
    context: ToolContext

    def issue_exists(self, key: str) -> bool:
        return (
            issues_read.get_issue_by_key(self.context.session, self.context.migration_id, key)
            is not None
        )

    def record_exists(self, natural_key: str) -> bool:
        try:
            runs_read.get_record(self.context.session, self.context.run_id, natural_key)
        except ResourceNotFoundError:
            return False
        return True

    def account_exists(self, code: str, side: Literal["legacy", "target"]) -> bool:
        return self.record_exists(f"acct:{side}:{code}")

    def party_exists(self, party_type: str, code: str) -> bool:
        return self.record_exists(f"party:{party_type}:{code}")

    def dataset_type_exists(self, dataset_type: str) -> bool:
        return any(
            d.dataset_type == dataset_type
            for d in workspace_read.datasets_for(self.context.session, self.context.migration_id)
        )
