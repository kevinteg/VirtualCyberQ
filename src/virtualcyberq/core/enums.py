# SPDX-License-Identifier: BSD-3-Clause
"""On-wire enumerations for the CyberQ WiFi protocol.

Every integer value in these enums is the exact code the physical device emits
on the wire (see ``docs/CYBERQ_PROTOCOL.md`` section 8 and ``docs/DESIGN.md``
Appendix A). Do not renumber: clients navigate by these integers.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "DegUnits",
    "Dhcp",
    "OnOff",
    "RampSource",
    "StatusCode",
    "TimeoutAction",
    "WifiEnc",
    "WifiMode",
]


class StatusCode(IntEnum):
    """Shared status enum used by every ``*_STATUS`` element (PROTOCOL 8.1)."""

    OK = 0
    HIGH = 1
    LOW = 2
    DONE = 3
    ERROR = 4
    HOLD = 5
    ALARM = 6
    SHUTDOWN = 7


class RampSource(IntEnum):
    """``COOK_RAMP`` selector: which food probe drives cook-and-hold (8.3)."""

    OFF = 0
    FOOD1 = 1
    FOOD2 = 2
    FOOD3 = 3


class TimeoutAction(IntEnum):
    """``TIMEOUT_ACTION``: what happens when the cook timer expires (8.4)."""

    NO_ACTION = 0
    HOLD = 1
    ALARM = 2
    SHUTDOWN = 3


class DegUnits(IntEnum):
    """``DEG_UNITS``: LCD display unit. Wire temps stay tenths-degF regardless."""

    CELSIUS = 0
    FAHRENHEIT = 1


class OnOff(IntEnum):
    """Generic 0/1 boolean enum (OPENDETECT, MENU_SCROLLING, KEY_BEEPS)."""

    OFF = 0
    ON = 1


class WifiMode(IntEnum):
    """``WIFIMODE`` radio mode (INFERRED map, PROTOCOL 8.6; default 0)."""

    INFRASTRUCTURE = 0
    ADHOC = 1


class Dhcp(IntEnum):
    """``DHCP`` static/dynamic addressing (INFERRED map, 8.6; default 0)."""

    OFF = 0
    ON = 1


class WifiEnc(IntEnum):
    """``WIFI_ENC`` encryption type (INFERRED map, PROTOCOL 8.6; default 6)."""

    NONE = 0
    WEP64 = 1
    WEP128 = 2
    WPA_TKIP = 3
    WPA_AES = 4
    WPA2_TKIP = 5
    WPA2_AES = 6
