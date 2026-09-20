"""Fast-forward Brightwater to just before sign-off (docs/demo-scenario.md §7, step 10).

DEMO TOOLING: this script knows the documented resolution of each planted problem. It applies them
the way the team would, through the same orchestration the API uses, as the seeded people: the
specialist uploads and proposes, the lead and the controller approve what policy requires. Nothing
is written directly and no approval rule is bypassed. Steps already done (for example in the demo
walkthrough) are skipped, so it can run from any day-9-or-later state.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relay.changes import kinds as change_kinds
from relay.changes.models import ApprovalDecision, ChangeRequest, ChangeRequestKind
from relay.core.actor import Actor
from relay.core.db import session_scope
from relay.identity import service as identity
from relay.identity.models import Role
from relay.imports import service as imports
from relay.imports.blob_store import BlobStore
from relay.issues.models import OPEN_STATUSES, Issue
from relay.jobs.models import Job, JobStatus
from relay.mapping_sets import accounts
from relay.pipeline import approvals
from relay.pipeline import readiness as readiness_resolver
from relay.pipeline import service as pipeline
from relay.pipeline.models import PipelineRun, RuleExceptionRow, RunStatus
from relay.worker import WorkerContext, drain
from relay.workspace import read_model as workspace_read
from relay.workspace import service as workspace
from relay_scenarios.brightwater.scenario import Scenario, build_scenario, reexport_files
from relay_scenarios.brightwater.seed import PEOPLE

MAYA, DANIEL, PRIYA = PEOPLE[0][0], PEOPLE[1][0], PEOPLE[2][0]
REVIEWER_BY_ROLE: Final = {
    Role.IMPLEMENTATION_LEAD.value: DANIEL,
    Role.CUSTOMER_CONTROLLER.value: PRIYA,
}
MAPPING_CHANGES: Final = (
    ("1205", "1210", "The allowance is a contra-asset, not receivables"),
    ("6999", "1999", "The inactive suspense account maps to target suspense"),
)
DATE_CORRECTIONS: Final = (
    ("je:JE-2026-0388", "2026-03-31", "The adjustment belongs to the March close"),
    ("je:JE-AP-20455", "2026-03-14", "Keying error; bill date and posting period are March 2026"),
)
ENTITY_DECISIONS: Final = (
    ("vendor", "same_entity", ("V-1042", "V-1187"), "V-1042",
     "Same tax id, address and vendor invoice reference"),
    ("customer", "same_entity", ("C-0107", "C-0154"), "C-0107",
     "Same billing entity and AP contact"),
    ("customer", "distinct", ("C-0107", "C-0198"), None,
     "Separate store with its own billing"),
    ("customer", "distinct", ("C-0154", "C-0198"), None,
     "Separate store with its own billing"),
)  # fmt: skip
DISPOSITIONS: Final = (
    (("AP.DUPLICATE_BILL", "PAY.DUPLICATE_PAYMENT"), "carry_forward_adjustment", "14862.50",
     "Request a refund or credit from the vendor",
     "Real overpayment in the legacy books; record the vendor receivable in the new ERP"),
    (("CUR.PARTY_CURRENCY_MISMATCH",), "carry_forward_adjustment", "2347.95",
     "Post the correcting revenue entry in July",
     "EUR invoices keyed as USD; correct in the new ERP's opening period"),
    (("BANK.UNRECORDED_ACTIVITY",), "carry_forward_adjustment", "270.00",
     "Book the bank fees in the opening entries",
     "Six monthly bank fees were never recorded in the legacy GL"),
    (("DATA.INSTRUCTION_LIKE_TEXT",), "not_applicable", None, "",
     "Vendor note text is data; it has no accounting effect"),
)  # fmt: skip


class FastForwardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FastForwardResult:
    migration_id: uuid.UUID
    applied: tuple[str, ...]
    failing_gates: tuple[str, ...]


def _actor(session: Session, email: str) -> Actor:
    user = identity.find_active_user_by_email(session, email)
    if user is None:
        raise FastForwardError(f"seed user {email} is missing")
    return identity.actor_for(user)


class _Script:
    def __init__(
        self, factory: sessionmaker[Session], context: WorkerContext, migration_id: uuid.UUID
    ) -> None:
        self.factory = factory
        self.context = context
        self.migration_id = migration_id
        self.applied: list[str] = []

    def settle(self, timeout_seconds: int = 600) -> None:
        """Process queued work here (or wait for the stack's worker) until nothing is queued."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            drain(self.context)
            with session_scope(self.factory) as session:
                busy = session.scalars(
                    select(Job.id).where(
                        Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value])
                    )
                ).first()
            if busy is None:
                return
            if time.monotonic() > deadline:
                raise FastForwardError("timed out waiting for pipeline runs")
            time.sleep(1)

    def change(
        self,
        title: str,
        kind: ChangeRequestKind,
        justification: str,
        *,
        payload: dict[str, Any] | None = None,
        field_override: dict[str, Any] | None = None,
        quarantine_repair: dict[str, Any] | None = None,
    ) -> None:
        with session_scope(self.factory) as session:
            requester = _actor(session, MAYA)
            change = approvals.create(
                session, actor=requester, migration_id=self.migration_id, kind=kind, title=title,
                payload=payload, field_override=field_override,
                quarantine_repair=quarantine_repair,
            )  # fmt: skip
            approvals.submit(session, actor=requester, change=change, justification=justification)
            change_id = change.id
            roles = [r["role"] for r in change.required_approvals]
        for role in roles:
            with session_scope(self.factory) as session:
                outcome = approvals.review(
                    session,
                    actor=_actor(session, REVIEWER_BY_ROLE[role]),
                    change=session.get_one(ChangeRequest, change_id),
                    decision=ApprovalDecision.APPROVE,
                    comment="Checked against the evidence.",
                )
                status = outcome.change.status
        if status != "applied":
            raise FastForwardError(f"{title} ended as {status}")
        self.applied.append(title)
        self.settle()

    def open_issues(self, rule_id: str) -> list[Issue]:
        with session_scope(self.factory) as session:
            rows = session.scalars(
                select(Issue).where(
                    Issue.migration_id == self.migration_id,
                    Issue.rule_or_recon_id == rule_id,
                    Issue.status.in_([s.value for s in OPEN_STATUSES]),
                )
            ).all()
            session.expunge_all()
            return list(rows)

    def latest_run_id(self) -> uuid.UUID:
        with session_scope(self.factory) as session:
            run_id = session.scalars(
                select(PipelineRun.id)
                .where(
                    PipelineRun.migration_id == self.migration_id,
                    PipelineRun.status == RunStatus.SUCCEEDED.value,
                )
                .order_by(PipelineRun.sequence.desc())
            ).first()
        if run_id is None:
            raise FastForwardError("the migration has no succeeded run")
        return run_id


