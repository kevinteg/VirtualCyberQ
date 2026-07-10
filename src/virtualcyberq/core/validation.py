# SPDX-License-Identifier: BSD-3-Clause
"""Writable-parameter allow-list, ranges, and clamp/reject policy.

Implements PROTOCOL section 7: the canonical 23-key writable allow-list plus the
WIFI/SMTP keys, per-key value ranges, the read-only key set, and the
lenient-vs-strict write policy.

* **Lenient mode (default, matches real firmware):** out-of-range numeric values
  are *clamped*, unknown/read-only keys are *silently ignored*. The real device
  gives no structured error, so neither do we.
* **Strict mode:** out-of-range and unknown/read-only writes are *rejected* with
  a reason (for negative-path testing).

This module validates the *shape and range* of a value; it does not itself
mutate device state. Temperatures here are validated in **whole degF** (POST
input convention); callers convert to internal tenths-degF with
:mod:`virtualcyberq.core.units`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "CANONICAL_23_KEYS",
    "READONLY_KEYS",
    "SMTP_KEYS",
    "WIFI_KEYS",
    "WRITABLE_PARAMS",
    "ParamKind",
    "ParamSpec",
    "ValidationResult",
    "WriteMode",
    "is_readonly",
    "is_writable",
    "validate_write",
]


class WriteMode(str, Enum):
    """Write policy for out-of-range / unknown keys."""

    LENIENT = "lenient"
    STRICT = "strict"


class ParamKind(str, Enum):
    """The value domain of a writable parameter."""

    STRING = "string"  # free text, length-limited
    INT = "int"  # plain integer in a range
    ENUM = "enum"  # integer restricted to a discrete set
    TEMP_F = "temp_f"  # temperature in whole degF (input side)
    TIMER = "timer"  # HH:MM:SS string


@dataclass(frozen=True)
class ParamSpec:
    """Validation spec for one writable POST key.

    Attributes:
        key: The on-wire POST key (e.g. ``"COOK_SET"``).
        kind: The value domain (:class:`ParamKind`).
        lo: Minimum allowed value for numeric kinds (inclusive), else ``None``.
        hi: Maximum allowed value for numeric kinds (inclusive), else ``None``.
        max_len: Maximum string length for ``STRING`` kinds, else ``None``.
        choices: Allowed integers for ``ENUM`` kinds, else ``None``.
    """

    key: str
    kind: ParamKind
    lo: float | None = None
    hi: float | None = None
    max_len: int | None = None
    choices: tuple[int, ...] | None = None


# --- Ranges (input side; temperatures in whole degF) ------------------------
_TEMP_LO = 32.0
_TEMP_HI = 475.0
_NAME_MAX = 16

# --- The canonical 23-key writable allow-list (PROTOCOL 7.1) ----------------
_CANONICAL_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("COOK_NAME", ParamKind.STRING, max_len=_NAME_MAX),
    ParamSpec("COOK_SET", ParamKind.TEMP_F, lo=_TEMP_LO, hi=_TEMP_HI),
    ParamSpec("FOOD1_NAME", ParamKind.STRING, max_len=_NAME_MAX),
    ParamSpec("FOOD1_SET", ParamKind.TEMP_F, lo=_TEMP_LO, hi=_TEMP_HI),
    ParamSpec("FOOD2_NAME", ParamKind.STRING, max_len=_NAME_MAX),
    ParamSpec("FOOD2_SET", ParamKind.TEMP_F, lo=_TEMP_LO, hi=_TEMP_HI),
    ParamSpec("FOOD3_NAME", ParamKind.STRING, max_len=_NAME_MAX),
    ParamSpec("FOOD3_SET", ParamKind.TEMP_F, lo=_TEMP_LO, hi=_TEMP_HI),
    ParamSpec("_COOK_TIMER", ParamKind.TIMER),
    ParamSpec("COOK_TIMER", ParamKind.TIMER),
    ParamSpec("COOKHOLD", ParamKind.TEMP_F, lo=_TEMP_LO, hi=_TEMP_HI),
    ParamSpec("TIMEOUT_ACTION", ParamKind.ENUM, choices=(0, 1, 2, 3)),
    ParamSpec("ALARMDEV", ParamKind.TEMP_F, lo=10.0, hi=100.0),
    ParamSpec("COOK_RAMP", ParamKind.ENUM, choices=(0, 1, 2, 3)),
    ParamSpec("OPENDETECT", ParamKind.ENUM, choices=(0, 1)),
    ParamSpec("CYCTIME", ParamKind.INT, lo=4, hi=10),
    ParamSpec("PROPBAND", ParamKind.TEMP_F, lo=5.0, hi=100.0),
    ParamSpec("MENU_SCROLLING", ParamKind.ENUM, choices=(0, 1)),
    ParamSpec("LCD_BACKLIGHT", ParamKind.INT, lo=0, hi=100),
    ParamSpec("LCD_CONTRAST", ParamKind.INT, lo=0, hi=100),
    ParamSpec("DEG_UNITS", ParamKind.ENUM, choices=(0, 1)),
    ParamSpec("ALARM_BEEPS", ParamKind.INT, lo=0, hi=5),
    ParamSpec("KEY_BEEPS", ParamKind.ENUM, choices=(0, 1)),
)

# --- WIFI / SMTP writable keys (PROTOCOL 7.2) -------------------------------
_WIFI_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("IP", ParamKind.STRING, max_len=15),
    ParamSpec("NM", ParamKind.STRING, max_len=15),
    ParamSpec("GW", ParamKind.STRING, max_len=15),
    ParamSpec("DNS", ParamKind.STRING, max_len=15),
    ParamSpec("WIFIMODE", ParamKind.ENUM, choices=(0, 1)),
    ParamSpec("DHCP", ParamKind.ENUM, choices=(0, 1)),
    ParamSpec("SSID", ParamKind.STRING, max_len=32),
    ParamSpec("WIFI_ENC", ParamKind.ENUM, choices=(0, 1, 2, 3, 4, 5, 6)),
    ParamSpec("WIFI_KEY", ParamKind.STRING, max_len=64),
    ParamSpec("HTTP_PORT", ParamKind.INT, lo=1, hi=65535),
)

_SMTP_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("SMTP_HOST", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_PORT", ParamKind.INT, lo=0, hi=65535),
    ParamSpec("SMTP_USER", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_PWD", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_TO", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_FROM", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_SUBJ", ParamKind.STRING, max_len=64),
    ParamSpec("SMTP_ALERT", ParamKind.INT, lo=0, hi=1440),
)

#: All writable params keyed by wire key.
WRITABLE_PARAMS: dict[str, ParamSpec] = {
    spec.key: spec for spec in (*_CANONICAL_SPECS, *_WIFI_SPECS, *_SMTP_SPECS)
}

#: The 23 canonical writable keys, in catalog order.
CANONICAL_23_KEYS: tuple[str, ...] = tuple(spec.key for spec in _CANONICAL_SPECS)

#: The WIFI writable keys.
WIFI_KEYS: tuple[str, ...] = tuple(spec.key for spec in _WIFI_SPECS)

#: The SMTP writable keys.
SMTP_KEYS: tuple[str, ...] = tuple(spec.key for spec in _SMTP_SPECS)

#: Read-only keys that must never be settable (PROTOCOL 7.3).
READONLY_KEYS: set[str] = {
    "OUTPUT_PERCENT",
    "TIMER_CURR",
    "COOK_TEMP",
    "FOOD1_TEMP",
    "FOOD2_TEMP",
    "FOOD3_TEMP",
    "COOK_STATUS",
    "FOOD1_STATUS",
    "FOOD2_STATUS",
    "FOOD3_STATUS",
    "TIMER_STATUS",
    "FAN_SHORTED",
    "FAN_SHORT",
    "FWVER",
    "MAC",
}


def is_writable(key: str) -> bool:
    """Return ``True`` if ``key`` is in the writable allow-list."""
    return key in WRITABLE_PARAMS


def is_readonly(key: str) -> bool:
    """Return ``True`` if ``key`` is a known read-only element."""
    return key in READONLY_KEYS


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one write.

    Attributes:
        key: The submitted key.
        accepted: Whether the write should be applied.
        value: The coerced value to apply when ``accepted`` (an ``int`` in whole
            degF for temperatures, an ``int`` for INT/ENUM, a ``str`` for strings
            and timers), else ``None``.
        clamped: Whether a numeric value was clamped to range (lenient mode).
        reason: A human-readable explanation when rejected, else ``None``.
    """

    key: str
    accepted: bool
    value: object | None = None
    clamped: bool = False
    reason: str | None = None


