# SPDX-License-Identifier: BSD-3-Clause
"""Render ``config.xml`` -- the ``<nutcallstatus>`` superset with config blocks.

``config.xml`` (PROTOCOL section 6) is a superset of ``all.xml``: inside the root
it opens with a ``this is similar to all.xml`` comment and the two-line
temperature comment block, then the same four probe containers and volatile
status siblings, **plus** the four config blocks (``<SYSTEM>``, ``<CONTROL>``,
``<WIFI>``, ``<SMTP>``) and the read-only ``<FWVER>`` firmware string. Inside
``<WIFI>`` the read-only ``<MAC>`` sits right after ``<SSID>`` (real-unit order).
Byte-shape (CRLF, indentation, ``TIMER_CURR`` trailing spaces) comes from the
selected firmware persona.

Temperatures/setpoints/bands stay tenths-degF on read-back; ``ALARMDEV``,
``COOKHOLD`` and ``PROPBAND`` in the ``<CONTROL>`` block are tenths on the wire
even though they are written in whole degF.
"""

from __future__ import annotations

from virtualcyberq.core.personas import get_persona
from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import _comment_lines, _finish, _probe_status, _probe_temp

__all__ = ["render_config"]

#: The config.xml-specific lead comment (precedes the shared temperature block).
_CONFIG_LEAD_COMMENT = "<!--this is similar to all.xml, but with more values-->"


def _container(tag: str, probe: ProbeState, i: str) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines."""
    return [
        f"{i}<{tag}>",
        f"{i}{i}<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"{i}{i}<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"{i}{i}<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"{i}{i}<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"{i}</{tag}>",
    ]


def _system_block(state: DeviceState, i: str) -> list[str]:
    """Render the ``<SYSTEM>`` config block."""
    sys = state.system
    ii = i + i
    return [
        f"{i}<SYSTEM>",
        f"{ii}<MENU_SCROLLING>{int(sys.menu_scrolling)}</MENU_SCROLLING>",
        f"{ii}<LCD_BACKLIGHT>{int(sys.lcd_backlight)}</LCD_BACKLIGHT>",
        f"{ii}<LCD_CONTRAST>{int(sys.lcd_contrast)}</LCD_CONTRAST>",
        f"{ii}<DEG_UNITS>{int(sys.deg_units)}</DEG_UNITS>",
        f"{ii}<ALARM_BEEPS>{int(sys.alarm_beeps)}</ALARM_BEEPS>",
        f"{ii}<KEY_BEEPS>{int(sys.key_beeps)}</KEY_BEEPS>",
        f"{i}</SYSTEM>",
    ]


def _control_block(state: DeviceState, i: str) -> list[str]:
    """Render the ``<CONTROL>`` config block (bands are tenths-degF)."""
    ctl = state.control
    ii = i + i
    return [
        f"{i}<CONTROL>",
        f"{ii}<TIMEOUT_ACTION>{int(ctl.timeout_action)}</TIMEOUT_ACTION>",
        f"{ii}<COOKHOLD>{int(ctl.cookhold)}</COOKHOLD>",
        f"{ii}<ALARMDEV>{int(ctl.alarmdev)}</ALARMDEV>",
        f"{ii}<COOK_RAMP>{int(ctl.cook_ramp)}</COOK_RAMP>",
        f"{ii}<OPENDETECT>{int(ctl.opendetect)}</OPENDETECT>",
        f"{ii}<CYCTIME>{int(ctl.cyctime)}</CYCTIME>",
        f"{ii}<PROPBAND>{int(ctl.propband)}</PROPBAND>",
        f"{i}</CONTROL>",
    ]


def _wifi_block(state: DeviceState, i: str) -> list[str]:
    """Render the ``<WIFI>`` config block (read-only ``MAC`` right after ``SSID``)."""
    wifi = state.wifi
    ii = i + i
    return [
        f"{i}<WIFI>",
        f"{ii}<IP>{wifi.ip}</IP>",
        f"{ii}<NM>{wifi.nm}</NM>",
        f"{ii}<GW>{wifi.gw}</GW>",
        f"{ii}<DNS>{wifi.dns}</DNS>",
        f"{ii}<WIFIMODE>{int(wifi.wifimode)}</WIFIMODE>",
        f"{ii}<DHCP>{int(wifi.dhcp)}</DHCP>",
        f"{ii}<SSID>{wifi.ssid}</SSID>",
        f"{ii}<MAC>{wifi.mac}</MAC>",
        f"{ii}<WIFI_ENC>{int(wifi.wifi_enc)}</WIFI_ENC>",
        f"{ii}<WIFI_KEY>{wifi.wifi_key}</WIFI_KEY>",
        f"{ii}<HTTP_PORT>{int(wifi.http_port)}</HTTP_PORT>",
        f"{i}</WIFI>",
    ]


def _smtp_block(state: DeviceState, i: str) -> list[str]:
    """Render the ``<SMTP>`` config block."""
    smtp = state.smtp
    ii = i + i
    return [
        f"{i}<SMTP>",
        f"{ii}<SMTP_HOST>{smtp.host}</SMTP_HOST>",
        f"{ii}<SMTP_PORT>{int(smtp.port)}</SMTP_PORT>",
        f"{ii}<SMTP_USER>{smtp.user}</SMTP_USER>",
        f"{ii}<SMTP_PWD>{smtp.pwd}</SMTP_PWD>",
        f"{ii}<SMTP_TO>{smtp.to}</SMTP_TO>",
        f"{ii}<SMTP_FROM>{smtp.frm}</SMTP_FROM>",
        f"{ii}<SMTP_SUBJ>{smtp.subj}</SMTP_SUBJ>",
        f"{ii}<SMTP_ALERT>{int(smtp.alert)}</SMTP_ALERT>",
        f"{i}</SMTP>",
    ]


def render_config(state: DeviceState) -> str:
    """Render the ``config.xml`` document for ``state`` (per its firmware persona)."""
    wire = get_persona(state.fwver).wire
    i = wire.indent
    lines = ["<nutcallstatus>", *_comment_lines(_CONFIG_LEAD_COMMENT, wire)]
    lines += _container("COOK", state.cook, i)
    lines += _container("FOOD1", state.food1, i)
    lines += _container("FOOD2", state.food2, i)
    lines += _container("FOOD3", state.food3, i)
    lines += [
        f"{i}<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"{i}<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>"
        f"{wire.list_timer_trailing}",
        f"{i}<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
    ]
    lines += _system_block(state, i)
    lines += _control_block(state, i)
    lines += _wifi_block(state, i)
    lines += _smtp_block(state, i)
    lines += [
        f"{i}<FWVER>{state.fwver}</FWVER>",
        "</nutcallstatus>",
    ]
    return _finish(lines, wire)
