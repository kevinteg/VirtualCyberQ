# SPDX-License-Identifier: BSD-3-Clause
"""The single injectable virtual clock (DESIGN section 7).

Every physics step and every timer reads simulated time from one
:class:`VirtualClock`. **No other module may read the wall clock directly.** The
clock exposes one knob, ``speed``:

* ``speed = 1.0`` -> real time.
* ``speed = 60`` -> 1 simulated minute per wall second.
* ``speed = 0`` (frozen) -> time advances only via explicit :meth:`advance`.

The clock tracks *simulated* seconds elapsed; the driver (a background loop or a
test) is responsible for feeding it wall deltas via :meth:`tick`, or stepping it
deterministically via :meth:`advance`.
"""

from __future__ import annotations

__all__ = ["VirtualClock"]


class VirtualClock:
    """Accumulates simulated time under a scalable speed factor.

    Args:
        speed: Initial acceleration factor (sim-seconds per wall-second). ``0``
            means frozen; must be non-negative.
        start: Initial simulated time in seconds (default ``0.0``).

    Raises:
        ValueError: If ``speed`` is negative.
    """

    def __init__(self, speed: float = 1.0, start: float = 0.0) -> None:
        if speed < 0:
            raise ValueError("speed must be non-negative")
        self._speed = float(speed)
        self._now = float(start)
        self._resume_speed = float(speed) if speed > 0 else 1.0

    @property
    def speed(self) -> float:
        """The current acceleration factor (0 == frozen)."""
        return self._speed

    @property
    def frozen(self) -> bool:
        """``True`` when the clock is frozen (``speed == 0``)."""
        return self._speed == 0.0

    def now(self) -> float:
        """Return the current simulated time in seconds."""
        return self._now

    def tick(self, dt_wall: float) -> float:
        """Advance by ``dt_wall`` wall-seconds scaled by the current speed.

        Args:
            dt_wall: Elapsed wall-clock seconds since the last tick.

        Returns:
            The number of *simulated* seconds that elapsed (``dt_wall * speed``).
        """
        dt_sim = dt_wall * self._speed
        self._now += dt_sim
        return dt_sim

    def advance(self, seconds: float) -> float:
        """Advance the simulated clock by exactly ``seconds``, ignoring speed.

        This is the deterministic stepping entry point used by tests and the
        admin ``time/advance`` endpoint; it works even when frozen.

        Args:
            seconds: Simulated seconds to add; must be non-negative.

        Returns:
            The new simulated time in seconds.

        Raises:
            ValueError: If ``seconds`` is negative.
        """
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._now += float(seconds)
        return self._now

    def freeze(self) -> None:
        """Freeze the clock (set ``speed`` to 0), remembering the prior speed."""
        if self._speed > 0:
            self._resume_speed = self._speed
        self._speed = 0.0

    def resume(self, speed: float | None = None) -> float:
        """Resume ticking at ``speed`` (or the speed in effect before freezing).

        Args:
            speed: The speed to resume at. If ``None``, restores the speed the
                clock had before the last :meth:`freeze`.

        Returns:
            The new speed.

        Raises:
            ValueError: If ``speed`` is negative.
        """
        if speed is None:
            self._speed = self._resume_speed
        else:
            if speed < 0:
                raise ValueError("speed must be non-negative")
            self._speed = float(speed)
            if speed > 0:
                self._resume_speed = float(speed)
        return self._speed

    def scale(self, factor: float) -> float:
        """Set the acceleration factor directly.

        Args:
            factor: The new speed (sim-seconds per wall-second); ``0`` freezes.

        Returns:
            The new speed.

        Raises:
            ValueError: If ``factor`` is negative.
        """
        if factor < 0:
            raise ValueError("factor must be non-negative")
        self._speed = float(factor)
        if factor > 0:
            self._resume_speed = float(factor)
        return self._speed
