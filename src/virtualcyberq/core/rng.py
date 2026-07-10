# SPDX-License-Identifier: BSD-3-Clause
"""The single seeded RNG wrapper (DESIGN section 1).

All randomness in the emulator -- fault activation, sensor noise, jitter --
draws from one :class:`SeededRNG`, so the same seed replays byte-identically in
CI. The wrapper counts draws so the admin API can report ``{seed, draws}`` and a
determinism meta-test can assert reproducibility.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TypeVar

__all__ = ["SeededRNG"]

_T = TypeVar("_T")


class SeededRNG:
    """A reproducible RNG facade over :class:`random.Random`.

    Every draw increments an internal counter. Reseeding via :meth:`seed` resets
    both the underlying generator and the draw count, so identical seeds produce
    identical streams.

    Args:
        seed: The initial seed value.
    """

    def __init__(self, seed: int = 0) -> None:
        self._seed = int(seed)
        self._draws = 0
        self._random = random.Random(self._seed)

    @property
    def current_seed(self) -> int:
        """The seed currently driving the generator."""
        return self._seed

    @property
    def draws(self) -> int:
        """The number of draws taken since the last (re)seed."""
        return self._draws

    def seed(self, seed: int) -> None:
        """Reseed the generator and reset the draw counter.

        Args:
            seed: The new seed value.
        """
        self._seed = int(seed)
        self._draws = 0
        self._random = random.Random(self._seed)

    def random(self) -> float:
        """Return the next float in ``[0.0, 1.0)`` and count the draw."""
        self._draws += 1
        return self._random.random()

    def uniform(self, low: float, high: float) -> float:
        """Return a float uniformly drawn from ``[low, high]``.

        Args:
            low: Lower bound (inclusive).
            high: Upper bound (inclusive).
        """
        self._draws += 1
        return self._random.uniform(low, high)

    def gauss(self, mu: float, sigma: float) -> float:
        """Return a Gaussian draw with mean ``mu`` and stddev ``sigma``.

        Args:
            mu: The distribution mean.
            sigma: The distribution standard deviation.
        """
        self._draws += 1
        return self._random.gauss(mu, sigma)

    def randint(self, low: int, high: int) -> int:
        """Return an integer uniformly drawn from ``[low, high]`` inclusive.

        Args:
            low: Lower bound (inclusive).
            high: Upper bound (inclusive).
        """
        self._draws += 1
        return self._random.randint(low, high)

    def chance(self, probability: float) -> bool:
        """Return ``True`` with the given ``probability`` (one draw).

        Args:
            probability: Probability in ``[0.0, 1.0]``; values <=0 always
                return ``False`` and values >=1 always return ``True``, but a
                draw is still consumed for stream reproducibility.
        """
        draw = self.random()
        return draw < probability

    def choice(self, seq: Sequence[_T]) -> _T:
        """Return a uniformly random element of ``seq`` (one draw).

        Args:
            seq: A non-empty sequence to choose from.
        """
        self._draws += 1
        return self._random.choice(seq)
