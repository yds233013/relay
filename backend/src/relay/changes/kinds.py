"""Per-kind change request behaviour: payload, submission snapshot, staleness, application.

Each kind defines:
- ``payload``: the Pydantic model a stored payload must satisfy;
- ``check_draft``: preconditions checked when a draft is created or edited;
- ``prepare``: server-computed ``before``/``after``/``impact`` and required approvals at submit;
- ``versions``: the base entity versions whose change makes a submitted request stale;
- ``apply``: the effect, run inside the approval transaction, with its own audit events;
- ``release``: what happens to held objects when the request is rejected, withdrawn or stale.

Record override payloads arrive already resolved against a pipeline run by
``relay.pipeline.overrides`` (expected current value, source import, amount); clients never supply
those values directly.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.canonical.records import validate_period
from relay.changes.domain import (
    disposition_approvals,
    record_override_approvals,
    required_approvals,
)
from relay.changes.models import (
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestStatus,
    Disposition,
    EntityDecision,
    GateWaiver,
    OverlayStatus,
    OverrideTarget,
    ReadinessSignoff,
    RecordOverride,
    SignoffStatus,
    WaiverStatus,
)
from relay.core.actor import Actor
from relay.core.clock import Clock
from relay.core.dates import parse_iso_business_date
from relay.core.errors import InvalidInputError, RelayError
from relay.core.ids import uuid7
from relay.core.money import Money, validate_amount
from relay.engine.exceptions import Severity
from relay.engine.rules import REGISTRY
from relay.identity import service as identity
from relay.issues import workflow as issue_workflow
from relay.issues.models import OPEN_STATUSES, Issue, IssueStatus
from relay.mapping_sets import accounts
from relay.mapping_sets import service as column_sets
from relay.mapping_sets.models import AccountMappingSet, ColumnMappingSet, MappingSetStatus
from relay.workspace import service as workspace
from relay.workspace.models import Dataset, MigrationStatus, PolicyVersion

MAX_REPLACEMENT_TEXT: Final = 65_536
MAX_LISTED_CHANGES: Final = 500
OVERRIDABLE_FIELDS: Final = {"je": frozenset({"entry_date", "posting_period"})}
"""Canonical fields the engine can override, by natural key prefix."""

type Versions = dict[str, str | int | None]


class ChangeRequestPreconditionError(RelayError):
    code: ClassVar[str] = "change_request.precondition_failed"
    title: ClassVar[str] = "Change request cannot be made against the current state"
    http_status: ClassVar[int] = 409


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MappingSetPayload(_Payload):
    mapping_set_id: uuid.UUID


class CanonicalFieldOverridePayload(_Payload):
    target: Literal["canonical_field"]
    run_id: uuid.UUID
    dataset_type: str
    dataset_id: uuid.UUID
    import_id: uuid.UUID
    natural_key: str
    field: str
    expected_current: str
    new_value: str
    amount: str | None = None
    currency: str | None = None

    @field_validator("new_value")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("new value is required")
        return value.strip()


class QuarantineRepairPayload(_Payload):
    target: Literal["quarantined_row_repair"]
    run_id: uuid.UUID
    exception_id: uuid.UUID
    dataset_type: str
    dataset_id: uuid.UUID
    import_id: uuid.UUID
    natural_key: str
    quarantine_key: str
    raw_text: str
    replacement_text: str = Field(max_length=MAX_REPLACEMENT_TEXT)
    expected_fields: int
    delimiter: str = ","
    line_start: int
    line_end: int


class RecordOverridePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    override: Annotated[
        CanonicalFieldOverridePayload | QuarantineRepairPayload, Field(discriminator="target")
    ]


class PolicyChangePayload(_Payload):
    changes: dict[str, Any] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class Prepared:
    before: dict[str, Any]
    after: dict[str, Any]
    impact: dict[str, Any]
    required_approvals: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class Kind:
    payload: type[BaseModel]
    check_draft: Callable[[Session, uuid.UUID, Any], None]
    prepare: Callable[[Session, ChangeRequest, Any], Prepared]
    versions: Callable[[Session, ChangeRequest, Any], Versions]
    apply: Callable[[Session, Actor, ChangeRequest, Any, Clock | None], None]
    release: Callable[[Session, ChangeRequest, Any, ChangeRequestStatus], None] = field(
        default=lambda *_: None
    )


def parse_payload(kind: ChangeRequestKind, raw: dict[str, Any]) -> Any:
    handler = KINDS.get(kind)
    if handler is None:
        raise InvalidInputError(f"{kind.value} change requests are not available yet")
    try:
        return handler.payload.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'payload'}: {e['msg']}" for e in exc.errors()
        )
        raise InvalidInputError(f"invalid payload for {kind.value}: {problems}") from exc


def _released_status(outcome: ChangeRequestStatus) -> MappingSetStatus:
    return (
        MappingSetStatus.REJECTED
        if outcome is ChangeRequestStatus.REJECTED
        else MappingSetStatus.ABANDONED
    )


# ------------------------------------------------------------------------ column mapping sets
def _column_set(session: Session, payload: MappingSetPayload) -> tuple[ColumnMappingSet, Dataset]:
    mapping_set = session.get(ColumnMappingSet, payload.mapping_set_id)
    if mapping_set is None:
        raise InvalidInputError("mapping set does not exist")
    return mapping_set, workspace.get_dataset(session, mapping_set.dataset_id)


def _column_check(session: Session, migration_id: uuid.UUID, payload: MappingSetPayload) -> None:
    mapping_set, dataset = _column_set(session, payload)
    if dataset.migration_id != migration_id:
        raise InvalidInputError("mapping set belongs to another migration")
    if mapping_set.status != MappingSetStatus.DRAFT.value:
        raise ChangeRequestPreconditionError("only a draft mapping set can be proposed")


def _column_prepare(session: Session, _: ChangeRequest, payload: MappingSetPayload) -> Prepared:
    mapping_set, dataset = _column_set(session, payload)
    column_sets.mark_pending(mapping_set)
    current = column_sets.approved_set(session, dataset.id)
    before_fields = (
        column_sets.engine_config(session, current, dataset.dataset_type)["fields"]
        if current
        else {}
    )
    after_fields = column_sets.engine_config(session, mapping_set, dataset.dataset_type)["fields"]
    changed = sorted(
        name
        for name in set(before_fields) | set(after_fields)
        if before_fields.get(name) != after_fields.get(name)
    )
    return Prepared(
        before={"approved_version": current.version if current else None, "fields": before_fields},
        after={"approved_version": mapping_set.version, "fields": after_fields},
        impact={
            "dataset_id": str(dataset.id),
            "dataset_name": dataset.name,
            "dataset_type": dataset.dataset_type,
            "changed_fields": changed,
        },
        required_approvals=required_approvals(ChangeRequestKind.COLUMN_MAPPING_SET),
    )


def _column_versions(session: Session, _: ChangeRequest, payload: MappingSetPayload) -> Versions:
    mapping_set, dataset = _column_set(session, payload)
    current = column_sets.approved_set(session, dataset.id)
    return {
        f"column_mapping_set:{mapping_set.id}": mapping_set.lock_version,
        f"dataset:{dataset.id}:approved_column_mapping_set": str(current.id) if current else None,
    }


def _column_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: MappingSetPayload,
    _: Clock | None,
) -> None:
    mapping_set = session.get(ColumnMappingSet, payload.mapping_set_id, with_for_update=True)
    if mapping_set is None:
        raise ChangeRequestPreconditionError("mapping set disappeared")
    column_sets.approve(
        session,
        actor=actor,
        mapping_set=mapping_set,
        change_request_id=change.id,
        migration_id=change.migration_id,
    )


def _column_release(
    session: Session, _: ChangeRequest, payload: MappingSetPayload, outcome: ChangeRequestStatus
) -> None:
    mapping_set = session.get(ColumnMappingSet, payload.mapping_set_id)
    if mapping_set is not None and mapping_set.status in {
        MappingSetStatus.PENDING_APPROVAL.value,
        MappingSetStatus.DRAFT.value,
    }:
        mapping_set.status = _released_status(outcome).value


# ----------------------------------------------------------------------- account mapping sets
def _account_set(session: Session, payload: MappingSetPayload) -> AccountMappingSet:
    mapping_set = session.get(AccountMappingSet, payload.mapping_set_id)
    if mapping_set is None:
        raise InvalidInputError("account mapping set does not exist")
    return mapping_set


def _account_check(session: Session, migration_id: uuid.UUID, payload: MappingSetPayload) -> None:
    mapping_set = _account_set(session, payload)
    if mapping_set.migration_id != migration_id:
        raise InvalidInputError("account mapping set belongs to another migration")
    if mapping_set.status != MappingSetStatus.DRAFT.value:
        raise ChangeRequestPreconditionError("only a draft account mapping set can be proposed")


def _account_prepare(
    session: Session, change: ChangeRequest, payload: MappingSetPayload
) -> Prepared:
    mapping_set = _account_set(session, payload)
    current = accounts.approved_set(session, change.migration_id)
    if mapping_set.based_on_set_id is not None and (
        current is None or current.id != mapping_set.based_on_set_id
    ):
        raise ChangeRequestPreconditionError(
            "the draft was based on an account mapping version that is no longer approved; "
            "draft again from the approved set"
        )
    accounts.mark_pending(mapping_set)
    before = accounts.effective_pairs(session, change.migration_id)
    after = {k: e.target for k, e in accounts.entries(session, mapping_set.id).items()}
    rationale = {k: e.rationale for k, e in accounts.entries(session, mapping_set.id).items()}
    changed = accounts.diff(before, after)
    described = accounts.describe(session, change.migration_id, changed)
    for item in described:
        item["rationale"] = rationale.get(str(item["legacy"]))
    return Prepared(
        before={
            "approved_version": current.version if current else None,
            "source": "approved_set" if current else "account_mapping_file",
            "entries": len(before),
        },
        after={"version": mapping_set.version, "entries": len(after)},
        impact={
            "changed_count": len(changed),
            "changes": described[:MAX_LISTED_CHANGES],
            "changes_truncated": len(changed) > MAX_LISTED_CHANGES,
        },
        required_approvals=required_approvals(ChangeRequestKind.ACCOUNT_MAPPING_SET),
    )


def _account_versions(
    session: Session, change: ChangeRequest, payload: MappingSetPayload
) -> Versions:
    mapping_set = _account_set(session, payload)
    current = accounts.approved_set(session, change.migration_id)
    return {
        f"account_mapping_set:{mapping_set.id}": mapping_set.lock_version,
        "approved_account_mapping_set": str(current.id) if current else None,
    }


def _account_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: MappingSetPayload,
    _: Clock | None,
) -> None:
    mapping_set = session.get(AccountMappingSet, payload.mapping_set_id, with_for_update=True)
    if mapping_set is None:
        raise ChangeRequestPreconditionError("account mapping set disappeared")
    accounts.approve(session, actor=actor, mapping_set=mapping_set, change_request_id=change.id)


def _account_release(
    session: Session, _: ChangeRequest, payload: MappingSetPayload, outcome: ChangeRequestStatus
) -> None:
    mapping_set = session.get(AccountMappingSet, payload.mapping_set_id)
    if mapping_set is not None:
        accounts.release(mapping_set, _released_status(outcome))


# --------------------------------------------------------------------------- record overrides
def _override_slot(override: CanonicalFieldOverridePayload | QuarantineRepairPayload) -> str:
    if isinstance(override, CanonicalFieldOverridePayload):
        return f"{override.natural_key}#{override.field}"
    return override.natural_key


def _active_override(
    session: Session, migration_id: uuid.UUID, slot_key: str, field_name: str | None
) -> RecordOverride | None:
    query = select(RecordOverride).where(
        RecordOverride.migration_id == migration_id,
        RecordOverride.natural_key == slot_key,
        RecordOverride.status == OverlayStatus.ACTIVE.value,
    )
    if field_name is not None:
        query = query.where(RecordOverride.field == field_name)
    return session.scalars(query).first()


def _validate_new_value(override: CanonicalFieldOverridePayload) -> None:
    prefix = override.natural_key.partition(":")[0]
    if override.field not in OVERRIDABLE_FIELDS.get(prefix, frozenset()):
        raise InvalidInputError(f"{override.field} cannot be overridden on {override.natural_key}")
    try:
        if override.field == "entry_date":
            parse_iso_business_date(override.new_value)
        elif override.field == "posting_period":
            validate_period(override.new_value)
    except (InvalidInputError, ValueError) as exc:
        raise InvalidInputError(f"{override.field} value is invalid: {override.new_value}") from exc
    if override.new_value == override.expected_current:
        raise InvalidInputError("the new value equals the current value")


def _validate_replacement(repair: QuarantineRepairPayload) -> None:
    rows = list(csv.reader(io.StringIO(repair.replacement_text), delimiter=repair.delimiter))
    if len(rows) != 1:
        raise InvalidInputError("the replacement must be exactly one CSV record")
    if len(rows[0]) != repair.expected_fields:
        raise InvalidInputError(
            f"the replacement has {len(rows[0])} fields; the file header has "
            f"{repair.expected_fields}"
        )


def _override_check(
    session: Session, migration_id: uuid.UUID, payload: RecordOverridePayload
) -> None:
    override = payload.override
    dataset = workspace.get_dataset(session, override.dataset_id)
    if dataset.migration_id != migration_id:
        raise InvalidInputError("the record belongs to another migration")
    if dataset.active_import_id != override.import_id:
        raise ChangeRequestPreconditionError(
            "the record comes from an import that is no longer active; rerun and try again"
        )
    if isinstance(override, CanonicalFieldOverridePayload):
        _validate_new_value(override)
        field_name: str | None = override.field
    else:
        _validate_replacement(override)
        field_name = None
    if _active_override(session, migration_id, override.natural_key, field_name) is not None:
        raise ChangeRequestPreconditionError(
            "an active override already covers this record; revert it first"
        )


def _override_prepare(
    session: Session, change: ChangeRequest, payload: RecordOverridePayload
) -> Prepared:
    _override_check(session, change.migration_id, payload)
    override = payload.override
    if isinstance(override, CanonicalFieldOverridePayload):
        try:
            amount = Decimal(override.amount) if override.amount is not None else None
        except InvalidOperation as exc:
            raise InvalidInputError("override amount is invalid") from exc
        return Prepared(
            before={
                "natural_key": override.natural_key,
                "field": override.field,
                "value": override.expected_current,
            },
            after={
                "natural_key": override.natural_key,
                "field": override.field,
                "value": override.new_value,
            },
            impact={
                "dataset_type": override.dataset_type,
                "natural_key": override.natural_key,
                "amount": override.amount,
                "currency": override.currency,
                "run_id": str(override.run_id),
            },
            required_approvals=record_override_approvals(
                field=override.field, restores_row=False, impact=amount
            ),
        )
    return Prepared(
        before={
            "natural_key": override.natural_key,
            "raw_text": override.raw_text,
            "lines": [override.line_start, override.line_end],
        },
        after={"natural_key": override.natural_key, "replacement_text": override.replacement_text},
        impact={
            "dataset_type": override.dataset_type,
            "natural_key": override.natural_key,
            "restores_row": True,
            "run_id": str(override.run_id),
            "exception_id": str(override.exception_id),
        },
        required_approvals=record_override_approvals(field=None, restores_row=True, impact=None),
    )


def _override_versions(
    session: Session, change: ChangeRequest, payload: RecordOverridePayload
) -> Versions:
    override = payload.override
    dataset = workspace.get_dataset(session, override.dataset_id)
    field_name = override.field if isinstance(override, CanonicalFieldOverridePayload) else None
    active = _active_override(session, change.migration_id, override.natural_key, field_name)
    return {
        f"dataset:{dataset.id}:active_import": (
            str(dataset.active_import_id) if dataset.active_import_id else None
        ),
        f"override:{_override_slot(override)}": str(active.id) if active else None,
    }


def _override_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: RecordOverridePayload,
    clock: Clock | None,
) -> None:
    override = payload.override
    if isinstance(override, CanonicalFieldOverridePayload):
        row = RecordOverride(
            id=uuid7(clock),
            migration_id=change.migration_id,
            dataset_type=override.dataset_type,
            natural_key=override.natural_key,
            target=OverrideTarget.CANONICAL_FIELD.value,
            field=override.field,
            import_id=override.import_id,
            expected_current_value=override.expected_current,
            new_value=override.new_value,
            reason=change.justification,
            change_request_id=change.id,
            status=OverlayStatus.ACTIVE.value,
            version=1,
        )
    else:
        row = RecordOverride(
            id=uuid7(clock),
            migration_id=change.migration_id,
            dataset_type=override.dataset_type,
            natural_key=override.natural_key,
            target=OverrideTarget.QUARANTINED_ROW_REPAIR.value,
            field=None,
            import_id=override.import_id,
            expected_current_value={"raw_text": override.raw_text},
            new_value={
                "quarantine_key": override.quarantine_key,
                "replacement_text": override.replacement_text,
            },
            reason=change.justification,
            change_request_id=change.id,
            status=OverlayStatus.ACTIVE.value,
            version=1,
        )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="override.activated",
        entity_type="record_override",
        entity_id=row.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"value": row.expected_current_value},
        after={
            "natural_key": row.natural_key,
            "target": row.target,
            "field": row.field,
            "value": row.new_value,
            "status": row.status,
        },
        reason=change.justification,
        clock=clock,
    )


# ----------------------------------------------------------------------------- policy changes
def _merged_policy(
    session: Session, migration_id: uuid.UUID, payload: PolicyChangePayload
) -> tuple[PolicyVersion, dict[str, Any]]:
    current = workspace.current_policy(session, migration_id)
    unknown = set(payload.changes) - set(current.policy)
    if unknown:
        raise InvalidInputError(f"unknown policy keys: {sorted(unknown)}")
    merged = {**current.policy, **payload.changes}
    overrides = merged.get("severity_overrides")
    if not isinstance(overrides, dict):
        raise InvalidInputError("severity_overrides must be an object")
    for rule_id, severity in overrides.items():
        if rule_id not in REGISTRY:
            raise InvalidInputError(f"severity override names unknown rule {rule_id}")
        if severity not in {s.value for s in Severity}:
            raise InvalidInputError(f"severity override for {rule_id} is not a severity")
    try:
        policy = workspace.policy_from_document(merged)
    except (InvalidInputError, ValueError, TypeError, InvalidOperation) as exc:
        raise InvalidInputError("policy change does not produce a valid policy") from exc
    document = workspace.policy_document(policy)
    if document == current.policy:
        raise InvalidInputError("the policy change changes nothing")
    return current, document


def _policy_check(session: Session, migration_id: uuid.UUID, payload: PolicyChangePayload) -> None:
    _merged_policy(session, migration_id, payload)


def _policy_prepare(
    session: Session, change: ChangeRequest, payload: PolicyChangePayload
) -> Prepared:
    current, document = _merged_policy(session, change.migration_id, payload)
    keys = sorted(k for k in document if document[k] != current.policy.get(k))
    return Prepared(
        before={"policy_version": current.version, **{k: current.policy.get(k) for k in keys}},
        after={"policy_version": current.version + 1, **{k: document[k] for k in keys}},
        impact={"changed_keys": keys},
        # Approval requirements are not part of the policy document, so a policy change cannot
        # lower its own requirements (governance.md §2.3).
        required_approvals=required_approvals(ChangeRequestKind.POLICY_CHANGE),
    )


def _policy_versions(session: Session, change: ChangeRequest, _: PolicyChangePayload) -> Versions:
    return {"policy_version": workspace.current_policy(session, change.migration_id).version}


def _policy_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: PolicyChangePayload,
    clock: Clock | None,
) -> None:
    current, document = _merged_policy(session, change.migration_id, payload)
    row = PolicyVersion(
        id=uuid7(clock),
        migration_id=change.migration_id,
        version=current.version + 1,
        policy=document,
        change_request_id=change.id,
        created_by=change.requested_by,
    )
    session.add(row)
    session.flush()
    keys = sorted(k for k in document if document[k] != current.policy.get(k))
    audit.record(
        session,
        actor=actor,
        action="policy.version_created",
        entity_type="policy_version",
        entity_id=row.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"version": current.version, **{k: current.policy.get(k) for k in keys}},
        after={"version": row.version, **{k: document[k] for k in keys}},
        clock=clock,
    )


# --------------------------------------------------------------------------- entity decisions
MAX_DECISION_MEMBERS: Final = 50


class EntityDecisionPayload(_Payload):
    party_type: Literal["customer", "vendor"]
    decision: Literal["same_entity", "distinct"]
    members: list[str] = Field(min_length=2, max_length=MAX_DECISION_MEMBERS)
    survivor: str | None = None
    run_id: uuid.UUID
    """The succeeded run whose staged parties the members were checked against."""

    @field_validator("members")
    @classmethod
    def _codes(cls, members: list[str]) -> list[str]:
        cleaned = sorted({m.strip() for m in members})
        if len(cleaned) != len(members) or any(not m or len(m) > 64 for m in cleaned):
            raise ValueError("members must be distinct, non-blank party codes")
        return cleaned


def _pairs(members: list[str]) -> set[frozenset[str]]:
    return {frozenset((a, b)) for i, a in enumerate(members) for b in members[i + 1 :]}


def active_entity_decisions(session: Session, migration_id: uuid.UUID) -> list[EntityDecision]:
    return list(
        session.scalars(
            select(EntityDecision)
            .where(
                EntityDecision.migration_id == migration_id,
                EntityDecision.status == OverlayStatus.ACTIVE.value,
            )
            .order_by(EntityDecision.created_at, EntityDecision.id)
        )
    )


def _overlapping(
    session: Session, migration_id: uuid.UUID, payload: EntityDecisionPayload
) -> list[EntityDecision]:
    proposed = _pairs(payload.members)
    return [
        d
        for d in active_entity_decisions(session, migration_id)
        if d.party_type == payload.party_type and _pairs(sorted(d.members)) & proposed
    ]


def _decision_check(
    session: Session, migration_id: uuid.UUID, payload: EntityDecisionPayload
) -> None:
    if payload.decision == "same_entity" and payload.survivor not in payload.members:
        raise InvalidInputError("a same-entity decision needs a survivor among the members")
    if payload.decision == "distinct" and payload.survivor is not None:
        raise InvalidInputError("a distinct decision has no survivor")
    if _overlapping(session, migration_id, payload):
        raise ChangeRequestPreconditionError(
            "an active decision already covers some of these parties; revert it first"
        )


def _decision_prepare(
    session: Session, change: ChangeRequest, payload: EntityDecisionPayload
) -> Prepared:
    _decision_check(session, change.migration_id, payload)
    return Prepared(
        before={"decisions": [], "members": payload.members},
        after={
            "party_type": payload.party_type,
            "decision": payload.decision,
            "members": payload.members,
            "survivor": payload.survivor,
        },
        impact={"run_id": str(payload.run_id), "pairs": len(_pairs(payload.members))},
        required_approvals=required_approvals(ChangeRequestKind.ENTITY_DECISION),
    )


def _decision_versions(
    session: Session, change: ChangeRequest, payload: EntityDecisionPayload
) -> Versions:
    overlapping = sorted(str(d.id) for d in _overlapping(session, change.migration_id, payload))
    return {f"entity_decisions:{payload.party_type}": ",".join(overlapping) or None}


def _decision_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: EntityDecisionPayload,
    clock: Clock | None,
) -> None:
    row = EntityDecision(
        id=uuid7(clock),
        migration_id=change.migration_id,
        party_type=payload.party_type,
        decision=payload.decision,
        members=payload.members,
        survivor=payload.survivor,
        reason=change.justification,
        change_request_id=change.id,
        status=OverlayStatus.ACTIVE.value,
        version=1,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="entity_decision.activated",
        entity_type="entity_decision",
        entity_id=row.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"status": None},
        after={
            "party_type": row.party_type,
            "decision": row.decision,
            "members": row.members,
            "survivor": row.survivor,
            "status": row.status,
        },
        reason=change.justification,
        clock=clock,
    )


# ------------------------------------------------------------------------------- dispositions
MAX_DISPOSITION_ISSUES: Final = 100


class DispositionPayload(_Payload):
    """One decision about one or more findings (for example six months of the same bank fee).

    ``amount`` is the total the decision concerns. It is stored on the disposition row when the
    decision covers a single issue, and on the change request otherwise.
    """

    issue_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_DISPOSITION_ISSUES)
    kind: Literal["carry_forward_adjustment", "accepted_risk", "false_positive", "not_applicable"]
    amount: str | None = None
    follow_up: str = Field(default="", max_length=2000)
    follow_up_owner_id: uuid.UUID | None = None

    @field_validator("issue_ids")
    @classmethod
    def _distinct(cls, ids: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(ids)) != len(ids):
            raise ValueError("issues must be distinct")
        return sorted(ids)


def _disposition_issues(
    session: Session, migration_id: uuid.UUID, payload: DispositionPayload
) -> list[Issue]:
    issues = []
    for issue_id in payload.issue_ids:
        issue = session.get(Issue, issue_id)
        if issue is None or issue.migration_id != migration_id:
            raise InvalidInputError("issue not found in this migration")
        issues.append(issue)
    return issues


def active_dispositions(session: Session, migration_id: uuid.UUID) -> list[Disposition]:
    return list(
        session.scalars(
            select(Disposition)
            .where(
                Disposition.migration_id == migration_id,
                Disposition.status == OverlayStatus.ACTIVE.value,
            )
            .order_by(Disposition.created_at, Disposition.id)
        )
    )


def _disposition_check(
    session: Session, migration_id: uuid.UUID, payload: DispositionPayload
) -> None:
    issues = _disposition_issues(session, migration_id, payload)
    dispositioned = {d.fingerprint for d in active_dispositions(session, migration_id)}
    for issue in issues:
        if issue.fingerprint is None:
            raise InvalidInputError(
                f"{issue.key}: only issues reported by rules or reconciliations are dispositioned"
            )
        if IssueStatus(issue.status) not in OPEN_STATUSES:
            raise ChangeRequestPreconditionError(
                f"{issue.key} is {issue.status} and cannot be dispositioned"
            )
        if payload.kind == "accepted_risk" and issue.severity == "critical":
            raise InvalidInputError(f"{issue.key}: critical findings cannot be accepted as a risk")
        if issue.fingerprint in dispositioned:
            raise ChangeRequestPreconditionError(f"{issue.key} already has an active disposition")
    if payload.kind == "carry_forward_adjustment" and payload.amount is None:
        raise InvalidInputError("a carry-forward adjustment states its amount")
    if payload.amount is not None:
        try:
            validate_amount(payload.amount)
        except InvalidInputError as exc:
            raise InvalidInputError("disposition amount is invalid") from exc
    if payload.follow_up_owner_id is not None:
        owner = identity.get_user(session, payload.follow_up_owner_id)
        if owner is None or not owner.is_active:
            raise InvalidInputError("the follow-up owner must be an active user")


_SEVERITY_ORDER: Final = ("low", "medium", "high", "critical")


def _disposition_prepare(
    session: Session, change: ChangeRequest, payload: DispositionPayload
) -> Prepared:
    _disposition_check(session, change.migration_id, payload)
    issues = _disposition_issues(session, change.migration_id, payload)
    currency = workspace.get_migration(session, change.migration_id).functional_currency
    severity = max((i.severity for i in issues), key=_SEVERITY_ORDER.index)
    listed = [
        {
            "issue_id": str(i.id),
            "key": i.key,
            "title": i.title,
            "severity": i.severity,
            "nature": i.nature,
            "amount_at_risk": (
                Money(i.amount_at_risk, currency).amount_str
                if i.amount_at_risk is not None
                else None
            ),
        }
        for i in issues
    ]
    return Prepared(
        before={"issues": {i.key: i.status for i in issues}},
        after={
            "issues": {i.key: IssueStatus.DISPOSITIONED.value for i in issues},
            "kind": payload.kind,
            "amount": (
                Money(validate_amount(payload.amount), currency).amount_str
                if payload.amount is not None
                else None
            ),
            "currency": currency.code,
            "follow_up": payload.follow_up,
        },
        impact={
            "issues": listed,
            "highest_severity": severity,
            "currency": currency.code,
            "excluded_from_exposure": True,
        },
        required_approvals=disposition_approvals(kind=payload.kind, severity=severity),
    )


def _disposition_versions(
    session: Session, change: ChangeRequest, payload: DispositionPayload
) -> Versions:
    dispositioned = {d.fingerprint for d in active_dispositions(session, change.migration_id)}
    versions: Versions = {}
    for issue in _disposition_issues(session, change.migration_id, payload):
        state = "open" if IssueStatus(issue.status) in OPEN_STATUSES else issue.status
        versions[f"issue:{issue.id}"] = f"{state}:{issue.severity}"
        versions[f"disposition:{issue.fingerprint}"] = (
            "active" if issue.fingerprint in dispositioned else None
        )
    return versions


def _disposition_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: DispositionPayload,
    clock: Clock | None,
) -> None:
    issues = _disposition_issues(session, change.migration_id, payload)
    migration = workspace.get_migration(session, change.migration_id)
    single = len(issues) == 1 and payload.amount is not None
    for issue in issues:
        row = Disposition(
            id=uuid7(clock),
            migration_id=change.migration_id,
            issue_id=issue.id,
            fingerprint=str(issue.fingerprint),
            kind=payload.kind,
            amount=validate_amount(payload.amount) if single and payload.amount else None,
            currency=migration.functional_currency if single else None,
            follow_up=payload.follow_up.strip(),
            follow_up_owner_id=payload.follow_up_owner_id,
            reason=change.justification,
            change_request_id=change.id,
            status=OverlayStatus.ACTIVE.value,
            version=1,
        )
        session.add(row)
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="disposition.activated",
            entity_type="disposition",
            entity_id=row.id,
            migration_id=change.migration_id,
            change_request_id=change.id,
            before={"status": None},
            after={
                "issue_id": issue.id,
                "kind": row.kind,
                "amount": payload.amount,
                "follow_up": row.follow_up,
                "status": row.status,
            },
            reason=change.justification,
            clock=clock,
        )
        issue_workflow.mark_dispositioned(
            session, actor=actor, issue_id=issue.id, change_request_id=change.id, clock=clock
        )


# ---------------------------------------------------------------------------- readiness waivers
WAIVABLE_GATES: Final = frozenset({"G6", "G7", "G8", "G9"})


class GateWaiverPayload(_Payload):
    """Resolved from the current run's readiness evaluation by ``relay.pipeline.readiness``."""

    gate_id: str
    run_id: uuid.UUID
    run_fingerprint: str
    evaluation_id: uuid.UUID
    scope: dict[str, str] = Field(min_length=1)


