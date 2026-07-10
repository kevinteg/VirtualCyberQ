# SPDX-License-Identifier: BSD-3-Clause
"""Typed Python client for the control plane (DESIGN section 11).

:class:`~virtualcyberq.client.admin_client.AdminClient` is a namespaced wrapper
over the ``/__admin`` JSON API (via httpx) with an equivalent **in-process mode**
that calls the :class:`~virtualcyberq.core.simulation.Simulation` directly (no
HTTP), so tests need not go through the network.
"""

from __future__ import annotations

from virtualcyberq.client.admin_client import (
    AdminClient,
    FaultsNamespace,
    ProbesNamespace,
    RngNamespace,
    ScenarioNamespace,
    StateView,
    TimeNamespace,
)

__all__ = [
    "AdminClient",
    "FaultsNamespace",
    "ProbesNamespace",
    "RngNamespace",
    "ScenarioNamespace",
    "StateView",
    "TimeNamespace",
]
