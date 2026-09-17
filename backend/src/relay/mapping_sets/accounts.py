"""Account mapping sets: complete legacy → target mappings, versioned, approved by change request.

Version 1 is usually drafted from the project's account mapping file. Later versions start from the
approved set and apply edits. The approved set replaces the file's pairs in every run
(``MigrationInputs.governed_account_mapping``); without one, runs read the file and gate G3 fails.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relay.audit import service as audit
from relay.canonical.enums import AccountSubtype, account_type_of
from relay.core.actor import Actor
from relay.core.errors import InvalidInputError, NotFoundError
from relay.core.ids import uuid7
from relay.engine.rules import subtype_conflict
from relay.mapping_sets import service as column_sets
from relay.mapping_sets.models import (
    AccountMapping,
    AccountMappingBasis,
    AccountMappingSet,
    MappingSetStatus,
)
from relay.mapping_sets.service import MappingSetStateError
from relay.workspace.models import Dataset, DatasetType

MAX_CODE_LENGTH: Final = 64
MAX_RATIONALE_LENGTH: Final = 2000
NAME_MATCH_THRESHOLD: Final = Decimal("0.50")
_STOPWORDS: Final = frozenset({"and", "for", "of", "the", "to", "a", "an", "account", "accounts"})


@dataclass(frozen=True, slots=True)
class Entry:
    target: str
    basis: str
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class EntryChange:
    legacy: str
    target: str | None
    """``None`` removes the legacy account from the set."""
    rationale: str | None = None
    basis: AccountMappingBasis = AccountMappingBasis.OPERATOR


def _code(value: str, label: str) -> str:
    code = value.strip()
    if not code or len(code) > MAX_CODE_LENGTH or any(ch in code for ch in "\r\n\t"):
        raise InvalidInputError(f"{label} must be a non-blank account code")
    return code


def get_set(session: Session, set_id: uuid.UUID) -> AccountMappingSet:
    mapping_set = session.get(AccountMappingSet, set_id)
    if mapping_set is None:
        raise NotFoundError("account mapping set not found")
    return mapping_set


def sets_for(session: Session, migration_id: uuid.UUID) -> list[AccountMappingSet]:
    return list(
        session.scalars(
            select(AccountMappingSet)
            .where(AccountMappingSet.migration_id == migration_id)
            .order_by(AccountMappingSet.version.desc())
        )
    )


def approved_set(session: Session, migration_id: uuid.UUID) -> AccountMappingSet | None:
    return session.scalars(
        select(AccountMappingSet).where(
            AccountMappingSet.migration_id == migration_id,
            AccountMappingSet.status == MappingSetStatus.APPROVED.value,
        )
    ).first()


def entries(session: Session, set_id: uuid.UUID) -> dict[str, Entry]:
    rows = session.scalars(
        select(AccountMapping)
        .where(AccountMapping.mapping_set_id == set_id)
        .order_by(AccountMapping.legacy_account_code)
    )
    return {r.legacy_account_code: Entry(r.target_account_code, r.basis, r.rationale) for r in rows}


def _datasets(
    session: Session, migration_id: uuid.UUID, dataset_type: DatasetType
) -> list[Dataset]:
    return list(
        session.scalars(
            select(Dataset)
            .where(Dataset.migration_id == migration_id, Dataset.dataset_type == dataset_type.value)
            .order_by(Dataset.created_at, Dataset.id)
        )
    )


def imported_pairs(
    session: Session, migration_id: uuid.UUID
) -> tuple[dict[str, str], uuid.UUID | None]:
    """Pairs from the account mapping file(s), first occurrence of a legacy code winning."""
    pairs: dict[str, str] = {}
    import_id = None
    for dataset in _datasets(session, migration_id, DatasetType.ACCOUNT_MAPPING):
        for record in column_sets.mapped_records(session, dataset):
            legacy = str(record.get("legacy_account_code") or "").strip()
            target = str(record.get("target_account_code") or "").strip()
            if legacy and target:
                pairs.setdefault(legacy, target)
        import_id = import_id or dataset.active_import_id
    return pairs, import_id


def effective_pairs(session: Session, migration_id: uuid.UUID) -> dict[str, str]:
    approved = approved_set(session, migration_id)
    if approved is not None:
        return {k: e.target for k, e in entries(session, approved.id).items()}
    return imported_pairs(session, migration_id)[0]


def create_draft(
    session: Session,
    *,
    actor: Actor,
    migration_id: uuid.UUID,
    base: str,
    changes: list[EntryChange],
) -> AccountMappingSet:
    """Draft a version from the approved set (``base="approved"``) or the file (``"import"``)."""
    if base == "approved":
        based_on = approved_set(session, migration_id)
        if based_on is None:
            raise MappingSetStateError("there is no approved account mapping set to start from")
        current = entries(session, based_on.id)
        based_on_import = None
    elif base == "import":
        based_on = None
        pairs, based_on_import = imported_pairs(session, migration_id)
        if not pairs:
            raise MappingSetStateError(
                "no mapped account mapping file: import one and approve its column mapping"
            )
        current = {k: Entry(v, AccountMappingBasis.IMPORTED.value) for k, v in pairs.items()}
    else:
        raise InvalidInputError("base must be 'approved' or 'import'")
    seen: set[str] = set()
    for change in changes:
        legacy = _code(change.legacy, "legacy account")
        if legacy in seen:
            raise InvalidInputError(f"legacy account {legacy} is changed more than once")
        seen.add(legacy)
        rationale = (change.rationale or "").strip() or None
        if rationale and len(rationale) > MAX_RATIONALE_LENGTH:
            raise InvalidInputError("rationale is too long")
        if change.target is None:
            if legacy not in current:
                raise InvalidInputError(f"legacy account {legacy} is not in the set")
            del current[legacy]
        else:
            current[legacy] = Entry(
                _code(change.target, "target account"), change.basis.value, rationale
            )
    version = (
        session.scalar(
            select(func.max(AccountMappingSet.version)).where(
                AccountMappingSet.migration_id == migration_id
            )
        )
        or 0
    ) + 1
    mapping_set = AccountMappingSet(
        id=uuid7(),
        migration_id=migration_id,
        version=version,
        status=MappingSetStatus.DRAFT.value,
        based_on_set_id=based_on.id if based_on else None,
        based_on_import_id=based_on_import,
        created_by=actor.user_id,
        lock_version=1,
    )
    session.add(mapping_set)
    session.flush()
    session.add_all(
        AccountMapping(
            id=uuid7(),
            mapping_set_id=mapping_set.id,
            legacy_account_code=legacy,
            target_account_code=entry.target,
            basis=entry.basis,
            rationale=entry.rationale,
        )
        for legacy, entry in sorted(current.items())
    )
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="account_mapping_set.draft_created",
        entity_type="account_mapping_set",
        entity_id=mapping_set.id,
        migration_id=migration_id,
        after={
            "version": version,
            "base": base,
            "entries": len(current),
            "changes": [
                {"legacy": c.legacy.strip(), "target": c.target, "rationale": c.rationale}
                for c in changes
            ],
        },
    )
    return mapping_set


def diff(before: Mapping[str, str], after: Mapping[str, str]) -> list[dict[str, str | None]]:
    """Changed legacy accounts: ``{"legacy", "before", "after"}``, sorted by legacy code."""
    return [
        {"legacy": code, "before": before.get(code), "after": after.get(code)}
        for code in sorted(set(before) | set(after))
        if before.get(code) != after.get(code)
    ]


def describe(
    session: Session, migration_id: uuid.UUID, changed: list[dict[str, str | None]]
) -> list[dict[str, Any]]:
    """Changed pairs with account names and the compatibility signals of the new target."""
    legacy_chart = _chart(session, migration_id, DatasetType.LEGACY_COA)
    target_chart = _chart(session, migration_id, DatasetType.TARGET_COA)
    described = []
    for item in changed:
        legacy = legacy_chart.get(str(item["legacy"]))
        before = target_chart.get(item["before"]) if item["before"] else None
        after = target_chart.get(item["after"]) if item["after"] else None
        described.append(
            {
                **item,
                "legacy_name": legacy.name if legacy else None,
                "legacy_subtype": legacy.subtype.value if legacy and legacy.subtype else None,
                "before_name": before.name if before else None,
                "after_name": after.name if after else None,
                "after_subtype": after.subtype.value if after and after.subtype else None,
                "signals": signals(legacy, after) if item["after"] else None,
            }
        )
    return described


def mark_pending(mapping_set: AccountMappingSet) -> None:
    if mapping_set.status != MappingSetStatus.DRAFT.value:
        raise MappingSetStateError("only draft mapping sets can be submitted")
    mapping_set.status = MappingSetStatus.PENDING_APPROVAL.value


def approve(
    session: Session,
    *,
    actor: Actor,
    mapping_set: AccountMappingSet,
    change_request_id: uuid.UUID,
) -> None:
    """Applier for an approved ``account_mapping_set`` change request."""
    if mapping_set.status != MappingSetStatus.PENDING_APPROVAL.value:
        raise MappingSetStateError("only mapping sets pending approval can be approved")
    previous = session.scalars(
        select(AccountMappingSet)
        .where(
            AccountMappingSet.migration_id == mapping_set.migration_id,
            AccountMappingSet.status == MappingSetStatus.APPROVED.value,
        )
        .with_for_update()
    ).first()
    if previous is not None:
        previous.status = MappingSetStatus.SUPERSEDED.value
        previous.lock_version += 1
        session.flush()
        audit.record(
            session,
            actor=actor,
            action="account_mapping_set.superseded",
            entity_type="account_mapping_set",
            entity_id=previous.id,
            migration_id=mapping_set.migration_id,
            change_request_id=change_request_id,
            before={"status": MappingSetStatus.APPROVED.value, "version": previous.version},
            after={"status": MappingSetStatus.SUPERSEDED.value},
        )
    mapping_set.status = MappingSetStatus.APPROVED.value
    mapping_set.change_request_id = change_request_id
    mapping_set.lock_version += 1
    session.flush()
    audit.record(
        session,
        actor=actor,
        action="account_mapping_set.approved",
        entity_type="account_mapping_set",
        entity_id=mapping_set.id,
        migration_id=mapping_set.migration_id,
        change_request_id=change_request_id,
        before={"status": MappingSetStatus.PENDING_APPROVAL.value},
        after={"status": MappingSetStatus.APPROVED.value, "version": mapping_set.version},
    )


def release(mapping_set: AccountMappingSet, status: MappingSetStatus) -> None:
    """End a pending set whose change request was rejected, withdrawn or went stale."""
    if mapping_set.status in {
        MappingSetStatus.PENDING_APPROVAL.value,
        MappingSetStatus.DRAFT.value,
    }:
        mapping_set.status = status.value


# ---------------------------------------------------------------------------------- suggestions
@dataclass(frozen=True, slots=True)
class ChartAccount:
    code: str
    name: str
    subtype: AccountSubtype | None


def _chart(
    session: Session, migration_id: uuid.UUID, dataset_type: DatasetType
) -> dict[str, ChartAccount]:
    accounts: dict[str, ChartAccount] = {}
    for dataset in _datasets(session, migration_id, dataset_type):
        for record in column_sets.mapped_records(session, dataset):
            code = str(record.get("account_code") or "").strip()
            if not code or code in accounts:
                continue
            try:
                subtype: AccountSubtype | None = AccountSubtype(str(record.get("subtype")))
            except ValueError:
                subtype = None
            accounts[code] = ChartAccount(code, str(record.get("name") or ""), subtype)
    return accounts


def _tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", name.casefold())) - _STOPWORDS


def _similarity(a: str, b: str) -> Decimal:
    """Jaccard similarity of name tokens, as an exact ratio rounded to hundredths."""
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return Decimal(0)
    return (Decimal(len(left & right)) / Decimal(len(left | right))).quantize(Decimal("0.01"))


def signals(legacy: ChartAccount | None, target: ChartAccount | None) -> dict[str, bool | None]:
    """Compatibility of one pair; ``None`` where a side's subtype is unknown."""
    left = legacy.subtype if legacy else None
    right = target.subtype if target else None
    if left is None or right is None:
        return {
            "target_exists": target is not None,
            "type_compatible": None,
            "subtype_compatible": None,
        }
    return {
        "target_exists": True,
        "type_compatible": account_type_of(left) == account_type_of(right),
        "subtype_compatible": not subtype_conflict(left, right),
    }