def active_waivers(session: Session, migration_id: uuid.UUID) -> list[GateWaiver]:
    return list(
        session.scalars(
            select(GateWaiver)
            .where(
                GateWaiver.migration_id == migration_id,
                GateWaiver.status == WaiverStatus.ACTIVE.value,
            )
            .order_by(GateWaiver.created_at, GateWaiver.id)
        )
    )


def _waiver_check(session: Session, migration_id: uuid.UUID, payload: GateWaiverPayload) -> None:
    if payload.gate_id not in WAIVABLE_GATES:
        raise InvalidInputError(f"{payload.gate_id} cannot be waived")
    if any(key.startswith("not_applicable:") for key in payload.scope):
        raise InvalidInputError("a reconciliation that could not run cannot be waived")
    if any(
        w.gate_id == payload.gate_id and w.scope == payload.scope
        for w in active_waivers(session, migration_id)
    ):
        raise ChangeRequestPreconditionError("an active waiver already covers this gate")


def _waiver_prepare(
    session: Session, change: ChangeRequest, payload: GateWaiverPayload
) -> Prepared:
    _waiver_check(session, change.migration_id, payload)
    return Prepared(
        before={"gate_id": payload.gate_id, "status": "fail"},
        after={"gate_id": payload.gate_id, "status": "waived"},
        impact={
            "gate_id": payload.gate_id,
            "run_id": str(payload.run_id),
            "scope": payload.scope,
            "lapses_when": "any waived amount changes or a discrepancy appears or disappears",
        },
        required_approvals=required_approvals(ChangeRequestKind.GATE_WAIVER),
    )


