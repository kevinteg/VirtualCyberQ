# SPDX-License-Identifier: BSD-3-Clause
"""The device-plane FastAPI app (DESIGN section 5, PROTOCOL section 2).

Serves **only** the real CyberQ WiFi surface -- nothing admin leaks here:

* ``GET /status.xml``  -> ``<nutcstatus>``   (``text/xml``)
* ``GET /all.xml``     -> ``<nutcallstatus>`` (``text/xml``)
* ``GET /config.xml``  -> ``<nutcallstatus>`` superset (``text/xml``)
* ``GET /``            -> the HTML Control Status page (``text/html``)
* ``GET /*.htm``       -> the legacy config HTML pages
* ``POST /``           -> form-encoded ``KEY=value`` writes (200)
* ``POST /*.htm``      -> same write surface on the legacy page URLs
* ``POST /status.xml`` -> tolerant form POST (``IGNOREDTAG`` cache-buster)

The app owns a shared :class:`~virtualcyberq.core.simulation.Simulation`; reads
serialize its state, writes route the body through the pure XML
:func:`~virtualcyberq.xml.post_parse.parse_and_apply` parser. Fidelity touches
(``Connection: close``, a terse ``Server:`` header) are added centrally by the
:class:`~virtualcyberq.web.device_faults.DeviceFaultMiddleware`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from virtualcyberq.web.device_faults import DeviceFaultMiddleware
from virtualcyberq.xml import (
    render_all,
    render_config,
    render_legacy_page,
    render_status,
)
from virtualcyberq.xml.post_parse import parse_and_apply

if TYPE_CHECKING:  # pragma: no cover - typing only
    from virtualcyberq.core.simulation import Simulation
    from virtualcyberq.web.server import RequestJournal

__all__ = ["build_device_app"]

_XML_MEDIA_TYPE = "text/xml"
_HTML_MEDIA_TYPE = "text/html"


def build_device_app(
    sim: Simulation,
    *,
    journal: RequestJournal | None = None,
) -> FastAPI:
    """Build the device-plane FastAPI app over a shared simulation.

    Args:
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        journal: Optional request journal (ring buffer) the app records each
            request into so the admin plane can expose it.

    Returns:
        A configured :class:`fastapi.FastAPI` device app. It carries the
        simulation on ``app.state.sim`` and wraps itself in
        :class:`~virtualcyberq.web.device_faults.DeviceFaultMiddleware`.
    """
    app = FastAPI(
        title="CyberQ WiFi",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.sim = sim
    app.state.journal = journal

    def _xml(text: str) -> Response:
        return Response(content=text, media_type=_XML_MEDIA_TYPE)

    def _xml_read(request: Request, text: str) -> Response:
        # HEAD returns the same status/content-type with no body, so a proxy's
        # health-check HEAD succeeds instead of getting a 405.
        return _xml("" if request.method == "HEAD" else text)

    # A real embedded unit does not emit FastAPI-style JSON error bodies; return
    # a minimal text/html page for any HTTP error so the device plane cannot be
    # fingerprinted as an emulator by its error shape (DESIGN section 1).
    @app.exception_handler(StarletteHTTPException)
    async def _device_http_error(request: Request, exc: StarletteHTTPException) -> Response:
        code = exc.status_code
        body = f"<html><head><title>{code}</title></head><body>{code}</body></html>"
        return Response(
            content=body,
            status_code=exc.status_code,
            media_type=_HTML_MEDIA_TYPE,
            headers=exc.headers,
        )

    # Request journaling (method/path/body + fired fault ids) is handled centrally
    # by DeviceFaultMiddleware, which has the fault decision in hand.

    # ------------------------------------------------------------------ reads
    @app.api_route("/status.xml", methods=["GET", "HEAD"])
    async def get_status(request: Request) -> Response:
        return _xml_read(request, render_status(sim.state))

    @app.api_route("/all.xml", methods=["GET", "HEAD"])
    async def get_all(request: Request) -> Response:
        return _xml_read(request, render_all(sim.state))

    @app.api_route("/config.xml", methods=["GET", "HEAD"])
    async def get_config(request: Request) -> Response:
        return _xml_read(request, render_config(sim.state))

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> Response:
        return Response(
            content=render_legacy_page("index.htm", sim.state),
            media_type=_HTML_MEDIA_TYPE,
        )

    @app.get("/{page}.htm", response_class=HTMLResponse)
    async def get_legacy(page: str) -> Response:
        return Response(
            content=render_legacy_page(f"{page}.htm", sim.state),
            media_type=_HTML_MEDIA_TYPE,
        )

    # ----------------------------------------------------------------- writes
    async def _apply_post(request: Request) -> list[str]:
        raw = (await request.body()).decode("latin-1")
        applied = parse_and_apply(sim, raw)
        return [k for k, _ in applied]

    @app.post("/", response_class=HTMLResponse)
    async def post_index(request: Request) -> Response:
        await _apply_post(request)
        return Response(
            content=render_legacy_page("index.htm", sim.state),
            media_type=_HTML_MEDIA_TYPE,
        )

    @app.post("/{page}.htm", response_class=HTMLResponse)
    async def post_legacy(page: str, request: Request) -> Response:
        await _apply_post(request)
        return Response(
            content=render_legacy_page(f"{page}.htm", sim.state),
            media_type=_HTML_MEDIA_TYPE,
        )

    @app.post("/status.xml")
    async def post_status(request: Request) -> Response:
        # Tolerant POST: apply any recognized keys (IGNOREDTAG cache-buster is
        # silently ignored by the parser), then return a fresh status.xml.
        await _apply_post(request)
        return _xml(render_status(sim.state))

    # Wrap the whole app so per-request faults + fidelity headers + journaling
    # apply. Starlette's add_middleware instantiates ``cls(app, **options)``.
    app.add_middleware(DeviceFaultMiddleware, sim=sim, journal=journal)
    return app
