"""Audit writer and chain verification (governance.md §3, GV-05, GV-06).

``record`` must be called inside the same session (transaction) as the change it describes, so an
event is never written for a change that rolls back, and a change never commits without its event.
Each migration has its own hash chain; events without a migration form the platform chain.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import structlog
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from relay.audit.models import AuditEvent
from relay.core.actor import Actor
from relay.core.clock import Clock, SystemClock
from relay.core.hashing import canonical_json, sha256_hex, to_canonical
from relay.core.ids import uuid7

GENESIS_HASH: Final = "0" * 64


def advisory_lock_key(namespace: str, identifier: uuid.UUID | None) -> int:
    """A signed 64-bit advisory lock key derived from a namespace and an identifier."""
    digest = hashlib.sha256(f"{namespace}:{identifier or 'platform'}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _hashed_fields(event: AuditEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "migration_id": event.migration_id,
        "migration_seq": event.migration_seq,
        "occurred_at": event.occurred_at,
        "actor_type": event.actor_type,
        "actor_user_id": event.actor_user_id,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "before": event.before,
        "after": event.after,
        "reason": event.reason,
        "change_request_id": event.change_request_id,
        "evidence_refs": event.evidence_refs,
        "request_id": event.request_id,
        "prev_hash": event.prev_hash,
    }


def event_hash(event: AuditEvent) -> str:
    return sha256_hex(event.prev_hash.encode("ascii") + canonical_json(_hashed_fields(event)))


def _json(value: Mapping[str, Any] | Sequence[Any] | None) -> Any:
    """Canonical JSON-compatible form (decimals as strings, dates ISO), so hashes are stable."""
    return None if value is None else to_canonical(value)


def record(
    session: Session,
    *,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    migration_id: uuid.UUID | None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    change_request_id: uuid.UUID | None = None,
    evidence_refs: Sequence[Any] | None = None,
    clock: Clock | None = None,
) -> AuditEvent:
    session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": advisory_lock_key("audit", migration_id)},
    )
    migration_filter = (
        AuditEvent.migration_id.is_(None)
        if migration_id is None
        else AuditEvent.migration_id == migration_id
    )
    last = session.execute(
        select(AuditEvent.migration_seq, AuditEvent.hash)
        .where(migration_filter)
        .order_by(AuditEvent.migration_seq.desc())
        .limit(1)
    ).first()
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    event = AuditEvent(
        id=uuid7(clock),
        migration_id=migration_id,
        migration_seq=(last.migration_seq + 1) if last else 1,
        occurred_at=(clock or SystemClock()).now(),
        actor_type=actor.kind,
        actor_user_id=actor.user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=_json(before),
        after=_json(after),
        reason=reason,
        change_request_id=change_request_id,
        evidence_refs=_json(evidence_refs),
        request_id=request_id if isinstance(request_id, str) else None,
        prev_hash=last.hash if last else GENESIS_HASH,
    )
    event.hash = event_hash(event)
    session.add(event)
    session.flush()
    return event


@dataclass(frozen=True, slots=True)
class ChainVerification:
    migration_id: uuid.UUID | None
    events_checked: int
    valid: bool
    first_broken_seq: int | None = None
    problem: str | None = None


def verify_chain(session: Session, migration_id: uuid.UUID | None) -> ChainVerification:
    """Recompute every hash in order and report the first broken link."""
    migration_filter = (
        AuditEvent.migration_id.is_(None)
        if migration_id is None
        else AuditEvent.migration_id == migration_id
    )
    previous = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for event in session.scalars(
        select(AuditEvent).where(migration_filter).order_by(AuditEvent.migration_seq)
    ).yield_per(1000):
        checked += 1
        if event.migration_seq != expected_seq:
            return ChainVerification(
                migration_id, checked, False, event.migration_seq, "sequence gap"
            )
        if event.prev_hash != previous:
            return ChainVerification(
                migration_id, checked, False, event.migration_seq, "previous hash mismatch"
            )
        if event_hash(event) != event.hash:
            return ChainVerification(
                migration_id, checked, False, event.migration_seq, "event content altered"
            )
        previous = event.hash
        expected_seq += 1
    return ChainVerification(migration_id, checked, True)