def _waiver_versions(
    session: Session, change: ChangeRequest, payload: GateWaiverPayload
) -> Versions:
    active = [
        str(w.id)
        for w in active_waivers(session, change.migration_id)
        if w.gate_id == payload.gate_id
    ]
    return {f"gate_waivers:{payload.gate_id}": ",".join(active) or None}


def _waiver_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: GateWaiverPayload,
    clock: Clock | None,
) -> None:
    row = GateWaiver(
        id=uuid7(clock),
        migration_id=change.migration_id,
        gate_id=payload.gate_id,
        run_id=payload.run_id,
        run_fingerprint=payload.run_fingerprint,
        scope=payload.scope,
        reason=change.justification,
        change_request_id=change.id,
        status=WaiverStatus.ACTIVE.value,
        version=1,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="gate_waiver.activated",
        entity_type="gate_waiver",
        entity_id=row.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"status": None},
        after={"gate_id": row.gate_id, "scope": row.scope, "status": row.status},
        reason=change.justification,
        clock=clock,
    )


# --------------------------------------------------------------------------- readiness sign-off
class SignoffPayload(_Payload):
    """Resolved by ``relay.pipeline.readiness``: G1-G11 pass or are waived on this current run."""

    run_id: uuid.UUID
    run_fingerprint: str
    evaluation_id: uuid.UUID


