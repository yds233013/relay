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

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.canonical.records import validate_period
from relay.changes.domain import record_override_approvals, required_approvals
from relay.changes.models import (
    ChangeRequest,
    ChangeRequestKind,
    ChangeRequestStatus,
    OverlayStatus,
    OverrideTarget,
    RecordOverride,
)
from relay.core.actor import Actor
from relay.core.clock import Clock
from relay.core.dates import parse_iso_business_date
from relay.core.errors import InvalidInputError, RelayError
from relay.core.ids import uuid7
from relay.engine.exceptions import Severity
from relay.engine.rules import REGISTRY
from relay.mapping_sets import accounts
from relay.mapping_sets import service as column_sets
from relay.mapping_sets.models import AccountMappingSet, ColumnMappingSet, MappingSetStatus
from relay.workspace import service as workspace
from relay.workspace.models import Dataset, PolicyVersion

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


class RevertPayload(_Payload):
    record_override_id: uuid.UUID


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


# ------------------------------------------------------------------------------------ reverts
def _revert_target(session: Session, payload: RevertPayload) -> RecordOverride:
    override = session.get(RecordOverride, payload.record_override_id)
    if override is None:
        raise InvalidInputError("override does not exist")
    return override


def _revert_check(session: Session, migration_id: uuid.UUID, payload: RevertPayload) -> None:
    override = _revert_target(session, payload)
    if override.migration_id != migration_id:
        raise InvalidInputError("override belongs to another migration")
    if override.status != OverlayStatus.ACTIVE.value:
        raise ChangeRequestPreconditionError("only an active override can be reverted")


def _revert_prepare(session: Session, change: ChangeRequest, payload: RevertPayload) -> Prepared:
    _revert_check(session, change.migration_id, payload)
    override = _revert_target(session, payload)
    original = session.get_one(ChangeRequest, override.change_request_id)
    described = {
        "record_override_id": str(override.id),
        "natural_key": override.natural_key,
        "target": override.target,
        "field": override.field,
        "value": override.new_value,
        "original_change_request": original.key,
    }
    return Prepared(
        before={**described, "status": OverlayStatus.ACTIVE.value},
        after={**described, "status": OverlayStatus.REVERTED.value, "value": None},
        impact={"natural_key": override.natural_key, "restores": override.expected_current_value},
        # governance.md §2.3: a revert needs the same approvals as the change it reverts.
        required_approvals=list(original.required_approvals),
    )


def _revert_versions(session: Session, _: ChangeRequest, payload: RevertPayload) -> Versions:
    override = _revert_target(session, payload)
    return {f"record_override:{override.id}": override.version}


def _revert_apply(
    session: Session,
    actor: Actor,
    change: ChangeRequest,
    payload: RevertPayload,
    clock: Clock | None,
) -> None:
    override = session.get(RecordOverride, payload.record_override_id, with_for_update=True)
    if override is None or override.status != OverlayStatus.ACTIVE.value:
        raise ChangeRequestPreconditionError("override is no longer active")
    override.status = OverlayStatus.REVERTED.value
    override.reverted_by_cr_id = change.id
    override.version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="override.reverted",
        entity_type="record_override",
        entity_id=override.id,
        migration_id=change.migration_id,
        change_request_id=change.id,
        before={"status": OverlayStatus.ACTIVE.value, "value": override.new_value},
        after={"status": OverlayStatus.REVERTED.value},
        reason=change.justification,
        clock=clock,
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
