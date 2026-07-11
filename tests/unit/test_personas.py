# SPDX-License-Identifier: BSD-3-Clause
"""Firmware persona registry + persona-driven behavior (DESIGN 14.3)."""

from __future__ import annotations

from virtualcyberq.core.enums import TimeoutAction
from virtualcyberq.core.personas import (
    DEFAULT_PERSONA,
    CyberQClassicWire,
    get_persona,
    persona_names,
)
from virtualcyberq.core.simulation import Simulation


class TestPersonaRegistry:
    def test_default_is_1_7(self) -> None:
        assert DEFAULT_PERSONA == "1.7"

    def test_known_personas(self) -> None:
        assert set(persona_names()) >= {"1.7", "2.3", "3.1"}

    def test_1_7_is_verified_with_legacy_shutdown(self) -> None:
        p = get_persona("1.7")
        assert p.verified is True
        assert p.shutdown_fan_off is False

    def test_modern_personas_are_documented_fan_off(self) -> None:
        for fwver in ("2.3", "3.1"):
            p = get_persona(fwver)
            assert p.verified is False
            assert p.shutdown_fan_off is True

    def test_alias_maps_to_canonical(self) -> None:
        assert get_persona("3.0").fwver == "3.1"

    def test_unknown_fwver_is_lenient(self) -> None:
        assert get_persona("9.9").shutdown_fan_off is True  # non-1.x -> modern
        assert get_persona("1.99").shutdown_fan_off is False  # 1.x -> legacy

    def test_classic_wire_defaults(self) -> None:
        w = CyberQClassicWire
        assert w.eol == "\r\n"
        assert w.trailing_newline is False
        assert w.status_fan_shorted is False
        assert w.content_type == "text/xml"
        assert w.cache_control == "no-cache"
        assert w.send_server_header is False


class TestPersonaShutdownBehavior:
    """The verified 1.7-vs-2.3 SHUTDOWN difference (PROTOCOL 11)."""

    def _shutdown(self, fwver: str) -> Simulation:
        sim = Simulation(seed=0, speed=0.0)
        sim.set_persona(fwver)
        sim.state.control.timeout_action = TimeoutAction.SHUTDOWN
        sim.state.timer.remaining_s = 2
        sim.state.timer.running = True
        sim.advance(5)  # timer expires -> SHUTDOWN action fires
        return sim

    def test_1_7_shutdown_drops_setpoint_to_32f(self) -> None:
        sim = self._shutdown("1.7")
        assert sim.state.cook.set == 320  # 32.0 degF in tenths

    def test_3_1_shutdown_turns_fan_off(self) -> None:
        sim = self._shutdown("3.1")
        assert sim.state.cook.set != 320  # setpoint left alone
        assert sim.state.output_percent == 0  # blower forced off
