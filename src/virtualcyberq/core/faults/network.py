# SPDX-License-Identifier: BSD-3-Clause
"""Network fault handlers (DESIGN section 8, network category).

These faults do not touch device state; they return *decisions* the device-plane
web middleware enacts per request. Each handler mutates a shared
:class:`~virtualcyberq.core.faults.RequestFaultDecision`; the middleware then
sleeps, refuses, hangs, or drops accordingly. The core stays framework-agnostic.

Catalog entries:

* ``net.unreachable`` -- refuse connections (ECONNREFUSED) for a window.
* ``net.blackhole`` -- accept then hang silently (client-timeout path).
* ``net.latency`` -- delay responses (fixed / jittered / distribution).
* ``net.conn_cap`` -- cap concurrent connections; refuse beyond it.
* ``net.keepalive_drop`` -- drop the connection mid-stream after N bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from virtualcyberq.core.rng import SeededRNG

if TYPE_CHECKING:  # pragma: no cover
    from virtualcyberq.core.faults import (
        Fault,
        FaultRegistry,
        RequestContext,
        RequestFaultDecision,
    )

__all__ = ["register"]


def register(registry: FaultRegistry) -> None:
    """Register every network handler on ``registry``."""
    registry.register_request_handler("net.unreachable", _unreachable)
    registry.register_request_handler("net.blackhole", _blackhole)
    registry.register_request_handler("net.latency", _latency)
    registry.register_request_handler("net.conn_cap", _conn_cap)
    registry.register_request_handler("net.keepalive_drop", _keepalive_drop)


def _unreachable(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Refuse the connection outright (ECONNREFUSED) while active."""
    decision.refuse = True


def _blackhole(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Accept the connection then hang silently (drive the client timeout)."""
    decision.blackhole = True
    decision.hang_forever = True


def _latency(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Add response latency from ``mean_ms`` +/- ``jitter_ms`` (seeded).

    Params:
        mean_ms: Mean delay in milliseconds (default 0).
        jitter_ms: Uniform +/- jitter in milliseconds (default 0).
        dist: ``"uniform"`` (default) or ``"gauss"`` for the jitter shape.
    """
    mean_ms = _as_float(fault.params.get("mean_ms"), 0.0)
    jitter_ms = _as_float(fault.params.get("jitter_ms"), 0.0)
    dist = str(fault.params.get("dist", "uniform"))
    if jitter_ms > 0:
        if dist == "gauss":
            delay_ms = rng.gauss(mean_ms, jitter_ms)
        else:
            delay_ms = rng.uniform(mean_ms - jitter_ms, mean_ms + jitter_ms)
    else:
        delay_ms = mean_ms
    decision.delay_s += max(0.0, delay_ms / 1000.0)


def _conn_cap(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Refuse the request when open connections exceed ``max_conns``.

    Params:
        max_conns: Maximum concurrent connections allowed (default 1).
    """
    max_conns = int(_as_float(fault.params.get("max_conns"), 1.0))
    if ctx.open_conns > max_conns:
        decision.refuse = True


def _keepalive_drop(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Drop the connection mid-stream after ``after_bytes`` bytes.

    Params:
        after_bytes: Number of bytes to send before dropping (default 0).
    """
    decision.drop_after_bytes = int(_as_float(fault.params.get("after_bytes"), 0.0))


def _as_float(value: object, default: float) -> float:
    """Coerce a param to float, falling back to ``default`` on bad input."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default
