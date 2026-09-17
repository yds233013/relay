"""GV-06: properties of the audit hash chain, checked over generated events.

These test the hashing itself, without a database: any change to a hashed field changes the event's
hash, and each event's hash depends on every event before it, so an edit anywhere breaks the chain
from that point on. `tests/integration/test_persistence.py` checks detection against PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from relay.audit.models import AuditEvent
from relay.audit.service import GENESIS_HASH, event_hash

_TEXT = st.text(min_size=0, max_size=40)
_JSON = st.none() | st.dictionaries(_TEXT, _TEXT | st.integers() | st.none(), max_size=4)


def _event(index: int, fields: dict[str, Any], prev_hash: str) -> AuditEvent:
    return AuditEvent(
        id=uuid.UUID(int=index + 1),
        migration_id=uuid.UUID(int=999),
        migration_seq=index + 1,
        occurred_at=datetime(2026, 6, 30, 12, 0, index % 60, tzinfo=UTC),
        actor_type="user",
        actor_user_id=uuid.UUID(int=7),
        action=fields["action"],
        entity_type="change_request",
        entity_id=uuid.UUID(int=index + 100),
        before=fields["before"],
        after=fields["after"],
        reason=fields["reason"],
        change_request_id=None,
        evidence_refs=[],
        request_id=None,
        prev_hash=prev_hash,
    )


def _chain(rows: list[dict[str, Any]]) -> list[AuditEvent]:
    events = []
    previous = GENESIS_HASH
    for index, fields in enumerate(rows):
        event = _event(index, fields, previous)
        event.hash = event_hash(event)
        previous = event.hash
        events.append(event)
    return events


_ROWS = st.lists(
    st.fixed_dictionaries(
        {
            "action": st.sampled_from(["issue.created", "change_request.applied", "import.parsed"]),
            "before": _JSON,
            "after": _JSON,
            "reason": st.none() | _TEXT,
        }
    ),
    min_size=1,
    max_size=8,
)


@given(rows=_ROWS)
@settings(max_examples=50, deadline=None)
def test_a_chain_recomputes_to_itself(rows: list[dict[str, Any]]) -> None:
    events = _chain(rows)
    previous = GENESIS_HASH
    for event in events:
        assert event.prev_hash == previous
        assert event_hash(event) == event.hash
        previous = event.hash
    assert len({e.hash for e in events}) == len(events)


@given(
    rows=_ROWS,
    index=st.integers(min_value=0, max_value=7),
    field=st.sampled_from(["action", "before", "after", "reason", "entity_id", "occurred_at"]),
)
@settings(max_examples=50, deadline=None)
def test_editing_any_hashed_field_breaks_that_event_and_everything_after_it(
    rows: list[dict[str, Any]], index: int, field: str
) -> None:
    events = _chain(rows)
    position = index % len(events)
    tampered = events[position]
    replacements: dict[str, Any] = {
        "action": "issue.resolved_by_hand",
        "before": {"tampered": "yes"},
        "after": {"tampered": "yes"},
        "reason": "rewritten",
        "entity_id": uuid.UUID(int=4242),
        "occurred_at": datetime(2020, 1, 1, tzinfo=UTC),
    }
    if getattr(tampered, field) == replacements[field]:
        return  # the generated value already equals the replacement: nothing was changed
    setattr(tampered, field, replacements[field])

    assert event_hash(tampered) != tampered.hash  # the edited event no longer hashes to its record
    # Every later event's stored prev_hash still points at the old hash, so the chain cannot be
    # repaired without rewriting all of them.
    for later in events[position + 1 :]:
        assert later.prev_hash != event_hash(tampered)
