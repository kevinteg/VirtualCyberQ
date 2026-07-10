# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for fault-object seed determinism (DESIGN 12.1 / 12.7).

The core property that makes VirtualCyberQ usable in CI: the same seed + same
sequence of operations produces identical fault activations. These tests pin
that at the ``FaultRegistry`` / ``Simulation`` level for both probabilistic
request faults and sensor-noise faults.
"""

from __future__ import annotations

from virtualcyberq.core.faults import Fault, RequestContext
from virtualcyberq.core.simulation import Simulation


def _probabilistic_error_pattern(seed: int, n: int = 30) -> list[bool]:
    """Return the fire/no-fire pattern of a p=0.5 http.error over n requests."""
    sim = Simulation(seed=seed, speed=0.0)
    sim.faults.inject(Fault(id="http.error", probability=0.5, params={"status": 500}))
    pattern = []
    for _ in range(n):
        decision = sim.query_request_faults(RequestContext("GET", "/status.xml"))
        pattern.append("http.error" in decision.fired)
    return pattern


class TestRequestFaultDeterminism:
    def test_same_seed_identical_pattern(self) -> None:
        a = _probabilistic_error_pattern(42)
        b = _probabilistic_error_pattern(42)
        assert a == b

    def test_different_seed_differs(self) -> None:
        a = _probabilistic_error_pattern(1)
        b = _probabilistic_error_pattern(2)
        # Overwhelmingly likely to differ across 30 draws.
        assert a != b

    def test_probability_one_always_fires(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sim.faults.inject(Fault(id="http.error", probability=1.0, params={"status": 500}))
        for _ in range(10):
            d = sim.query_request_faults(RequestContext("GET", "/status.xml"))
            assert d.status_code == 500

    def test_reseed_resets_stream(self) -> None:
        first = _probabilistic_error_pattern(7)
        # A fresh sim reseeded to the same value reproduces the same stream.
        second = _probabilistic_error_pattern(7)
        assert first == second


class TestCountExpiry:
    def test_count_bounded_activations(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sim.faults.inject(Fault(id="http.error", probability=1.0, count=3, params={"status": 500}))
        fires = 0
        for _ in range(10):
            d = sim.query_request_faults(RequestContext("GET", "/status.xml"))
            if d.status_code == 500:
                fires += 1
        assert fires == 3
        assert sim.faults.get("http.error") is None  # auto-cleared


class TestSensorNoiseDeterminism:
    def _noisy_run(self, seed: int) -> list[int]:
        sim = Simulation(seed=seed, speed=0.0)
        sim.set_pit_temp_f(225.0)
        sim.faults.inject(
            Fault(id="sensor.noise", probability=1.0, params={"probe": "cook", "sigma_f": 5})
        )
        readings = []
        for _ in range(20):
            sim.advance(10.0)
            readings.append(sim.state.cook.temp)
        return readings

    def test_noise_is_reproducible(self) -> None:
        assert self._noisy_run(99) == self._noisy_run(99)

    def test_noise_actually_perturbs(self) -> None:
        # With sigma_f > 0 the readings should not all be identical.
        readings = self._noisy_run(99)
        assert len(set(readings)) > 1


class TestDurationExpiry:
    def test_duration_fault_expires(self) -> None:
        sim = Simulation(seed=0, speed=0.0)
        sim.faults.inject(Fault(id="probe.open", duration_s=100.0, params={"probe": "food1"}))
        sim.advance(50.0)
        assert sim.faults.get("probe.open") is not None
        sim.advance(60.0)  # now past the 100 s window
        assert sim.faults.get("probe.open") is None
