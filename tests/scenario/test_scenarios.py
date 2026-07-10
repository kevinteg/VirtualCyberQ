# SPDX-License-Identifier: BSD-3-Clause
"""Scenario runner + builtin scenario tests (DESIGN 12.5).

Covers:

* the scenario model / runner mechanics (load, step, cursor, run-to-completion),
* every shipped builtin scenario runs to completion with its in-scenario asserts
  passing, using the scenario's own seed,
* a custom deterministic scenario whose asserts are known to hold, and
* snapshot / restore round-trips through the admin surface.
"""

from __future__ import annotations

import pytest

from virtualcyberq.core.simulation import Simulation
from virtualcyberq.scenario import (
    AssertionFailure,
    ScenarioRunner,
    builtin_names,
    load_builtin,
    load_scenario,
    parse_duration,
)


class TestDurationParsing:
    @pytest.mark.parametrize(
        "literal, seconds",
        [
            ("0m", 0.0),
            ("20m", 1200.0),
            ("3h", 10800.0),
            ("3h30m", 12600.0),
            ("90s", 90.0),
            ("250", 250.0),
            (600, 600.0),
        ],
    )
    def test_parse_duration(self, literal: object, seconds: float) -> None:
        assert parse_duration(literal) == seconds  # type: ignore[arg-type]


class TestBuiltins:
    def test_builtins_discovered(self) -> None:
        names = builtin_names()
        assert "brisket_with_flaky_wifi" in names
        assert "flaky_wifi" in names

    def test_builtin_loads_and_validates(self) -> None:
        sc = load_builtin("flaky_wifi")
        assert sc.name == "flaky_wifi"
        assert sc.seed == 7
        assert sc.persona == "3.1"
        assert len(sc.timeline) >= 1

    def test_missing_builtin_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_builtin("does_not_exist")


class TestRunnerMechanics:
    def test_apply_initial_seeds_and_persona(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sc = load_builtin("flaky_wifi")
        ScenarioRunner(sim, sc)  # applies initial on construction
        assert sim.rng.current_seed == 7
        assert sim.state.fwver == "3.1"

    def test_step_advances_cursor(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        # A tiny scenario with two innocuous steps.
        sc = load_scenario(
            {
                "name": "mech",
                "seed": 0,
                "timeline": [
                    {"at": "0s", "set": {"cook": {"set": 2250}}},
                    {"at": "10s", "set": {"cook": {"set": 2300}}},
                ],
            }
        )
        runner = ScenarioRunner(sim, sc)
        assert runner.total_steps == 2
        assert runner.index == 0
        assert runner.step() is True
        assert runner.index == 1
        assert sim.state.cook.set == 2250
        assert runner.step() is True
        assert runner.done
        assert runner.step() is False  # nothing left

    def test_run_to_completion(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sc = load_scenario(
            {
                "name": "runcomplete",
                "seed": 0,
                "timeline": [
                    {"at": "0s", "set": {"cook": {"set": 2250}}},
                    {"at": "30s", "set": {"food1": {"set": 2030}}},
                ],
            }
        )
        runner = ScenarioRunner(sim, sc)
        runner.run()
        assert runner.done
        assert sim.now() >= 30.0
        assert sim.state.food1.set == 2030

    def test_failed_assert_still_advances_cursor(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sc = load_scenario(
            {
                "name": "failassert",
                "seed": 0,
                "timeline": [
                    {"at": "0s", "set": {"cook": {"temp": 2250}}},
                    {"at": "0s", "assert": {"pit_temp_f": {">=": 999}}},
                ],
            }
        )
        runner = ScenarioRunner(sim, sc)
        runner.step()  # the set
        with pytest.raises(AssertionFailure):
            runner.step()  # the failing assert
        # Cursor moved past the failing step (retry-friendly).
        assert runner.index == 2


class TestCustomScenarioAssertsPass:
    def test_custom_deterministic_scenario_runs(self) -> None:
        """A scenario whose asserts are known to hold under the thermal model."""
        sim = Simulation(seed=0, speed=0.0)
        sc = load_scenario(
            {
                "name": "custom_ok",
                "seed": 0,
                "persona": "3.1",
                "initial": {
                    "profile": {"pit": {"start_f": 70, "ambient_f": 70, "cook_set_f": 225}}
                },
                "timeline": [
                    {"at": "0s", "set": {"cook": {"set": 2250}}},
                    # Wide band that comfortably contains the settled pit temp.
                    {"at": "3h", "assert": {"pit_temp_f": {">=": 190, "<=": 250}}},
                    {"at": "3h", "assert": {"output_percent": {">=": 0, "<=": 100}}},
                ],
            }
        )
        runner = ScenarioRunner(sim, sc)
        runner.run()  # must not raise
        assert runner.done


@pytest.mark.parametrize("name", ["brisket_with_flaky_wifi", "flaky_wifi"])
def test_builtin_scenario_runs_to_completion(name: str) -> None:
    """Each builtin runs end-to-end with all its in-scenario asserts passing.

    Wired per DESIGN 12.5. Uses the scenario's own seed so fault activation is
    deterministic. ``runner.run()`` raises :class:`AssertionFailure` if any
    in-scenario assert fails.
    """
    sc = load_builtin(name)
    sim = Simulation(seed=sc.seed, speed=0.0)
    runner = ScenarioRunner(sim, sc)
    runner.run()
    assert runner.done


class TestSnapshotRestore:
    def test_roundtrip_reproduces_state(self) -> None:
        sim = Simulation(seed=42, speed=0.0)
        sim.set_pit_temp_f(225.0)
        sim.apply_write("COOK_SET", "250")
        sim.advance(300.0)
        blob = sim.snapshot()
        cook_temp = sim.state.cook.temp
        now = sim.now()

        # Mutate, then restore.
        sim.set_pit_temp_f(50.0)
        sim.advance(600.0)
        assert sim.state.cook.temp != cook_temp

        sim.restore(blob)
        assert sim.state.cook.temp == cook_temp
        assert sim.now() == now
        assert sim.state.cook.set == 2500

    def test_restore_continues_deterministically(self) -> None:
        # Snapshot at a point, then two restores + identical advances must agree.
        base = Simulation(seed=7, speed=0.0)
        base.set_pit_temp_f(150.0)
        base.advance(120.0)
        blob = base.snapshot()

        def continue_run() -> int:
            sim = Simulation(seed=0, speed=0.0)
            sim.restore(blob)
            sim.advance(300.0)
            return sim.state.cook.temp

        assert continue_run() == continue_run()

    def test_snapshot_restore_via_admin(self, cyberq) -> None:
        cyberq.sim.set_pit_temp_f(200.0)
        snap = cyberq.admin.snapshot()
        assert "blob" in snap
        cyberq.sim.set_pit_temp_f(300.0)
        cyberq.admin.restore(snap["blob"])
        assert cyberq.admin.state().cook.temp == 2000
