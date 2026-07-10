# SPDX-License-Identifier: BSD-3-Clause
"""The CyberQ proportional-band control law (DESIGN 6.1/6.4, PROTOCOL 9/10).

The CyberQ is a proportional-band blower controller with time-proportioned
(slow-PWM) fan pulsing. This module computes ``OUTPUT_PERCENT`` from the pit
error and folds in every verified feature behavior:

* **Proportional band** (verified points: set 225 / propband 25 -> 100% below
  200, 50% at 212.5, 0% above 225).
* **COOK_RAMP** (cook-and-hold): lowers an *effective* setpoint when the ramp
  food nears done, without overwriting the stored ``COOK_SET``.
* **COOKHOLD** on a HOLD timeout: rewrites ``COOK_SET`` to ``COOKHOLD``.
* **OPENDETECT**: a fast negative dT/dt trips ``lid_open``; while open, force
  ``OUTPUT_PERCENT=0`` and suppress the LOW alarm.
* **Timer + TIMEOUT_ACTION** (HOLD/ALARM/SHUTDOWN/NO_ACTION), with the v1.7-vs-
  v2.3 SHUTDOWN difference.
* **ALARMDEV** deviation alarm with warm-up gating (LOW suppressed until the pit
  first reaches near setpoint via ``cook_armed``).
* **\\*_STATUS** transitions for cook, food, and timer.

It is framework-agnostic pure logic operating on :class:`DeviceState` and
:class:`SimState`; the thermal model has already written the current
temperatures into the probes (in tenths-degF) before this runs. All temperatures
here are tenths-degF integers, matching the wire.
"""

from __future__ import annotations

from dataclasses import dataclass

from virtualcyberq.core.enums import (
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
)
from virtualcyberq.core.state import DeviceState, ProbeState, SimState

__all__ = [
    "ControlConstants",
    "compute_output_percent",
    "control_tick",
    "effective_cook_set",
]


@dataclass(frozen=True)
class ControlConstants:
    """Tunable control constants (DESIGN 6.4 / PROTOCOL 10; verified/inferred).

    Attributes:
        ramp_window_tenths: Ramp window in tenths-degF (30 degF, verified).
        hold_margin_tenths: Degrees above food set held during ramp, tenths-degF.
        open_drop_rate_tenths_per_s: dT/dt (tenths-degF per second) that trips the
            open-lid detector when the pit is falling below setpoint.
        arm_margin_tenths: How near setpoint the pit must first reach to arm the
            deviation alarm (defaults to one ALARMDEV band; overridable).
        v17_shutdown_set_tenths: The pit setpoint v1.7 uses on SHUTDOWN (32 degF).
    """

    ramp_window_tenths: int = 300
    hold_margin_tenths: int = 50
    open_drop_rate_tenths_per_s: float = 8.0
    arm_margin_tenths: int = 0
    v17_shutdown_set_tenths: int = 320


DEFAULT_CONSTANTS = ControlConstants()


def compute_output_percent(
    cook_temp_tenths: int, effective_set_tenths: int, propband_tenths: int
) -> int:
    """Compute the proportional-band fan output percent (DESIGN 6.1).

    ``output = clamp(100 * error / propband, 0, 100)`` where
    ``error = effective_set - cook_temp`` (positive when the pit is too cold).
    The band sits entirely below the setpoint.

    Verified against BBQ Guru's worked example (set 225, propband 25): below 200
    -> 100%, at 212.5 -> 50%, at/above 225 -> 0%.

    Args:
        cook_temp_tenths: Current pit temperature, tenths-degF.
        effective_set_tenths: Effective pit setpoint, tenths-degF.
        propband_tenths: Proportional band width, tenths-degF (>0).

    Returns:
        The fan output percent as an integer in ``[0, 100]``.
    """
    if propband_tenths <= 0:
        # Degenerate band -> bang-bang: full on below setpoint, off at/above.
        return 100 if cook_temp_tenths < effective_set_tenths else 0
    error = effective_set_tenths - cook_temp_tenths
    duty = 100.0 * error / propband_tenths
    if duty <= 0.0:
        return 0
    if duty >= 100.0:
        return 100
    return round(duty)