def active_signoffs(session: Session, migration_id: uuid.UUID) -> list[ReadinessSignoff]:
    return list(
        session.scalars(
            select(ReadinessSignoff)
            .where(
                ReadinessSignoff.migration_id == migration_id,
                ReadinessSignoff.status == SignoffStatus.ACTIVE.value,
            )
            .order_by(ReadinessSignoff.created_at, ReadinessSignoff.id)
        )
    )


def _signoff_check(session: Session, migration_id: uuid.UUID, payload: SignoffPayload) -> None:
    if any(
        s.run_fingerprint == payload.run_fingerprint for s in active_signoffs(session, migration_id)
    ):
        raise ChangeRequestPreconditionError("this run is already signed off")


def _signoff_prepare(session: Session, change: ChangeRequest, payload: SignoffPayload) -> Prepared:
    _signoff_check(session, change.migration_id, payload)
    migration = workspace.get_migration(session, change.migration_id)
    return Prepared(
        before={"migration_status": migration.status, "run_fingerprint": payload.run_fingerprint},
        after={"migration_status": "signed_off", "run_fingerprint": payload.run_fingerprint},
        impact={
            "run_id": str(payload.run_id),
            "evaluation_id": str(payload.evaluation_id),
            "invalidated_by": "any later change to the run inputs",
        },
        required_approvals=required_approvals(ChangeRequestKind.READINESS_SIGNOFF),
    )


