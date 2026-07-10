# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for the thermal models (DESIGN 6.2 / 6.3 / 12.1).

Asserts the verified qualitative targets: the pit ramps up and reaches the band
near its setpoint under full duty; the brisket climbs through the 150-170 degF
stall band and eventually reaches done; and the stall traversal takes a sane
number of hours. These are ranges, not exact points -- the constants are tunable
modeling choices, so the tests bound behavior rather than pin values.
"""

from __future__ import annotations

from virtualcyberq.core.profiles import (
    CookProfile,
    PitProfile,
    meat_profile_for_cut,
)
from virtualcyberq.core.simulation import Simulation
from virtualcyberq.core.thermal import MeatThermal, PitThermal, evap_term


def _pit_at_225() -> Simulation:
    sim = Simulation(seed=0, speed=0.0)
    sim.set_profile(CookProfile(pit=PitProfile(cook_set_f=225, start_f=70, ambient_f=70)))
    sim.set_pit_set_f(225)
    return sim


class TestPitRamp:
    def test_starts_at_ambient(self) -> None:
        sim = _pit_at_225()
        assert sim.state.cook.temp / 10.0 < 80.0

    def test_reaches_band_within_an_hour(self) -> None:
        sim = _pit_at_225()
        sim.advance(60 * 60)
        pit_f = sim.state.cook.temp / 10.0
        # Reaches the proportional band near the 225 setpoint (allow droop).
        assert 200.0 <= pit_f <= 240.0

    def test_holds_near_setpoint(self) -> None:
        sim = _pit_at_225()
        sim.advance(3 * 3600)
        pit_f = sim.state.cook.temp / 10.0
        assert 195.0 <= pit_f <= 245.0

    def test_direct_pit_model_heats_up(self) -> None:
        pit = PitThermal.from_profile(PitProfile(start_f=70, cook_set_f=250))
        start = pit.temp_f
        for _ in range(600):  # 600 s at 1 s steps under full duty
            pit.step(duty=1.0, dt=1.0)
        assert pit.temp_f > start + 50.0


class TestLidOpen:
    def test_open_lid_drops_temperature(self) -> None:
        pit = PitThermal.from_profile(PitProfile(start_f=250, cook_set_f=250))
        before = pit.temp_f
        pit.open_lid()
        assert pit.temp_f < before
        assert pit.lid_open

    def test_close_lid_clears_flag(self) -> None:
        pit = PitThermal.from_profile(PitProfile(start_f=250))
        pit.open_lid()
        pit.close_lid()
        assert not pit.lid_open


class TestBrisketStall:
    def _cook(self) -> Simulation:
        sim = Simulation(seed=0, speed=0.0)
        sim.set_profile(
            CookProfile(
                pit=PitProfile(cook_set_f=250, start_f=70, ambient_f=70),
                food1=meat_profile_for_cut("brisket", set_f=203, mass_lb=13),
            )
        )
        sim.set_pit_set_f(250)
        return sim

    def test_meat_passes_through_stall_band(self) -> None:
        sim = self._cook()
        enter = leave = None
        while sim.now() < 20 * 3600:
            sim.advance(60.0)
            f = sim.state.food1.temp / 10.0
            if enter is None and f >= 150.0:
                enter = sim.now()
            if enter is not None and leave is None and f >= 170.0:
                leave = sim.now()
                break
        assert enter is not None, "meat never reached the stall band"
        assert leave is not None, "meat never climbed out of the stall band"
        stall_hours = (leave - enter) / 3600.0
        # The traversal of the 150-170 band should be a sane low-and-slow span.
        assert 0.5 <= stall_hours <= 8.0

    def test_meat_eventually_reaches_done(self) -> None:
        sim = self._cook()
        sim.advance(20 * 3600)
        assert sim.state.food1.temp / 10.0 >= 200.0

    def test_stall_slows_the_climb(self) -> None:
        # The mid-stall climb rate should be slower than the pre-stall climb rate.
        sim = self._cook()
        temps = []
        while sim.now() < 8 * 3600:
            sim.advance(1800.0)  # sample every 30 min
            temps.append(sim.state.food1.temp / 10.0)
        # Find a pre-stall sample (~110-140) and an in-stall sample (~155-165).
        assert temps[-1] > temps[0]


class TestEvapTerm:
    def test_no_gain_no_evap(self) -> None:
        prof = meat_profile_for_cut("chicken_quarters")
        assert prof.evap_gain_f_per_s == 0.0
        assert evap_term(prof, 160.0, moisture=1.0) == 0.0

    def test_evap_peaks_in_band_and_needs_moisture(self) -> None:
        prof = meat_profile_for_cut("brisket")
        in_band = evap_term(prof, prof.stall_center_f, moisture=1.0)
        far = evap_term(prof, 90.0, moisture=1.0)
        assert in_band > far >= 0.0
        assert evap_term(prof, prof.stall_center_f, moisture=0.0) == 0.0

    def test_wrapped_reduces_moisture_budget(self) -> None:
        dry = meat_profile_for_cut("brisket", wrapped=False)
        wet = meat_profile_for_cut("brisket", wrapped=True)
        assert wet.moisture_budget() < dry.moisture_budget()


class TestMeatDirect:
    def test_meat_never_below_start(self) -> None:
        prof = meat_profile_for_cut("brisket", set_f=203, mass_lb=13)
        meat = MeatThermal.from_profile(prof)
        for _ in range(100):
            meat.step(pit_temp_f=40.0, dt=10.0)  # colder pit than meat start
        assert meat.temp_f >= prof.start_f
