# SPDX-License-Identifier: BSD-3-Clause
"""Render ``status.xml`` -- the fast ``<nutcstatus>`` live-status feed.

This is the volatile-only feed the real device's web UI AJAX-polls ~1/sec
(PROTOCOL section 4). It is a flat document (no nested containers) whose root
element is ``<nutcstatus>``. Every temperature is emitted as integer
tenths-of-degF, an open probe as the literal string ``OPEN``, and each
``*_STATUS`` as the shared 0..7 status integer.

The document opens with ``<nutcstatus>`` and then the device's verbatim two-line
temperature comment block -- the comments live *inside* the root element, indented
like the data (3 spaces). Aligned to a captured real v1.7 unit; note it does NOT
emit a ``FAN_SHORTED`` element on this firmware.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms

__all__ = ["INDENT", "TEMP_COMMENT_BLOCK", "TEMP_COMMENT_LINES", "render_status"]

#: The device indents 3 spaces per level (6 spaces for nested probe children).
INDENT = "   "

#: The verbatim two-line temperature-comment block the device emits *inside* every
#: feed's root element (PROTOCOL section 3) -- note the double space after "in F."
#: on the second line.
TEMP_COMMENT_LINES = (
    "<!--all temperatures are displayed in tenths F, regardless of setting of unit-->",
    "<!--all temperatures sent by browser to unit should be in F.  "
    "you can send tenths F with a decimal place, ex: 123.5-->",
)

#: The temperature comment block joined as one string (kept for callers/tests).
TEMP_COMMENT_BLOCK = "\n".join(TEMP_COMMENT_LINES)


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

    i = INDENT
    lines = ["<nutcstatus>", *(i + c for c in TEMP_COMMENT_LINES)]
    lines += [
        f"{i}<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"{i}<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>",
        f"{i}<COOK_TEMP>{_probe_temp(cook)}</COOK_TEMP>",
        f"{i}<FOOD1_TEMP>{_probe_temp(food1)}</FOOD1_TEMP>",
        f"{i}<FOOD2_TEMP>{_probe_temp(food2)}</FOOD2_TEMP>",
        f"{i}<FOOD3_TEMP>{_probe_temp(food3)}</FOOD3_TEMP>",
        f"{i}<COOK_STATUS>{_probe_status(cook)}</COOK_STATUS>",
        f"{i}<FOOD1_STATUS>{_probe_status(food1)}</FOOD1_STATUS>",
        f"{i}<FOOD2_STATUS>{_probe_status(food2)}</FOOD2_STATUS>",
        f"{i}<FOOD3_STATUS>{_probe_status(food3)}</FOOD3_STATUS>",
        f"{i}<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
        f"{i}<DEG_UNITS>{int(state.system.deg_units)}</DEG_UNITS>",
        f"{i}<COOK_CYCTIME>{int(state.control.cyctime)}</COOK_CYCTIME>",
        f"{i}<COOK_PROPBAND>{int(state.control.propband)}</COOK_PROPBAND>",
        f"{i}<COOK_RAMP>{int(state.control.cook_ramp)}</COOK_RAMP>",
        "</nutcstatus>",
    ]
    return "\n".join(lines) + "\n"
