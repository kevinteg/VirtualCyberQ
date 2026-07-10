# SPDX-License-Identifier: BSD-3-Clause
"""Parse and apply device-plane form POSTs (PROTOCOL sections 2 and 7).

Writes to the real CyberQ are ``application/x-www-form-urlencoded`` POST bodies
(``KEY=value&KEY2=value2&...``) to ``/`` (or a legacy ``*.htm`` page, or the
tolerant ``/status.xml``). This module turns such a body into a list of
``(key, raw_value)`` pairs, validates each through
:func:`virtualcyberq.core.validation.validate_write`, converts temperature
inputs from whole degF to internal tenths-degF via
:mod:`virtualcyberq.core.units`, and applies the accepted writes to the device
state.

Fidelity rules honored (all VERIFIED in PROTOCOL):

* **Unknown / read-only keys are silently ignored** (no error), matching the
  real device.
* **Partial POSTs are legal** -- only the submitted keys change.
* **The ``IGNOREDTAG`` cache-buster** (posted to ``/status.xml`` to force a
  fresh read) is tolerated and ignored.
* **Both ``COOK_TIMER`` and ``_COOK_TIMER`` timer spellings** are accepted; the
  timer's remaining seconds are set from either.

The parser operates on a :class:`~virtualcyberq.core.state.DeviceState`. It
accepts either a simulation object exposing a ``.state`` attribute (the usual
:class:`~virtualcyberq.core.simulation.Simulation` shape) or a bare
``DeviceState`` -- so it is usable before the simulation layer exists.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from urllib.parse import parse_qsl

from virtualcyberq.core.enums import (
    DegUnits,
    OnOff,
    RampSource,
    TimeoutAction,
)
from virtualcyberq.core.state import DeviceState
from virtualcyberq.core.units import float_to_tenths, hms_to_seconds
from virtualcyberq.core.validation import (
    WRITABLE_PARAMS,
    ParamKind,
    WriteMode,
    validate_write,
)

__all__ = ["IGNORED_KEYS", "parse_and_apply", "parse_form_body"]

#: Keys the device accepts on a POST but which drive no state change. The
#: ``IGNOREDTAG`` cache-buster is posted to ``/status.xml`` to force a fresh read
#: (PROTOCOL 2.1); ``REBOOT`` is our reboot-flag placeholder (exact wire key is
#: undocumented -- INFERRED). Both are tolerated and produce no applied write.
IGNORED_KEYS = frozenset({"IGNOREDTAG", "REBOOT"})


def parse_form_body(body: str) -> list[tuple[str, str]]:
    """Parse an ``x-www-form-urlencoded`` body into ``(key, value)`` pairs.

    URL-decodes keys and values (``+`` -> space, ``%3A`` -> ``:``), preserves
    submission order, keeps duplicate keys (last-wins is left to the caller), and
    tolerates blank values and stray ``&`` separators.

    Args:
        body: The raw request body (may be empty).

    Returns:
        A list of decoded ``(key, value)`` tuples in submission order.
    """
    if not body:
        return []
    return parse_qsl(body, keep_blank_values=True)


def _resolve_state(sim: object) -> DeviceState:
    """Return the :class:`DeviceState` to mutate from ``sim``.

    Accepts a simulation-like object with a ``.state`` attribute, or a bare
    :class:`DeviceState`.

    Raises:
        TypeError: If no ``DeviceState`` can be resolved from ``sim``.
    """
    if isinstance(sim, DeviceState):
        return sim
    state = getattr(sim, "state", None)
    if isinstance(state, DeviceState):
        return state
    raise TypeError(
        "parse_and_apply requires a Simulation with a .state DeviceState or a DeviceState instance"
    )


def _probe_for(key: str, state: DeviceState) -> object:
    """Return the probe object owning a ``*_NAME`` / ``*_SET`` key."""
    prefix = key.split("_", 1)[0]
    return {
        "COOK": state.cook,
        "FOOD1": state.food1,
        "FOOD2": state.food2,
        "FOOD3": state.food3,
    }[prefix]


def _apply_temp_setpoint(key: str, whole_degf: float, state: DeviceState) -> None:
    """Apply a ``*_SET`` / ``COOKHOLD`` / ``ALARMDEV`` / ``PROPBAND`` write.

    ``value`` arrives as whole degF, possibly with a decimal (the device accepts
    e.g. ``123.5``); it is converted to internal tenths-degF before storage, so
    the decimal is preserved to tenths resolution rather than truncated.
    """
    tenths = float_to_tenths(float(whole_degf))
    if key.endswith("_SET"):
        _probe_for(key, state).set = tenths  # type: ignore[attr-defined]
    elif key == "COOKHOLD":
        state.control.cookhold = tenths
    elif key == "ALARMDEV":
        state.control.alarmdev = tenths
    elif key == "PROPBAND":
        state.control.propband = tenths


def _apply_name(key: str, value: str, state: DeviceState) -> None:
    """Apply a ``*_NAME`` string write to the owning probe."""
    _probe_for(key, state).name = value  # type: ignore[attr-defined]


def _apply_timer(value: str, state: DeviceState) -> None:
    """Apply a ``COOK_TIMER`` / ``_COOK_TIMER`` ``HH:MM:SS`` write."""
    seconds = hms_to_seconds(value)
    if seconds is None:  # defensive: validation already checked the format
        return
    state.timer.remaining_s = seconds
    state.timer.running = seconds > 0


# --- Direct scalar setters for the remaining writable keys -------------------
def _set_timeout_action(v: int, s: DeviceState) -> None:
    s.control.timeout_action = TimeoutAction(v)


def _set_cook_ramp(v: int, s: DeviceState) -> None:
    s.control.cook_ramp = RampSource(v)


def _set_opendetect(v: int, s: DeviceState) -> None:
    s.control.opendetect = OnOff(v)


def _set_cyctime(v: int, s: DeviceState) -> None:
    s.control.cyctime = v


def _set_menu_scrolling(v: int, s: DeviceState) -> None:
    s.system.menu_scrolling = OnOff(v)


def _set_lcd_backlight(v: int, s: DeviceState) -> None:
    s.system.lcd_backlight = v


def _set_lcd_contrast(v: int, s: DeviceState) -> None:
    s.system.lcd_contrast = v


def _set_deg_units(v: int, s: DeviceState) -> None:
    s.system.deg_units = DegUnits(v)


def _set_alarm_beeps(v: int, s: DeviceState) -> None:
    s.system.alarm_beeps = v


def _set_key_beeps(v: int, s: DeviceState) -> None:
    s.system.key_beeps = OnOff(v)


#: Setters for the non-probe INT/ENUM canonical keys (value already coerced).
_SCALAR_SETTERS: dict[str, Callable[[int, DeviceState], None]] = {
    "TIMEOUT_ACTION": _set_timeout_action,
    "COOK_RAMP": _set_cook_ramp,
    "OPENDETECT": _set_opendetect,
    "CYCTIME": _set_cyctime,
    "MENU_SCROLLING": _set_menu_scrolling,
    "LCD_BACKLIGHT": _set_lcd_backlight,
    "LCD_CONTRAST": _set_lcd_contrast,
    "DEG_UNITS": _set_deg_units,
    "ALARM_BEEPS": _set_alarm_beeps,
    "KEY_BEEPS": _set_key_beeps,
}

#: WIFI string/enum/int keys -> the ``WifiConfig`` attribute they write.
_WIFI_ATTR: dict[str, str] = {
    "IP": "ip",
    "NM": "nm",
    "GW": "gw",
    "DNS": "dns",
    "WIFIMODE": "wifimode",
    "DHCP": "dhcp",
    "SSID": "ssid",
    "WIFI_ENC": "wifi_enc",
    "WIFI_KEY": "wifi_key",
    "HTTP_PORT": "http_port",
}

#: SMTP keys -> the ``SmtpConfig`` attribute they write.
_SMTP_ATTR: dict[str, str] = {
    "SMTP_HOST": "host",
    "SMTP_PORT": "port",
    "SMTP_USER": "user",
    "SMTP_PWD": "pwd",
    "SMTP_TO": "to",
    "SMTP_FROM": "frm",
    "SMTP_SUBJ": "subj",
    "SMTP_ALERT": "alert",
}


def _apply_one(key: str, value: object, state: DeviceState) -> None:
    """Apply one already-validated ``(key, value)`` to ``state``.

    ``value`` is the coerced value from validation: whole-degF ``float`` for
    temperatures (a decimal like ``123.5`` is preserved), ``int`` for INT/ENUM,
    ``str`` for strings and timers.
    """
    spec = WRITABLE_PARAMS[key]
    if spec.kind is ParamKind.TEMP_F:
        _apply_temp_setpoint(key, cast("float", value), state)
        return
    if spec.kind is ParamKind.TIMER:
        _apply_timer(str(value), state)
        return
    if key.endswith("_NAME"):
        _apply_name(key, str(value), state)
        return
    if key in _SCALAR_SETTERS:
        _SCALAR_SETTERS[key](int(cast("float", value)), state)
        return
    if key in _WIFI_ATTR:
        setattr(state.wifi, _WIFI_ATTR[key], value)
        return
    if key in _SMTP_ATTR:
        setattr(state.smtp, _SMTP_ATTR[key], value)
        return


def parse_and_apply(
    sim: object, body: str, mode: WriteMode = WriteMode.LENIENT
) -> list[tuple[str, object]]:
    """Parse a POST body, validate every field, and apply accepted writes.

    Unknown keys, read-only keys, and the ``IGNOREDTAG`` cache-buster are
    silently ignored (fidelity). Temperature inputs (whole degF) are converted to
    internal tenths-degF before storage. Duplicate keys are last-wins.

    Args:
        sim: A simulation object with a ``.state`` :class:`DeviceState`, or a
            bare :class:`DeviceState`.
        body: The raw ``x-www-form-urlencoded`` request body.
        mode: Validation policy; :attr:`WriteMode.LENIENT` (default) clamps
            out-of-range numbers, :attr:`WriteMode.STRICT` rejects them.

    Returns:
        The list of applied ``(key, value)`` pairs in submission order, where
        ``value`` is the coerced value that was stored (whole-degF ``int`` for
        temperatures, matching the validation convention). Ignored/rejected keys
        do not appear.
    """
    state = _resolve_state(sim)
    applied: list[tuple[str, object]] = []
    for key, raw in parse_form_body(body):
        if key in IGNORED_KEYS:
            continue
        result = validate_write(key, raw, mode)
        if not result.accepted:
            continue
        _apply_one(key, result.value, state)
        applied.append((key, result.value))
    return applied
