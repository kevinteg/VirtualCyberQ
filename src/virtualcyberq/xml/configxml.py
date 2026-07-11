# SPDX-License-Identifier: BSD-3-Clause
"""Render ``config.xml`` -- the ``<nutcallstatus>`` superset with config blocks.

``config.xml`` (PROTOCOL section 6) is a superset of ``all.xml``: inside the root
it opens with a ``this is similar to all.xml`` comment and the two-line
temperature comment block, then the same four probe containers and volatile
status siblings, **plus** the four config blocks (``<SYSTEM>``, ``<CONTROL>``,
``<WIFI>``, ``<SMTP>``) and the read-only ``<FWVER>`` firmware string. Inside
``<WIFI>`` the read-only ``<MAC>`` sits right after ``<SSID>`` (real-unit order).

Temperatures/setpoints/bands stay tenths-degF on read-back; ``ALARMDEV``,
``COOKHOLD`` and ``PROPBAND`` in the ``<CONTROL>`` block are tenths on the wire
even though they are written in whole degF.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import INDENT, TEMP_COMMENT_LINES, _probe_status, _probe_temp

__all__ = ["render_config"]

#: The config.xml-specific lead comment (precedes the shared temperature block).
_CONFIG_LEAD_COMMENT = "<!--this is similar to all.xml, but with more values-->"

_I = INDENT
_II = INDENT * 2


def _container(tag: str, probe: ProbeState) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines."""
    return [
        f"{_I}<{tag}>",
        f"{_II}<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"{_II}<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"{_II}<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"{_II}<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"{_I}</{tag}>",
    ]


def _system_block(state: DeviceState) -> list[str]:
    """Render the ``<SYSTEM>`` config block."""
    sys = state.system
    return [
        f"{_I}<SYSTEM>",
        f"{_II}<MENU_SCROLLING>{int(sys.menu_scrolling)}</MENU_SCROLLING>",
        f"{_II}<LCD_BACKLIGHT>{int(sys.lcd_backlight)}</LCD_BACKLIGHT>",
        f"{_II}<LCD_CONTRAST>{int(sys.lcd_contrast)}</LCD_CONTRAST>",
        f"{_II}<DEG_UNITS>{int(sys.deg_units)}</DEG_UNITS>",
        f"{_II}<ALARM_BEEPS>{int(sys.alarm_beeps)}</ALARM_BEEPS>",
        f"{_II}<KEY_BEEPS>{int(sys.key_beeps)}</KEY_BEEPS>",
        f"{_I}</SYSTEM>",
    ]


def _control_block(state: DeviceState) -> list[str]:
    """Render the ``<CONTROL>`` config block (bands are tenths-degF)."""
    ctl = state.control
    return [
        f"{_I}<CONTROL>",
        f"{_II}<TIMEOUT_ACTION>{int(ctl.timeout_action)}</TIMEOUT_ACTION>",
        f"{_II}<COOKHOLD>{int(ctl.cookhold)}</COOKHOLD>",
        f"{_II}<ALARMDEV>{int(ctl.alarmdev)}</ALARMDEV>",
        f"{_II}<COOK_RAMP>{int(ctl.cook_ramp)}</COOK_RAMP>",
        f"{_II}<OPENDETECT>{int(ctl.opendetect)}</OPENDETECT>",
        f"{_II}<CYCTIME>{int(ctl.cyctime)}</CYCTIME>",
        f"{_II}<PROPBAND>{int(ctl.propband)}</PROPBAND>",
        f"{_I}</CONTROL>",
    ]


def _wifi_block(state: DeviceState) -> list[str]:
    """Render the ``<WIFI>`` config block (read-only ``MAC`` right after ``SSID``)."""
    wifi = state.wifi
    return [
        f"{_I}<WIFI>",
        f"{_II}<IP>{wifi.ip}</IP>",
        f"{_II}<NM>{wifi.nm}</NM>",
        f"{_II}<GW>{wifi.gw}</GW>",
        f"{_II}<DNS>{wifi.dns}</DNS>",
        f"{_II}<WIFIMODE>{int(wifi.wifimode)}</WIFIMODE>",
        f"{_II}<DHCP>{int(wifi.dhcp)}</DHCP>",
        f"{_II}<SSID>{wifi.ssid}</SSID>",
        f"{_II}<MAC>{wifi.mac}</MAC>",
        f"{_II}<WIFI_ENC>{int(wifi.wifi_enc)}</WIFI_ENC>",
        f"{_II}<WIFI_KEY>{wifi.wifi_key}</WIFI_KEY>",
        f"{_II}<HTTP_PORT>{int(wifi.http_port)}</HTTP_PORT>",
        f"{_I}</WIFI>",
    ]


def _smtp_block(state: DeviceState) -> list[str]:
    """Render the ``<SMTP>`` config block."""
    smtp = state.smtp
    return [
        f"{_I}<SMTP>",
        f"{_II}<SMTP_HOST>{smtp.host}</SMTP_HOST>",
        f"{_II}<SMTP_PORT>{int(smtp.port)}</SMTP_PORT>",
        f"{_II}<SMTP_USER>{smtp.user}</SMTP_USER>",
        f"{_II}<SMTP_PWD>{smtp.pwd}</SMTP_PWD>",
        f"{_II}<SMTP_TO>{smtp.to}</SMTP_TO>",
        f"{_II}<SMTP_FROM>{smtp.frm}</SMTP_FROM>",
        f"{_II}<SMTP_SUBJ>{smtp.subj}</SMTP_SUBJ>",
        f"{_II}<SMTP_ALERT>{int(smtp.alert)}</SMTP_ALERT>",
        f"{_I}</SMTP>",
    ]


def render_config(state: DeviceState) -> str:
    """Render the ``config.xml`` document for ``state``.

    Args:
        state: The device state to serialize.

    Returns:
        A ``str`` containing the full ``<nutcallstatus>`` superset: the lead +
        temperature comments, the four probe containers, the volatile status
        siblings, then the ``<SYSTEM>``, ``<CONTROL>``, ``<WIFI>``, ``<SMTP>``
        blocks and the ``<FWVER>`` string.
    """
    lines = ["<nutcallstatus>", _I + _CONFIG_LEAD_COMMENT, *(_I + c for c in TEMP_COMMENT_LINES)]
    lines += _container("COOK", state.cook)
    lines += _container("FOOD1", state.food1)
    lines += _container("FOOD2", state.food2)
    lines += _container("FOOD3", state.food3)
    lines += [
        f"{_I}<OUTPUT_PERCENT>{int(state.output_percent)}</OUTPUT_PERCENT>",
        f"{_I}<TIMER_CURR>{seconds_to_hms(state.timer.remaining_s)}</TIMER_CURR>",
        f"{_I}<TIMER_STATUS>{int(state.timer.status)}</TIMER_STATUS>",
    ]
    lines += _system_block(state)
    lines += _control_block(state)
    lines += _wifi_block(state)
    lines += _smtp_block(state)
    lines += [
        f"{_I}<FWVER>{state.fwver}</FWVER>",
        "</nutcallstatus>",
    ]
    return "\n".join(lines) + "\n"