def effective_cook_set(state: DeviceState, constants: ControlConstants = DEFAULT_CONSTANTS) -> int:
    """Compute the effective pit setpoint, applying COOK_RAMP (DESIGN 6.4).

    When ``COOK_RAMP`` selects a connected food probe within the ramp window of
    its setpoint, the effective setpoint is gradually lowered toward
    ``food.set + HOLD_MARGIN``. The stored ``COOK_SET`` is **not** modified.

    Args:
        state: The device state (probes carry current temps in tenths-degF).
        constants: Tunable ramp constants.

    Returns:
        The effective pit setpoint in tenths-degF.
    """
    cook_set = state.cook.set
    ramp = state.control.cook_ramp
    if ramp is RampSource.OFF:
        return cook_set
    food = _ramp_probe(state, ramp)
    if food is None or not food.connected or food.temp is None:
        return cook_set

    hold_target = food.set + constants.hold_margin_tenths
    gap = food.set - food.temp  # tenths-degF still to go
    if gap <= 0:
        return hold_target
    if gap < constants.ramp_window_tenths:
        frac = gap / constants.ramp_window_tenths  # 1.0 at window edge, 0.0 at done
        return round(hold_target + frac * (cook_set - hold_target))
    return cook_set


def _ramp_probe(state: DeviceState, ramp: RampSource) -> ProbeState | None:
    """Return the food probe selected by ``ramp``, or ``None`` if OFF."""
    if ramp is RampSource.FOOD1:
        return state.food1
    if ramp is RampSource.FOOD2:
        return state.food2
    if ramp is RampSource.FOOD3:
        return state.food3
    return None


def control_tick(
    state: DeviceState,
    sim: SimState,
    dt: float,
    prev_cook_temp_tenths: int | None,
    constants: ControlConstants = DEFAULT_CONSTANTS,
) -> int:
    """Run one control tick: timer, ramp, open-lid, output, and all statuses.

    Reads the current probe temperatures (already written by the thermal model),
    advances the cook timer, computes the effective setpoint and fan output,
    updates the PWM phase, and sets every ``*_STATUS`` per PROTOCOL 9.6. Mutates
    ``state`` (statuses, ``output_percent``, ``timer``, possibly ``COOK_SET`` on
    HOLD) and ``sim`` (``cook_armed``, ``lid_open``, timeout flags, ``phase``).

    Args:
        state: The visible device state to update.
        sim: The hidden physical/gating state to update.
        dt: Simulated seconds elapsed this tick.
        prev_cook_temp_tenths: The pit temperature at the previous tick (for the
            open-lid dT/dt heuristic); ``None`` on the first tick.
        constants: Tunable control constants.

    Returns:
        The new ``output_percent`` (also stored on ``state``).
    """
    # 1. Cook timer countdown + timeout action.
    _advance_timer(state, sim, dt)

    # 2. Effective setpoint (COOK_RAMP overrides on the fly).
    target = effective_cook_set(state, constants)

    # 3. Open-lid detection (OPENDETECT).
    _update_open_lid(state, sim, dt, prev_cook_temp_tenths, target, constants)

    # 4. Proportional output.
    cook_temp = state.cook.temp
    if cook_temp is None:
        output = 0
    else:
        output = compute_output_percent(cook_temp, target, state.control.propband)
    if sim.timeout_shutdown_active and _shutdown_is_fan_off(state):
        output = 0
    if sim.lid_open:
        output = 0
    state.output_percent = output

    # 5. Slow-PWM phase clock over CYCTIME.
    cyctime = max(1, state.control.cyctime)
    sim.phase = (sim.phase + dt) % cyctime

    # 6. Deviation-alarm gating + COOK_STATUS.
    _update_cook_status(state, sim, target, constants)

    # 7. Food DONE statuses.
    _update_food_statuses(state)

    return output


# --- timer ------------------------------------------------------------------
def _advance_timer(state: DeviceState, sim: SimState, dt: float) -> None:
    """Count the cook timer down and fire the timeout action at zero."""
    timer = state.timer
    if timer.running and timer.remaining_s > 0:
        timer.remaining_s = max(0, round(timer.remaining_s - dt))
        if timer.remaining_s <= 0:
            timer.remaining_s = 0
            timer.running = False
            _apply_timeout_action(state, sim)
    _update_timer_status(state, sim)


