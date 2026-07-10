# SPDX-License-Identifier: BSD-3-Clause
"""Demonstrate fault injection against the device plane.

Shows three of the fault families from DESIGN section 8, driven through the
control plane while a real HTTP client hits the device plane:

* ``net.latency``  -- responses are delayed;
* ``http.error``   -- the device returns 500s for the next N requests;
* ``probe.open``   -- a food probe reports the literal ``OPEN`` sentinel.

Run it with::

    python examples/inject_faults.py

Faults are seed-deterministic, so this replays identically under ``seed=7``.
"""

from __future__ import annotations

import time

import httpx

from virtualcyberq.testing import VirtualCyberQ


def main() -> int:
    """Inject latency, HTTP-500, and probe-open faults and observe them."""
    # A real background tick keeps the device evolving; use a normal clock.
    with VirtualCyberQ(seed=7, speed=1.0) as cq:
        url = cq.device_url
        admin = cq.admin
        admin.reset("demo")

        # --- 1. latency -------------------------------------------------------
        admin.faults.inject("net.latency", mean_ms=750, jitter_ms=0)
        t0 = time.perf_counter()
        httpx.get(f"{url}/status.xml", timeout=10.0)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        print(f"net.latency:   /status.xml took ~{elapsed_ms:.0f} ms")
        admin.faults.clear("net.latency")

        # --- 2. http.error ----------------------------------------------------
        admin.faults.inject("http.error", status=500, probability=1.0, count=2)
        codes = [httpx.get(f"{url}/status.xml", timeout=10.0).status_code for _ in range(3)]
        print(f"http.error:    status codes for 3 GETs -> {codes} (first two 500, then recovers)")

        # --- 3. probe.open ----------------------------------------------------
        admin.faults.inject("probe.open", probe="food2", duration_s=3600)
        body = httpx.get(f"{url}/all.xml", timeout=10.0).text
        has_open = "<FOOD2_TEMP>OPEN</FOOD2_TEMP>" in body
        print(f"probe.open:    FOOD2 reports OPEN in all.xml -> {has_open}")
        admin.faults.clear()  # clear all faults

        # The request journal records exactly what the client sent.
        recent = admin.requests(limit=5)
        print(f"\nrequest journal (last {len(recent)}):")
        for entry in recent:
            print(f"  {entry.get('method'):4} {entry.get('path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
