# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for the write allow-list, ranges, and clamp/reject policy.

Covers PROTOCOL section 7 (DESIGN 12.1): the canonical 23-key allow-list, the
read-only key set, lenient clamping vs strict rejection, and the whole-degF
input convention (validation returns whole degF; the Simulation converts to
tenths).
"""

from __future__ import annotations

import pytest

from virtualcyberq.core.validation import (
    CANONICAL_23_KEYS,
    READONLY_KEYS,
    WriteMode,
    is_readonly,
    is_writable,
    validate_write,
)


class TestAllowList:
    def test_canonical_key_count(self) -> None:
        assert len(CANONICAL_23_KEYS) == 23

    def test_canonical_keys_are_writable(self) -> None:
        for key in CANONICAL_23_KEYS:
            assert is_writable(key)

    def test_wifi_and_smtp_writable(self) -> None:
        assert is_writable("IP")
        assert is_writable("SMTP_HOST")

    def test_unknown_key_not_writable(self) -> None:
        assert not is_writable("NOT_A_KEY")

    def test_read_only_keys(self) -> None:
        for key in ("OUTPUT_PERCENT", "TIMER_CURR", "COOK_TEMP", "FWVER", "MAC"):
            assert is_readonly(key)
            assert key in READONLY_KEYS


class TestReadOnlyRejected:
    @pytest.mark.parametrize("key", ["OUTPUT_PERCENT", "COOK_TEMP", "FWVER", "MAC"])
    def test_readonly_rejected_both_modes(self, key: str) -> None:
        for mode in (WriteMode.LENIENT, WriteMode.STRICT):
            r = validate_write(key, "5", mode)
            assert not r.accepted
            assert r.reason == "read-only key"


class TestUnknownRejected:
    def test_unknown_key_rejected(self) -> None:
        r = validate_write("BOGUS", "1")
        assert not r.accepted
        assert r.reason == "unknown key"


class TestTempValidation:
    def test_valid_temp_returns_whole_degf(self) -> None:
        r = validate_write("COOK_SET", "225")
        assert r.accepted
        assert r.value == 225  # whole degF, NOT tenths
        assert not r.clamped

    def test_decimal_temp_preserved_to_tenths(self) -> None:
        # The device documents that you may send tenths with a decimal (ex: 123.5),
        # so a decimal setpoint must survive to tenths resolution (225.4 -> 2254 tenths),
        # not be rounded to a whole degree.
        r = validate_write("COOK_SET", "225.4")
        assert r.accepted
        assert r.value == 225.4

    def test_lenient_clamps_high(self) -> None:
        r = validate_write("COOK_SET", "999", WriteMode.LENIENT)
        assert r.accepted
        assert r.clamped
        assert r.value == 475  # clamped to max

    def test_lenient_clamps_low(self) -> None:
        r = validate_write("COOK_SET", "10", WriteMode.LENIENT)
        assert r.accepted
        assert r.clamped
        assert r.value == 32  # clamped to min

    def test_strict_rejects_out_of_range(self) -> None:
        r = validate_write("COOK_SET", "999", WriteMode.STRICT)
        assert not r.accepted
        assert "maximum" in (r.reason or "")

    def test_non_numeric_temp_rejected(self) -> None:
        r = validate_write("COOK_SET", "hot")
        assert not r.accepted


class TestBandRanges:
    def test_propband_range(self) -> None:
        assert validate_write("PROPBAND", "25").value == 25
        assert validate_write("PROPBAND", "3", WriteMode.LENIENT).value == 5  # min 5
        assert validate_write("PROPBAND", "500", WriteMode.LENIENT).value == 100  # max

    def test_alarmdev_range(self) -> None:
        assert validate_write("ALARMDEV", "50").value == 50
        assert validate_write("ALARMDEV", "5", WriteMode.LENIENT).value == 10  # min 10


class TestIntEnumValidation:
    def test_cyctime_int(self) -> None:
        assert validate_write("CYCTIME", "6").value == 6
        assert validate_write("CYCTIME", "1", WriteMode.LENIENT).value == 4  # min 4

    def test_enum_accepts_valid_choice(self) -> None:
        assert validate_write("TIMEOUT_ACTION", "3").value == 3
        assert validate_write("DEG_UNITS", "1").value == 1

    def test_enum_rejects_invalid_choice(self) -> None:
        r = validate_write("TIMEOUT_ACTION", "9")
        assert not r.accepted

    def test_enum_rejects_non_integer(self) -> None:
        r = validate_write("OPENDETECT", "1.5")
        assert not r.accepted


class TestStringValidation:
    def test_name_ok(self) -> None:
        r = validate_write("COOK_NAME", "Brisket")
        assert r.accepted
        assert r.value == "Brisket"

    def test_name_truncated_lenient(self) -> None:
        r = validate_write("COOK_NAME", "X" * 40, WriteMode.LENIENT)
        assert r.accepted
        assert len(str(r.value)) == 16
        assert r.clamped

    def test_name_rejected_strict(self) -> None:
        r = validate_write("COOK_NAME", "X" * 40, WriteMode.STRICT)
        assert not r.accepted


class TestTimerValidation:
    def test_valid_timer(self) -> None:
        r = validate_write("COOK_TIMER", "01:30:00")
        assert r.accepted
        assert r.value == "01:30:00"

    def test_alias_timer_key(self) -> None:
        assert validate_write("_COOK_TIMER", "00:10:00").accepted

    def test_bad_timer_rejected(self) -> None:
        assert not validate_write("COOK_TIMER", "nope").accepted
