# SPDX-License-Identifier: BSD-3-Clause
"""HTTP fault handlers (DESIGN section 8, http category).

Like the network family, these return *decisions* the device-plane middleware
enacts per request; they never touch device state or perform I/O. Each handler
mutates a shared :class:`~virtualcyberq.core.faults.RequestFaultDecision`.

Catalog entries:

* ``http.error`` -- return 500/503/404/400 with (probabilistic) frequency.
* ``http.truncate`` -- cut the XML body mid-tag / early.
* ``http.malformed`` -- invalid entities, wrong root element, bad encoding.
* ``http.wrong_content_type`` -- serve XML as the wrong Content-Type.
* ``http.slowloris`` -- byte-drip a partial response.
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
    """Register every http handler on ``registry``."""
    registry.register_request_handler("http.error", _error)
    registry.register_request_handler("http.truncate", _truncate)
    registry.register_request_handler("http.malformed", _malformed)
    registry.register_request_handler("http.wrong_content_type", _wrong_content_type)
    registry.register_request_handler("http.slowloris", _slowloris)


def _error(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Override the response status code.

    Params:
        status: The HTTP status to return (default 500).
    """
    decision.status_code = int(_as_float(fault.params.get("status"), 500.0))


def _truncate(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Cut the body short at ``at_byte`` or by ``fraction`` (DESIGN section 8).

    Params:
        at_byte: Absolute byte offset to cut at (takes precedence), or ``None``.
        fraction: Keep this fraction of the body (0..1) when ``at_byte`` unset.
    """
    body = decision.body if decision.body is not None else ctx.body
    if body is None:
        return
    at_byte = fault.params.get("at_byte")
    if at_byte is not None:
        cut = max(0, int(_as_float(at_byte, 0.0)))
    else:
        fraction = _as_float(fault.params.get("fraction"), 0.5)
        fraction = min(1.0, max(0.0, fraction))
        cut = int(len(body) * fraction)
    decision.body = body[:cut]


def _malformed(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Corrupt the body per ``mode`` so parsers choke (DESIGN section 8).

    Params:
        mode: One of ``"bad_entity"``, ``"wrong_root"``, ``"missing_close"``,
            ``"bad_encoding"`` (default ``"bad_entity"``).
    """
    body = decision.body if decision.body is not None else ctx.body
    if body is None:
        body = b""
    mode = str(fault.params.get("mode", "bad_entity"))
    if mode == "wrong_root":
        text = body.decode("utf-8", errors="replace")
        text = text.replace("nutcstatus", "wrongroot").replace("nutcallstatus", "wrongroot")
        decision.body = text.encode("utf-8")
    elif mode == "missing_close":
        # Drop the final closing tag so the document is unbalanced.
        idx = body.rfind(b"</")
        decision.body = body[:idx] if idx >= 0 else body
    elif mode == "bad_encoding":
        decision.body = body + b"\xff\xfe invalid-bytes"
    else:  # bad_entity
        decision.body = body + b"<BROKEN>&notanentity;</BROKEN>"


def _wrong_content_type(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Override the response Content-Type.

    Params:
        content_type: The wrong type to send (default ``"text/plain"``).
    """
    decision.content_type = str(fault.params.get("content_type", "text/plain"))


def _slowloris(
    fault: Fault,
    ctx: RequestContext,
    decision: RequestFaultDecision,
    rng: SeededRNG,
) -> None:
    """Byte-drip the response at ``bytes_per_s`` (partial, slow response).

    Params:
        bytes_per_s: Streaming rate in bytes/second (default 1).
    """
    decision.bytes_per_s = max(0.0, _as_float(fault.params.get("bytes_per_s"), 1.0))


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
