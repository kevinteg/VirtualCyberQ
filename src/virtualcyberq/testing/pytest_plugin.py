# SPDX-License-Identifier: BSD-3-Clause
"""Pytest fixtures for VirtualCyberQ (DESIGN section 11).

Registered as an entry point (``pytest11``), so installing the package makes
these fixtures available in **any** repo -- including an external api-proxy repo,
which need only add ``pytest_plugins = ["virtualcyberq.testing.pytest_plugin"]``
to its ``conftest.py`` if entry-point discovery is disabled.

Fixtures:

* ``cyberq``         -- function-scoped :class:`VirtualCyberQ` (frozen clock;
  seed/scenario taken from a ``@pytest.mark.cyberq(...)`` marker if present).
* ``cyberq_session`` -- session-scoped shared server (faster; no marker input).
* ``cyberq_url``     -- the device base URL string (from ``cyberq``).
* ``cyberq_admin``   -- the :class:`~virtualcyberq.client.AdminClient` handle.

Marker::

    @pytest.mark.cyberq(seed=7, scenario="flaky_wifi", speed=0)
    def test_x(cyberq, cyberq_url): ...
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from virtualcyberq.client import AdminClient
from virtualcyberq.testing.harness import VirtualCyberQ

__all__ = [
    "cyberq",
    "cyberq_admin",
    "cyberq_session",
    "cyberq_url",
    "pytest_configure",
]


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``cyberq`` marker so pytest does not warn about it."""
    config.addinivalue_line(
        "markers",
        "cyberq(seed=0, speed=0, scenario=None, admin_over_http=False): "
        "configure the VirtualCyberQ fixture for this test.",
    )


def _marker_kwargs(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Extract kwargs from a ``@pytest.mark.cyberq(...)`` marker, if present."""
    marker = request.node.get_closest_marker("cyberq")
    if marker is None:
        return {}
    return dict(marker.kwargs)


@pytest.fixture
def cyberq(request: pytest.FixtureRequest) -> Iterator[VirtualCyberQ]:
    """Function-scoped VirtualCyberQ (frozen clock unless the marker overrides).

    Reads ``seed`` / ``speed`` / ``scenario`` / ``admin_over_http`` from a
    ``@pytest.mark.cyberq(...)`` marker when present.
    """
    kwargs = _marker_kwargs(request)
    kwargs.setdefault("speed", 0.0)
    with VirtualCyberQ(**kwargs) as cq:
        yield cq


@pytest.fixture(scope="session")
def cyberq_session() -> Iterator[VirtualCyberQ]:
    """Session-scoped shared VirtualCyberQ (frozen clock, seed 0)."""
    with VirtualCyberQ(seed=0, speed=0.0) as cq:
        yield cq


@pytest.fixture
def cyberq_url(cyberq: VirtualCyberQ) -> str:
    """The device-plane base URL for the function-scoped :func:`cyberq`."""
    return cyberq.device_url


@pytest.fixture
def cyberq_admin(cyberq: VirtualCyberQ) -> AdminClient:
    """The :class:`~virtualcyberq.client.AdminClient` for :func:`cyberq`."""
    return cyberq.admin
