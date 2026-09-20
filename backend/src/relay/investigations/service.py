"""Start, run and review AI investigations; draft change requests from findings.

The model reads through a separate READ ONLY database session (any write raises in PostgreSQL) with
a statement timeout. Steps are written as they happen through a sink using their own short
transactions, so a running investigation's transcript is visible. Findings are verified by
``relay.ai.verification`` before they are stored; ``requires_approval`` is server policy.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, ClassVar, Final

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from relay.ai.findings import FindingsSubmission, requires_approval
from relay.ai.investigator import Budgets, Outcome, Step, briefing_for, investigate
from relay.ai.prompts import INVESTIGATOR_VERSION
from relay.ai.providers.base import AIUnavailableError, LLMProvider
from relay.ai.references import RunReferences
from relay.ai.tools.registry import ToolContext
from relay.ai.verification import verify
from relay.audit import service as audit
from relay.changes.models import ChangeRequest, ChangeRequestKind, ChangeRequestOrigin
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.config import Settings
from relay.core.db import session_scope
from relay.core.errors import InvalidInputError, NotFoundError, RelayError
from relay.core.ids import uuid7
from relay.investigations.models import (
    Finding,
    Investigation,
    InvestigationStatus,
    InvestigationStep,
    ReviewStatus,
    VerificationStatus,
)
from relay.issues.models import Issue
from relay.jobs import service as jobs
from relay.jobs.models import JobKind
from relay.mapping_sets import accounts
from relay.pipeline import approvals
from relay.pipeline import read_model as runs_read
from relay.workspace import service as workspace

MAX_QUESTION_LENGTH: Final = 2_000
MAX_INVESTIGATIONS_PER_HOUR: Final = 20
TOOL_STATEMENT_TIMEOUT_MS: Final = 5_000


class RateLimitedError(RelayError):
    code: ClassVar[str] = "ai.rate_limited"
    title: ClassVar[str] = "Too many investigations"
    http_status: ClassVar[int] = 429


class FindingNotPromotableError(RelayError):
    code: ClassVar[str] = "ai.finding_not_promotable"
    title: ClassVar[str] = "This finding cannot become a change request"
    http_status: ClassVar[int] = 409


@dataclass(frozen=True, slots=True)
class AIStatus:
    provider: str
    configured: bool
    migration_enabled: bool

    @property
    def available(self) -> bool:
        return self.configured and self.migration_enabled


def status(settings: Settings, migration_ai_enabled: bool) -> AIStatus:
    configured = settings.ai_provider != "disabled"
    return AIStatus(settings.ai_provider, configured, migration_ai_enabled)


def start(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    question: str,
    issue_id: uuid.UUID | None,
    settings: Settings,
    model: str,
    clock: Clock | None = None,
    reuse_existing: bool = False,
) -> Investigation:
    """Queue an investigation pinned to the latest succeeded run (SEC-17, SEC-22).

    With ``reuse_existing`` an investigation of the same issue against the same run is returned
    as it stands instead of a second one being queued. The public demo needs that because every
    visitor is the same person: the answer depends only on the issue and the run's evidence, so
    re-deriving it per click would queue unbounded identical work for an identical result.
    """
    if actor.user_id is None:
        raise InvalidInputError("investigations are started by a person")
    migration = workspace.get_migration(session, migration_id)
    ai = status(settings, migration.ai_enabled)
    if not ai.configured:
        raise AIUnavailableError("AI investigation is disabled for this installation")
    if not ai.migration_enabled:
        raise AIUnavailableError(
            "the customer has not consented to AI processing for this migration (ai_enabled)"
        )
    question = question.strip()
    if not question or len(question) > MAX_QUESTION_LENGTH:
        raise InvalidInputError("a question of at most 2,000 characters is required")
    if issue_id is not None:
        issue = session.get(Issue, issue_id)
        if issue is None or issue.migration_id != migration_id:
            raise NotFoundError("issue not found in this migration")
    run = runs_read.latest_succeeded_run(session, migration_id)
    if run is None:
        raise InvalidInputError("the migration has no succeeded pipeline run to investigate")
    if reuse_existing:
        # Before the rate limit: repeating a question already answered from this run costs
        # nothing and must not consume anyone's budget.
        existing = session.scalars(
            select(Investigation)
            .where(
                Investigation.migration_id == migration_id,
                Investigation.issue_id == issue_id,
                Investigation.run_id == run.id,
            )
            .order_by(Investigation.created_at.desc())
            .limit(1)
        ).first()
        if existing is not None:
            return existing
    now = (clock or SystemClock()).now()
    recent = session.scalar(
        select(func.count())
        .select_from(Investigation)
        .where(
            Investigation.started_by == actor.user_id,
            Investigation.created_at >= now - timedelta(hours=1),
        )
    )
    if (recent or 0) >= MAX_INVESTIGATIONS_PER_HOUR:
        raise RateLimitedError("at most 20 investigations per person per hour")
    investigation = Investigation(
        id=uuid7(clock),
        migration_id=migration_id,
        issue_id=issue_id,
        run_id=run.id,
        question=question,
        status=InvestigationStatus.QUEUED.value,
        provider=settings.ai_provider,
        model=model,
        prompt_version=INVESTIGATOR_VERSION,
        started_by=actor.user_id,
        input_tokens=0,
        output_tokens=0,
        tool_call_count=0,
        sent_fields=[],
    )
    session.add(investigation)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="investigation.requested",
        entity_type="investigation",
        entity_id=investigation.id,
        migration_id=migration_id,
        before={"status": None},
        after={"status": investigation.status, "run_id": run.id, "issue_id": issue_id},
        clock=clock,
    )
    jobs.enqueue(
        session,
        JobKind.RUN_INVESTIGATION,
        {"investigation_id": str(investigation.id)},
        dedupe_key=f"run_investigation:{investigation.id}",
        clock=clock,
    )
    return investigation


@contextmanager
def read_only_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session whose transaction PostgreSQL refuses to let write (ai-safety.md §3.2)."""
    session = factory()
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        # set_config takes a bound value; `SET LOCAL` would need the number in the statement.
        session.execute(
            text("SELECT set_config('statement_timeout', :ms, true)"),
            {"ms": str(TOOL_STATEMENT_TIMEOUT_MS)},
        )
        yield session
    finally:
        session.rollback()
        session.close()