def _reimport(script: _Script, scenario: Scenario) -> None:
    files = reexport_files(scenario)
    with session_scope(script.factory) as session:
        uploader = _actor(session, MAYA)
        by_name = {d.name: d for d in workspace.datasets_for(session, script.migration_id)}
        for path, content in files.items():
            dataset = by_name[path.rsplit("/", 1)[-1]]
            outcome = imports.upload(
                session, actor=uploader, dataset=dataset, filename=dataset.name, chunks=[content],
                blob_store=script.context.blob_store, limits=script.context.limits,
            )  # fmt: skip
            if outcome.created:
                script.applied.append(f"re-import {dataset.name}")
    drain(script.context)
    with session_scope(script.factory) as session:
        pipeline.request_run(session, actor=_actor(session, MAYA), migration_id=script.migration_id)
    script.settle()


def _mappings(script: _Script) -> None:
    with session_scope(script.factory) as session:
        effective = accounts.effective_pairs(session, script.migration_id)
        needed = [c for c in MAPPING_CHANGES if effective.get(c[0]) != c[1]]
        if not needed:
            return
        draft = accounts.create_draft(
            session,
            actor=_actor(session, MAYA),
            migration_id=script.migration_id,
            base="approved",
            changes=[accounts.EntryChange(legacy, target, why) for legacy, target, why in needed],
        )
        draft_id = draft.id
    script.change(
        "Account mapping corrections", ChangeRequestKind.ACCOUNT_MAPPING_SET,
        "Contra account and inactive suspense account.",
        payload={"mapping_set_id": str(draft_id)},
    )  # fmt: skip


