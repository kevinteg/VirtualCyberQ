# SPDX-License-Identifier: BSD-3-Clause
"""Sensor fault handlers (DESIGN section 8, sensor category).

These mutate :class:`DeviceState` / :class:`SimState` directly during a physics
step (called from :meth:`Simulation.step` via
:meth:`FaultRegistry.apply_sim_faults`). They perturb probe *readings* only --
the underlying thermal truth in the simulation's thermal models is untouched, so
clearing a sensor fault restores the true reading on the next tick.

Catalog entries:

* ``probe.open`` -- force a probe to OPEN + STATUS=ERROR(4).
* ``probe.short`` -- set ``FAN_SHORTED=1`` (fan/probe short).
* ``sensor.noise`` -- additive Gaussian noise on a probe reading.
* ``sensor.drift`` -- slow bias/drift over time.
* ``sensor.stuck`` -- freeze a probe at a value.
* ``sensor.spike`` -- occasional out-of-range spike/glitch.

All temperatures written here are internal tenths-degF. Temperature params in
``fault.params`` (``value_f``, ``sigma_f``, ...) are whole-degF (human input) and
are converted here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from virtualcyberq.core.enums import StatusCode
from virtualcyberq.core.rng import SeededRNG
from virtualcyberq.core.units import float_to_tenths

if TYPE_CHECKING:  # pragma: no cover
    from virtualcyberq.core.faults import Fault, FaultRegistry
    from virtualcyberq.core.state import DeviceState, ProbeState, SimState

__all__ = ["register"]

_PROBE_ATTRS = ("cook", "food1", "food2", "food3")


def register(registry: FaultRegistry) -> None:
    """Register every sensor handler on ``registry``."""
    registry.register_sim_handler("probe.open", _probe_open)
    registry.register_sim_handler("probe.short", _probe_short)
    registry.register_sim_handler("sensor.noise", _sensor_noise)
    registry.register_sim_handler("sensor.drift", _sensor_drift)
    registry.register_sim_handler("sensor.stuck", _sensor_stuck)
    registry.register_sim_handler("sensor.spike", _sensor_spike)


def _probe(state: DeviceState, params: dict[str, object]) -> ProbeState | None:
    """Resolve the ``probe`` param (``cook``/``food1..3``) to a probe, or None."""
    name = str(params.get("probe", "cook")).lower()
    if name not in _PROBE_ATTRS:
        return None
    return cast("ProbeState", getattr(state, name))


def _probe_open(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Force the target probe OPEN with STATUS=ERROR."""
    probe = _probe(state, fault.params)
    if probe is None:
        return
    probe.connected = False
    probe.temp = None
    probe.status = StatusCode.ERROR


def _probe_short(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Set the fan-short flag (probe/fan short-circuit)."""
    state.fan_shorted = True


def _sensor_noise(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Add zero-mean Gaussian noise (``sigma_f`` degF) to the probe reading.

    Params:
        probe: Target probe id (default ``"cook"``).
        sigma_f: Noise standard deviation in whole degF (default 1).
    """
    probe = _probe(state, fault.params)
    if probe is None or probe.temp is None:
        return
    sigma_f = _as_float(fault.params.get("sigma_f"), 1.0)
    probe.temp = round(probe.temp + rng.gauss(0.0, sigma_f * 10.0))


def _sensor_drift(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Apply a slow linear bias to the probe reading.

    Params:
        probe: Target probe id (default ``"cook"``).
        f_per_hour: Drift rate in whole degF per hour (default 0); may be
            negative.
    """
    probe = _probe(state, fault.params)
    if probe is None or probe.temp is None:
        return
    f_per_hour = _as_float(fault.params.get("f_per_hour"), 0.0)
    delta_tenths = (f_per_hour * 10.0) * (dt / 3600.0)
    probe.temp = round(probe.temp + delta_tenths)


def _sensor_stuck(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Freeze the probe reading at ``value_f`` (or its first-seen value).

    Params:
        probe: Target probe id (default ``"cook"``).
        value_f: The value to hold in whole degF; if omitted, the reading is
            latched at whatever value it has when the fault first fires.
    """
    probe = _probe(state, fault.params)
    if probe is None:
        return
    value_f = fault.params.get("value_f")
    if value_f is not None:
        probe.temp = float_to_tenths(_as_float(value_f, 0.0))
    else:
        latched = fault.params.get("_latched_tenths")
        if latched is None:
            if probe.temp is not None:
                fault.params["_latched_tenths"] = probe.temp
        else:
            # ``_latched_tenths`` is only ever stored from ``probe.temp`` (an int).
            probe.temp = int(cast("float", latched))


def _sensor_spike(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Add a one-tick out-of-range spike of +/- ``magnitude_f`` degF.

    Params:
        probe: Target probe id (default ``"cook"``).
        magnitude_f: Spike magnitude in whole degF (default 100); sign random.
    """
    probe = _probe(state, fault.params)
    if probe is None or probe.temp is None:
        return
    magnitude_f = _as_float(fault.params.get("magnitude_f"), 100.0)
    sign = 1.0 if rng.random() < 0.5 else -1.0
    probe.temp = round(probe.temp + sign * magnitude_f * 10.0)


def _as_float(value: object, default: float) -> float:
    """Coerce a param to float, falling back to ``default`` on bad input."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default
