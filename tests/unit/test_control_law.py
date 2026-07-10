# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for the proportional-band control law (DESIGN 6.1 / 12.1).

The load-bearing assertion is BBQ Guru's verified worked example: with the pit
setpoint at 225 degF and PROPBAND 25 degF, the fan output is 100% below 200,
50% at 212.5, and 0% at or above 225. Temperatures are tenths-degF internally.
"""

from __future__ import annotations

import itertools

from virtualcyberq.core.control import (
    compute_output_percent,
    control_tick,
    effective_cook_set,
)
from virtualcyberq.core.defaults import factory_state
from virtualcyberq.core.enums import OnOff, RampSource, StatusCode, TimeoutAction
from virtualcyberq.core.state import SimState

# set 225 degF -> 2250 tenths; propband 25 degF -> 250 tenths.
_SET = 2250
_PB = 250


class TestVerifiedPBandPoints:
    """The three verified worked-example points."""

    def test_below_200_is_full_output(self) -> None:
        # error = 2250 - 1990 = 260 tenths > propband -> 100%.
        assert compute_output_percent(1990, _SET, _PB) == 100
        assert compute_output_percent(1000, _SET, _PB) == 100

    def test_at_2000_is_full_output(self) -> None:
        # error = 250 == propband -> exactly 100%.
        assert compute_output_percent(2000, _SET, _PB) == 100

    def test_at_212_5_is_half_output(self) -> None:
        # 212.5 degF -> 2125 tenths; error 125 = half the band -> 50%.
        assert compute_output_percent(2125, _SET, _PB) == 50

    def test_at_225_is_zero_output(self) -> None:
        assert compute_output_percent(2250, _SET, _PB) == 0

    def test_above_225_is_zero_output(self) -> None:
        assert compute_output_percent(2300, _SET, _PB) == 0
        assert compute_output_percent(5000, _SET, _PB) == 0

    def test_output_is_monotonic_across_band(self) -> None:
        outs = [compute_output_percent(t, _SET, _PB) for t in range(1990, 2260, 5)]
        assert all(a >= b for a, b in itertools.pairwise(outs))
        assert max(outs) == 100
        assert min(outs) == 0


class TestOutputEdges:
    def test_output_always_in_range(self) -> None:
        for temp in range(0, 5000, 50):
            out = compute_output_percent(temp, _SET, _PB)
            assert 0 <= out <= 100

    def test_zero_propband_is_bang_bang(self) -> None:
        assert compute_output_percent(2249, 2250, 0) == 100
        assert compute_output_percent(2250, 2250, 0) == 0
        assert compute_output_percent(2251, 2250, 0) == 0


class TestEffectiveCookSet:
    def test_ramp_off_returns_cook_set(self) -> None:
        state = factory_state()
        state.cook.set = 2250
        state.control.cook_ramp = RampSource.OFF
        assert effective_cook_set(state) == 2250

    def test_ramp_lowers_setpoint_near_food_done(self) -> None:
        state = factory_state()
        state.cook.set = 3000  # 300 degF
        state.control.cook_ramp = RampSource.FOOD1
        state.food1.set = 2030  # 203 degF
        state.food1.temp = 2010  # within the 30 degF ramp window (gap 20 tenths... )
        state.food1.temp = 2000  # gap = 30 tenths, well inside window
        eff = effective_cook_set(state)
        # Effective setpoint must be pulled below the stored COOK_SET.
        assert eff < 3000
        # Stored COOK_SET is not modified.
        assert state.cook.set == 3000

    def test_ramp_ignores_open_food(self) -> None:
        state = factory_state()
        state.cook.set = 3000
        state.control.cook_ramp = RampSource.FOOD1
        state.food1.connected = False
        state.food1.temp = None
        assert effective_cook_set(state) == 3000


class TestControlTickStatuses:
    """control_tick sets output + statuses; drives the full loop once."""

    def _state(self) -> object:
        state = factory_state()
        state.cook.set = 2250
        state.control.propband = 250
        state.control.alarmdev = 500  # 50 degF
        state.control.opendetect = OnOff.OFF  # keep lid detection out of the way
        return state

    def test_output_written_to_state(self) -> None:
        state = self._state()
        state.cook.temp = 2000  # error = 250 -> 100%
        out = control_tick(state, SimState(), dt=1.0, prev_cook_temp_tenths=2000)
        assert out == 100
        assert state.output_percent == 100

    def test_open_cook_probe_is_error(self) -> None:
        state = self._state()
        state.cook.connected = False
        state.cook.temp = None
        control_tick(state, SimState(), dt=1.0, prev_cook_temp_tenths=None)
        assert state.cook.status == StatusCode.ERROR
        assert state.output_percent == 0

    def test_food_done_status(self) -> None:
        state = self._state()
        state.cook.temp = 2250
        state.food1.temp = state.food1.set  # at setpoint -> DONE
        control_tick(state, SimState(), dt=1.0, prev_cook_temp_tenths=2250)
        assert state.food1.status == StatusCode.DONE

    def test_low_alarm_gated_until_armed(self) -> None:
        state = self._state()
        # Pit far below setpoint but never armed -> LOW suppressed (warm-up).
        state.cook.temp = 1500
        sim = SimState()
        control_tick(state, sim, dt=1.0, prev_cook_temp_tenths=1500)
        assert not sim.cook_armed
        assert state.cook.status == StatusCode.OK

    def test_high_alarm_after_arming(self) -> None:
        state = self._state()
        sim = SimState()
        # Arm by reaching near setpoint first.
        state.cook.temp = 2250
        control_tick(state, sim, dt=1.0, prev_cook_temp_tenths=2250)
        assert sim.cook_armed
        # Now above set by >= ALARMDEV (50 degF == 500 tenths) -> HIGH.
        # set is 2250 tenths, so temp >= 2750 tenths trips the HIGH alarm.
        state.cook.temp = 2800
        control_tick(state, sim, dt=1.0, prev_cook_temp_tenths=2800)
        assert state.cook.status == StatusCode.HIGH

    def test_timer_hold_rewrites_cook_set(self) -> None:
        state = self._state()
        state.control.timeout_action = TimeoutAction.HOLD
        state.control.cookhold = 2000
        state.cook.temp = 2250
        state.timer.remaining_s = 1
        state.timer.running = True
        sim = SimState()
        control_tick(state, sim, dt=2.0, prev_cook_temp_tenths=2250)
        assert state.cook.set == 2000  # COOKHOLD applied
        assert sim.timeout_hold_active
        assert state.timer.status == StatusCode.HOLD


class TestShutdownPersona:
    def test_v17_shutdown_sets_low_setpoint(self) -> None:
        state = factory_state(fwver="1.7")
        state.control.timeout_action = TimeoutAction.SHUTDOWN
        state.cook.temp = 2250
        state.timer.remaining_s = 1
        state.timer.running = True
        sim = SimState()
        control_tick(state, sim, dt=2.0, prev_cook_temp_tenths=2250)
        # v1.7 forces a low setpoint (32 degF) rather than a fan-off flag.
        assert state.cook.set == 320
        assert sim.timeout_shutdown_active

    def test_v23_shutdown_forces_fan_off(self) -> None:
        state = factory_state(fwver="2.3")
        state.control.timeout_action = TimeoutAction.SHUTDOWN
        state.control.propband = 250
        state.cook.set = 2250
        state.cook.temp = 1500  # would normally be 100% output
        state.timer.remaining_s = 1
        state.timer.running = True
        sim = SimState()
        out = control_tick(state, sim, dt=2.0, prev_cook_temp_tenths=1500)
        assert out == 0  # fan forced off on shutdown for v2.3+
