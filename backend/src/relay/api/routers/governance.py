"""Mappings, change requests, approvals and record overrides."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.api.deps import ActorDep, ClockDep, ReaderDep, SessionDep, require
from relay.api.routers.workspace import audit_event_out
from relay.api.schemas import (
    AccountMappingDraftIn,
    AccountMappingOverviewOut,
    AccountMappingRowOut,
    AccountMappingSetDetailOut,
    AccountMappingSetOut,
    AccountProposalOut,
    ApprovalOut,
    CanonicalFieldOut,
    ChangeRequestDetailOut,
    ChangeRequestIn,
    ChangeRequestOut,
    ChangeRequestUpdateIn,
    ColumnMappingOut,
    ColumnMappingPreviewOut,
    ColumnMappingSetOut,
    ColumnMappingSuggestionOut,
    FieldSuggestionOut,
    JustificationIn,
    MappingConfigIn,
    PreviewRowOut,
    RecordOverrideOut,
    RequirementOut,
    ReviewerOut,
    ReviewIn,
    ReviewOutcomeOut,
    SignalsOut,
    WithdrawIn,
)
from relay.audit import read_model as audit_read
from relay.changes import service as changes
from relay.changes.domain import RecordedApproval, eligibility
from relay.changes.models import (
    ApprovalDecision,
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestStatus,
    RecordOverride,
)
from relay.core.actor import Actor
from relay.core.errors import InvalidInputError
from relay.identity import service as identity
from relay.identity.permissions import Permission, allowed
from relay.imports import read_model as imports_read
from relay.imports.models import Import, ImportStatus, SourceRow
from relay.mapping import registry
from relay.mapping.transforms import MappingConfigError
from relay.mapping_sets import accounts, suggest
from relay.mapping_sets import service as column_sets
from relay.mapping_sets.models import AccountMappingSet, ColumnMappingSet
from relay.mapping_sets.service import InvalidMappingError, MappingSetStateError
from relay.pipeline import approvals
from relay.pipeline.models import PipelineRun
from relay.profiling.domain import DatasetProfile
from relay.workspace import service as workspace

router = APIRouter(prefix="/api/v1", tags=["governance"])

DrafterDep = Annotated[Actor, Depends(require(Permission.DRAFT_CHANGE_REQUEST))]
ReviewerDep = Annotated[Actor, Depends(require(Permission.REVIEW_CHANGE_REQUEST))]


# ------------------------------------------------------------------------------ column mappings
def _parsed_import(session: Session, dataset_id: uuid.UUID) -> tuple[Any, Import]:
    dataset = workspace.get_dataset(session, dataset_id)
    active = session.get(Import, dataset.active_import_id) if dataset.active_import_id else None
    if active is None or active.status != ImportStatus.PARSED.value or active.header is None:
        raise MappingSetStateError("the dataset has no parsed, active import")
    return dataset, active


def _column_set_out(session: Session, mapping_set: ColumnMappingSet) -> ColumnMappingSetOut:
    dataset = workspace.get_dataset(session, mapping_set.dataset_id)
    rows = column_sets.mappings(session, mapping_set.id)
    return ColumnMappingSetOut(
        id=mapping_set.id,
        dataset_id=mapping_set.dataset_id,
        version=mapping_set.version,
        status=mapping_set.status,
        based_on_import_id=mapping_set.based_on_import_id,
        change_request_id=mapping_set.change_request_id,
        created_at=mapping_set.created_at,
        exclude_rows_where_blank=list(mapping_set.exclude_rows_where_blank),
        mappings=[
            ColumnMappingOut(
                target_field=m.target_field,
                specification=m.transform,
                required=m.required,
                basis=m.basis,
            )
            for m in rows
        ],
        missing_required_fields=registry.missing_required(
            dataset.dataset_type, {m.target_field for m in rows}
        ),
    )


@router.get("/datasets/{dataset_id}/column-mapping-sets")
def list_column_mapping_sets(
    dataset_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[ColumnMappingSetOut]:
    workspace.get_dataset(session, dataset_id)
    return [_column_set_out(session, s) for s in column_sets.sets_for(session, dataset_id)]


@router.get("/column-mapping-sets/{set_id}")
def get_column_mapping_set(
    set_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> ColumnMappingSetOut:
    return _column_set_out(session, column_sets.get_set(session, set_id))


@router.get("/datasets/{dataset_id}/column-mapping-suggestion")
def column_mapping_suggestion(
    dataset_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> ColumnMappingSuggestionOut:
    """Deterministic proposal from header names and the column profile; nothing is saved."""
    dataset, active = _parsed_import(session, dataset_id)
    stored = imports_read.profile(session, active.id)
    profile = DatasetProfile.model_validate(stored.profile) if stored else None
    header = [str(h) for h in active.header or []]
    proposal = suggest.suggest(dataset.dataset_type, header, profile)
    return ColumnMappingSuggestionOut(
        dataset_id=dataset.id,
        dataset_type=dataset.dataset_type,
        import_id=active.id,
        header=header,
        fields=[
            FieldSuggestionOut(
                field=f.field,
                kind=f.kind,
                required=f.required,
                specification=f.specification,
                basis=f.basis,
                notes=list(f.notes),
            )
            for f in proposal.fields
        ],
        unmatched_columns=list(proposal.unmatched_columns),
        canonical_fields=[
            CanonicalFieldOut(
                name=f.name, kind=f.kind.value, required=f.required, values=list(f.values)
            )
            for f in registry.fields_for(dataset.dataset_type)
        ],
    )


@router.post("/datasets/{dataset_id}/column-mapping-preview")
def column_mapping_preview(
    dataset_id: uuid.UUID, body: MappingConfigIn, _actor: DrafterDep, session: SessionDep
) -> ColumnMappingPreviewOut:
    """Apply a mapping to the first rows of the active import without saving anything."""
    dataset, active = _parsed_import(session, dataset_id)
    header = [str(h) for h in active.header or []]
    sample = session.execute(
        select(SourceRow.row_number, SourceRow.values)
        .where(SourceRow.import_id == active.id)
        .order_by(SourceRow.row_number)
        .limit(suggest.MAX_PREVIEW_ROWS)
    ).all()
    try:
        rows = suggest.preview(
            dataset.dataset_type,
            body.model_dump(),
            header,
            [(number, values) for number, values in sample],
        )
    except MappingConfigError as exc:
        raise InvalidMappingError(exc.detail) from exc
    names = set(body.fields)
    return ColumnMappingPreviewOut(
        import_id=active.id,
        rows=[
            PreviewRowOut(
                row_number=r.row_number, values=r.values, errors=r.errors, excluded=r.excluded
            )
            for r in rows
        ],
        missing_required_fields=registry.missing_required(dataset.dataset_type, names),
        unknown_fields=registry.unknown_fields(dataset.dataset_type, names),
    )


@router.post("/datasets/{dataset_id}/column-mapping-sets", status_code=status.HTTP_201_CREATED)
def create_column_mapping_set(
    dataset_id: uuid.UUID, body: MappingConfigIn, actor: DrafterDep, session: SessionDep
) -> ColumnMappingSetOut:
    dataset = workspace.get_dataset(session, dataset_id)
    mapping_set = column_sets.create_draft(
        session, actor=actor, dataset=dataset, config=body.model_dump()
    )
    return _column_set_out(session, mapping_set)


# ----------------------------------------------------------------------------- account mappings
def _signals(raw: dict[str, Any] | None) -> SignalsOut | None:
    return SignalsOut(**raw) if raw is not None else None


def _account_row(row: dict[str, Any], **extra: Any) -> AccountMappingRowOut:
    proposal = row.get("proposal")
    return AccountMappingRowOut(
        legacy_account_code=row["legacy_account_code"],
        legacy_name=row["legacy_name"],
        legacy_subtype=row["legacy_subtype"],
        target_account_code=row["target_account_code"],
        target_name=row["target_name"],
        target_subtype=row["target_subtype"],
        signals=_signals(row["signals"]),
        proposal=AccountProposalOut(
            target=proposal["target"],
            basis=proposal["basis"],
            score=proposal["score"],
            signals=SignalsOut(**proposal["signals"]),
        )
        if proposal
        else None,
        **extra,
    )


def _account_set_out(session: Session, mapping_set: AccountMappingSet) -> AccountMappingSetOut:
    return AccountMappingSetOut(
        id=mapping_set.id,
        version=mapping_set.version,
        status=mapping_set.status,
        based_on_set_id=mapping_set.based_on_set_id,
        based_on_import_id=mapping_set.based_on_import_id,
        change_request_id=mapping_set.change_request_id,
        created_at=mapping_set.created_at,
        entry_count=len(accounts.entries(session, mapping_set.id)),
    )


@router.get("/migrations/{migration_id}/account-mapping")
def account_mapping(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> AccountMappingOverviewOut:
    """The mapping in effect, compatibility signals per pair, proposals for doubtful pairs."""
    workspace.get_migration(session, migration_id)
    approved = accounts.approved_set(session, migration_id)
    return AccountMappingOverviewOut(
        approved_set=_account_set_out(session, approved) if approved else None,
        source="approved_set" if approved else "account_mapping_file",
        rows=[_account_row(r) for r in accounts.suggestions(session, migration_id)],
        sets=[_account_set_out(session, s) for s in accounts.sets_for(session, migration_id)],
    )


@router.get("/account-mapping-sets/{set_id}")
def get_account_mapping_set(
    set_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> AccountMappingSetDetailOut:
    mapping_set = accounts.get_set(session, set_id)
    entries = accounts.entries(session, set_id)
    described = accounts.describe(
        session,
        mapping_set.migration_id,
        [{"legacy": code, "before": None, "after": e.target} for code, e in entries.items()],
    )
    return AccountMappingSetDetailOut(
        mapping_set=_account_set_out(session, mapping_set),
        rows=[
            AccountMappingRowOut(
                legacy_account_code=str(item["legacy"]),
                legacy_name=item["legacy_name"],
                legacy_subtype=item["legacy_subtype"],
                target_account_code=item["after"],
                target_name=item["after_name"],
                target_subtype=item["after_subtype"],
                signals=_signals(item["signals"]),
                proposal=None,
                basis=entries[str(item["legacy"])].basis,
                rationale=entries[str(item["legacy"])].rationale,
            )
            for item in described
        ],
    )


@router.post("/migrations/{migration_id}/account-mapping-sets", status_code=status.HTTP_201_CREATED)
def create_account_mapping_set(
    migration_id: uuid.UUID, body: AccountMappingDraftIn, actor: DrafterDep, session: SessionDep
) -> AccountMappingSetOut:
    workspace.get_migration(session, migration_id)
    mapping_set = accounts.create_draft(
        session,
        actor=actor,
        migration_id=migration_id,
        base=body.base,
        changes=[accounts.EntryChange(c.legacy, c.target, c.rationale) for c in body.changes],
    )
    return _account_set_out(session, mapping_set)


# ----------------------------------------------------------------------------- change requests
def _names(session: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    names = {}
    for user_id in user_ids:
        user = identity.get_user(session, user_id)
        names[user_id] = user.display_name if user else "Unknown user"
    return names


def change_request_out(
    session: Session, change: ChangeRequest, names: dict[uuid.UUID, str] | None = None
) -> ChangeRequestOut:
    names = names or _names(session, {change.requested_by})
    approvals = changes.approvals_for(session, change.id)
    return ChangeRequestOut(
        id=change.id,
        migration_id=change.migration_id,
        key=change.key,
        kind=change.kind,
        status=change.status,
        title=change.title,
        justification=change.justification,
        origin=change.origin,
        origin_finding_id=change.origin_finding_id,
        requested_by=change.requested_by,
        requested_by_name=names.get(change.requested_by, "Unknown user"),
        created_at=change.created_at,
        submitted_at=change.submitted_at,
        decided_at=change.decided_at,
        applied_at=change.applied_at,
        version=change.version,
        approvals_required=len(change.required_approvals),
        approvals_given=sum(1 for a in approvals if a.decision == ApprovalDecision.APPROVE.value),
    )


@router.get("/migrations/{migration_id}/change-requests")
def list_change_requests(
    migration_id: uuid.UUID,
    _actor: ReaderDep,
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[ChangeRequestOut]:
    workspace.get_migration(session, migration_id)
    rows = changes.change_requests_for(
        session, migration_id, status=status_filter, kind=kind, offset=offset, limit=limit
    )
    names = _names(session, {c.requested_by for c in rows})
    return [change_request_out(session, c, names) for c in rows]


@router.post("/migrations/{migration_id}/change-requests", status_code=status.HTTP_201_CREATED)
def create_change_request(
    migration_id: uuid.UUID,
    body: ChangeRequestIn,
    actor: DrafterDep,
    session: SessionDep,
    clock: ClockDep,
) -> ChangeRequestOut:
    """Create a draft. Record overrides name the record; the server resolves the current value."""
    workspace.get_migration(session, migration_id)
    try:
        kind = ChangeRequestKind(body.kind)
    except ValueError as exc:
        raise InvalidInputError(f"unknown change request kind {body.kind}") from exc
    change = approvals.create(
        session,
        actor=actor,
        migration_id=migration_id,
        kind=kind,
        title=body.title,
        payload=body.payload,
        field_override=body.field_override.model_dump() if body.field_override else None,
        quarantine_repair=body.quarantine_repair.model_dump() if body.quarantine_repair else None,
        evidence_refs=list(body.evidence_refs),
        clock=clock,
    )
    return change_request_out(session, change)


@router.get("/change-requests/{change_id}")
def get_change_request(
    change_id: uuid.UUID, actor: ReaderDep, session: SessionDep
) -> ChangeRequestDetailOut:
    change = changes.get_change_request(session, change_id)
    approvals = changes.approvals_for(session, change.id)
    names = _names(session, {change.requested_by, *(a.reviewer_user_id for a in approvals)})
    satisfied = {
        a.satisfies_requirement_index: names[a.reviewer_user_id]
        for a in approvals
        if a.decision == ApprovalDecision.APPROVE.value
    }
    if change.status != ChangeRequestStatus.SUBMITTED.value:
        viewer = ReviewerOut(
            can_review=False,
            reason=f"the change request is {change.status}",
            is_requester=actor.user_id == change.requested_by,
        )
    elif (
        actor.role is None
        or not allowed(actor.role, Permission.REVIEW_CHANGE_REQUEST)
        or actor.user_id is None
    ):
        viewer = ReviewerOut(
            can_review=False,
            reason="your role does not review change requests",
            is_requester=actor.user_id == change.requested_by,
        )
    else:
        check = eligibility(
            requirements=change.required_approvals,
            approvals=[
                RecordedApproval(a.reviewer_user_id, a.satisfies_requirement_index, a.decision)
                for a in approvals
            ],
            requested_by=change.requested_by,
            reviewer_id=actor.user_id,
            reviewer_role=actor.role or "",
        )
        viewer = ReviewerOut(
            can_review=check.allowed,
            reason=check.reason,
            is_requester=actor.user_id == change.requested_by,
        )
    runs = session.scalars(
        select(PipelineRun.id)
        .where(PipelineRun.change_request_id == change.id)
        .order_by(PipelineRun.sequence)
    )
    return ChangeRequestDetailOut(
        change_request=change_request_out(session, change, names),
        payload=change.payload,
        before=change.before,
        after=change.after,
        impact=change.impact,
        evidence_refs=list(change.evidence_refs),
        base_entity_versions=change.base_entity_versions,
        requirements=[
            RequirementOut(index=i, role=r["role"], satisfied_by=satisfied.get(i))
            for i, r in enumerate(change.required_approvals)
        ],
        approvals=[
            ApprovalOut(
                reviewer_user_id=a.reviewer_user_id,
                reviewer_name=names[a.reviewer_user_id],
                role=a.reviewer_role_at_decision,
                decision=a.decision,
                comment=a.comment,
                decided_at=a.decided_at,
            )
            for a in approvals
        ],
        viewer=viewer,
        runs=list(runs),
        history=[
            audit_event_out(e) for e in audit_read.events_for_change_request(session, change.id)
        ],
    )


@router.put("/change-requests/{change_id}")
def update_change_request(
    change_id: uuid.UUID,
    body: ChangeRequestUpdateIn,
    actor: DrafterDep,
    session: SessionDep,
    clock: ClockDep,
) -> ChangeRequestOut:
    change = changes.get_change_request(session, change_id)
    if change.kind == ChangeRequestKind.RECORD_OVERRIDE.value and body.payload is not None:
        raise InvalidInputError("withdraw a record override and draft it again to change it")
    changes.update_draft(
        session,
        actor=actor,
        change=change,
        title=body.title,
        payload=body.payload,
        expected_version=body.version,
        clock=clock,
    )
    return change_request_out(session, change)


@router.post("/change-requests/{change_id}/submit")
def submit_change_request(
    change_id: uuid.UUID,
    body: JustificationIn,
    actor: DrafterDep,
    session: SessionDep,
    clock: ClockDep,
) -> ChangeRequestOut:
    change = changes.get_change_request(session, change_id)
    approvals.submit(
        session, actor=actor, change=change, justification=body.justification, clock=clock
    )
    return change_request_out(session, change)


def _review(
    session: Session,
    actor: Actor,
    change_id: uuid.UUID,
    decision: ApprovalDecision,
    comment: str,
    clock: Any,
) -> ReviewOutcomeOut:
    change = changes.get_change_request(session, change_id)
    outcome = approvals.review(
        session, actor=actor, change=change, decision=decision, comment=comment, clock=clock
    )
    return ReviewOutcomeOut(
        change_request=change_request_out(session, outcome.change), run_id=outcome.run_id
    )


@router.post("/change-requests/{change_id}/approve")
def approve_change_request(
    change_id: uuid.UUID, body: ReviewIn, actor: ReviewerDep, session: SessionDep, clock: ClockDep
) -> ReviewOutcomeOut:
    """Record an approval. The response status is ``stale`` when the base changed meanwhile."""
    return _review(session, actor, change_id, ApprovalDecision.APPROVE, body.comment, clock)


@router.post("/change-requests/{change_id}/reject")
def reject_change_request(
    change_id: uuid.UUID, body: ReviewIn, actor: ReviewerDep, session: SessionDep, clock: ClockDep
) -> ReviewOutcomeOut:
    return _review(session, actor, change_id, ApprovalDecision.REJECT, body.comment, clock)


@router.post("/change-requests/{change_id}/withdraw")
def withdraw_change_request(
    change_id: uuid.UUID, body: WithdrawIn, actor: ActorDep, session: SessionDep, clock: ClockDep
) -> ChangeRequestOut:
    change = changes.get_change_request(session, change_id)
    approvals.withdraw(session, actor=actor, change=change, reason=body.reason, clock=clock)
    return change_request_out(session, change)


@router.get("/migrations/{migration_id}/record-overrides")
def list_record_overrides(
    migration_id: uuid.UUID, _actor: ReaderDep, session: SessionDep
) -> list[RecordOverrideOut]:
    workspace.get_migration(session, migration_id)
    rows = session.scalars(
        select(RecordOverride)
        .where(RecordOverride.migration_id == migration_id)
        .order_by(RecordOverride.created_at.desc(), RecordOverride.id)
    )
    return [
        RecordOverrideOut(
            id=r.id,
            natural_key=r.natural_key,
            dataset_type=r.dataset_type,
            target=r.target,
            field=r.field,
            expected_current_value=r.expected_current_value,
            new_value=r.new_value,
            reason=r.reason,
            status=r.status,
            change_request_id=r.change_request_id,
            reverted_by_cr_id=r.reverted_by_cr_id,
            created_at=r.created_at,
        )
        for r in rows
    ]
