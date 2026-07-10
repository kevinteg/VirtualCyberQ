# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for :class:`virtualcyberq.core.clock.VirtualClock` (DESIGN 7)."""

from __future__ import annotations

import pytest

from virtualcyberq.core.clock import VirtualClock


class TestConstruction:
    def test_defaults(self) -> None:
        clk = VirtualClock()
        assert clk.now() == 0.0
        assert clk.speed == 1.0
        assert not clk.frozen

    def test_start_and_speed(self) -> None:
        clk = VirtualClock(speed=60.0, start=100.0)
        assert clk.now() == 100.0
        assert clk.speed == 60.0

    def test_negative_speed_rejected(self) -> None:
        with pytest.raises(ValueError):
            VirtualClock(speed=-1.0)

    def test_frozen_at_zero_speed(self) -> None:
        assert VirtualClock(speed=0.0).frozen


class TestTick:
    def test_tick_scales_by_speed(self) -> None:
        clk = VirtualClock(speed=60.0)
        elapsed = clk.tick(1.0)  # 1 wall-second at 60x -> 60 sim-seconds
        assert elapsed == 60.0
        assert clk.now() == 60.0

    def test_tick_frozen_no_advance(self) -> None:
        clk = VirtualClock(speed=0.0)
        assert clk.tick(5.0) == 0.0
        assert clk.now() == 0.0

    def test_tick_accumulates(self) -> None:
        clk = VirtualClock(speed=1.0)
        clk.tick(1.5)
        clk.tick(2.5)
        assert clk.now() == pytest.approx(4.0)


class TestAdvance:
    def test_advance_ignores_speed(self) -> None:
        clk = VirtualClock(speed=0.0)  # frozen
        assert clk.advance(30.0) == 30.0
        assert clk.now() == 30.0

    def test_advance_returns_new_time(self) -> None:
        clk = VirtualClock(speed=2.0, start=10.0)
        assert clk.advance(5.0) == 15.0

    def test_advance_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            VirtualClock().advance(-1.0)


class TestFreezeResumeScale:
    def test_freeze_remembers_speed(self) -> None:
        clk = VirtualClock(speed=42.0)
        clk.freeze()
        assert clk.frozen
        assert clk.speed == 0.0
        assert clk.resume() == 42.0
        assert clk.speed == 42.0

    def test_resume_with_explicit_speed(self) -> None:
        clk = VirtualClock(speed=10.0)
        clk.freeze()
        assert clk.resume(5.0) == 5.0
        assert clk.speed == 5.0

    def test_resume_negative_rejected(self) -> None:
        clk = VirtualClock(speed=1.0)
        clk.freeze()
        with pytest.raises(ValueError):
            clk.resume(-1.0)

    def test_scale_sets_speed(self) -> None:
        clk = VirtualClock(speed=1.0)
        assert clk.scale(600.0) == 600.0
        assert clk.speed == 600.0

    def test_scale_zero_freezes(self) -> None:
        clk = VirtualClock(speed=1.0)
        clk.scale(0.0)
        assert clk.frozen

    def test_scale_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            VirtualClock().scale(-3.0)