def _signoff_versions(session: Session, change: ChangeRequest, _: SignoffPayload) -> Versions:
    active = [str(s.id) for s in active_signoffs(session, change.migration_id)]
    return {"readiness_signoffs": ",".join(active) or None}


def _signoff_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: SignoffPayload,
    clock: Clock | None,
) -> None:
    row = ReadinessSignoff(
        id=uuid7(clock),
        migration_id=change.migration_id,
        run_id=payload.run_id,
        run_fingerprint=payload.run_fingerprint,
        readiness_evaluation_id=payload.evaluation_id,
        change_request_id=change.id,
        status=SignoffStatus.ACTIVE.value,
        version=1,
    )
    session.add(row)
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="readiness.signed_off",
        entity_type="readiness_signoff",
        entity_id=row.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"status": None},
        after={"run_id": row.run_id, "run_fingerprint": row.run_fingerprint, "status": row.status},
        reason=change.justification,
        clock=clock,
    )
    workspace.set_migration_status(
        session,
        actor=actor,
        migration=workspace.get_migration(session, change.migration_id),
        status=MigrationStatus.SIGNED_OFF,
        reason="readiness sign-off applied",
        change_request_id=change.id,
    )


def invalidate_signoffs(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    current_fingerprint: str,
    clock: Clock | None = None,
) -> int:
    """governance.md §4.2: any change to the inputs invalidates a sign-off (audited)."""
    invalidated = 0
    for signoff in active_signoffs(session, migration_id):
        if signoff.run_fingerprint == current_fingerprint:
            continue
        signoff.status = SignoffStatus.INVALIDATED.value
        signoff.invalidated_by_fingerprint = current_fingerprint
        signoff.version += 1
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="readiness.signoff_invalidated",
            entity_type="readiness_signoff",
            entity_id=signoff.id,
            migration_id=migration_id,
            before={
                "status": SignoffStatus.ACTIVE.value,
                "run_fingerprint": signoff.run_fingerprint,
            },
            after={"status": signoff.status, "current_fingerprint": current_fingerprint},
            reason="the migration's inputs changed after sign-off",
            clock=clock,
        )
        invalidated += 1
    if invalidated and not active_signoffs(session, migration_id):
        workspace.set_migration_status(
            session,
            actor=actor,
            migration=workspace.get_migration(session, migration_id),
            status=MigrationStatus.IN_PROGRESS,
            reason="sign-off invalidated by an input change",
        )
    return invalidated


