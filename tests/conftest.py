# SPDX-License-Identifier: BSD-3-Clause
"""Shared pytest configuration and fixtures for the VirtualCyberQ test suite.

The package uses a ``src/`` layout and may not be installed while the suite runs
in CI/dev, so this conftest prepends ``src/`` to ``sys.path`` before any test
imports ``virtualcyberq``. It also loads the shipped pytest plugin so the
``cyberq`` fixtures and the ``@pytest.mark.cyberq(...)`` marker are available even
without entry-point discovery, and provides a handful of small deterministic
helpers (a frozen simulation, a factory/demo device state, the fixtures dir).

Everything here is deterministic: a fixed seed and a frozen clock (``speed=0``)
so the same run reproduces byte-identically.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# --- Make the src/ layout importable without an editable install ------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# Load the shipped fixtures/marker even if the package is not pip-installed.
# When the package IS installed, its ``pytest11`` entry point already registers
# the plugin; registering it here too makes pluggy raise "Plugin already
# registered under a different name". So only load it explicitly when no
# entry point provides it (i.e. running straight from a source checkout).
def _plugin_registered_via_entrypoint() -> bool:
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - Python < 3.8
        return False
    try:
        eps = entry_points(group="pytest11")  # Python >= 3.10 selectable API
    except TypeError:  # pragma: no cover - Python 3.8/3.9 dict API
        eps = entry_points().get("pytest11", [])
    return any(getattr(ep, "value", "").startswith("virtualcyberq") for ep in eps)


if not _plugin_registered_via_entrypoint():
    pytest_plugins = ["virtualcyberq.testing.pytest_plugin"]

#: The directory holding the golden/placeholder wire fixtures.
FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to ``tests/fixtures``."""
    return FIXTURES_DIR


@pytest.fixture
def frozen_sim() -> Iterator[object]:
    """A frozen, seed-0 :class:`Simulation` for direct-API unit tests.

    The clock is frozen (``speed=0``); advance physics deterministically via
    ``sim.advance(seconds)``.
    """
    from virtualcyberq.core.simulation import Simulation

    yield Simulation(seed=0, speed=0.0)


@pytest.fixture
def factory_device_state() -> object:
    """A fresh factory-default :class:`DeviceState`."""
    from virtualcyberq.core.defaults import factory_state

    return factory_state()


@pytest.fixture
def demo_device_state() -> object:
    """A fresh demo-seeded :class:`DeviceState`."""
    from virtualcyberq.core.defaults import demo_state

    return demo_state()
