# SPDX-License-Identifier: BSD-3-Clause
"""First-order pit + meat thermal models (DESIGN 6.2 / 6.3).

Two continuous first-order sub-models, stepped per-second:

* :class:`PitThermal` -- an asymmetric first-order pit model with an ignition
  lag (``fire`` lags fan duty via ``TAU_FIRE`` after a ``T_LAG`` dead-time),
  heating fast (``TAU_UP``) and cooling slow (``TAU_DOWN``), fuel exhaustion, and
  lid-open behavior.
* :class:`MeatThermal` -- per-probe Newton's-law heat-up toward the pit minus an
  evaporative-cooling sink gated on the 150-170 degF stall band that depletes a
  per-probe moisture budget (producing the classic stall plateau, then release).

Both operate on **whole-degF floats** internally (physics is nicer in real
degrees); :mod:`virtualcyberq.core.simulation` converts to/from the tenths-degF
integers the wire uses. All time constants are tunable via the profiles, with
defaults fitted to the verified anecdotes in DESIGN Appendix A.

This module is pure physics: it reads a fan duty and a profile and integrates
temperatures. It does not touch :class:`DeviceState`, statuses, or the wire.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from virtualcyberq.core.profiles import MeatProfile, PitProfile

__all__ = [
    "MeatThermal",
    "PitThermal",
    "evap_term",
]


@dataclass
class PitThermal:
    """Asymmetric first-order pit model with ignition lag and fuel budget.

    The state is ``temp_f`` (pit temperature), ``fire`` (0..1 ignition
    intensity), ``fuel_remaining`` (0..1 budget), plus an internal lag timer.

    Attributes:
        profile: The :class:`PitProfile` supplying constants and ambient.
        temp_f: Current pit temperature in whole degF.
        fire: Ignition intensity 0..1 (lags fan duty).
        fuel_remaining: Fuel budget 0..1; when spent the fire cannot be driven.
        lid_open: Whether a lid-open event is currently active.
        elapsed_s: Seconds of simulated cook time (drives the start dead-time).
    """

    profile: PitProfile
    temp_f: float
    fire: float = 0.0
    fuel_remaining: float = 1.0
    lid_open: bool = False
    elapsed_s: float = 0.0

    @classmethod
    def from_profile(cls, profile: PitProfile) -> PitThermal:
        """Build a pit at its profile's ``start_f`` with a full fuel budget."""
        return cls(profile=profile, temp_f=profile.start_f)

    def open_lid(self) -> None:
        """Apply a lid-open event: drop the pit temperature immediately.

        The instantaneous drop models the rush of cold air; the subsequent
        recovery is handled by :meth:`step` while ``lid_open`` remains ``True``.
        """
        self.lid_open = True
        self.temp_f = max(
            self.profile.ambient_f,
            self.temp_f - self.profile.lid_open_drop_f,
        )

    def close_lid(self) -> None:
        """Clear the lid-open flag (recovery resumes at the normal tau)."""
        self.lid_open = False

    def step(self, duty: float, dt: float) -> float:
        """Advance the pit by ``dt`` seconds under fan ``duty`` in ``[0, 1]``.

        Args:
            duty: Fan duty fraction 0..1 (the control law's output/100).
            dt: Simulated seconds to integrate (should be << min(tau); the
                caller sub-steps for stability).

        Returns:
            The new pit temperature in whole degF.
        """
        p = self.profile
        duty = _clamp01(duty)
        self.elapsed_s += dt

        # Fuel exhaustion: budget decays with duty; when spent the fire dies.
        self.fuel_remaining = max(0.0, self.fuel_remaining - duty * p.fuel_burn_rate * dt)

        # Ignition lag: during the start dead-time the fire cannot rise; after
        # that it chases duty with TAU_FIRE, scaled by remaining fuel.
        effective_duty = duty if self.elapsed_s >= p.t_lag_s else 0.0
        effective_duty *= self.fuel_remaining
        self.fire += (effective_duty - self.fire) / p.tau_fire_s * dt
        self.fire = _clamp01(self.fire)

        # The fire drives the pit toward a temperature between ambient and max.
        t_drive = p.ambient_f + self.fire * (p.t_fire_max_f - p.ambient_f)

        if self.lid_open:
            # While the lid is open the pit sheds heat quickly toward ambient.
            tau = p.tau_open_s
            target = p.ambient_f
        else:
            # Asymmetric: heat fast (TAU_UP) when driven above, cool slow
            # (TAU_DOWN) when the drive is below the current temperature.
            target = t_drive
            tau = p.tau_up_s if t_drive > self.temp_f else p.tau_down_s

        self.temp_f += (target - self.temp_f) / tau * dt
        return self.temp_f