def lapse_waivers(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    applied_waiver_ids: set[str],
    run_id: uuid.UUID,
    clock: Clock | None = None,
) -> int:
    """Active waivers the current evaluation did not apply have lapsed (audited)."""
    lapsed = 0
    for waiver in active_waivers(session, migration_id):
        if str(waiver.id) in applied_waiver_ids:
            continue
        waiver.status = WaiverStatus.LAPSED.value
        waiver.lapsed_run_id = run_id
        waiver.version += 1
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="gate_waiver.lapsed",
            entity_type="gate_waiver",
            entity_id=waiver.id,
            migration_id=migration_id,
            before={"status": WaiverStatus.ACTIVE.value, "scope": waiver.scope},
            after={"status": waiver.status, "run_id": run_id},
            reason="the waived gate's discrepancies or amounts changed",
            clock=clock,
        )
        lapsed += 1
    return lapsed


# ------------------------------------------------------------------------------------ reverts
RevertTarget = Literal["record_override", "entity_decision", "disposition", "gate_waiver"]
type Revertable = RecordOverride | EntityDecision | Disposition | GateWaiver
_REVERTABLE: Final[dict[str, type[Revertable]]] = {
    "record_override": RecordOverride,
    "entity_decision": EntityDecision,
    "disposition": Disposition,
    "gate_waiver": GateWaiver,
}


