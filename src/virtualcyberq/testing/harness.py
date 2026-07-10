# SPDX-License-Identifier: BSD-3-Clause
"""The :class:`VirtualCyberQ` in-process test harness (DESIGN section 11).

A context manager that spins up both planes over one
:class:`~virtualcyberq.core.simulation.Simulation` on ephemeral ports in a daemon
thread and exposes everything a test needs:

* ``cq.device_url`` -- the device-plane base URL (hit it with any HTTP client).
* ``cq.admin_url``  -- the admin-plane base URL.
* ``cq.admin``      -- an :class:`~virtualcyberq.client.AdminClient` (in-process
  by default, so admin ops don't race the HTTP loop; pass ``admin_over_http=True``
  to route admin through HTTP instead).
* ``cq.sim``        -- the shared :class:`Simulation` for zero-HTTP puppeteering.

Usage::

    with VirtualCyberQ(seed=42, speed=0) as cq:
        cq.sim.set_pit_temp_f(225.0)
        r = httpx.get(f"{cq.device_url}/status.xml")
        assert cq.admin.state().cook.temp == 2250
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from virtualcyberq.client import AdminClient
from virtualcyberq.core.simulation import Simulation
from virtualcyberq.scenario import ScenarioRunner, load_scenario
from virtualcyberq.web.server import ServerHandle, start_in_process

if TYPE_CHECKING:  # pragma: no cover - typing only
    from virtualcyberq.scenario.model import Scenario

__all__ = ["VirtualCyberQ"]


class VirtualCyberQ:
    """In-process device + admin server pair over one shared simulation.

    Args:
        seed: RNG seed for reproducible faults/noise.
        speed: Clock acceleration factor (``0`` freezes; the default, so tests
            step deterministically via ``cq.sim.advance`` / the admin API).
        scenario: Optional scenario to load on start -- a builtin name, an inline
            dict, YAML text, a path, or a parsed :class:`Scenario`.
        tick: Whether to run the background physics tick loop (harmless while the
            clock is frozen). Defaults to ``True``.
        admin_over_http: When ``True``, ``cq.admin`` talks to the admin plane over
            HTTP; otherwise it drives the simulation directly (default).
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        speed: float = 0.0,
        scenario: str | dict[str, Any] | Scenario | None = None,
        tick: bool = True,
        admin_over_http: bool = False,
    ) -> None:
        self._seed = seed
        self._speed = speed
        self._scenario_src = scenario
        self._tick = tick
        self._admin_over_http = admin_over_http
        self._handle: ServerHandle | None = None
        self._admin: AdminClient | None = None
        self._runner: ScenarioRunner | None = None
        self.sim = Simulation(seed=seed, speed=speed)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> VirtualCyberQ:
        """Start both servers and (optionally) load the initial scenario."""
        if self._scenario_src is not None:
            self.load_scenario(self._scenario_src)
        self._handle = start_in_process(self.sim, tick=self._tick)
        if self._admin_over_http:
            self._admin = AdminClient(base_url=self._handle.admin_url)
        else:
            # Share the server's journal so in-process admin ``requests()`` sees
            # what the device plane actually received.
            self._admin = AdminClient(sim=self.sim, journal=self._handle.journal)
        return self

    def stop(self) -> None:
        """Tear down the servers and close the admin client."""
        if self._admin is not None:
            self._admin.close()
            self._admin = None
        if self._handle is not None:
            self._handle.stop()
            self._handle = None

    def __enter__(self) -> VirtualCyberQ:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # ------------------------------------------------------------- accessors
    @property
    def device_url(self) -> str:
        """The device-plane base URL (e.g. ``http://127.0.0.1:53411``)."""
        self._require_started()
        assert self._handle is not None
        return self._handle.device_url

    @property
    def admin_url(self) -> str:
        """The admin-plane base URL."""
        self._require_started()
        assert self._handle is not None
        return self._handle.admin_url

    @property
    def admin(self) -> AdminClient:
        """The :class:`~virtualcyberq.client.AdminClient` handle."""
        self._require_started()
        assert self._admin is not None
        return self._admin

    @property
    def journal(self) -> Any:
        """The shared request journal (WireMock-style ring buffer)."""
        self._require_started()
        assert self._handle is not None
        return self._handle.journal

    @property
    def runner(self) -> ScenarioRunner | None:
        """The active :class:`ScenarioRunner`, if a scenario was loaded."""
        return self._runner

    # ------------------------------------------------------------- scenarios
    def load_scenario(self, source: str | dict[str, Any] | Scenario) -> ScenarioRunner:
        """Load a scenario onto the simulation and return its runner.

        Accepts a builtin name, an inline dict, YAML/JSON text, a path, or a
        parsed :class:`Scenario`. Bare builtin names (no ``/`` or newline) are
        resolved against the shipped builtins first.
        """
        scenario = self._resolve_scenario(source)
        self._runner = ScenarioRunner(self.sim, scenario)
        return self._runner

    def _resolve_scenario(self, source: str | dict[str, Any] | Scenario) -> Scenario:
        from virtualcyberq.scenario import load_builtin
        from virtualcyberq.scenario.model import Scenario

        if isinstance(source, Scenario):
            return source
        if (
            isinstance(source, str)
            and "\n" not in source
            and "/" not in source
            and not source.endswith(".yaml")
        ):
            try:
                return load_builtin(source)
            except FileNotFoundError:
                pass
        return load_scenario(source)

    def _require_started(self) -> None:
        if self._handle is None:
            raise RuntimeError("VirtualCyberQ not started; use as a context manager")
