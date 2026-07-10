# SPDX-License-Identifier: BSD-3-Clause
"""Fault registry + activation gates (DESIGN section 8).

Faults live in the framework-agnostic core so they are seed-deterministic and
drivable in-process. Every fault is a :class:`Fault` record; the
:class:`FaultRegistry` owns the active set, gates activation through the single
seeded RNG, and auto-expires faults by simulated ``duration_s`` or by activation
``count``.

Two families, applied differently:

* **sensor.\\*** and **power.\\*** mutate simulation state *during* a physics
  step. The registry's :meth:`FaultRegistry.apply_sim_faults` is called by
  :class:`~virtualcyberq.core.simulation.Simulation.step` each tick.
* **network.\\*** and **http.\\*** are queried by the device-plane web middleware
  *per request* via :meth:`FaultRegistry.query_request`, which returns a plain
  :class:`RequestFaultDecision` (delay/error/mutate-body) the adapter enacts.
  The core returns decisions only; it never touches HTTP itself.

The catalog implementations live in the sibling modules ``network``, ``http``,
``sensor``, and ``power`` and are registered here as handlers keyed by fault id.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from virtualcyberq.core.clock import VirtualClock
from virtualcyberq.core.rng import SeededRNG

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance for typing only
    from virtualcyberq.core.state import DeviceState, SimState

__all__ = [
    "KNOWN_FAULT_IDS",
    "Fault",
    "FaultRegistry",
    "RequestContext",
    "RequestFaultDecision",
    "RequestFaultHandler",
    "SimFaultHandler",
]


@dataclass
class Fault:
    """A single registered fault (DESIGN section 8).

    Attributes:
        id: Stable catalog id, e.g. ``"http.error"`` (see :data:`KNOWN_FAULT_IDS`).
        enabled: Whether the fault is active. Injected faults default to ``True``.
        probability: Per-request / per-tick activation chance, drawn from the
            seeded RNG (``1.0`` == always).
        scope: Device endpoints the fault applies to (glob-ish paths; ``["*"]``
            means all).
        duration_s: Auto-expire after this many *simulated* seconds, or ``None``.
        count: Auto-expire after this many activations, or ``None``.
        params: Fault-specific knobs (e.g. ``{"status": 500}``).
        activations: Running count of times the fault has fired (bookkeeping).
        started_s: Simulated time the fault became active (set on injection).
    """

    id: str
    enabled: bool = True
    probability: float = 1.0
    scope: list[str] = field(default_factory=lambda: ["*"])
    duration_s: float | None = None
    count: int | None = None
    params: dict[str, object] = field(default_factory=dict)
    activations: int = 0
    started_s: float = 0.0

    def matches_path(self, path: str) -> bool:
        """Return ``True`` if ``path`` is in this fault's scope.

        A scope entry of ``"*"`` matches everything; a trailing ``"*"`` matches
        by prefix; otherwise the match is exact.
        """
        for pattern in self.scope:
            if pattern == "*":
                return True
            if pattern.endswith("*") and path.startswith(pattern[:-1]):
                return True
            if pattern == path:
                return True
        return False


@dataclass
class RequestContext:
    """The minimal request facts the network/http fault handlers need.

    Attributes:
        method: HTTP method (upper-case, e.g. ``"GET"``).
        path: Request path (e.g. ``"/status.xml"``).
        body: The response body the adapter would otherwise send (for mutation),
            or ``None`` for the pre-response network phase.
        open_conns: Current concurrent-connection count (for ``net.conn_cap``).
    """

    method: str
    path: str
    body: bytes | None = None
    open_conns: int = 0


@dataclass
class RequestFaultDecision:
    """The plain decision the web middleware enacts for one request.

    All fields are inert data; the core never performs I/O. The middleware reads
    these and does the framework-specific work (sleep, status, truncate, hang).

    Attributes:
        fired: The ids of the faults that fired for this request.
        delay_s: Seconds to delay the response (network latency), summed.
        refuse: Refuse the connection (``ECONNREFUSED`` / conn-cap / unreachable).
        blackhole: Accept then hang silently (client-timeout path).
        hang_forever: Hold the connection open indefinitely (slow-loris tail).
        drop_after_bytes: Drop the connection after N bytes, or ``None``.
        status_code: Override the HTTP status (e.g. 500/503/404/400), or ``None``.
        body: Replacement/mutated response body, or ``None`` to leave unchanged.
        content_type: Override the response ``Content-Type``, or ``None``.
        bytes_per_s: Byte-drip rate for slow-loris streaming, or ``None``.
    """

    fired: list[str] = field(default_factory=list)
    delay_s: float = 0.0
    refuse: bool = False
    blackhole: bool = False
    hang_forever: bool = False
    drop_after_bytes: int | None = None
    status_code: int | None = None
    body: bytes | None = None
    content_type: str | None = None
    bytes_per_s: float | None = None


#: A sim-mutating fault handler: ``(fault, state, sim, rng, dt) -> None``.
SimFaultHandler = Callable[["Fault", "DeviceState", "SimState", SeededRNG, float], None]

#: A request fault handler: mutates ``decision`` in place given the context.
RequestFaultHandler = Callable[["Fault", "RequestContext", "RequestFaultDecision", SeededRNG], None]


#: Every known catalog id (DESIGN section 8; 18 entries).
KNOWN_FAULT_IDS: tuple[str, ...] = (
    # network
    "net.unreachable",
    "net.blackhole",
    "net.latency",
    "net.conn_cap",
    "net.keepalive_drop",
    # http
    "http.error",
    "http.truncate",
    "http.malformed",
    "http.wrong_content_type",
    "http.slowloris",
    # sensor
    "probe.open",
    "probe.short",
    "sensor.noise",
    "sensor.drift",
    "sensor.stuck",
    "sensor.spike",
    # power
    "power.brownout",
    "power.reboot",
)


class FaultRegistry:
    """Owns the active faults; gates activation through the seeded RNG.

    The registry is created by :class:`~virtualcyberq.core.simulation.Simulation`
    with the shared clock and RNG. It routes each fault id to a handler (sim vs
    request family) registered by the catalog modules.

    Args:
        clock: The shared :class:`VirtualClock` (for duration expiry).
        rng: The shared :class:`SeededRNG` (for probability gates).
    """

    def __init__(self, clock: VirtualClock, rng: SeededRNG) -> None:
        self._clock = clock
        self._rng = rng
        self._faults: dict[str, Fault] = {}
        self._sim_handlers: dict[str, SimFaultHandler] = {}
        self._request_handlers: dict[str, RequestFaultHandler] = {}
        self._register_catalog()

    # --- catalog wiring -----------------------------------------------------
    def _register_catalog(self) -> None:
        """Register the built-in catalog handlers from the sibling modules."""
        from virtualcyberq.core.faults import http, network, power, sensor

        network.register(self)
        http.register(self)
        sensor.register(self)
        power.register(self)

    def register_sim_handler(self, fault_id: str, handler: SimFaultHandler) -> None:
        """Register a sim-mutating handler for a fault id."""
        self._sim_handlers[fault_id] = handler

    def register_request_handler(self, fault_id: str, handler: RequestFaultHandler) -> None:
        """Register a request-decision handler for a fault id."""
        self._request_handlers[fault_id] = handler

    # --- admin surface ------------------------------------------------------
    def inject(self, fault: Fault) -> Fault:
        """Add or replace a fault, stamping its start time. Returns the fault.

        Args:
            fault: The :class:`Fault` to activate. Its ``started_s`` is set to the
                current simulated time and ``activations`` reset to zero.
        """
        fault.started_s = self._clock.now()
        fault.activations = 0
        self._faults[fault.id] = fault
        return fault

    def list(self) -> builtins.list[Fault]:
        """Return the currently registered faults (active + latent)."""
        return list(self._faults.values())

    def get(self, fault_id: str) -> Fault | None:
        """Return the fault with ``fault_id``, or ``None`` if not present."""
        return self._faults.get(fault_id)

    def clear(self, fault_id: str) -> bool:
        """Remove one fault by id. Returns ``True`` if it was present."""
        return self._faults.pop(fault_id, None) is not None

    def clear_all(self) -> None:
        """Remove all faults."""
        self._faults.clear()

    def tick(self) -> None:
        """Expire faults whose simulated ``duration_s`` has elapsed.

        Called once per :meth:`~virtualcyberq.core.simulation.Simulation.step`.
        Count-based expiry happens at activation time in the apply/query paths.
        """
        now = self._clock.now()
        expired = [
            f.id
            for f in self._faults.values()
            if f.duration_s is not None and (now - f.started_s) >= f.duration_s
        ]
        for fid in expired:
            self._faults.pop(fid, None)

    # --- activation ---------------------------------------------------------
    def _should_fire(self, fault: Fault) -> bool:
        """Gate a fault on ``enabled`` + the seeded probability draw.

        A probability draw is consumed only for enabled faults with
        ``probability < 1`` so the RNG stream stays stable and meaningful.
        """
        if not fault.enabled:
            return False
        if fault.probability >= 1.0:
            return True
        if fault.probability <= 0.0:
            return False
        return self._rng.chance(fault.probability)

    def _record_activation(self, fault: Fault) -> None:
        """Increment the activation count and auto-expire on the count budget."""
        fault.activations += 1
        if fault.count is not None and fault.activations >= fault.count:
            self._faults.pop(fault.id, None)

    def apply_sim_faults(self, state: DeviceState, sim: SimState, dt: float) -> builtins.list[str]:
        """Apply all active sensor/power faults to the sim state this tick.

        Called by :meth:`Simulation.step` after physics + control each sub-step.

        Args:
            state: The visible device state (mutated by handlers).
            sim: The hidden physical state (mutated by handlers).
            dt: Simulated seconds this tick.

        Returns:
            The ids of the faults that fired this tick.
        """
        fired: list[str] = []
        for fault in list(self._faults.values()):
            handler = self._sim_handlers.get(fault.id)
            if handler is None:
                continue
            if not self._should_fire(fault):
                continue
            handler(fault, state, sim, self._rng, dt)
            self._record_activation(fault)
            fired.append(fault.id)
        return fired

    def query_request(self, ctx: RequestContext) -> RequestFaultDecision:
        """Return the combined network/http fault decision for one request.

        Called by the device-plane middleware. Iterates active network/http
        faults in catalog order, letting each mutate a shared decision; consumes
        a probability draw + counts an activation per fired fault.

        Args:
            ctx: The :class:`RequestContext` (method, path, body, open conns).

        Returns:
            A :class:`RequestFaultDecision` for the adapter to enact.
        """
        decision = RequestFaultDecision()
        for fault in list(self._faults.values()):
            handler = self._request_handlers.get(fault.id)
            if handler is None:
                continue
            if not fault.matches_path(ctx.path):
                continue
            if not self._should_fire(fault):
                continue
            handler(fault, ctx, decision, self._rng)
            self._record_activation(fault)
            decision.fired.append(fault.id)
        return decision