class RevertPayload(_Payload):
    target: RevertTarget
    target_id: uuid.UUID

    @model_validator(mode="before")
    @classmethod
    def _legacy_override_form(cls, raw: Any) -> Any:
        """M5 stored reverts as ``{"record_override_id": ...}``."""
        if isinstance(raw, dict) and set(raw) == {"record_override_id"}:
            return {"target": "record_override", "target_id": raw["record_override_id"]}
        return raw


def _revert_target(
    session: Session, payload: RevertPayload, *, for_update: bool = False
) -> Revertable:
    target = session.get(_REVERTABLE[payload.target], payload.target_id, with_for_update=for_update)
    if not isinstance(target, RecordOverride | EntityDecision | Disposition | GateWaiver):
        raise InvalidInputError(f"{payload.target.replace('_', ' ')} does not exist")
    return target


def _revert_check(session: Session, migration_id: uuid.UUID, payload: RevertPayload) -> None:
    target = _revert_target(session, payload)
    if target.migration_id != migration_id:
        raise InvalidInputError("the target belongs to another migration")
    if target.status != OverlayStatus.ACTIVE.value:
        raise ChangeRequestPreconditionError("only an active overlay can be reverted")


def _describe_target(target: Revertable) -> dict[str, Any]:
    if isinstance(target, RecordOverride):
        return {
            "natural_key": target.natural_key,
            "target": target.target,
            "field": target.field,
            "value": target.new_value,
        }
    if isinstance(target, EntityDecision):
        return {
            "party_type": target.party_type,
            "decision": target.decision,
            "members": target.members,
            "survivor": target.survivor,
        }
    if isinstance(target, GateWaiver):
        return {"gate_id": target.gate_id, "scope": target.scope}
    return {"issue_id": str(target.issue_id), "kind": target.kind, "amount": str(target.amount)}