class _DatabaseSink:
    def __init__(self, factory: sessionmaker[Session], investigation_id: uuid.UUID) -> None:
        self.factory = factory
        self.investigation_id = investigation_id

    def record(self, step: Step) -> None:
        with session_scope(self.factory) as session:
            session.add(
                InvestigationStep(
                    id=uuid7(),
                    investigation_id=self.investigation_id,
                    seq=step.seq,
                    type=step.type,
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                    result=step.result,
                    result_sha256=step.result_sha256,
                    truncated=step.truncated,
                    is_error=step.is_error,
                    text=step.text,
                    latency_ms=step.latency_ms,
                )
            )


def execute(
    factory: sessionmaker[Session],
    *,
    investigation_id: uuid.UUID,
    provider: LLMProvider,
    budgets: Budgets,
    clock: Clock | None = None,
) -> Investigation:
    """Job handler body. Uses its own transactions; returns the finished investigation."""
    with session_scope(factory) as session:
        investigation = session.get(Investigation, investigation_id, with_for_update=True)
        if investigation is None:
            raise NotFoundError("investigation not found")
        if investigation.status != InvestigationStatus.QUEUED.value:
            session.expunge(investigation)
            return investigation
        investigation.status = InvestigationStatus.RUNNING.value
        investigation.started_at = (clock or SystemClock()).now()
        migration_id, run_id = investigation.migration_id, investigation.run_id
        question, issue_id = investigation.question, investigation.issue_id
        issue_key = session.get(Issue, issue_id).key if issue_id else None  # type: ignore[union-attr]
    sink = _DatabaseSink(factory, investigation_id)
    verifications = []
    with read_only_session(factory) as reader:
        context = ToolContext(session=reader, migration_id=migration_id, run_id=run_id)
        outcome = investigate(
            provider=provider,
            context=context,
            question=question,
            briefing=briefing_for(context, issue_key),
            sink=sink,
            budgets=budgets,
        )
        if outcome.submission is not None:
            verifications = verify(outcome.submission, outcome.tool_results, RunReferences(context))
    return _finish(factory, investigation_id, outcome, verifications, clock)


