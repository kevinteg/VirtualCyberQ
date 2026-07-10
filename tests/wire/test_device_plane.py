# SPDX-License-Identifier: BSD-3-Clause
"""Device-plane wire tests driven through the VirtualCyberQ harness (DESIGN 11).

These exercise the fidelity plane end-to-end over in-process HTTP: the three XML
GETs, the tolerant form POST, and the request journal -- the way an external
CyberQ client / proxy repo would hit it. Uses the frozen-clock ``cyberq`` fixture
so readings are deterministic (set explicitly via the direct sim API).
"""

from __future__ import annotations

import httpx


class TestDeviceGets:
    def test_status_xml(self, cyberq, cyberq_url: str) -> None:
        cyberq.sim.set_pit_temp_f(225.0)
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert r.status_code == 200
        assert "<nutcstatus>" in r.text
        assert "<COOK_TEMP>2250</COOK_TEMP>" in r.text

    def test_all_xml(self, cyberq_url: str) -> None:
        r = httpx.get(f"{cyberq_url}/all.xml")
        assert r.status_code == 200
        assert "<nutcallstatus>" in r.text
        assert "<COOK>" in r.text

    def test_config_xml(self, cyberq_url: str) -> None:
        r = httpx.get(f"{cyberq_url}/config.xml")
        assert r.status_code == 200
        assert "<CONTROL>" in r.text
        assert "<FWVER>" in r.text

    def test_open_probe_serializes_open(self, cyberq, cyberq_url: str) -> None:
        cyberq.sim.disconnect_probe("food3")
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert "<FOOD3_TEMP>OPEN</FOOD3_TEMP>" in r.text
        assert "<FOOD3_STATUS>4</FOOD3_STATUS>" in r.text


class TestDevicePost:
    def test_form_post_updates_setpoint(self, cyberq, cyberq_url: str) -> None:
        r = httpx.post(
            f"{cyberq_url}/",
            content="COOK_SET=225",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200
        # Whole-degF in -> tenths stored.
        assert cyberq.admin.state().cook.set == 2250

    def test_unknown_key_ignored(self, cyberq, cyberq_url: str) -> None:
        before = cyberq.admin.state().cook.set
        r = httpx.post(
            f"{cyberq_url}/",
            content="BOGUS_KEY=1",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200
        assert cyberq.admin.state().cook.set == before


class TestRequestJournal:
    def test_journal_records_requests(self, cyberq, cyberq_url: str) -> None:
        httpx.get(f"{cyberq_url}/status.xml")
        httpx.post(
            f"{cyberq_url}/",
            content="COOK_SET=230",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        entries = cyberq.admin.requests()
        assert len(entries) >= 2
        paths = [e.get("path") for e in entries]
        assert any("/status.xml" in (p or "") for p in paths)


class TestFaultsOverHttp:
    def test_http_error_fault_returns_500(self, cyberq, cyberq_url: str) -> None:
        cyberq.admin.faults.inject("http.error", status=500, count=1)
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert r.status_code == 500
        # Count-expiry: the next request is healthy again.
        r2 = httpx.get(f"{cyberq_url}/status.xml")
        assert r2.status_code == 200


class TestDeviceFidelity:
    """Behaviors that keep the device plane indistinguishable from real hardware."""

    def test_status_xml_content_type_is_text_xml(self, cyberq_url: str) -> None:
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert r.headers["content-type"].startswith("text/xml")

    def test_fidelity_headers(self, cyberq_url: str) -> None:
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert r.headers.get("server") == "CyberQ"
        assert r.headers.get("connection") == "close"

    def test_head_status_xml_succeeds(self, cyberq_url: str) -> None:
        # A proxy's health-check HEAD must succeed with the XML content-type and
        # no body -- not a 405.
        r = httpx.head(f"{cyberq_url}/status.xml")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/xml")
        assert r.text == ""

    def test_unknown_path_is_not_json_error(self, cyberq_url: str) -> None:
        # The real unit does not emit FastAPI JSON error bodies; an unknown path
        # must not fingerprint the emulator.
        r = httpx.get(f"{cyberq_url}/bogus")
        assert r.status_code == 404
        assert "application/json" not in r.headers.get("content-type", "")
        assert "detail" not in r.text

    def test_decimal_setpoint_preserved_over_the_wire(self, cyberq, cyberq_url: str) -> None:
        # The device accepts tenths via a decimal (ex: 123.5); a POSTed decimal
        # setpoint must survive to tenths resolution rather than being truncated.
        r = httpx.post(
            f"{cyberq_url}/",
            content="COOK_SET=225.4",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200
        assert cyberq.admin.state().cook.set == 2254
