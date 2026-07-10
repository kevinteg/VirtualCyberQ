# SPDX-License-Identifier: BSD-3-Clause
"""Build and run both planes over one shared simulation (DESIGN section 7, 11).

This module wires the device plane and the admin plane to a single
:class:`~virtualcyberq.core.simulation.Simulation`, adds a background async task
that ticks the simulation at the configured speed (the real-time / accelerated
drive mode, DESIGN section 7), and offers:

* :func:`build_apps` -- construct both FastAPI apps + the shared journal.
* :func:`run_servers` -- serve both on fixed ports with uvicorn (the CLI path).
* :func:`start_in_process` -- bind both on **ephemeral** ports in a daemon
  thread, returning a :class:`ServerHandle` with the actually-bound ports (the
  in-process test path). Clean shutdown via :meth:`ServerHandle.stop`.

The request journal is a WireMock-style ring buffer shared by both apps: the
device plane records each request, the admin plane exposes it.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from virtualcyberq.web.admin_app import build_admin_app
from virtualcyberq.web.device_app import build_device_app

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

    from virtualcyberq.core.simulation import Simulation

__all__ = [
    "TICK_WALL_S",
    "RequestJournal",
    "RequestRecord",
    "ServerHandle",
    "build_apps",
    "run_servers",
    "start_in_process",
]

#: Default background tick period in wall-seconds (DESIGN section 7; 100 ms).
TICK_WALL_S = 0.1

#: Default ring-buffer capacity for the request journal.
_JOURNAL_CAPACITY = 1000


class RequestRecord(dict[str, Any]):
    """One journal entry (a plain dict: method, path, body, ts, fired)."""


class RequestJournal:
    """A thread-safe ring buffer of device-plane requests (DESIGN section 9).

    Args:
        capacity: Maximum number of retained records (oldest evicted first).
    """

    def __init__(self, capacity: int = _JOURNAL_CAPACITY) -> None:
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._total = 0
        self._total_fired = 0

    def record(
        self,
        *,
        method: str,
        path: str,
        body: str | None,
        ts: float,
        fired: list[str],
    ) -> None:
        """Append one request record (thread-safe)."""
        entry = {
            "method": method,
            "path": path,
            "body": body,
            "ts": ts,
            "fired": list(fired),
        }
        with self._lock:
            self._records.append(entry)
            self._total += 1
            self._total_fired += len(fired)

    def entries(self, *, limit: int = 100, path: str | None = None) -> list[dict[str, Any]]:
        """Return up to ``limit`` most-recent records, optionally filtered by path."""
        with self._lock:
            items = list(self._records)
        if path is not None:
            items = [e for e in items if e["path"] == path]
        return items[-limit:]

    def clear(self) -> None:
        """Drop all retained records (counters are preserved)."""
        with self._lock:
            self._records.clear()

    @property
    def total(self) -> int:
        """Total requests ever recorded (survives :meth:`clear`)."""
        return self._total

    @property
    def total_fired(self) -> int:
        """Total fault activations ever recorded across requests."""
        return self._total_fired


def build_apps(
    sim: Simulation,
    *,
    journal: RequestJournal | None = None,
    started_at: float | None = None,
) -> tuple[FastAPI, FastAPI, RequestJournal]:
    """Build the device + admin apps over one simulation and shared journal.

    Args:
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        journal: An existing :class:`RequestJournal`, or ``None`` to create one.
        started_at: Wall-clock boot time for the admin ``/health`` uptime.

    Returns:
        ``(device_app, admin_app, journal)``.
    """
    journal = journal if journal is not None else RequestJournal()
    device_app = build_device_app(sim, journal=journal)
    admin_app = build_admin_app(sim, journal=journal, started_at=started_at)
    return device_app, admin_app, journal


# --------------------------------------------------------------- background tick
async def _tick_loop(sim: Simulation, stop: asyncio.Event, period: float = TICK_WALL_S) -> None:
    """Tick the simulation at wall-real cadence, scaled by the clock speed.

    Sleeps ``period`` wall-seconds and advances physics by ``period * speed``
    simulated seconds (a no-op while frozen). Cancelled/stopped cleanly.
    """
    last = time.monotonic()
    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=period)
        now = time.monotonic()
        dt_wall = now - last
        last = now
        if sim.clock.speed > 0 and dt_wall > 0:
            sim.tick_wall(dt_wall)


class ServerHandle:
    """A running device+admin server pair, for in-process tests.

    Attributes:
        device_url: Base URL of the device plane (e.g. ``http://127.0.0.1:53411``).
        admin_url: Base URL of the admin plane.
        device_port: The actually-bound device port.
        admin_port: The actually-bound admin port.
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        journal: The shared :class:`RequestJournal`.
    """

    def __init__(
        self,
        *,
        sim: Simulation,
        journal: RequestJournal,
        device_port: int,
        admin_port: int,
        thread: threading.Thread,
        stop_event: asyncio.Event,
        loop: asyncio.AbstractEventLoop,
        servers: list[Any],
    ) -> None:
        self.sim = sim
        self.journal = journal
        self.device_port = device_port
        self.admin_port = admin_port
        self.device_url = f"http://127.0.0.1:{device_port}"
        self.admin_url = f"http://127.0.0.1:{admin_port}"
        self._thread = thread
        self._stop_event = stop_event
        self._loop = loop
        self._servers = servers

    def stop(self, timeout: float = 5.0) -> None:
        """Signal shutdown and join the server thread cleanly."""

        def _signal() -> None:
            self._stop_event.set()
            for server in self._servers:
                server.should_exit = True

        with contextlib.suppress(RuntimeError):  # pragma: no cover - loop already closed
            self._loop.call_soon_threadsafe(_signal)
        self._thread.join(timeout=timeout)

    def __enter__(self) -> ServerHandle:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()


def _bind_ephemeral() -> tuple[socket.socket, int]:
    """Bind a fresh ephemeral TCP socket on 127.0.0.1 and return it + its port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    return sock, port


def start_in_process(
    sim: Simulation,
    *,
    tick: bool = True,
    journal: RequestJournal | None = None,
) -> ServerHandle:
    """Start both planes on ephemeral 127.0.0.1 ports in a daemon thread.

    Binds two ephemeral sockets up front so the caller learns the real ports
    immediately, hands them to uvicorn, and spins the event loop (plus an
    optional background tick task) in a daemon thread.

    Args:
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        tick: Whether to run the background tick loop (advances physics at the
            clock speed). Tests that step deterministically usually pass a frozen
            clock, making the loop a no-op regardless.
        journal: An existing :class:`RequestJournal`, or ``None`` to create one.

    Returns:
        A :class:`ServerHandle` with the bound ports and a working :meth:`stop`.
    """
    import uvicorn

    device_app, admin_app, journal = build_apps(sim, journal=journal)

    device_sock, device_port = _bind_ephemeral()
    admin_sock, admin_port = _bind_ephemeral()

    stop_event_box: dict[str, Any] = {}
    servers: list[Any] = []
    ready = threading.Event()

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop_event = asyncio.Event()
        stop_event_box["event"] = stop_event
        stop_event_box["loop"] = loop

        device_cfg = uvicorn.Config(
            device_app,
            log_level="warning",
            lifespan="on",
            server_header=False,
            date_header=False,
        )
        admin_cfg = uvicorn.Config(
            admin_app,
            log_level="warning",
            lifespan="on",
        )
        device_server = uvicorn.Server(device_cfg)
        admin_server = uvicorn.Server(admin_cfg)
        # Signal handlers can only be installed on the main thread; this server
        # runs in a daemon thread, so disable them. ``install_signal_handlers``
        # exists on uvicorn's ``Server`` at runtime but is absent from its type
        # stubs, hence the narrowly-scoped ignore.
        device_server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]
        admin_server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]
        servers.append(device_server)
        servers.append(admin_server)

        async def _serve() -> None:
            tasks = [
                loop.create_task(device_server.serve(sockets=[device_sock])),
                loop.create_task(admin_server.serve(sockets=[admin_sock])),
            ]
            if tick:
                tasks.append(loop.create_task(_tick_loop(sim, stop_event)))
            ready.set()
            await stop_event.wait()
            for server in (device_server, admin_server):
                server.should_exit = True
            await asyncio.gather(*tasks, return_exceptions=True)

        try:
            loop.run_until_complete(_serve())
        finally:
            loop.close()

    thread = threading.Thread(target=_run, name="virtualcyberq-server", daemon=True)
    thread.start()
    ready.wait(timeout=10.0)

    return ServerHandle(
        sim=sim,
        journal=journal,
        device_port=device_port,
        admin_port=admin_port,
        thread=thread,
        stop_event=stop_event_box["event"],
        loop=stop_event_box["loop"],
        servers=servers,
    )


