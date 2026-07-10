# SPDX-License-Identifier: BSD-3-Clause
"""Render ``config.xml`` -- the ``<nutcallstatus>`` superset with config blocks.

``config.xml`` (PROTOCOL section 6) is a superset of ``all.xml``: the same four
probe containers and volatile status/control siblings, **plus** the four config
blocks (``<SYSTEM>``, ``<CONTROL>``, ``<WIFI>``, ``<SMTP>``) and the read-only
``<FWVER>`` firmware string. ``WIFI.MAC`` is likewise read-only.

Temperatures/setpoints/bands stay tenths-degF on read-back; ``ALARMDEV``,
``COOKHOLD`` and ``PROPBAND`` in the ``<CONTROL>`` block are tenths on the wire
even though they are written in whole degF.
"""

from __future__ import annotations

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms
from virtualcyberq.xml.status import _probe_status, _probe_temp

__all__ = ["render_config"]


def _container(tag: str, probe: ProbeState) -> list[str]:
    """Render a probe container (``<COOK>`` / ``<FOODn>``) as indented lines."""
    return [
        f"\t<{tag}>",
        f"\t\t<{tag}_NAME>{probe.name}</{tag}_NAME>",
        f"\t\t<{tag}_TEMP>{_probe_temp(probe)}</{tag}_TEMP>",
        f"\t\t<{tag}_SET>{encode_temp(probe.set)}</{tag}_SET>",
        f"\t\t<{tag}_STATUS>{_probe_status(probe)}</{tag}_STATUS>",
        f"\t</{tag}>",
    ]


def _system_block(state: DeviceState) -> list[str]:
    """Render the ``<SYSTEM>`` config block."""
    sys = state.system
    return [
        "\t<SYSTEM>",
        f"\t\t<MENU_SCROLLING>{int(sys.menu_scrolling)}</MENU_SCROLLING>",
        f"\t\t<LCD_BACKLIGHT>{int(sys.lcd_backlight)}</LCD_BACKLIGHT>",
        f"\t\t<LCD_CONTRAST>{int(sys.lcd_contrast)}</LCD_CONTRAST>",
        f"\t\t<DEG_UNITS>{int(sys.deg_units)}</DEG_UNITS>",
        f"\t\t<ALARM_BEEPS>{int(sys.alarm_beeps)}</ALARM_BEEPS>",
        f"\t\t<KEY_BEEPS>{int(sys.key_beeps)}</KEY_BEEPS>",
        "\t</SYSTEM>",
    ]


def _control_block(state: DeviceState) -> list[str]:
    """Render the ``<CONTROL>`` config block (bands are tenths-degF)."""
    ctl = state.control
    return [
        "\t<CONTROL>",
        f"\t\t<TIMEOUT_ACTION>{int(ctl.timeout_action)}</TIMEOUT_ACTION>",
        f"\t\t<COOKHOLD>{int(ctl.cookhold)}</COOKHOLD>",
        f"\t\t<ALARMDEV>{int(ctl.alarmdev)}</ALARMDEV>",
        f"\t\t<COOK_RAMP>{int(ctl.cook_ramp)}</COOK_RAMP>",
        f"\t\t<OPENDETECT>{int(ctl.opendetect)}</OPENDETECT>",
        f"\t\t<CYCTIME>{int(ctl.cyctime)}</CYCTIME>",
        f"\t\t<PROPBAND>{int(ctl.propband)}</PROPBAND>",
        "\t</CONTROL>",
    ]


def _wifi_block(state: DeviceState) -> list[str]:
    """Render the ``<WIFI>`` config block (``MAC`` is read-only)."""
    wifi = state.wifi
    return [
        "\t<WIFI>",
        f"\t\t<IP>{wifi.ip}</IP>",
        f"\t\t<NM>{wifi.nm}</NM>",
        f"\t\t<GW>{wifi.gw}</GW>",
        f"\t\t<DNS>{wifi.dns}</DNS>",
        f"\t\t<WIFIMODE>{int(wifi.wifimode)}</WIFIMODE>",
        f"\t\t<DHCP>{int(wifi.dhcp)}</DHCP>",
        f"\t\t<SSID>{wifi.ssid}</SSID>",
        f"\t\t<WIFI_ENC>{int(wifi.wifi_enc)}</WIFI_ENC>",
        f"\t\t<WIFI_KEY>{wifi.wifi_key}</WIFI_KEY>",
        f"\t\t<HTTP_PORT>{int(wifi.http_port)}</HTTP_PORT>",
        f"\t\t<MAC>{wifi.mac}</MAC>",
        "\t</WIFI>",
    ]


def _smtp_block(state: DeviceState) -> list[str]:
    """Render the ``<SMTP>`` config block."""
    smtp = state.smtp
    return [
        "\t<SMTP>",
        f"\t\t<SMTP_HOST>{smtp.host}</SMTP_HOST>",
        f"\t\t<SMTP_PORT>{int(smtp.port)}</SMTP_PORT>",
        f"\t\t<SMTP_USER>{smtp.user}</SMTP_USER>",
        f"\t\t<SMTP_PWD>{smtp.pwd}</SMTP_PWD>",
        f"\t\t<SMTP_TO>{smtp.to}</SMTP_TO>",
        f"\t\t<SMTP_FROM>{smtp.frm}</SMTP_FROM>",
        f"\t\t<SMTP_SUBJ>{smtp.subj}</SMTP_SUBJ>",
        f"\t\t<SMTP_ALERT>{int(smtp.alert)}</SMTP_ALERT>",
        "\t</SMTP>",
    ]


def render_config(state: DeviceState) -> str:
    """Render the ``config.xml`` document for ``state``.

    Args:
        state: The device state to serialize.

    Returns:
        A ``str`` containing the full ``<nutcallstatus>`` superset: the four
        probe containers, the volatile status siblings, then the ``<SYSTEM>``,
        ``<CONTROL>``, ``<WIFI>``, ``<SMTP>`` blocks and the ``<FWVER>`` string.
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
    ]
    lines += _system_block(state)
    lines += _control_block(state)
    lines += _wifi_block(state)
    lines += _smtp_block(state)
    lines += [
        f"\t<FWVER>{state.fwver}</FWVER>",
        "</nutcallstatus>",
    ]
    return "\n".join(lines) + "\n"
