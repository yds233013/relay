"""Scenario identifier-assignment helpers."""

from __future__ import annotations

import pytest

from relay_scenarios.brightwater import numbering
from relay_scenarios.errors import ScenarioConsistencyError
from relay_scenarios.rng import ScenarioRng


def test_sequential_with_anchor() -> None:
    assert numbering.sequential_with_anchor(5, 2, 100) == [98, 99, 100, 101, 102]
    with pytest.raises(ScenarioConsistencyError):
        numbering.sequential_with_anchor(5, 5, 100)


def test_sequential_with_reserved_gap() -> None:
    numbers = numbering.sequential_with_reserved_gap(5, 7730, 2)
    assert numbers == [7728, 7729, 7731, 7732, 7733]
    assert 7730 not in numbers


def test_numbers_between_anchors_respects_pins_and_gaps() -> None:
    slots = [None, None, 10, None, 15, None]
    numbers = numbering.numbers_between_anchors(ScenarioRng(1), slots, first_number=1)
    assert numbers[2] == 10
    assert numbers[4] == 15
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_numbers_between_anchors_fails_when_items_do_not_fit() -> None:
    with pytest.raises(ScenarioConsistencyError, match="must fit"):
        numbering.numbers_between_anchors(ScenarioRng(1), [5, None, None, 7], first_number=1)


def test_rng_streams_are_independent_and_deterministic() -> None:
    a = ScenarioRng(42).child("x")
    b = ScenarioRng(42).child("x")
    assert [a.integer(0, 10**9) for _ in range(5)] == [b.integer(0, 10**9) for _ in range(5)]
    assert ScenarioRng(42).child("x").integer(0, 10**9) != ScenarioRng(42).child("y").integer(
        0, 10**9
    )
