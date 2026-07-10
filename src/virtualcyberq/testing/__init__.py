# SPDX-License-Identifier: BSD-3-Clause
"""Reusable test harness (DESIGN section 11).

:class:`~virtualcyberq.testing.harness.VirtualCyberQ` is a context manager that
starts both device and admin planes in-thread over one
:class:`~virtualcyberq.core.simulation.Simulation` on ephemeral 127.0.0.1 ports,
exposes ``.device_url`` / ``.admin`` (:class:`~virtualcyberq.client.AdminClient`)
/ ``.sim`` (direct simulation), and tears down cleanly.

Installing the package auto-registers the pytest fixtures in
:mod:`~virtualcyberq.testing.pytest_plugin` (``cyberq``, ``cyberq_session``,
``cyberq_url``, ``cyberq_admin``) plus a ``@pytest.mark.cyberq`` marker.
"""

from __future__ import annotations

from virtualcyberq.testing.harness import VirtualCyberQ

__all__ = ["VirtualCyberQ"]
