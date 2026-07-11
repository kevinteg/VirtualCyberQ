# SPDX-License-Identifier: BSD-3-Clause
"""Firmware personas: per-version wire format + behavior (DESIGN 14.3).

A real CyberQ WiFi's exact HTTP/XML output and a couple of control behaviors vary
by firmware version. A :class:`Persona` bundles those differences so the emulator
can impersonate a specific firmware, and the user can choose which one to run.

Only **firmware 1.7** is byte-verified here (captured from a real unit on
2026-07-10); the 2.3 / 3.1 personas encode the *documented* behavioral difference
(SHUTDOWN turns the blower off instead of dropping the setpoint to 32 degF) and
otherwise reuse the 1.7 wire format until a real capture of those versions lands.

This module is framework-agnostic core: it imports no web framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "DEFAULT_PERSONA",
    "PERSONAS",
    "CyberQClassicWire",
    "Persona",
    "WireFormat",
    "get_persona",
    "persona_choices",
    "persona_names",
]


@dataclass(frozen=True)
class WireFormat:
    """The exact byte-level shape of the device's XML feeds + HTTP headers.

    Defaults are the values **verified byte-for-byte against a real firmware-1.7
    unit**: CRLF line endings, 3-space indentation, no trailing newline, the
    ``FAN_SHORTED`` element absent from ``status.xml``, two trailing spaces after
    the second temperature comment, three trailing spaces after ``TIMER_CURR`` in
    ``all.xml`` / ``config.xml`` (but not ``status.xml``), a bare ``text/xml``
    content type, a ``Cache-Control: no-cache`` header, and no ``Server`` header.
    """

    eol: str = "\r\n"
    indent: str = "   "
    trailing_newline: bool = False
    status_fan_shorted: bool = False
    #: Trailing spaces appended after the 2nd temperature comment line.
    comment2_trailing: str = "  "
    #: Trailing spaces appended after ``TIMER_CURR`` in all.xml / config.xml.
    list_timer_trailing: str = "   "
    #: Trailing spaces appended after ``TIMER_CURR`` in status.xml (none observed).
    status_timer_trailing: str = ""
    content_type: str = "text/xml"
    cache_control: str = "no-cache"
    send_server_header: bool = False
    send_content_length: bool = False


#: The classic CyberQ WiFi wire format (verified on firmware 1.7).
CyberQClassicWire = WireFormat()


@dataclass(frozen=True)
class Persona:
    """A selectable firmware persona: its ``FWVER`` string, wire format, behavior.

    Attributes:
        fwver: The ``<FWVER>`` string the device reports.
        label: A human-readable name for menus / ``--help``.
        verified: ``True`` only for firmware whose wire output was captured from
            real hardware; ``False`` marks documented-but-unconfirmed personas.
        shutdown_fan_off: If ``True`` (2.3+), a SHUTDOWN timeout turns the blower
            off; if ``False`` (1.7), it drops ``COOK_SET`` to 32 degF instead.
        notes: Provenance / caveats.
        wire: The :class:`WireFormat` this persona serializes with.
    """

    fwver: str
    label: str
    verified: bool
    shutdown_fan_off: bool
    notes: str = ""
    wire: WireFormat = field(default=CyberQClassicWire)


PERSONAS: dict[str, Persona] = {
    "1.7": Persona(
        fwver="1.7",
        label="CyberQ WiFi firmware 1.7",
        verified=True,
        shutdown_fan_off=False,
        notes=(
            "Byte-verified against a real unit (2026-07-10). SHUTDOWN drops the "
            "pit setpoint to 32 degF (the fire is left to die out)."
        ),
    ),
    "2.3": Persona(
        fwver="2.3",
        label="CyberQ WiFi firmware 2.3",
        verified=False,
        shutdown_fan_off=True,
        notes=(
            "Documented behavior; wire format assumed identical to 1.7 pending a "
            "real capture. SHUTDOWN turns the blower off."
        ),
    ),
    "3.1": Persona(
        fwver="3.1",
        label="CyberQ WiFi firmware 3.1",
        verified=False,
        shutdown_fan_off=True,
        notes=(
            "Documented behavior; wire format assumed identical to 1.7 pending a "
            "real capture. SHUTDOWN turns the blower off."
        ),
    ),
}

#: The default persona (the validated real unit).
DEFAULT_PERSONA = "1.7"

#: Aliases -> canonical persona key (e.g. a web-UI version string to firmware).
_ALIASES = {"2.2": "2.3", "3.0": "3.1"}


def _normalize(fwver: str) -> str:
    """Normalize a firmware string to a canonical persona key."""
    key = fwver.strip()
    return _ALIASES.get(key, key)


def get_persona(fwver: str) -> Persona:
    """Return the :class:`Persona` for ``fwver``, synthesizing a lenient fallback.

    Known firmware strings (and aliases) map to a registered persona. An
    unrecognized string still yields a usable persona -- the classic wire format
    plus a prefix-based behavior guess (``1.x`` -> legacy setpoint SHUTDOWN, else
    fan-off) -- so scenarios and tests may set arbitrary ``FWVER`` values.

    Args:
        fwver: The firmware string, e.g. ``"1.7"`` or ``"3.1"``.

    Returns:
        The matching or synthesized :class:`Persona`.
    """
    key = _normalize(fwver)
    known = PERSONAS.get(key)
    if known is not None:
        return known
    return Persona(
        fwver=fwver,
        label=f"CyberQ (firmware {fwver})",
        verified=False,
        shutdown_fan_off=not fwver.startswith("1."),
        notes="Unrecognized firmware; using the classic wire format + prefix-based behavior.",
    )


def persona_names() -> list[str]:
    """Return the registered persona keys, in a stable order (oldest first)."""
    return list(PERSONAS)


def persona_choices() -> list[tuple[str, str]]:
    """Return ``(fwver, label)`` pairs for the registered personas (for menus)."""
    return [(p.fwver, p.label) for p in PERSONAS.values()]
