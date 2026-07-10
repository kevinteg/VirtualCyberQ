# SPDX-License-Identifier: BSD-3-Clause
"""Copy-paste ``conftest.py`` for an EXTERNAL CyberQ api-proxy repo.

Drop this file into the ROOT of your api-proxy / client repo (e.g. ``ha_cyberq``,
``CyberQInterface``) as ``conftest.py`` after installing VirtualCyberQ::

    pip install virtual-cyberq

The single ``pytest_plugins`` line below enables VirtualCyberQ's pytest plugin,
which provides these fixtures to *your* test suite -- no imports required in the
tests themselves:

* ``cyberq``         -- a function-scoped :class:`VirtualCyberQ` (frozen clock;
                        ``seed``/``scenario``/``speed`` come from a
                        ``@pytest.mark.cyberq(...)`` marker when present);
* ``cyberq_session`` -- a session-scoped shared server (faster);
* ``cyberq_url``     -- the device-plane base URL string (point your client here);
* ``cyberq_admin``   -- an :class:`AdminClient` handle for the control plane.

Because the package registers the plugin via the ``pytest11`` entry point,
installing it is technically enough -- but declaring it explicitly here makes the
dependency obvious and lets you pin it in one place.

Example test in your repo::

    import httpx

    def test_proxy_reads_pit_temp(cyberq, cyberq_url):
        cyberq.sim.set_pit_temp_f(225.0)
        r = httpx.get(f"{cyberq_url}/status.xml")
        assert r.status_code == 200
        assert "<COOK_TEMP>2250</COOK_TEMP>" in r.text   # tenths-degF on the wire

    @pytest.mark.cyberq(seed=7, scenario="flaky_wifi")
    def test_proxy_survives_500s(cyberq, cyberq_url):
        cyberq.admin.faults.inject("http.error", status=500, count=2)
        # ... assert your proxy retries / degrades gracefully ...
"""

from __future__ import annotations

# This one line wires VirtualCyberQ's fixtures into your test session.
pytest_plugins = ["virtualcyberq.testing.pytest_plugin"]
