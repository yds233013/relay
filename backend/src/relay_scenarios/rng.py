"""Deterministic random streams.

Every generator decision draws from a named substream derived from the scenario seed, so adding a
draw in one area never shifts values in another. Only integer operations are used: no floats.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal


class ScenarioRng:
    def __init__(self, seed: int, name: str = "root") -> None:
        self.seed = seed
        self.name = name
        digest = hashlib.sha256(f"{seed}:{name}".encode()).digest()
        self._random = random.Random(int.from_bytes(digest[:8], "big"))  # noqa: S311 - not crypto

    def child(self, name: str) -> ScenarioRng:
        return ScenarioRng(self.seed, f"{self.name}/{name}")

    def integer(self, low: int, high: int) -> int:
        """Inclusive range."""
        return self._random.randint(low, high)

    def chance(self, numerator: int, denominator: int) -> bool:
        return self._random.randrange(denominator) < numerator

    def choice[T](self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("cannot choose from an empty sequence")
        return items[self._random.randrange(len(items))]

    def sample[T](self, items: Sequence[T], count: int) -> list[T]:
        return self._random.sample(list(items), count)

    def shuffled[T](self, items: Sequence[T]) -> list[T]:
        result = list(items)
        self._random.shuffle(result)
        return result

    def cents(self, low: Decimal, high: Decimal) -> Decimal:
        """Uniform amount in [low, high] with two decimal places."""
        low_cents = int(low.scaleb(2))
        high_cents = int(high.scaleb(2))
        return Decimal(self._random.randint(low_cents, high_cents)).scaleb(-2)

    def digits(self, count: int) -> str:
        return "".join(str(self._random.randrange(10)) for _ in range(count))

    def date_between(self, start: date, end: date) -> date:
        return start + timedelta(days=self._random.randint(0, (end - start).days))