def _corrections(script: _Script) -> None:
    for key, value, why in DATE_CORRECTIONS:
        with session_scope(script.factory) as session:
            active = [
                o
                for o in change_kinds.active_overrides(session, script.migration_id)
                if o.natural_key == key
            ]
        if active:
            continue
        script.change(
            f"Correct entry date of {key}", ChangeRequestKind.RECORD_OVERRIDE, why,
            field_override={"run_id": script.latest_run_id(), "natural_key": key,
                            "field": "entry_date", "new_value": value},
        )  # fmt: skip
    with session_scope(script.factory) as session:
        finding = session.scalars(
            select(RuleExceptionRow).where(
                RuleExceptionRow.run_id == script.latest_run_id(),
                RuleExceptionRow.rule_id == "NORM.MALFORMED_ROW",
            )
        ).first()
        repair = (finding.id, str(finding.details["raw_text"])) if finding is not None else None
    if repair is not None:
        exception_id, raw = repair
        script.change(
            "Repair the journal line broken by a line break", ChangeRequestKind.RECORD_OVERRIDE,
            "The export split one record at an unquoted line break in its memo.",
            quarantine_repair={"exception_id": exception_id,
                               "replacement_text": raw.replace("\r\n", " ").replace("\n", " ")
                               .rstrip()},
        )  # fmt: skip


def _decisions(script: _Script) -> None:
    for party_type, decision, members, survivor, why in ENTITY_DECISIONS:
        with session_scope(script.factory) as session:
            decided = {
                (d.party_type, frozenset(d.members))
                for d in change_kinds.active_entity_decisions(session, script.migration_id)
            }
        if (party_type, frozenset(members)) in decided:
            continue
        script.change(
            f"{decision.replace('_', ' ')}: {', '.join(members)}",
            ChangeRequestKind.ENTITY_DECISION, why,
            payload={"party_type": party_type, "decision": decision, "members": list(members),
                     "survivor": survivor, "run_id": str(script.latest_run_id())},
        )  # fmt: skip


def _dispositions(script: _Script) -> None:
    with session_scope(script.factory) as session:
        owner = identity.find_active_user_by_email(session, PRIYA)
        owner_id = str(owner.id) if owner else None
    for rules, kind, amount, follow_up, why in DISPOSITIONS:
        issues = [i for rule in rules for i in script.open_issues(rule)]
        if not issues:
            continue
        script.change(
            f"Disposition: {', '.join(rules)}", ChangeRequestKind.DISPOSITION, why,
            payload={"issue_ids": [str(i.id) for i in issues], "kind": kind, "amount": amount,
                     "follow_up": follow_up,
                     "follow_up_owner_id": owner_id if follow_up else None},
        )  # fmt: skip


STEPS: Final[tuple[Callable[[_Script], None], ...]] = (_mappings, _corrections, _decisions)


def fast_forward(
    factory: sessionmaker[Session],
    blob_store: BlobStore,
    limits: imports.ImportLimits,
    *,
    migration_id: uuid.UUID,
) -> FastForwardResult:
    context = WorkerContext(session_factory=factory, blob_store=blob_store, limits=limits)
    script = _Script(factory, context, migration_id)
    script.settle()
    _reimport(script, build_scenario())
    for step in STEPS:
        step(script)
    _dispositions(script)
    script.settle()
    with session_scope(factory) as session:
        _, _, gates = readiness_resolver.current_evaluation(session, migration_id)
        failing = tuple(sorted((g for g, r in gates.items() if r.status == "fail"),
                               key=lambda g: int(g[1:])))  # fmt: skip
    if failing != ("G12",):
        raise FastForwardError(f"expected only G12 to fail before sign-off, found {failing}")
    return FastForwardResult(migration_id, tuple(script.applied), failing)


def brightwater_migration(session: Session) -> uuid.UUID:
    matches = [
        m.id for m, c in workspace_read.migrations(session) if c.name.startswith("Brightwater")
    ]
    if len(matches) != 1:
        raise FastForwardError(f"expected one Brightwater migration, found {len(matches)}")
    return matches[0]


def enable_ai(
    factory: sessionmaker[Session],
    blob_store: BlobStore,
    limits: imports.ImportLimits,
    *,
    migration_id: uuid.UUID,
) -> str:
    """Record the customer's consent to AI processing, through the governed path.

    Consent is a `policy_change` carrying `ai_enabled`, and it needs the implementation lead and
    the customer controller exactly like any other policy change. There is deliberately no shortcut
    that writes the flag directly: a demo that bypassed the control would be demonstrating
    something Relay does not do.
    """
    context = WorkerContext(session_factory=factory, blob_store=blob_store, limits=limits)
    script = _Script(factory, context, migration_id)
    script.change(
        "Enable AI investigation for this implementation",
        ChangeRequestKind.POLICY_CHANGE,
        "The customer agreed that Relay may read this migration's data to investigate findings. "
        "Investigations are read-only and cannot change anything.",
        payload={"changes": {"ai_enabled": True}},
    )
    with session_scope(factory) as session:
        return "enabled" if workspace.get_migration(session, migration_id).ai_enabled else "off"
