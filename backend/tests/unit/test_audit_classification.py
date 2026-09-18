"""Every mapped table is classified governed or exempt (GV-05).

Same spirit as ``test_route_inventory.py``: a new table is a deliberate act. Either a mutation to it
must carry an audit event, or it is operational and says in one line why. The check itself lives in
``relay.audit.instrumentation`` and runs over the integration suite.
"""

from __future__ import annotations

from typing import Final

from relay.audit.instrumentation import EXEMPT, GOVERNED
from relay.models import metadata

TABLES: Final = frozenset(metadata.tables)


def test_the_schema_is_not_empty() -> None:
    assert len(TABLES) > 30  # the classification below is not vacuous


def test_every_mapped_table_is_classified() -> None:
    classified = GOVERNED | EXEMPT.keys()
    assert classified == TABLES, (
        "unclassified tables "
        f"{sorted(TABLES - classified)}; stale entries {sorted(classified - TABLES)}"
    )


def test_no_table_is_both_governed_and_exempt() -> None:
    assert not GOVERNED & EXEMPT.keys()


def test_every_exemption_gives_a_reason() -> None:
    assert all(reason.strip() for reason in EXEMPT.values())