def run_servers(
    sim: Simulation,
    *,
    device_port: int = 8080,
    admin_port: int = 9000,
    host: str = "0.0.0.0",
    tick: bool = True,
) -> None:
    """Serve both planes on fixed ports until interrupted (the CLI path).

    Blocks the calling thread, running uvicorn for both apps plus the background
    tick task on one event loop.

    Args:
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        device_port: The device-plane TCP port.
        admin_port: The admin-plane TCP port.
        host: Bind address.
        tick: Whether to run the background physics tick loop.
    """
    import uvicorn

    device_app, admin_app, _ = build_apps(sim)

    async def _serve() -> None:
        stop_event = asyncio.Event()
        device_cfg = uvicorn.Config(
            device_app,
            host=host,
            port=device_port,
            log_level="info",
            server_header=False,
            date_header=False,
        )
        admin_cfg = uvicorn.Config(
            admin_app,
            host=host,
            port=admin_port,
            log_level="info",
        )
        device_server = uvicorn.Server(device_cfg)
        admin_server = uvicorn.Server(admin_cfg)
        tasks = [
            asyncio.create_task(device_server.serve()),
            asyncio.create_task(admin_server.serve()),
        ]
        if tick:
            tasks.append(asyncio.create_task(_tick_loop(sim, stop_event)))
        await asyncio.gather(*tasks)

    asyncio.run(_serve())
