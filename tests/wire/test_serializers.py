# SPDX-License-Identifier: BSD-3-Clause
"""Wire / golden-file tests for the three XML serializers (DESIGN 12.2).

The fixtures in ``tests/fixtures/real_*.xml`` are captured from a real BBQ Guru
CyberQ WiFi (firmware **1.7**), canonicalized to LF line endings with the
WiFi/SMTP network fields sanitized to the shipped factory defaults. The
serializers must reproduce them exactly for a factory + probes-unplugged device.

``TestRealDeviceFacts`` additionally asserts the concrete fidelity facts learned
from the captured dumps (comments inside the root, no ``FAN_SHORTED`` on 1.7,
``MAC`` after ``SSID``, ``PROPBAND`` 300 = 30 degF, ``KEY_BEEPS`` off, ``FWVER``
persona) independently of the golden files.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from virtualcyberq.core.defaults import demo_state, factory_state
from virtualcyberq.core.enums import StatusCode
from virtualcyberq.core.state import DeviceState
from virtualcyberq.xml.allxml import render_all
from virtualcyberq.xml.configxml import render_config
from virtualcyberq.xml.status import TEMP_COMMENT_LINES, render_status

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

_CASES = [
    ("real_status.xml", render_status),
    ("real_all.xml", render_all),
    ("real_config.xml", render_config),
]


def _unplugged_factory() -> DeviceState:
    """Factory defaults with every probe disconnected (matches the captured dump)."""
    st = factory_state()
    for probe in (st.cook, st.food1, st.food2, st.food3):
        probe.connected = False
        probe.temp = None
    return st


def _sample_state() -> DeviceState:
    """A representative live (demo) state for structure assertions."""
    st = demo_state()
    st.output_percent = 24
    st.cook.temp = 2250
    st.cook.status = StatusCode.OK
    st.food1.temp = 1523
    st.food2.temp = 1801
    st.food2.status = StatusCode.DONE
    st.food3.connected = False
    st.food3.temp = None
    st.timer.remaining_s = 3661
    return st


class TestGoldenContract:
    """Byte-for-byte reproduction of the captured real-device documents."""

    @pytest.mark.parametrize("filename, render", _CASES)
    def test_matches_captured_real_device(self, filename: str, render: object) -> None:
        # Byte-for-byte (CRLF, trailing spaces, no trailing newline). status.xml and
        # all.xml are byte-identical to the real firmware-1.7 unit; config.xml matches
        # except the WiFi/SMTP network fields, which are sanitized in the fixtures.
        expected = (_FIXTURES / filename).read_bytes()
        produced = render(_unplugged_factory()).encode("latin-1")  # type: ignore[operator]
        assert produced == expected

    @pytest.mark.parametrize("filename, render", _CASES)
    def test_fixture_is_crlf_without_trailing_newline(self, filename: str, render: object) -> None:
        raw = (_FIXTURES / filename).read_bytes()
        assert b"\r\n" in raw
        assert raw.count(b"\n") == raw.count(b"\r\n")  # no lone LF
        assert not raw.endswith(b"\n")  # the device sends no trailing newline

    @pytest.mark.parametrize("filename, render", _CASES)
    def test_fixture_parses_as_xml(self, filename: str, render: object) -> None:
        # The comment block sits inside the root, so the whole document parses.
        ET.fromstring((_FIXTURES / filename).read_text())


class TestRealDeviceFacts:
    """Concrete fidelity facts learned from the captured firmware-1.7 dumps."""

    def test_comments_are_inside_the_root(self) -> None:
        doc = render_status(_unplugged_factory())
        assert doc.splitlines()[0] == "<nutcstatus>"  # root opens first
        assert doc.splitlines()[1].strip() == TEMP_COMMENT_LINES[0]  # comment inside

    def test_status_has_no_fan_shorted(self) -> None:
        assert "FAN_SHORTED" not in render_status(_unplugged_factory())

    def test_config_fwver_persona(self) -> None:
        assert "<FWVER>1.7</FWVER>" in render_config(_unplugged_factory())

    def test_config_mac_follows_ssid(self) -> None:
        doc = render_config(_unplugged_factory())
        assert doc.index("<SSID>") < doc.index("<MAC>") < doc.index("<WIFI_ENC>")

    def test_factory_propband_is_30f(self) -> None:
        assert "<PROPBAND>300</PROPBAND>" in render_config(_unplugged_factory())
        assert "<COOK_PROPBAND>300</COOK_PROPBAND>" in render_status(_unplugged_factory())

    def test_factory_key_beeps_off(self) -> None:
        assert "<KEY_BEEPS>0</KEY_BEEPS>" in render_config(_unplugged_factory())

    def test_open_probe_sentinel_and_status(self) -> None:
        doc = render_status(_unplugged_factory())
        assert "<COOK_TEMP>OPEN</COOK_TEMP>" in doc
        assert "<COOK_STATUS>4</COOK_STATUS>" in doc

    def test_all_lead_comment(self) -> None:
        assert "<!--this is similar to status.xml, but with more values-->" in render_all(
            _unplugged_factory()
        )

    def test_config_lead_comment(self) -> None:
        assert "<!--this is similar to all.xml, but with more values-->" in render_config(
            _unplugged_factory()
        )


class TestStructure:
    """Load-bearing shape checks against a representative live (demo) state."""

    def test_status_root(self) -> None:
        doc = render_status(_sample_state())
        assert "<nutcstatus>" in doc
        assert "</nutcstatus>" in doc

    def test_status_tenths_encoding(self) -> None:
        assert "<COOK_TEMP>2250</COOK_TEMP>" in render_status(_sample_state())

    def test_status_open_probe(self) -> None:
        doc = render_status(_sample_state())
        assert "<FOOD3_TEMP>OPEN</FOOD3_TEMP>" in doc
        assert "<FOOD3_STATUS>4</FOOD3_STATUS>" in doc

    def test_all_containers(self) -> None:
        doc = render_all(_sample_state())
        for tag in ("COOK", "FOOD1", "FOOD2", "FOOD3"):
            assert f"<{tag}>" in doc
            assert f"<{tag}_NAME>" in doc
            assert f"<{tag}_SET>" in doc

    def test_config_blocks_present(self) -> None:
        doc = render_config(_sample_state())
        for block in ("<SYSTEM>", "<CONTROL>", "<WIFI>", "<SMTP>", "<FWVER>", "<MAC>"):
            assert block in doc

    def test_all_parses_as_xml(self) -> None:
        ET.fromstring(render_all(_sample_state()))

    def test_config_parses_as_xml(self) -> None:
        ET.fromstring(render_config(_sample_state()))
