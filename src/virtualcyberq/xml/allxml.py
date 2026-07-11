# SPDX-License-Identifier: BSD-3-Clause
"""Render ``all.xml`` -- the ``<nutcallstatus>`` status + names/setpoints feed.

``all.xml`` (PROTOCOL section 5) is live status **plus** the per-probe name and
setpoint containers. Its root element is ``<nutcallstatus>``. Inside the root it
opens with a ``this is similar to status.xml`` comment and the two-line
temperature comment block, then a ``<COOK>`` container and a ``<FOODn>``
container per food probe (name / temp / set / status), then the flat volatile
status and control fields as siblings -- mirroring a captured real v1.7 unit.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import INDENT, TEMP_COMMENT_LINES, _probe_status, _probe_temp

__all__ = ["render_all"]

#: The all.xml-specific lead comment (precedes the shared temperature block).
_ALL_LEAD_COMMENT = "<!--this is similar to status.xml, but with more values-->"


def _container(tag: str, probe: ProbeState) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines.

    Args:
        tag: The container/element prefix, e.g. ``"COOK"`` or ``"FOOD1"``.
        probe: The probe to serialize.

    Returns:
        A list of XML lines: the open tag, four child elements, the close tag.
    """
    i = INDENT
    return [
        f"{i}<{tag}>",
        f"{i}{i}<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"{i}{i}<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"{i}{i}<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"{i}{i}<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"{i}</{tag}>",
    ]


def render_all(state: DeviceState) -> str:
    """Render the ``all.xml`` document for ``state``.

    Args:
        state: The device state to serialize.

    Returns:
        A ``str`` containing the full ``<nutcallstatus>`` document: the lead +
        temperature comments, the four probe containers, then the flat
        status/control sibling fields. Temperatures/setpoints are tenths-degF
        (or ``OPEN``).
    """
    i = INDENT
    lines = ["<nutcallstatus>", i + _ALL_LEAD_COMMENT, *(i + c for c in TEMP_COMMENT_LINES)]
    lines += _container("COOK", state.cook)
    lines += _container("FOOD1", state.food1)
    lines += _container("FOOD2", state.food2)
    lines += _container("FOOD3", state.food3)
    lines += [
        f"{i}<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"{i}<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>",
        f"{i}<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
        f"{i}<DEG_UNITS>{int(state.system.deg_units)}</DEG_UNITS>",
        f"{i}<COOK_CYCTIME>{int(state.control.cyctime)}</COOK_CYCTIME>",
        f"{i}<COOK_PROPBAND>{int(state.control.propband)}</COOK_PROPBAND>",
        f"{i}<COOK_RAMP>{int(state.control.cook_ramp)}</COOK_RAMP>",
        "</nutcallstatus>",
    ]
    return "\n".join(lines) + "\n"
