# SPDX-License-Identifier: BSD-3-Clause
"""FastAPI web adapters for VirtualCyberQ (DESIGN section 1, 2).

Two thin FastAPI apps sit over one framework-agnostic
:class:`~virtualcyberq.core.simulation.Simulation`:

* :mod:`~virtualcyberq.web.device_app` -- the **device plane**: only the real
  CyberQ surface (``status.xml`` / ``all.xml`` / ``config.xml``, the HTML pages,
  and permissive form POSTs). No admin functionality leaks here.
* :mod:`~virtualcyberq.web.admin_app` -- the **control plane**: the JSON/OpenAPI
  admin API namespaced under ``/__admin``.

:mod:`~virtualcyberq.web.server` builds both apps over one shared simulation and
runs them on two ports (with a helper for ephemeral in-process test binding).
The core never imports a web framework; this package is the only HTTP boundary.
"""

from __future__ import annotations

from virtualcyberq.web.admin_app import build_admin_app
from virtualcyberq.web.device_app import build_device_app
from virtualcyberq.web.server import (
    ServerHandle,
    build_apps,
    run_servers,
    start_in_process,
)

__all__ = [
    "ServerHandle",
    "build_admin_app",
    "build_apps",
    "build_device_app",
    "run_servers",
    "start_in_process",
]
