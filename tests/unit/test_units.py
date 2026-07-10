# SPDX-License-Identifier: BSD-3-Clause
"""Unit tests for :mod:`virtualcyberq.core.units` (DESIGN section 12.1).

Covers the load-bearing wire encodings: tenths <-> float, the ``OPEN`` sentinel,
the whole-degF POST-input parse, and ``HH:MM:SS`` timer round-trips.
"""

from __future__ import annotations

import pytest

from virtualcyberq.core.units import (
    OPEN,
    decode_temp,
    encode_temp,
    float_to_tenths,
    hms_to_seconds,
    parse_input_temp,
    seconds_to_hms,
    tenths_to_float,
)


class TestTenthsFloat:
    """tenths-degF <-> float conversions."""

    @pytest.mark.parametrize(
        "tenths, expected",
        [(3343, 334.3), (2250, 225.0), (0, 0.0), (1, 0.1), (-100, -10.0)],
    )
    def test_tenths_to_float(self, tenths: int, expected: float) -> None:
        assert tenths_to_float(tenths) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "value, expected",
        [(334.3, 3343), (225.0, 2250), (123.5, 1235), (0.0, 0), (0.14, 1)],
    )
    def test_float_to_tenths(self, value: float, expected: int) -> None:
        assert float_to_tenths(value) == expected

    @pytest.mark.parametrize("tenths", [0, 1, 320, 2250, 3343, 4750])
    def test_roundtrip_tenths(self, tenths: int) -> None:
        assert float_to_tenths(tenths_to_float(tenths)) == tenths


class TestOpenSentinel:
    """The ``OPEN`` sentinel for open/disconnected probes."""

    def test_open_constant(self) -> None:
        assert OPEN == "OPEN"

    def test_encode_none_is_open(self) -> None:
        assert encode_temp(None) == OPEN

    def test_encode_temp_is_int_string(self) -> None:
        assert encode_temp(2250) == "2250"
        assert encode_temp(0) == "0"

    def test_decode_open_is_none(self) -> None:
        assert decode_temp(OPEN) is None
        assert decode_temp("open") is None
        assert decode_temp("") is None
        assert decode_temp("  OPEN ") is None

    def test_decode_numeric(self) -> None:
        assert decode_temp("2250") == 2250
        assert decode_temp("3343") == 3343

    def test_decode_non_numeric_is_none(self) -> None:
        assert decode_temp("garbage") is None

    def test_encode_decode_roundtrip(self) -> None:
        for tenths in (None, 0, 2250, 3343):
            assert decode_temp(encode_temp(tenths)) == tenths


class TestParseInputTemp:
    """POST-side whole-degF (decimal allowed) -> internal tenths."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("225", 2250),
            ("123.5", 1235),
            (225, 2250),
            (225.0, 2250),
            ("  225 ", 2250),
        ],
    )
    def test_parse_ok(self, raw: object, expected: int) -> None:
        assert parse_input_temp(raw) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize("raw", ["", "abc", "   "])
    def test_parse_bad_is_none(self, raw: str) -> None:
        assert parse_input_temp(raw) is None

    def test_parse_rejects_bool(self) -> None:
        assert parse_input_temp(True) is None  # type: ignore[arg-type]


class TestHms:
    """``HH:MM:SS`` timer formatting and parsing round-trips."""

    @pytest.mark.parametrize(
        "seconds, hms",
        [
            (0, "00:00:00"),
            (1, "00:00:01"),
            (61, "00:01:01"),
            (3661, "01:01:01"),
            (3600, "01:00:00"),
            (359999, "99:59:59"),
        ],
    )
    def test_seconds_to_hms(self, seconds: int, hms: str) -> None:
        assert seconds_to_hms(seconds) == hms

    def test_negative_clamps_to_zero(self) -> None:
        assert seconds_to_hms(-5) == "00:00:00"

    @pytest.mark.parametrize(
        "hms, seconds",
        [("00:00:00", 0), ("01:01:01", 3661), ("99:59:59", 359999)],
    )
    def test_hms_to_seconds(self, hms: str, seconds: int) -> None:
        assert hms_to_seconds(hms) == seconds

    @pytest.mark.parametrize("hms", ["", "1:2", "aa:bb:cc", "12:60:00", "12:00:60"])
    def test_hms_bad_is_none(self, hms: str) -> None:
        assert hms_to_seconds(hms) is None

    @pytest.mark.parametrize("seconds", [0, 1, 61, 3661, 3600, 86399])
    def test_hms_roundtrip(self, seconds: int) -> None:
        assert hms_to_seconds(seconds_to_hms(seconds)) == seconds