def _to_number(raw: object) -> float | None:
    """Coerce ``raw`` to a float, or ``None`` if it is not numeric."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _validate_numeric(spec: ParamSpec, raw: object, mode: WriteMode) -> ValidationResult:
    """Validate INT / TEMP_F kinds, clamping (lenient) or rejecting (strict)."""
    num = _to_number(raw)
    if num is None:
        if mode is WriteMode.STRICT:
            return ValidationResult(spec.key, False, reason="not a number")
        return ValidationResult(spec.key, False, reason="not a number")
    lo, hi = spec.lo, spec.hi
    clamped = False
    if lo is not None and num < lo:
        if mode is WriteMode.STRICT:
            return ValidationResult(spec.key, False, reason=f"below minimum {lo}")
        num = lo
        clamped = True
    if hi is not None and num > hi:
        if mode is WriteMode.STRICT:
            return ValidationResult(spec.key, False, reason=f"above maximum {hi}")
        num = hi
        clamped = True
    # INT coerces to a plain int; TEMP_F keeps the whole-degF float so a decimal
    # input (e.g. 123.5, which the device accepts) survives the later tenths conversion.
    value: object = round(num) if spec.kind is ParamKind.INT else num
    return ValidationResult(spec.key, True, value=value, clamped=clamped)


def _validate_enum(spec: ParamSpec, raw: object, mode: WriteMode) -> ValidationResult:
    """Validate an ENUM kind against its allowed integer set."""
    num = _to_number(raw)
    choices = spec.choices or ()
    if num is None or int(num) != num:
        return ValidationResult(spec.key, False, reason="not an integer")
    ivalue = int(num)
    if ivalue not in choices:
        if mode is WriteMode.STRICT:
            return ValidationResult(spec.key, False, reason=f"not one of {choices}")
        return ValidationResult(spec.key, False, reason=f"not one of {choices}")
    return ValidationResult(spec.key, True, value=ivalue)


def _validate_string(spec: ParamSpec, raw: object, mode: WriteMode) -> ValidationResult:
    """Validate a STRING kind, truncating (lenient) or rejecting (strict)."""
    text = raw if isinstance(raw, str) else str(raw)
    max_len = spec.max_len
    clamped = False
    if max_len is not None and len(text) > max_len:
        if mode is WriteMode.STRICT:
            return ValidationResult(spec.key, False, reason=f"exceeds max length {max_len}")
        text = text[:max_len]
        clamped = True
    return ValidationResult(spec.key, True, value=text, clamped=clamped)


def _validate_timer(spec: ParamSpec, raw: object) -> ValidationResult:
    """Validate an HH:MM:SS timer string (colons may be raw or URL-decoded)."""
    from virtualcyberq.core.units import hms_to_seconds

    text = raw if isinstance(raw, str) else str(raw)
    if hms_to_seconds(text.strip()) is None:
        return ValidationResult(spec.key, False, reason="not HH:MM:SS")
    return ValidationResult(spec.key, True, value=text.strip())


def validate_write(key: str, raw: object, mode: WriteMode = WriteMode.LENIENT) -> ValidationResult:
    """Validate a single ``key=value`` write against the allow-list and ranges.

    Args:
        key: The submitted POST key.
        raw: The submitted value (string from a form, or a pre-coerced number).
        mode: :attr:`WriteMode.LENIENT` (clamp/ignore) or
            :attr:`WriteMode.STRICT` (reject).

    Returns:
        A :class:`ValidationResult`. When ``accepted`` is ``True``, ``value``
        holds the coerced value to apply (temperatures in whole degF; convert to
        tenths via :mod:`virtualcyberq.core.units`).
    """
    if key in READONLY_KEYS:
        return ValidationResult(key, False, reason="read-only key")
    spec = WRITABLE_PARAMS.get(key)
    if spec is None:
        return ValidationResult(key, False, reason="unknown key")
    if spec.kind in (ParamKind.INT, ParamKind.TEMP_F):
        return _validate_numeric(spec, raw, mode)
    if spec.kind is ParamKind.ENUM:
        return _validate_enum(spec, raw, mode)
    if spec.kind is ParamKind.STRING:
        return _validate_string(spec, raw, mode)
    if spec.kind is ParamKind.TIMER:
        return _validate_timer(spec, raw)
    return ValidationResult(key, False, reason="unhandled kind")
