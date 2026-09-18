"""Observational evidence for GV-05: governed mutations carry an audit event.

What this proves, exactly: **every transaction that mutated a governed table also inserted at
least one row into ``audit_events`` in that same transaction.** It does not prove that the event
describes the right row, the right actor or the right action — per-flow tests assert that, and this
check cannot. Do not read it as more than it is.

It is observational only. It never writes anything, never creates an audit event, and never takes a
lock (a deadlock between the audit lock and the pipeline lock is recorded in ``docs/progress.md``;
nothing here may acquire either). On a violation it raises, so the transaction rolls back.

Nothing installs it in production: :func:`install` is called by the integration test suite's autouse
fixture, and until it is called no listener exists. Import this module freely; importing is inert.

Two limitations follow from watching the ORM unit of work:

* Rows written outside the unit of work are invisible — ``relay.core.db.copy_rows`` (raw psycopg
  ``COPY``) and plain Core DML. Every table written that way today (``source_rows``,
  ``quarantined_rows``, staged and reconciliation output, ``gate_results``) is classified exempt
  below, and ORM-enabled bulk DML *is* observed via ``do_orm_execute``.
* Work split across several transactions is judged per transaction, which is the guarantee the
  requirement states.

:func:`bypass_check` opts one transaction out. It exists for tests that build rows by hand to
exercise a database constraint, where no service and therefore no audit event is involved.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, ClassVar, Final

from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Session, UOWTransaction

from relay.core.errors import RelayError

AUDIT_TABLE: Final = "audit_events"

# Tables whose mutation is a governed act: creating or changing them without an audit event in the
# same transaction is the failure GV-05 forbids. Plain strings, never model imports: this module
# sits below every module that writes (import-linter layering).
GOVERNED: Final[frozenset[str]] = frozenset(
    {
        # workspace and identity: the objects a migration is defined by
        "companies",
        "migrations",
        "source_systems",
        "datasets",
        "policy_versions",
        "users",
        # ingestion metadata (the rows themselves are exempt below)
        "stored_files",
        "imports",
        # configuration overlays: mapping sets and their pairs
        "column_mapping_sets",
        "column_mappings",
        "account_mapping_sets",
        "account_mappings",
        # change requests and their approvals
        "change_requests",
        "approvals",
        # overlays, each created only by applying an approved change request
        "record_overrides",
        "entity_decisions",
        "dispositions",
        "gate_waivers",
        "readiness_signoffs",
        # issue state and the human record around it
        "issues",
        "issue_comments",
        "issue_links",
        # pipeline and readiness decisions (their recomputed detail rows are exempt below)
        "pipeline_runs",
        "readiness_evaluations",
        # AI output an operator acts on
        "findings",
    }
)

# Operational tables, with the reason each one is not governed. A write to one of these on its own
# needs no audit event.
EXEMPT: Final[Mapping[str, str]] = {
    AUDIT_TABLE: "the evidence itself; an event never needs an event",
    "jobs": (
        "job queue bookkeeping (enqueue, claim, heartbeat, requeue); the work it runs audits itself"
    ),
    "source_rows": "append-only ingestion, bulk-COPYed under the audited import.parsed event",
    "quarantined_rows": "append-only ingestion, written under the audited import.parsed event",
    "dataset_profiles": "profiling output recomputed from source rows under import.parsed",
    "staged_records": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "rule_runs": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "rule_exceptions": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "reconciliation_results": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "reconciliation_lines": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "reconciling_items": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "entity_candidates": "pipeline recompute output, rewritten per run under pipeline_run.*",
    "gate_results": "readiness detail rows of one evaluation, written with it under pipeline_run.*",
    "issue_occurrences": "per-run sightings of an issue, recomputed under pipeline_run.*",
    "investigations": (
        "AI run lifecycle: investigation.requested and investigation.finished are audited, while "
        "the intermediate RUNNING transition is worker bookkeeping in its own transaction"
    ),
    "investigation_steps": (
        "the transcript of one investigation, written a step at a time and audited as a whole by "
        "investigation.finished"
    ),
}

_DIRTIED: Final = "relay.gv05.dirtied"
_BYPASSED: Final = "relay.gv05.bypassed"


class UnauditedMutationError(RelayError):
    """A transaction changed governed state without writing an audit event (GV-05)."""

    code: ClassVar[str] = "audit.unaudited_mutation"
    title: ClassVar[str] = "Governed mutation without an audit event"


class UnclassifiedTableError(RelayError):
    """A table is neither governed nor exempt; classify it deliberately (GV-05)."""

    code: ClassVar[str] = "audit.unclassified_table"
    title: ClassVar[str] = "Unclassified table"


def _tables_of(obj: object) -> set[str]:
    mapper = inspect(type(obj), raiseerr=False)
    return set() if mapper is None else {table.name for table in mapper.tables}


def _observe(session: Session) -> set[str]:
    """Accumulate the tables this transaction has mutated so far, and return the accumulator."""
    dirtied: set[str] = session.info.setdefault(_DIRTIED, set())
    for obj in (*session.new, *session.deleted):
        dirtied |= _tables_of(obj)
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            dirtied |= _tables_of(obj)
    return dirtied


def _after_flush(session: Session, flush_context: UOWTransaction) -> None:  # noqa: ARG001
    # The flush clears session.new/dirty/deleted, so record them while they are still there.
    _observe(session)


def _do_orm_execute(state: ORMExecuteState) -> None:
    """Observe ORM-enabled bulk DML (``session.execute(insert(Model), rows)``)."""
    if not (state.is_insert or state.is_update or state.is_delete):
        return
    dirtied: set[str] = state.session.info.setdefault(_DIRTIED, set())
    for mapper in state.all_mappers:
        dirtied |= {table.name for table in mapper.tables}


def bypass_check(session: Session) -> None:
    """Exempt this session's transaction from the check.

    For tests that build rows by hand to exercise a database constraint, where no service and so no
    audit event is involved. Never in runtime code, and never to quieten a service: a service that
    trips the check has the GV-05 defect the check exists to find.
    """
    session.info[_BYPASSED] = True


def _before_commit(session: Session) -> None:
    # before_commit runs ahead of the commit's own final flush, so fold in what is still pending.
    if session.info.get(_BYPASSED):
        return
    dirtied = _observe(session)
    unclassified = sorted(dirtied - GOVERNED - EXEMPT.keys())
    if unclassified:
        raise UnclassifiedTableError(
            f"{', '.join(unclassified)}: classify in relay.audit.instrumentation as governed "
            "(a mutation needs an audit event) or exempt (with a reason)"
        )
    governed = sorted(dirtied & GOVERNED)
    if governed and AUDIT_TABLE not in dirtied:
        raise UnauditedMutationError(
            f"transaction mutated governed table(s) {', '.join(governed)} without writing an "
            "audit event (GV-05); call relay.audit.service.record in the same transaction"
        )


def _reset(session: Session, *args: Any) -> None:  # noqa: ARG001 - listener signatures differ
    session.info.pop(_DIRTIED, None)
    session.info.pop(_BYPASSED, None)


_LISTENERS: Final = (
    ("after_flush", _after_flush),
    ("do_orm_execute", _do_orm_execute),
    ("before_commit", _before_commit),
    ("after_commit", _reset),
    ("after_rollback", _reset),
    ("after_soft_rollback", _reset),
)


def installed() -> bool:
    return event.contains(Session, "before_commit", _before_commit)


def install() -> None:
    """Start observing every ORM session in this process. Tests only; never a production path."""
    if installed():
        return
    for name, handler in _LISTENERS:
        event.listen(Session, name, handler)


def remove() -> None:
    for name, handler in _LISTENERS:
        if event.contains(Session, name, handler):
            event.remove(Session, name, handler)


@contextmanager
def observing() -> Iterator[None]:
    """Install the check for the duration of the block (no-op if it is already installed)."""
    if installed():
        yield
        return
    install()
    try:
        yield
    finally:
        remove()
