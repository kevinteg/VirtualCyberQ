# SPDX-License-Identifier: BSD-3-Clause
"""Start VirtualCyberQ locally and print the URLs, then block.

Run it with::

    python examples/run_local.py
    # or, equivalently, the installed console script:
    virtual-cyberq

It brings up both planes on the standard ports:

* the **device plane** on ``:8080`` -- point your CyberQ client / api-proxy here
  (``GET /status.xml``, ``GET /all.xml``, ``GET /config.xml``, ``POST /``);
* the **admin plane** on ``:9000`` -- JSON control API + Swagger UI at
  ``/__admin/docs``.

The clock runs at ``speed=60`` (1 simulated minute per wall-second) with a
seeded RNG so a polling client sees the pit warm up in a minute or two. Press
Ctrl-C to stop.
"""

from __future__ import annotations

from virtualcyberq.core.simulation import Simulation
from virtualcyberq.web.server import run_servers

DEVICE_PORT = 8080
ADMIN_PORT = 9000


def main() -> int:
    """Bring up both planes and serve until interrupted."""
    sim = Simulation(seed=42, speed=60.0)
    # Give the client something to watch: aim the pit at 225 degF from ambient.
    sim.reset("demo")

    print("VirtualCyberQ is up:")
    print(f"  device plane : http://localhost:{DEVICE_PORT}/status.xml")
    print("                 (point your CyberQ client / api-proxy here)")
    print(f"  admin plane  : http://localhost:{ADMIN_PORT}/__admin/docs  (Swagger UI)")
    print(f"  health       : http://localhost:{ADMIN_PORT}/__admin/health")
    print("Press Ctrl-C to stop.")

    try:
        run_servers(sim, device_port=DEVICE_PORT, admin_port=ADMIN_PORT, host="0.0.0.0")
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
