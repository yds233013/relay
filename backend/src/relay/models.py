"""Every persistent model, imported for metadata completeness (Alembic, tests).

Application code imports models from their owning module; this aggregator exists so that
``Base.metadata`` is complete wherever the whole schema is needed.
"""

from __future__ import annotations

from relay.audit.models import AuditEvent
from relay.changes.models import Approval, ChangeRequest, RecordOverride
from relay.core.db import Base
from relay.identity.models import User
from relay.imports.models import DatasetProfile, Import, QuarantinedRow, SourceRow, StoredFile
from relay.issues.models import Issue, IssueOccurrence
from relay.jobs.models import Job
from relay.mapping_sets.models import (
    AccountMapping,
    AccountMappingSet,
    ColumnMapping,
    ColumnMappingSet,
)
from relay.pipeline.models import (
    EntityCandidateRow,
    GateResultRow,
    PipelineRun,
    ReadinessEvaluationRow,
    ReconciliationLineRow,
    ReconciliationResultRow,
    ReconcilingItemRow,
    RuleExceptionRow,
    RuleRun,
    StagedRecord,
)
from relay.workspace.models import Company, Dataset, Migration, PolicyVersion, SourceSystem

metadata = Base.metadata

__all__ = [
    "AccountMapping",
    "AccountMappingSet",
    "Approval",
    "AuditEvent",
    "ChangeRequest",
    "ColumnMapping",
    "ColumnMappingSet",
    "Company",
    "Dataset",
    "DatasetProfile",
    "EntityCandidateRow",
    "GateResultRow",
    "Import",
    "Issue",
    "IssueOccurrence",
    "Job",
    "Migration",
    "PipelineRun",
    "PolicyVersion",
    "QuarantinedRow",
    "ReadinessEvaluationRow",
    "ReconciliationLineRow",
    "ReconciliationResultRow",
    "ReconcilingItemRow",
    "RecordOverride",
    "RuleExceptionRow",
    "RuleRun",
    "SourceRow",
    "SourceSystem",
    "StagedRecord",
    "StoredFile",
    "User",
    "metadata",
]
