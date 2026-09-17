"""Identifier assignment for generated LedgerPro records.

Identifiers are opaque (SC-05 to SC-07). Documented identifiers are pinned; all others are assigned
by the mechanism the corrected specification describes for each series.
"""

from __future__ import annotations

from collections.abc import Sequence

from relay_scenarios.errors import ScenarioConsistencyError
from relay_scenarios.rng import ScenarioRng


def sequential_with_anchor(count: int, anchor_index: int, anchor_number: int) -> list[int]:
    """Dense chronological numbers such that item ``anchor_index`` receives ``anchor_number``."""
    if not 0 <= anchor_index < count:
        raise ScenarioConsistencyError("anchor index out of range")
    start = anchor_number - anchor_index
    if start < 1:
        raise ScenarioConsistencyError("anchored sequence would start below 1")
    return [start + index for index in range(count)]


def sequential_with_reserved_gap(
    count: int, reserved_number: int, items_before_gap: int
) -> list[int]:
    """Dense numbers leaving ``reserved_number`` unused after ``items_before_gap`` items."""
    if not 0 <= items_before_gap <= count:
        raise ScenarioConsistencyError("gap position out of range")
    start = reserved_number - items_before_gap
    return [start + index + (1 if index >= items_before_gap else 0) for index in range(count)]


def numbers_between_anchors(
    rng: ScenarioRng,
    slots: Sequence[int | None],
    *,
    first_number: int,
    trailing_gap_max: int = 2,
) -> list[int]:
    """Monotonic numbers for items in creation order, some of which are pinned.

    ``slots[i]`` is the pinned number of item *i* or ``None``. Unpinned items between two pinned
    numbers are spread over the available numbers (abandoned drafts leave gaps, SC-06). Fails if
    more items fall between two anchors than there are numbers available.
    """
    result: list[int] = []
    index = 0
    previous_pinned = first_number - 1
    while index < len(slots):
        next_pinned_index = next(
            (j for j in range(index, len(slots)) if slots[j] is not None), None
        )
        if next_pinned_index is None:
            current = previous_pinned
            for _ in range(index, len(slots)):
                current += 1 + rng.integer(0, trailing_gap_max)
                result.append(current)
            break
        pinned = slots[next_pinned_index]
        if pinned is None:  # pragma: no cover - guarded by the search above
            raise ScenarioConsistencyError("pinned slot unexpectedly empty")
        unpinned = next_pinned_index - index
        available = list(range(previous_pinned + 1, pinned))
        if pinned <= previous_pinned or unpinned > len(available):
            raise ScenarioConsistencyError(
                f"{unpinned} items must fit between pinned numbers {previous_pinned} and {pinned}"
            )
        result.extend(sorted(rng.sample(available, unpinned)))
        result.append(pinned)
        previous_pinned = pinned
        index = next_pinned_index + 1
    if len(set(result)) != len(result) or result != sorted(result):
        raise ScenarioConsistencyError("assigned numbers must be unique and increasing")
    return result


def shuffled_pool(
    rng: ScenarioRng, count: int, start: int, end: int, reserved: set[int]
) -> list[int]:
    """``count`` distinct numbers from [start, end) excluding ``reserved``, in random order."""
    pool = [n for n in range(start, end) if n not in reserved]
    if len(pool) < count:
        raise ScenarioConsistencyError("number pool too small")
    return rng.sample(pool, count)
