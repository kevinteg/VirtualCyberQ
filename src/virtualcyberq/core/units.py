# SPDX-License-Identifier: BSD-3-Clause
"""Unit conversions and the OPEN-probe sentinel (PROTOCOL section 3).

The CyberQ wire format is the single most error-prone part of the API because
it uses a *dual representation*:

* **Read side (XML out):** temperatures are integer *tenths of degF*
  (``3343`` -> 334.3 degF). An open probe serializes to the literal string
  ``OPEN``.
* **Write side (POST in):** temperatures arrive in *whole degF* (``225``),
  optionally with a decimal (``123.5`` meaning 123.5 degF).

This module is the single place those conversions live. Internally the whole
codebase stores temperatures as ``int`` tenths-of-degF, with ``None`` meaning an
open/disconnected probe.
"""

from __future__ import annotations

import re

__all__ = [
    "OPEN",
    "decode_temp",
    "encode_temp",
    "float_to_tenths",
    "hms_to_seconds",
    "parse_input_temp",
    "seconds_to_hms",
    "tenths_to_float",
]

#: The literal sentinel string emitted for an open/disconnected probe.
OPEN = "OPEN"

_HMS_RE = re.compile(r"^\s*(\d{1,2}):([0-5]?\d):([0-5]?\d)\s*$")


def tenths_to_float(tenths: int) -> float:
    """Convert an internal tenths-degF integer to a degF float (``3343`` -> 334.3)."""
    return tenths / 10.0


def float_to_tenths(value: float) -> int:
    """Convert a degF float to internal tenths-degF, rounding to nearest tenth."""
    return round(value * 10.0)


def encode_temp(tenths: int | None) -> str:
    """Serialize an internal temperature to its wire string.

    Args:
        tenths: Temperature in tenths-degF, or ``None`` for an open probe.

    Returns:
        The literal ``OPEN`` for ``None``, otherwise the integer tenths as a
        string (e.g. ``"3343"``).
    """
    if tenths is None:
        return OPEN
    return str(int(tenths))


def decode_temp(raw: str) -> int | None:
    """Parse a wire ``*_TEMP`` value back to internal tenths-degF.

    Mirrors the reference client's robust decode: numeric strings parse to an
    ``int`` tenths value; the ``OPEN`` sentinel (or any non-numeric string)
    yields ``None``.

    Args:
        raw: The raw wire value, e.g. ``"3343"`` or ``"OPEN"``.

    Returns:
        The tenths-degF integer, or ``None`` if the probe is open/unparseable.
    """
    text = raw.strip()
    if not text or text.upper() == OPEN:
        return None
    try:
        return round(float(text))
    except ValueError:
        return None


def parse_input_temp(raw: str | int | float) -> int | None:
    """Parse a POST-side temperature (whole degF, decimal allowed) to tenths.

    Per PROTOCOL 3.2 the browser sends whole degF (``225``) and may send tenths
    with a decimal point (``123.5``). Both map to internal tenths-degF here
    (``225`` -> ``2250``, ``123.5`` -> ``1235``).

    Args:
        raw: The submitted value as a string, int, or float in whole degF.

    Returns:
        The tenths-degF integer, or ``None`` if the value is not a number
        (callers decide whether to ignore or reject).
    """
    if isinstance(raw, bool):  # guard: bool is an int subclass
        return None
    if isinstance(raw, (int, float)):
        return float_to_tenths(float(raw))
    text = raw.strip()
    if not text:
        return None
    try:
        return float_to_tenths(float(text))
    except ValueError:
        return None


def seconds_to_hms(seconds: int) -> str:
    """Format a countdown duration in whole seconds as ``HH:MM:SS``.

    Args:
        seconds: Non-negative duration; negative inputs clamp to zero.

    Returns:
        A zero-padded ``HH:MM:SS`` string (hours are not capped at 99).
    """
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def hms_to_seconds(hms: str) -> int | None:
    """Parse an ``HH:MM:SS`` timer string to whole seconds.

    Accepts the colon-separated form validated by real clients
    (``^(\\d{2}):(\\d{2}):(\\d{2})$``); tolerant of ``%3A`` already decoded to
    ``:`` by the caller.

    Args:
        hms: A ``HH:MM:SS`` string.

    Returns:
        Total seconds, or ``None`` if the string does not match the format.
    """
    match = _HMS_RE.match(hms)
    if match is None:
        return None
    hours, minutes, secs = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + secs