@dataclass
class MeatThermal:
    """Per-probe meat model with the evaporative stall (DESIGN 6.3).

    Attributes:
        profile: The :class:`MeatProfile` supplying constants and target.
        temp_f: Current meat temperature in whole degF.
        moisture: Remaining moisture budget 0..1 (depletes across the stall).
    """

    profile: MeatProfile
    temp_f: float
    moisture: float = 1.0

    @classmethod
    def from_profile(cls, profile: MeatProfile) -> MeatThermal:
        """Build a meat probe at its ``start_f`` with its moisture budget."""
        return cls(
            profile=profile,
            temp_f=profile.start_f,
            moisture=profile.moisture_budget(),
        )

    def _tau_meat(self) -> float:
        """Effective heat-up tau, lightly scaled by mass above a 1 lb baseline."""
        p = self.profile
        if p.mass_lb > 0:
            # Larger cuts heat slower; a gentle scaling keeps Appendix A tau as
            # the nominal value at the cut's default mass.
            return p.tau_meat_s * max(0.25, (p.mass_lb / max(p.mass_lb, 1.0)))
        return p.tau_meat_s

    def step(self, pit_temp_f: float, dt: float) -> float:
        """Advance the meat by ``dt`` seconds toward ``pit_temp_f``.

        Args:
            pit_temp_f: Current pit temperature in whole degF (the heat source).
            dt: Simulated seconds to integrate.

        Returns:
            The new meat temperature in whole degF.
        """
        p = self.profile
        # Newton heat-up toward the pit.
        drive = (pit_temp_f - self.temp_f) / self._tau_meat()

        # Evaporative-cooling sink, gated on the stall band and current moisture.
        q = evap_term(p, self.temp_f, self.moisture)

        # Deplete the moisture budget proportional to the evaporative loss.
        if q > 0 and p.evap_gain_f_per_s > 0:
            self.moisture = max(0.0, self.moisture - (q / p.evap_gain_f_per_s) * dt)

        self.temp_f += (drive - q) * dt
        # Meat never cools below its start (no runaway from the sink term).
        if self.temp_f < p.start_f:
            self.temp_f = p.start_f
        return self.temp_f


def evap_term(profile: MeatProfile, meat_temp_f: float, moisture: float) -> float:
    """Evaporative-cooling rate (degF/s) at a meat temperature (DESIGN 6.3).

    A bell curve centered on the stall band, scaled by the remaining moisture
    budget. Zero once moisture is spent (the stall releases) or for cuts with no
    evaporative gain (poultry).

    Args:
        profile: The :class:`MeatProfile` supplying the band + gain.
        meat_temp_f: Current meat temperature in whole degF.
        moisture: Remaining moisture budget 0..1.

    Returns:
        The instantaneous evaporative-cooling rate in degF/s (>= 0).
    """
    if profile.evap_gain_f_per_s <= 0 or moisture <= 0:
        return 0.0
    width = profile.stall_width_f if profile.stall_width_f > 0 else 1.0
    z = (meat_temp_f - profile.stall_center_f) / width
    bell = math.exp(-0.5 * z * z)
    return profile.evap_gain_f_per_s * bell * _clamp01(moisture)


def _clamp01(x: float) -> float:
    """Clamp ``x`` to the closed unit interval ``[0.0, 1.0]``."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x