def _compatible(sig: Mapping[str, bool | None]) -> bool:
    return all(v is not False for v in sig.values())


def _score(legacy: ChartAccount, target: ChartAccount) -> Decimal:
    """Name similarity with a bonus for the same subtype. Types must agree."""
    if legacy.subtype is None or target.subtype is None:
        return _similarity(legacy.name, target.name)
    if account_type_of(legacy.subtype) != account_type_of(target.subtype):
        return Decimal(0)
    if subtype_conflict(legacy.subtype, target.subtype):
        return Decimal(0)
    bonus = Decimal("0.50") if legacy.subtype == target.subtype else Decimal(0)
    return _similarity(legacy.name, target.name) + bonus


def suggestions(session: Session, migration_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per legacy account: current target, its compatibility, and a proposal when it is doubtful.

    A proposal is made only for unmapped accounts and for pairs with a failing signal. The exact
    code in the target chart is preferred; otherwise the best compatible name match above
    ``NAME_MATCH_THRESHOLD``.
    """
    legacy_chart = _chart(session, migration_id, DatasetType.LEGACY_COA)
    target_chart = _chart(session, migration_id, DatasetType.TARGET_COA)
    current = effective_pairs(session, migration_id)
    rows = []
    for code in sorted(set(legacy_chart) | set(current)):
        legacy = legacy_chart.get(code)
        target_code = current.get(code)
        target = target_chart.get(target_code) if target_code else None
        current_signals = signals(legacy, target) if target_code else None
        proposal: dict[str, Any] | None = None
        if legacy is not None and (current_signals is None or not _compatible(current_signals)):
            exact = target_chart.get(code)
            if exact is not None and _compatible(signals(legacy, exact)):
                proposal = {"target": exact.code, "basis": "exact", "score": None}
            else:
                scored = sorted(
                    ((_score(legacy, t), t.code) for t in target_chart.values()),
                    key=lambda pair: (-pair[0], pair[1]),
                )
                if scored and scored[0][0] >= NAME_MATCH_THRESHOLD:
                    proposal = {
                        "target": scored[0][1],
                        "basis": "name_match",
                        "score": str(scored[0][0]),
                    }
            if proposal is not None:
                proposal["signals"] = signals(legacy, target_chart[proposal["target"]])
        rows.append(
            {
                "legacy_account_code": code,
                "legacy_name": legacy.name if legacy else None,
                "legacy_subtype": legacy.subtype.value if legacy and legacy.subtype else None,
                "target_account_code": target_code,
                "target_name": target.name if target else None,
                "target_subtype": target.subtype.value if target and target.subtype else None,
                "signals": current_signals,
                "proposal": proposal,
            }
        )
    return rows
