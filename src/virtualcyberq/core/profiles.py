# SPDX-License-Identifier: BSD-3-Clause
"""Declarative cook profiles: pit setup + per-cut food profiles (DESIGN 6.5).

A :class:`PitProfile` describes the pit's thermal environment and setpoint; a
:class:`MeatProfile` describes one food probe's cut (``tau_meat``, evaporative
stall parameters, target). :class:`CookProfile` bundles a pit plus up to three
food profiles -- exactly what a scenario or the admin API hands to the thermal
model so a test can say "cook a brisket + two chicken quarters" without
hand-tuning ODEs.

All time constants come with defaults fitted to the verified anecdotes in
DESIGN Appendix A. Temperatures in these dataclasses are expressed in **whole
degF** (the human-facing convention used in profiles/scenarios); the thermal
model converts to internal tenths where it needs to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "CUT_DEFAULTS",
    "CookProfile",
    "MeatProfile",
    "PitProfile",
    "known_cuts",
    "meat_profile_for_cut",
]


# --- Pit thermal defaults (DESIGN Appendix A; tunable modeling choices) ------
DEFAULT_T_AMB_F = 70.0
DEFAULT_T_FIRE_MAX_F = 700.0
DEFAULT_TAU_UP_S = 12 * 60.0
DEFAULT_TAU_DOWN_S = 90 * 60.0
DEFAULT_TAU_FIRE_S = 3 * 60.0
DEFAULT_T_LAG_S = 4 * 60.0
DEFAULT_TAU_OPEN_S = 4 * 60.0
DEFAULT_LID_OPEN_DROP_F = 60.0


@dataclass
class PitProfile:
    """The pit's thermal environment and target (DESIGN 6.2).

    Attributes:
        cook_set_f: Initial pit setpoint in whole degF.
        start_f: Initial pit temperature in whole degF.
        ambient_f: Ambient (outside) temperature in whole degF.
        t_fire_max_f: Peak temperature the fire can drive toward at full duty.
        tau_up_s: Heat-up time constant in seconds (asymmetric, fast).
        tau_down_s: Cool-down time constant in seconds (asymmetric, slow).
        tau_fire_s: Ignition lag time constant (fire lags fan duty).
        t_lag_s: Dead-time at start before the fire responds, in seconds.
        tau_open_s: Recovery time constant while the lid is open, in seconds.
        lid_open_drop_f: Temperature drop induced by a lid-open event.
        fuel_burn_rate: Fraction of the fuel budget consumed per second at full
            duty (``fuel_remaining`` decays by ``duty * fuel_burn_rate * dt``).
    """

    cook_set_f: float = 275.0
    start_f: float = DEFAULT_T_AMB_F
    ambient_f: float = DEFAULT_T_AMB_F
    t_fire_max_f: float = DEFAULT_T_FIRE_MAX_F
    tau_up_s: float = DEFAULT_TAU_UP_S
    tau_down_s: float = DEFAULT_TAU_DOWN_S
    tau_fire_s: float = DEFAULT_TAU_FIRE_S
    t_lag_s: float = DEFAULT_T_LAG_S
    tau_open_s: float = DEFAULT_TAU_OPEN_S
    lid_open_drop_f: float = DEFAULT_LID_OPEN_DROP_F
    fuel_burn_rate: float = 1.0 / (18 * 3600.0)


@dataclass
class MeatProfile:
    """One food probe's cut definition (DESIGN 6.3).

    The meat follows Newton's law toward pit temperature with time constant
    ``tau_meat_s`` minus an evaporative-cooling sink gated on the stall band; the
    sink depletes a per-probe moisture budget so the stall eventually releases.

    Attributes:
        cut: Human cut name (e.g. ``"brisket"``); ``None`` for a generic probe.
        set_f: Done setpoint in whole degF.
        start_f: Initial meat temperature in whole degF.
        mass_lb: Cut mass in pounds (scales ``tau_meat`` when > 0).
        tau_meat_s: Base heat-up time constant in seconds.
        stall_center_f: Center of the evaporative stall band, whole degF.
        stall_width_f: Half-width of the stall bell curve, whole degF.
        evap_gain_f_per_s: Peak evaporative cooling rate (degF/s) at full moisture
            and band center; scaled by the remaining moisture budget.
        stall_hours: Nominal stall duration used to size the moisture budget.
        wrapped: Texas-crutch flag; scales the moisture budget down (shorter or
            no stall).
        wrapped_moisture_scale: Multiplier applied to the moisture budget when
            ``wrapped`` is set.
        connected: Whether the probe starts plugged in (``False`` -> ``OPEN``).
    """

    cut: str | None = None
    set_f: float = 180.0
    start_f: float = DEFAULT_T_AMB_F
    mass_lb: float = 0.0
    tau_meat_s: float = 180 * 60.0
    stall_center_f: float = 160.0
    stall_width_f: float = 10.0
    evap_gain_f_per_s: float = 0.0
    stall_hours: float = 0.0
    wrapped: bool = False
    wrapped_moisture_scale: float = 0.35
    connected: bool = True

    def moisture_budget(self) -> float:
        """Return the initial moisture budget (1.0 baseline, scaled if wrapped).

        The budget is a dimensionless 0..1 reservoir the evaporative sink draws
        down; a wrapped cut starts with a reduced budget so the stall is shorter
        or absent.
        """
        return self.wrapped_moisture_scale if self.wrapped else 1.0


@dataclass
class CookProfile:
    """A full cook definition: one pit + up to three food profiles.

    Attributes:
        pit: The :class:`PitProfile`.
        food1: Food probe 1 profile, or ``None`` to leave the current probe.
        food2: Food probe 2 profile, or ``None``.
        food3: Food probe 3 profile, or ``None``.
    """

    pit: PitProfile = field(default_factory=PitProfile)
    food1: MeatProfile | None = None
    food2: MeatProfile | None = None
    food3: MeatProfile | None = None

    def foods(self) -> dict[str, MeatProfile | None]:
        """Return the food profiles keyed by ``"food1"``/``"food2"``/``"food3"``."""
        return {"food1": self.food1, "food2": self.food2, "food3": self.food3}


# --- Per-cut defaults (DESIGN 6.5 + Appendix A) -----------------------------
# tau_meat in minutes, stall in hours per Appendix A; evap gain is a modeling
# choice tuned so the stall plateau width matches ``stall_hours`` at a 225 degF
# pit. All values are labeled tunable/inferred.
CUT_DEFAULTS: dict[str, MeatProfile] = {
    "brisket": MeatProfile(
        cut="brisket",
        set_f=203.0,
        mass_lb=13.0,
        tau_meat_s=360 * 60.0,
        stall_center_f=160.0,
        stall_width_f=12.0,
        evap_gain_f_per_s=0.020,
        stall_hours=4.0,
    ),
    "pork_butt": MeatProfile(
        cut="pork_butt",
        set_f=203.0,
        mass_lb=8.0,
        tau_meat_s=330 * 60.0,
        stall_center_f=160.0,
        stall_width_f=12.0,
        evap_gain_f_per_s=0.018,
        stall_hours=3.5,
    ),
    "ribs": MeatProfile(
        cut="ribs",
        set_f=195.0,
        mass_lb=3.0,
        tau_meat_s=180 * 60.0,
        stall_center_f=158.0,
        stall_width_f=10.0,
        evap_gain_f_per_s=0.008,
        stall_hours=0.75,
    ),
    "whole_chicken": MeatProfile(
        cut="whole_chicken",
        set_f=165.0,
        mass_lb=5.0,
        tau_meat_s=105 * 60.0,
        stall_center_f=150.0,
        stall_width_f=8.0,
        evap_gain_f_per_s=0.0,
        stall_hours=0.0,
    ),
    "chicken_quarters": MeatProfile(
        cut="chicken_quarters",
        set_f=175.0,
        mass_lb=0.7,
        tau_meat_s=55 * 60.0,
        stall_center_f=150.0,
        stall_width_f=8.0,
        evap_gain_f_per_s=0.0,
        stall_hours=0.0,
    ),
}

#: Aliases so callers may pass friendlier spellings.
_CUT_ALIASES: dict[str, str] = {
    "pork butt": "pork_butt",
    "porkbutt": "pork_butt",
    "butt": "pork_butt",
    "whole chicken": "whole_chicken",
    "chicken": "whole_chicken",
    "chicken quarters": "chicken_quarters",
    "quarters": "chicken_quarters",
    "leg quarters": "chicken_quarters",
}


def known_cuts() -> tuple[str, ...]:
    """Return the canonical cut names with per-cut defaults."""
    return tuple(CUT_DEFAULTS.keys())


def meat_profile_for_cut(
    cut: str,
    *,
    set_f: float | None = None,
    mass_lb: float | None = None,
    wrapped: bool = False,
) -> MeatProfile:
    """Build a :class:`MeatProfile` for a named cut with optional overrides.

    Args:
        cut: A cut name (canonical or a known alias, case-insensitive).
        set_f: Override the done setpoint (whole degF).
        mass_lb: Override the cut mass in pounds.
        wrapped: Texas-crutch flag; scales the moisture budget down.

    Returns:
        A fresh :class:`MeatProfile` seeded from :data:`CUT_DEFAULTS`.

    Raises:
        KeyError: If ``cut`` is not a known cut or alias.
    """
    normalized = cut.strip().lower().replace("-", "_")
    canonical = _CUT_ALIASES.get(normalized, normalized)
    base = CUT_DEFAULTS.get(canonical)
    if base is None:
        raise KeyError(f"unknown cut: {cut!r}")
    return MeatProfile(
        cut=base.cut,
        set_f=base.set_f if set_f is None else set_f,
        start_f=base.start_f,
        mass_lb=base.mass_lb if mass_lb is None else mass_lb,
        tau_meat_s=base.tau_meat_s,
        stall_center_f=base.stall_center_f,
        stall_width_f=base.stall_width_f,
        evap_gain_f_per_s=base.evap_gain_f_per_s,
        stall_hours=base.stall_hours,
        wrapped=wrapped,
        wrapped_moisture_scale=base.wrapped_moisture_scale,
        connected=base.connected,
    )
