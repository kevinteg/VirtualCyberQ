# SPDX-License-Identifier: BSD-3-Clause
"""Render ``all.xml`` -- the ``<nutcallstatus>`` status + names/setpoints feed.

``all.xml`` (PROTOCOL section 5) is live status **plus** the per-probe name and
setpoint containers. Its root element is ``<nutcallstatus>``. It adds a
``<COOK>`` container and a ``<FOODn>`` container per food probe (name / temp /
set / status), then repeats the flat volatile status and control fields as
siblings, mirroring the real-device document shape.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import _probe_status, _probe_temp

__all__ = ["render_all"]


def _container(tag: str, probe: ProbeState) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines.

    Args:
        tag: The container/element prefix, e.g. ``"COOK"`` or ``"FOOD1"``.
        probe: The probe to serialize.

    Returns:
        A list of XML lines: the open tag, four child elements, the close tag.
    """
    return [
        f"\t<{tag}>",
        f"\t\t<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"\t\t<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"\t\t<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"\t\t<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"\t</{tag}>",
    ]


def render_all(state: DeviceState) -> str:
    """Render the ``all.xml`` document for ``state``.

    Args:
        state: The device state to serialize.

    Returns:
        A ``str`` containing the full ``<nutcallstatus>`` document: the four
        probe containers followed by the flat status/control sibling fields.
        Temperatures and setpoints are tenths-degF (or ``OPEN``).
    """
    lines: list[str] = ["<nutcallstatus>"]
    lines += _container("COOK", state.cook)
    lines += _container("FOOD1", state.food1)
    lines += _container("FOOD2", state.food2)
    lines += _container("FOOD3", state.food3)
    lines += [
        f"\t<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"\t<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>",
        f"\t<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
        f"\t<DEG_UNITS>{int(state.system.deg_units)}</DEG_UNITS>",
        f"\t<COOK_CYCTIME>{int(state.control.cyctime)}</COOK_CYCTIME>",
        f"\t<COOK_PROPBAND>{int(state.control.propband)}</COOK_PROPBAND>",
        f"\t<COOK_RAMP>{int(state.control.cook_ramp)}</COOK_RAMP>",
        "</nutcallstatus>",
    ]
    return "\n".join(lines) + "\n"