def _apply_timeout_action(state: DeviceState, sim: SimState) -> None:
    """Apply TIMEOUT_ACTION effects when the timer reaches zero (PROTOCOL 11)."""
    action = state.control.timeout_action
    if action is TimeoutAction.HOLD:
        state.cook.set = state.control.cookhold
        sim.timeout_hold_active = True
    elif action is TimeoutAction.SHUTDOWN:
        sim.timeout_shutdown_active = True
        if not _shutdown_is_fan_off(state):
            # v1.7 persona: force an unreachably low setpoint to let the fire die.
            state.cook.set = DEFAULT_CONSTANTS.v17_shutdown_set_tenths
    elif action is TimeoutAction.ALARM:
        # No control change; latch the ALARM state on the timer status itself.
        state.timer.status = StatusCode.ALARM
    # NO_ACTION: nothing.


def _update_timer_status(state: DeviceState, sim: SimState) -> None:
    """Map timer + timeout flags to TIMER_STATUS (PROTOCOL 11.2).

    While counting down (or idle at zero having never expired) the timer reads
    OK. After expiry it reflects the timeout action: HOLD/SHUTDOWN follow the
    latched sim flags; ALARM reads ALARM until an admin clear.
    """
    timer = state.timer
    action = state.control.timeout_action
    if timer.running or timer.remaining_s > 0:
        timer.status = StatusCode.OK
        return
    if sim.timeout_shutdown_active:
        timer.status = StatusCode.SHUTDOWN
    elif sim.timeout_hold_active:
        timer.status = StatusCode.HOLD
    elif action is TimeoutAction.ALARM and timer.status is StatusCode.ALARM:
        # Preserve the ALARM latched at expiry until an admin clear resets it.
        timer.status = StatusCode.ALARM
    else:
        timer.status = StatusCode.OK


def _shutdown_is_fan_off(state: DeviceState) -> bool:
    """Whether this persona turns the fan off on SHUTDOWN (v2.3+) vs sets 32 degF."""
    return not state.fwver.startswith("1.")


# --- open-lid ---------------------------------------------------------------
def _update_open_lid(
    state: DeviceState,
    sim: SimState,
    dt: float,
    prev_cook_temp_tenths: int | None,
    target: int,
    constants: ControlConstants,
) -> None:
    """Trip/clear ``lid_open`` from a fast negative dT/dt (OPENDETECT)."""
    if state.control.opendetect is not OnOff.ON:
        sim.lid_open = False
        return
    cook_temp = state.cook.temp
    if cook_temp is None or prev_cook_temp_tenths is None or dt <= 0:
        return
    rate = (cook_temp - prev_cook_temp_tenths) / dt  # tenths-degF per second
    if not sim.lid_open:
        if rate <= -constants.open_drop_rate_tenths_per_s and cook_temp < target:
            sim.lid_open = True
    else:
        # Exit once the pit stops falling (recovering/stable) or reaches target.
        if rate >= 0.0 or cook_temp >= target:
            sim.lid_open = False


# --- cook status ------------------------------------------------------------
def _update_cook_status(
    state: DeviceState,
    sim: SimState,
    target: int,
    constants: ControlConstants,
) -> None:
    """Set COOK_STATUS with deviation-alarm warm-up gating (PROTOCOL 9.5/9.6)."""
    cook = state.cook
    if not cook.connected or cook.temp is None:
        cook.status = StatusCode.ERROR
        return

    alarmdev = state.control.alarmdev
    arm_margin = constants.arm_margin_tenths or alarmdev

    # Arm the deviation alarm only once the pit first reaches near setpoint.
    if not sim.cook_armed and cook.temp >= target - arm_margin:
        sim.cook_armed = True

    above = cook.temp - state.cook.set
    below = state.cook.set - cook.temp

    if sim.cook_armed and above >= alarmdev:
        cook.status = StatusCode.HIGH
    elif sim.cook_armed and below >= alarmdev and not sim.lid_open:
        cook.status = StatusCode.LOW
    elif sim.timeout_hold_active:
        cook.status = StatusCode.HOLD
    else:
        cook.status = StatusCode.OK


# --- food status ------------------------------------------------------------
def _update_food_statuses(state: DeviceState) -> None:
    """Set each FOODn_STATUS: ERROR if open, DONE at/above set, else OK."""
    for probe in state.food_probes():
        if not probe.connected or probe.temp is None:
            probe.status = StatusCode.ERROR
        elif probe.temp >= probe.set:
            probe.status = StatusCode.DONE
        else:
            probe.status = StatusCode.OK