def _revert_prepare(session: Session, change: ChangeRequest, payload: RevertPayload) -> Prepared:
    _revert_check(session, change.migration_id, payload)
    target = _revert_target(session, payload)
    original = session.get_one(ChangeRequest, target.change_request_id)
    described = {
        "target": payload.target,
        "target_id": str(target.id),
        "original_change_request": original.key,
        **_describe_target(target),
    }
    impact: dict[str, Any] = {"target": payload.target}
    if isinstance(target, RecordOverride):
        impact.update(natural_key=target.natural_key, restores=target.expected_current_value)
    elif isinstance(target, Disposition):
        impact.update(issue_id=str(target.issue_id), reopens_issue=True)
    elif isinstance(target, GateWaiver):
        impact.update(gate_id=target.gate_id)
    else:
        impact.update(members=target.members)
    return Prepared(
        before={**described, "status": OverlayStatus.ACTIVE.value},
        after={**described, "status": OverlayStatus.REVERTED.value},
        impact=impact,
        # governance.md §2.3: a revert needs the same approvals as the change it reverts.
        required_approvals=list(original.required_approvals),
    )


def _revert_versions(session: Session, _: ChangeRequest, payload: RevertPayload) -> Versions:
    target = _revert_target(session, payload)
    return {f"{payload.target}:{target.id}": target.version}


def _revert_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: RevertPayload,
    clock: Clock | None,
) -> None:
    target = _revert_target(session, payload, for_update=True)
    if target.status != OverlayStatus.ACTIVE.value:
        raise ChangeRequestPreconditionError("the target is no longer active")
    target.status = OverlayStatus.REVERTED.value
    target.reverted_by_cr_id = change.id
    target.version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action=f"{payload.target}.reverted",
        entity_type=payload.target,
        entity_id=target.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"status": OverlayStatus.ACTIVE.value, **_describe_target(target)},
        after={"status": OverlayStatus.REVERTED.value},
        reason=change.justification,
        clock=clock,
    )
    if isinstance(target, Disposition):
        issue_workflow.undo_disposition(
            session, actor=actor, issue_id=target.issue_id, change_request_id=change.id, clock=clock
        )


KINDS: Final[dict[ChangeRequestKind, Kind]] = {
    ChangeRequestKind.COLUMN_MAPPING_SET: Kind(
        MappingSetPayload, _column_check, _column_prepare, _column_versions, _column_apply,
        _column_release,
    ),
    ChangeRequestKind.ACCOUNT_MAPPING_SET: Kind(
        MappingSetPayload, _account_check, _account_prepare, _account_versions, _account_apply,
        _account_release,
    ),
    ChangeRequestKind.RECORD_OVERRIDE: Kind(
        RecordOverridePayload, _override_check, _override_prepare, _override_versions,
        _override_apply,
    ),
    ChangeRequestKind.POLICY_CHANGE: Kind(
        PolicyChangePayload, _policy_check, _policy_prepare, _policy_versions, _policy_apply
    ),
    ChangeRequestKind.ENTITY_DECISION: Kind(
        EntityDecisionPayload, _decision_check, _decision_prepare, _decision_versions,
        _decision_apply,
    ),
    ChangeRequestKind.DISPOSITION: Kind(
        DispositionPayload, _disposition_check, _disposition_prepare, _disposition_versions,
        _disposition_apply,
    ),
    ChangeRequestKind.GATE_WAIVER: Kind(
        GateWaiverPayload, _waiver_check, _waiver_prepare, _waiver_versions, _waiver_apply
    ),
    ChangeRequestKind.READINESS_SIGNOFF: Kind(
        SignoffPayload, _signoff_check, _signoff_prepare, _signoff_versions, _signoff_apply
    ),
    ChangeRequestKind.REVERT: Kind(
        RevertPayload, _revert_check, _revert_prepare, _revert_versions, _revert_apply
    ),
}  # fmt: skip


def active_overrides(session: Session, migration_id: uuid.UUID) -> list[RecordOverride]:
    return list(
        session.scalars(
            select(RecordOverride)
            .where(
                RecordOverride.migration_id == migration_id,
                RecordOverride.status == OverlayStatus.ACTIVE.value,
            )
            .order_by(RecordOverride.created_at, RecordOverride.id)
        )
    )


def waivers(session: Session, migration_id: uuid.UUID) -> list[GateWaiver]:
    return list(
        session.scalars(
            select(GateWaiver)
            .where(GateWaiver.migration_id == migration_id)
            .order_by(GateWaiver.created_at.desc(), GateWaiver.id)
        )
    )


def signoffs(session: Session, migration_id: uuid.UUID) -> list[ReadinessSignoff]:
    return list(
        session.scalars(
            select(ReadinessSignoff)
            .where(ReadinessSignoff.migration_id == migration_id)
            .order_by(ReadinessSignoff.created_at.desc(), ReadinessSignoff.id)
        )
    )
