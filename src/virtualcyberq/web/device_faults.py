# SPDX-License-Identifier: BSD-3-Clause
"""Device-plane fault middleware (DESIGN section 8).

A pure-ASGI middleware that consults the shared
:class:`~virtualcyberq.core.simulation.Simulation`'s
:class:`~virtualcyberq.core.faults.FaultRegistry` **once per request** and enacts
the returned :class:`~virtualcyberq.core.faults.RequestFaultDecision`:

* ``is_powered()`` False  -> the device is offline; emulate an unreachable unit.
* ``refuse``              -> connection refused (``ECONNREFUSED``-style close).
* ``blackhole`` / ``hang_forever`` -> hold the connection open (client timeout).
* ``delay_s``             -> async latency sleep (never blocks a worker).
* ``status_code``         -> override the HTTP status (500/503/404/400).
* ``body``                -> replace the response body (malformed/truncated XML).
* ``content_type``        -> override ``Content-Type`` (wrong content-type fault).
* ``drop_after_bytes``    -> truncate the body at N bytes.
* ``bytes_per_s``         -> byte-drip the body (slow-loris).

The middleware wraps the application at the ASGI level so it can buffer, mutate,
truncate, and slow-drip the response body -- finer control than a request/
response decorator gives. Because ``refuse`` / ``blackhole`` / ``delay`` must be
decided *before* the response is sent yet the body-mutating faults need the
buffered body, the registry is queried **exactly once** (with the buffered body
in context) after the wrapped app runs, and every field of the single decision
is enacted together. All randomness flows through the seeded RNG inside the
simulation, so faults are deterministic under a fixed seed.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from virtualcyberq.core.faults import RequestContext
from virtualcyberq.core.personas import get_persona

if TYPE_CHECKING:  # pragma: no cover - typing only
    from virtualcyberq.core.simulation import Simulation
    from virtualcyberq.web.server import RequestJournal

__all__ = ["DeviceFaultMiddleware"]

#: The ``Server:`` header the real firmware likely presents (terse; PROTOCOL 2.3).
SERVER_HEADER = b"CyberQ"


class DeviceFaultMiddleware:
    """Pure-ASGI middleware applying network/HTTP faults per request.

    Args:
        app: The wrapped ASGI application (the device FastAPI app).
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation` whose
            fault registry decides each request's fate.
    """

    def __init__(
        self,
        app: object,
        sim: Simulation,
        journal: RequestJournal | None = None,
    ) -> None:
        self._app = app
        self._sim = sim
        self._journal = journal
        self._open_conns = 0

    async def __call__(self, scope: dict[str, Any], receive: object, send: object) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)  # type: ignore[operator]
            return

        # Power-outage gating: the whole unit disappears (hold until timeout).
        if not self._sim.is_powered():
            self._record(scope, b"", [])
            await self._hang(send)
            return

        self._open_conns += 1
        try:
            await self._run(scope, receive, send)
        finally:
            self._open_conns -= 1

    # ------------------------------------------------------------------ helpers
    async def _run(self, scope: dict[str, Any], receive: object, send: object) -> None:
        """Buffer the request body + response, then query + enact one decision."""
        request_body: list[bytes] = []

        async def buffering_receive() -> dict[str, Any]:
            message = cast("dict[str, Any]", await receive())  # type: ignore[operator]
            if message.get("type") == "http.request":
                request_body.append(bytes(message.get("body", b"")))
            return message

        status_holder: list[int] = [200]
        headers_holder: list[list[tuple[bytes, bytes]]] = [[]]
        body_chunks: list[bytes] = []

        async def buffering_send(message: dict[str, Any]) -> None:
            mtype = message.get("type")
            if mtype == "http.response.start":
                status_holder[0] = int(message.get("status", 200))
                headers_holder[0] = [(bytes(k), bytes(v)) for (k, v) in message.get("headers", [])]
            elif mtype == "http.response.body":
                body_chunks.append(bytes(message.get("body", b"")))

        await self._app(scope, buffering_receive, buffering_send)  # type: ignore[operator]

        await self._decide_and_flush(
            scope,
            send,
            status_holder[0],
            headers_holder[0],
            b"".join(body_chunks),
            b"".join(request_body),
        )

    async def _decide_and_flush(
        self,
        scope: dict[str, Any],
        send: object,
        status: int,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
        request_body: bytes,
    ) -> None:
        """Query the registry once (body in context) and enact the decision."""
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/"))
        decision = self._sim.query_request_faults(
            RequestContext(method=method, path=path, body=body, open_conns=self._open_conns)
        )
        self._record(scope, request_body, decision.fired)

        # Pre-flight network faults, in order of severity.
        if decision.refuse:
            await self._close_connection(send)
            return
        if decision.blackhole or decision.hang_forever:
            await self._hang(send)
            return
        if decision.delay_s > 0:
            await asyncio.sleep(decision.delay_s)

        # HTTP-layer mutations.
        if decision.status_code is not None:
            status = int(decision.status_code)
        if decision.body is not None:
            body = decision.body
        if decision.drop_after_bytes is not None:
            body = body[: max(0, int(decision.drop_after_bytes))]

        content_type: bytes | None = None
        if decision.content_type is not None:
            content_type = decision.content_type.encode("latin-1")

        out_headers = self._fidelity_headers(headers, content_type, len(body))
        await send(
            {  # type: ignore[operator]
                "type": "http.response.start",
                "status": status,
                "headers": out_headers,
            }
        )

        if decision.bytes_per_s is not None and decision.bytes_per_s > 0 and body:
            await self._drip(send, body, decision.bytes_per_s)
        else:
            await send(
                {  # type: ignore[operator]
                    "type": "http.response.body",
                    "body": body,
                    "more_body": False,
                }
            )

    def _fidelity_headers(
        self,
        headers: list[tuple[bytes, bytes]],
        content_type: bytes | None,
        content_length: int,
    ) -> list[tuple[bytes, bytes]]:
        """Return response headers matching the selected firmware persona.

        Reproduces the real unit's header set (verified on firmware 1.7): a
        **bare** ``Content-Type`` (the device sends ``text/xml`` with no charset),
        ``Cache-Control: no-cache``, ``Connection: close``, and **no** ``Server``
        or ``Content-Length`` header. All of these are persona-configurable via
        :class:`~virtualcyberq.core.personas.WireFormat`. A fault ``content_type``
        override, when present, replaces the app's content type.
        """
        wire = get_persona(self._sim.state.fwver).wire
        out: list[tuple[bytes, bytes]] = []
        for k, v in headers:
            lk = bytes(k).lower()
            if lk in (b"connection", b"server", b"content-length", b"cache-control"):
                continue
            if lk == b"content-type":
                if content_type is not None:
                    continue  # fault override replaces it below
                # Bare the app's content type (drop "; charset=..."), like the device.
                out.append((b"content-type", bytes(v).split(b";", 1)[0].strip()))
                continue
            out.append((bytes(k), bytes(v)))
        if content_type is not None:
            out.append((b"content-type", content_type))
        if wire.cache_control:
            out.append((b"cache-control", wire.cache_control.encode("latin-1")))
        if wire.send_content_length:
            out.append((b"content-length", str(content_length).encode("ascii")))
        out.append((b"connection", b"close"))
        if wire.send_server_header:
            out.append((b"server", SERVER_HEADER))
        return out

    def _record(self, scope: dict[str, Any], request_body: bytes, fired: list[str]) -> None:
        """Record one request into the journal (if configured)."""
        if self._journal is None:
            return
        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", "/"))
        body: str | None = None
        if request_body:
            body = request_body.decode("latin-1")
        self._journal.record(
            method=method,
            path=path,
            body=body,
            ts=self._sim.now(),
            fired=list(fired),
        )

    async def _drip(self, send: object, body: bytes, bytes_per_s: float) -> None:
        """Byte-drip the body at ``bytes_per_s`` (slow-loris fault)."""
        chunk = max(1, int(bytes_per_s))
        delay = chunk / bytes_per_s
        for i in range(0, len(body), chunk):
            piece = body[i : i + chunk]
            more = (i + chunk) < len(body)
            await send(
                {  # type: ignore[operator]
                    "type": "http.response.body",
                    "body": piece,
                    "more_body": more,
                }
            )
            if more:
                await asyncio.sleep(delay)

    async def _hang(self, send: object) -> None:
        """Blackhole/hang: accept then never respond until the client times out."""
        while True:
            await asyncio.sleep(3600)

    async def _close_connection(self, send: object) -> None:
        """Emulate a refused/closed connection with no useful HTTP response.

        ASGI cannot literally refuse a TCP connect after accept, so the closest
        fidelity is an immediate close: a ``503`` with ``Connection: close`` and
        an empty body. Clients observe a broken/short read.
        """
        await send(
            {  # type: ignore[operator]
                "type": "http.response.start",
                "status": 503,
                "headers": [
                    (b"connection", b"close"),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send(
            {  # type: ignore[operator]
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            }
        )