def _finish(
    factory: sessionmaker[Session],
    investigation_id: uuid.UUID,
    outcome: Outcome,
    verifications: list[Any],
    clock: Clock | None,
) -> Investigation:
    with session_scope(factory) as session:
        investigation = session.get_one(Investigation, investigation_id, with_for_update=True)
        investigation.status = outcome.status
        investigation.input_tokens = outcome.usage.input_tokens
        investigation.output_tokens = outcome.usage.output_tokens
        investigation.tool_call_count = outcome.tool_calls
        investigation.sent_fields = [
            {"tool": s.tool_name, "arguments": sorted((s.arguments or {}).keys())}
            for s in outcome.steps
            if s.type == "tool_call"
        ]
        investigation.finished_at = (clock or SystemClock()).now()
        investigation.error = {"detail": outcome.error} if outcome.error else None
        submission: FindingsSubmission | None = outcome.submission
        stored = 0
        if submission is not None:
            for finding, verification in zip(submission.findings, verifications, strict=True):
                session.add(
                    Finding(
                        id=uuid7(clock),
                        investigation_id=investigation.id,
                        migration_id=investigation.migration_id,
                        issue_id=investigation.issue_id,
                        hypothesis=finding.hypothesis,
                        evidence=[e.model_dump() for e in finding.evidence],
                        affected_record_refs=list(finding.affected_records),
                        confidence=finding.confidence,
                        suggested_action=finding.suggested_action.model_dump(),
                        open_questions=list(finding.open_questions),
                        requires_approval=requires_approval(finding.suggested_action.type),
                        verification_status=verification.status,
                        verification_report=verification.report,
                        review_status=ReviewStatus.PROPOSED.value,
                        review_comment="",
                    )
                )
                stored += 1
        session.flush()
        audit.record(
            session,
            actor=Actor.system(),
            action="investigation.finished",
            entity_type="investigation",
            entity_id=investigation.id,
            migration_id=investigation.migration_id,
            before={"status": InvestigationStatus.RUNNING.value},
            after={
                "status": investigation.status,
                "findings": stored,
                "verification": sorted(v.status for v in verifications),
                "tool_calls": outcome.tool_calls,
            },
            clock=clock,
        )
        session.expunge(investigation)
        return investigation


def mark_failed(
    session: Session, *, investigation_id: uuid.UUID, error: dict[str, str], clock: Clock | None
) -> None:
    investigation = session.get(Investigation, investigation_id, with_for_update=True)
    if investigation is None or investigation.status not in {
        InvestigationStatus.QUEUED.value,
        InvestigationStatus.RUNNING.value,
    }:
        return
    investigation.status = InvestigationStatus.FAILED.value
    investigation.error = error
    investigation.finished_at = (clock or SystemClock()).now()


def get_finding(session: Session, finding_id: uuid.UUID) -> Finding:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise NotFoundError("finding not found")
    return finding


def review_finding(
    session: Session,
    *,
    actor: Actor,
    finding: Finding,
    accept: bool,
    comment: str,
    clock: Clock | None = None,
) -> Finding:
    """People accept or dismiss findings; accepting never changes anything else."""
    if finding.review_status != ReviewStatus.PROPOSED.value:
        raise InvalidInputError("this finding was already reviewed")
    if accept and finding.verification_status == VerificationStatus.FAILED.value:
        raise FindingNotPromotableError("a finding that failed verification cannot be accepted")
    finding.review_status = (ReviewStatus.ACCEPTED if accept else ReviewStatus.DISMISSED).value
    finding.reviewed_by = actor.user_id
    finding.reviewed_at = (clock or SystemClock()).now()
    finding.review_comment = comment.strip()[:2_000]
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="finding.reviewed",
        entity_type="finding",
        entity_id=finding.id,
        migration_id=finding.migration_id,
        before={"review_status": ReviewStatus.PROPOSED.value},
        after={"review_status": finding.review_status},
        reason=finding.review_comment or None,
        clock=clock,
    )
    return finding


_Drafter = Callable[[Session, Actor, Finding, dict[str, Any], Clock | None], ChangeRequest]


def promotion_problem(finding: Finding) -> str | None:
    """Why a finding cannot be drafted into a change request, or None when it can."""
    if finding.verification_status == VerificationStatus.FAILED.value:
        return "a finding that failed verification cannot be promoted"
    if finding.review_status == ReviewStatus.DISMISSED.value:
        return "a dismissed finding cannot be promoted"
    if not finding.requires_approval:
        return "this finding suggests no change"
    action_type = str(finding.suggested_action.get("type"))
    if action_type not in _DRAFTERS:
        return f"a {action_type} suggestion is carried out by people, not a change request"
    return None


