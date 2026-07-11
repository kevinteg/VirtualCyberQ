# SPDX-License-Identifier: BSD-3-Clause
"""Render ``all.xml`` -- the ``<nutcallstatus>`` status + names/setpoints feed.

``all.xml`` (PROTOCOL section 5) is live status **plus** the per-probe name and
setpoint containers. Its root element is ``<nutcallstatus>``. Inside the root it
opens with a ``this is similar to status.xml`` comment and the two-line
temperature comment block, then a ``<COOK>`` container and a ``<FOODn>``
container per food probe (name / temp / set / status), then the flat volatile
status and control fields as siblings. Byte-shape (CRLF, indentation, trailing
spaces after ``TIMER_CURR``) comes from the selected firmware persona.
"""

from __future__ import annotations

from virtualcyberq.core.personas import get_persona
from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import _comment_lines, _finish, _probe_status, _probe_temp

__all__ = ["render_all"]

#: The all.xml-specific lead comment (precedes the shared temperature block).
_ALL_LEAD_COMMENT = "<!--this is similar to status.xml, but with more values-->"


def _container(tag: str, probe: ProbeState, indent: str) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines.

    Args:
        tag: The container/element prefix, e.g. ``"COOK"`` or ``"FOOD1"``.
        probe: The probe to serialize.
        indent: The persona's one-level indentation string.

    Returns:
        A list of XML lines: the open tag, four child elements, the close tag.
    """
    i = indent
    return [
        f"{i}<{tag}>",
        f"{i}{i}<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"{i}{i}<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"{i}{i}<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"{i}{i}<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"{i}</{tag}>",
    ]


def render_all(state: DeviceState) -> str:
    """Render the ``all.xml`` document for ``state`` (per its firmware persona)."""
    wire = get_persona(state.fwver).wire
    i = wire.indent
    lines = ["<nutcallstatus>", *_comment_lines(_ALL_LEAD_COMMENT, wire)]
    lines += _container("COOK", state.cook, i)
    lines += _container("FOOD1", state.food1, i)
    lines += _container("FOOD2", state.food2, i)
    lines += _container("FOOD3", state.food3, i)
    lines += [
        f"{i}<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"{i}<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>"
        f"{wire.list_timer_trailing}",
        f"{i}<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
        f"{i}<DEG_UNITS>{int(state.system.deg_units)}</DEG_UNITS>",
        f"{i}<COOK_CYCTIME>{int(state.control.cyctime)}</COOK_CYCTIME>",
        f"{i}<COOK_PROPBAND>{int(state.control.propband)}</COOK_PROPBAND>",
        f"{i}<COOK_RAMP>{int(state.control.cook_ramp)}</COOK_RAMP>",
        "</nutcallstatus>",
    ]
    return _finish(lines, wire)
