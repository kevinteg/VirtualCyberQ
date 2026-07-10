# SPDX-License-Identifier: BSD-3-Clause
"""Render ``status.xml`` -- the fast ``<nutcstatus>`` live-status feed.

This is the volatile-only feed the real device's web UI AJAX-polls ~1/sec
(PROTOCOL section 4). It is a flat document (no nested containers) whose root
element is ``<nutcstatus>``. Every temperature is emitted as integer
tenths-of-degF, an open probe as the literal string ``OPEN``, and each
``*_STATUS`` as the shared 0..7 status integer.

The document is prefixed with the device's verbatim three-line temperature
comment block; real clients have been observed to depend on the exact document
shape, so it is reproduced byte-for-byte.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms

__all__ = ["TEMP_COMMENT_BLOCK", "render_status"]

#: The verbatim temperature-comment block the device emits ahead of every feed
#: (PROTOCOL section 3). Reproduced byte-for-byte, including the double space
#: after "unit." on the second line.
TEMP_COMMENT_BLOCK = (
    "<!--all temperatures are displayed in tenths F, regardless of setting of unit-->\n"
    "<!--all temperatures sent by browser to unit should be in F.  you can send-->\n"
    "<!--tenths F with a decimal place, ex: 123.5-->"
)


def _probe_temp(probe: ProbeState) -> str:
    """Return a probe's wire ``*_TEMP`` string (``OPEN`` when disconnected)."""
    if not probe.connected:
        return encode_temp(None)
    return encode_temp(probe.temp)


def _probe_status(probe: ProbeState) -> int:
    """Return a probe's wire ``*_STATUS`` integer (ERROR=4 when disconnected)."""
    if not probe.connected:
        return 4
    return int(probe.status)


def render_status(state: DeviceState) -> str:
    """Render the ``status.xml`` document for ``state``.

    Args:
        state: The device state to serialize.

    Returns:
        A ``str`` containing the full ``<nutcstatus>`` document, prefixed with
        the verbatim temperature-comment block. Temperatures are tenths-degF (or
        ``OPEN``); ``TIMER_CURR`` is ``HH:MM:SS``; statuses are 0..7 integers.
    """
    cook = state.cook
    food1 = state.food1
    food2 = state.food2
    food3 = state.food3

    lines = [
        TEMP_COMMENT_BLOCK,
        "<nutcstatus>",
        f"\t<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"\t<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>",
        f"\t<COOK_TEMP>{_probe_temp(cook)}</COOK_TEMP>",
        f"\t<FOOD1_TEMP>{_probe_temp(food1)}</FOOD1_TEMP>",
        f"\t<FOOD2_TEMP>{_probe_temp(food2)}</FOOD2_TEMP>",
        f"\t<FOOD3_TEMP>{_probe_temp(food3)}</FOOD3_TEMP>",
        f"\t<COOK_STATUS>{_probe_status(cook)}</COOK_STATUS>",
        f"\t<FOOD1_STATUS>{_probe_status(food1)}</FOOD1_STATUS>",
        f"\t<FOOD2_STATUS>{_probe_status(food2)}</FOOD2_STATUS>",
        f"\t<FOOD3_STATUS>{_probe_status(food3)}</FOOD3_STATUS>",
        f"\t<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
        f"\t<DEG_UNITS>{int(state.system.deg_units)}</DEG_UNITS>",
        f"\t<COOK_CYCTIME>{int(state.control.cyctime)}</COOK_CYCTIME>",
        f"\t<COOK_PROPBAND>{int(state.control.propband)}</COOK_PROPBAND>",
        f"\t<COOK_RAMP>{int(state.control.cook_ramp)}</COOK_RAMP>",
        f"\t<FAN_SHORTED>{1 if state.fan_shorted else 0}</FAN_SHORTED>",
        "</nutcstatus>",
    ]
    return "\n".join(lines) + "\n"