def draft_change_request(
    session: Session, *, actor: Actor, finding: Finding, clock: Clock | None = None
) -> ChangeRequest:
    """A draft owned by the operator (ai-safety.md §4.4). It goes through normal approval."""
    problem = promotion_problem(finding)
    if problem is not None:
        raise FindingNotPromotableError(problem)
    action = dict(finding.suggested_action)
    drafter = _DRAFTERS[str(action.get("type"))]
    change = drafter(session, actor, finding, action, clock)
    audit.record(
        session,
        actor=actor,
        action="finding.drafted_change_request",
        entity_type="finding",
        entity_id=finding.id,
        migration_id=finding.migration_id,
        change_request_id=change.id,
        before={"change_request": None},
        after={"change_request": change.key, "kind": change.kind},
        clock=clock,
    )
    return change


def _create(
    session: Session,
    actor: Actor,
    finding: Finding,
    *,
    kind: ChangeRequestKind,
    title: str,
    clock: Clock | None,
    **inputs: Any,
) -> ChangeRequest:
    evidence = [{"kind": "finding", "finding_id": str(finding.id)}]
    if finding.issue_id:
        evidence.append({"kind": "issue", "issue_id": str(finding.issue_id)})
    return approvals.create(
        session,
        actor=actor,
        migration_id=finding.migration_id,
        kind=kind,
        title=title[:200],
        evidence_refs=evidence,
        origin=ChangeRequestOrigin.AI_FINDING,
        origin_finding_id=finding.id,
        clock=clock,
        **inputs,
    )


def _draft_mapping(
    session: Session, actor: Actor, finding: Finding, action: dict[str, Any], clock: Clock | None
) -> ChangeRequest:
    draft = accounts.create_draft(
        session,
        actor=actor,
        migration_id=finding.migration_id,
        base="approved",
        changes=[
            accounts.EntryChange(
                action["legacy_account"], action["target_account"], finding.hypothesis[:2_000]
            )
        ],
    )
    return _create(
        session, actor, finding, kind=ChangeRequestKind.ACCOUNT_MAPPING_SET,
        title=f"Map {action['legacy_account']} to {action['target_account']}", clock=clock,
        payload={"mapping_set_id": str(draft.id)},
    )  # fmt: skip


def _draft_override(
    session: Session, actor: Actor, finding: Finding, action: dict[str, Any], clock: Clock | None
) -> ChangeRequest:
    investigation = session.get_one(Investigation, finding.investigation_id)
    if action["field"] == "quarantined_row_repair":
        raise FindingNotPromotableError(
            "a row repair needs the corrected text; propose it from the quarantine issue"
        )
    return _create(
        session, actor, finding, kind=ChangeRequestKind.RECORD_OVERRIDE,
        title=f"Correct {action['field']} of {action['natural_key']}", clock=clock,
        payload=None,
        field_override={"run_id": investigation.run_id, "natural_key": action["natural_key"],
                        "field": action["field"], "new_value": action["new_value"]},
    )  # fmt: skip


def _draft_entity(
    session: Session, actor: Actor, finding: Finding, action: dict[str, Any], clock: Clock | None
) -> ChangeRequest:
    investigation = session.get_one(Investigation, finding.investigation_id)
    return _create(
        session, actor, finding, kind=ChangeRequestKind.ENTITY_DECISION,
        title=f"{action['decision'].replace('_', ' ')}: {', '.join(action['members'])}",
        clock=clock,
        payload={"party_type": action["party_type"], "decision": action["decision"],
                 "members": list(action["members"]), "survivor": action.get("survivor"),
                 "run_id": str(investigation.run_id)},
    )  # fmt: skip


def _draft_disposition(
    session: Session, actor: Actor, finding: Finding, action: dict[str, Any], clock: Clock | None
) -> ChangeRequest:
    issue = session.scalars(
        select(Issue).where(
            Issue.migration_id == finding.migration_id, Issue.key == action["issue_key"]
        )
    ).first()
    if issue is None:
        raise FindingNotPromotableError(f"issue {action['issue_key']} no longer exists")
    return _create(
        session, actor, finding, kind=ChangeRequestKind.DISPOSITION,
        title=f"Disposition of {issue.key}", clock=clock,
        payload={"issue_ids": [str(issue.id)], "kind": action["kind"],
                 "amount": action.get("amount")},
    )  # fmt: skip


_DRAFTERS: Final[dict[str, _Drafter]] = {
    "change_account_mapping": _draft_mapping,
    "record_override": _draft_override,
    "entity_decision": _draft_entity,
    "disposition": _draft_disposition,
}
