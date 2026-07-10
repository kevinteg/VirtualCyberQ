# SPDX-License-Identifier: BSD-3-Clause
"""Fault-behavior tests (DESIGN 12.4).

Each fault must produce its specified effect and be reproducible under a fixed
seed. Network/HTTP faults are pull-based decisions (``query_request_faults``);
sensor/power faults mutate state during ``step``/``advance``. All runs use a
frozen clock (``speed=0``) and a fixed seed so activations replay identically.
"""

from __future__ import annotations

from virtualcyberq.core.faults import Fault, RequestContext
from virtualcyberq.core.simulation import Simulation


def _sim() -> Simulation:
    return Simulation(seed=0, speed=0.0)


def _get(
    sim: Simulation, path: str = "/status.xml", *, body: bytes = b"<x/>", open_conns: int = 0
) -> object:
    return sim.query_request_faults(RequestContext("GET", path, body=body, open_conns=open_conns))


# --- HTTP faults ------------------------------------------------------------
class TestHttpError:
    def test_status_override(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.error", params={"status": 503}))
        assert _get(sim).status_code == 503

    def test_default_status_500(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.error"))
        assert _get(sim).status_code == 500

    def test_reproducible_probabilistic(self) -> None:
        def run() -> list[bool]:
            sim = Simulation(seed=5, speed=0.0)
            sim.faults.inject(Fault(id="http.error", probability=0.5, params={"status": 500}))
            return [_get(sim).status_code == 500 for _ in range(25)]

        assert run() == run()


class TestHttpTruncate:
    def test_truncate_by_fraction(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.truncate", params={"fraction": 0.5}))
        body = b"0123456789"
        d = sim.query_request_faults(RequestContext("GET", "/status.xml", body=body))
        assert d.body == b"01234"

    def test_truncate_at_byte(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.truncate", params={"at_byte": 3}))
        body = b"0123456789"
        d = sim.query_request_faults(RequestContext("GET", "/status.xml", body=body))
        assert d.body == b"012"


class TestHttpMalformed:
    def test_wrong_root(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.malformed", params={"mode": "wrong_root"}))
        body = b"<nutcstatus></nutcstatus>"
        d = sim.query_request_faults(RequestContext("GET", "/status.xml", body=body))
        assert b"nutcstatus" not in (d.body or b"")
        assert b"wrongroot" in (d.body or b"")

    def test_bad_entity(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.malformed", params={"mode": "bad_entity"}))
        body = b"<nutcstatus/>"
        d = sim.query_request_faults(RequestContext("GET", "/status.xml", body=body))
        assert b"&notanentity;" in (d.body or b"")


class TestHttpWrongContentType:
    def test_override(self) -> None:
        sim = _sim()
        sim.faults.inject(
            Fault(id="http.wrong_content_type", params={"content_type": "text/plain"})
        )
        assert _get(sim).content_type == "text/plain"


class TestHttpSlowloris:
    def test_bytes_per_s(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="http.slowloris", params={"bytes_per_s": 4}))
        assert _get(sim).bytes_per_s == 4.0


# --- Network faults ---------------------------------------------------------
class TestNetworkFaults:
    def test_unreachable_refuses(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="net.unreachable"))
        assert _get(sim).refuse is True

    def test_blackhole_hangs(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="net.blackhole"))
        d = _get(sim)
        assert d.blackhole is True
        assert d.hang_forever is True

    def test_latency_delays(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="net.latency", params={"mean_ms": 800, "jitter_ms": 0}))
        assert _get(sim).delay_s == 0.8

    def test_latency_reproducible_with_jitter(self) -> None:
        def run() -> list[float]:
            sim = Simulation(seed=3, speed=0.0)
            sim.faults.inject(Fault(id="net.latency", params={"mean_ms": 500, "jitter_ms": 200}))
            return [round(_get(sim).delay_s, 6) for _ in range(15)]

        assert run() == run()

    def test_conn_cap_refuses_over_limit(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="net.conn_cap", params={"max_conns": 1}))
        assert _get(sim, open_conns=0).refuse is False
        # A fresh sim (fault fires once per query) to test the over-limit path.
        sim2 = _sim()
        sim2.faults.inject(Fault(id="net.conn_cap", params={"max_conns": 1}))
        assert _get(sim2, open_conns=5).refuse is True

    def test_keepalive_drop(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="net.keepalive_drop", params={"after_bytes": 128}))
        assert _get(sim).drop_after_bytes == 128


# --- Sensor faults ----------------------------------------------------------
class TestSensorFaults:
    def test_probe_open(self) -> None:
        sim = _sim()
        sim.set_pit_temp_f(225.0)
        sim.faults.inject(Fault(id="probe.open", params={"probe": "food1"}))
        sim.advance(1.0)
        assert sim.state.food1.temp is None
        assert not sim.state.food1.connected

    def test_probe_short_sets_fan_shorted(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="probe.short", params={"probe": "cook"}))
        sim.advance(1.0)
        assert sim.state.fan_shorted is True

    def test_sensor_stuck_holds_value(self) -> None:
        sim = _sim()
        sim.set_pit_temp_f(200.0)
        sim.faults.inject(Fault(id="sensor.stuck", params={"probe": "cook", "value_f": 150}))
        sim.advance(10.0)
        assert sim.state.cook.temp == 1500  # frozen at 150.0 degF

    def test_sensor_drift_biases(self) -> None:
        sim = _sim()
        sim.set_pit_temp_f(200.0)
        sim.faults.inject(Fault(id="sensor.drift", params={"probe": "cook", "f_per_hour": 3600}))
        base = sim.state.cook.temp
        sim.advance(1.0)  # 1 s of a 3600 degF/hour drift -> +1 degF -> +10 tenths
        assert sim.state.cook.temp > base

    def test_sensor_faults_reproducible(self) -> None:
        def run() -> list[int]:
            sim = Simulation(seed=11, speed=0.0)
            sim.set_pit_temp_f(225.0)
            sim.faults.inject(Fault(id="sensor.spike", params={"probe": "cook", "magnitude_f": 80}))
            out = []
            for _ in range(10):
                sim.advance(5.0)
                out.append(sim.state.cook.temp)
            return out

        assert run() == run()


# --- Power faults -----------------------------------------------------------
class TestPowerFaults:
    def test_brownout_makes_device_unpowered(self) -> None:
        sim = _sim()
        assert sim.is_powered()
        sim.faults.inject(Fault(id="power.brownout", duration_s=20.0, params={"reset": False}))
        sim.advance(1.0)  # enters the outage window
        assert not sim.is_powered()

    def test_brownout_returns_after_window(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="power.brownout", duration_s=20.0, params={"reset": False}))
        sim.advance(1.0)
        assert not sim.is_powered()
        sim.advance(30.0)  # past the 20 s window
        assert sim.is_powered()

    def test_brownout_reset_restores_factory(self) -> None:
        sim = _sim()
        # Change a setting, then a resetting brownout should revert it.
        sim.apply_write("PROPBAND", "40")
        assert sim.state.control.propband == 400
        sim.faults.inject(Fault(id="power.brownout", duration_s=10.0, params={"reset": True}))
        sim.advance(1.0)
        sim.advance(20.0)  # power returns -> factory reset applied
        assert sim.state.control.propband == 250  # back to factory 25.0 degF

    def test_reboot_offline_window(self) -> None:
        sim = _sim()
        sim.faults.inject(Fault(id="power.reboot", duration_s=5.0, params={"reset": False}))
        sim.advance(1.0)
        assert not sim.is_powered()
