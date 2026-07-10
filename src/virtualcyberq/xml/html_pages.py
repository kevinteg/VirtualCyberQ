# SPDX-License-Identifier: BSD-3-Clause
"""HTML pages served by the device plane (PROTOCOL section 2).

The real CyberQ WiFi serves a root **Control Status** HTML page at ``/`` and a
set of legacy ``*.htm`` configuration pages (``index.htm``, ``control.htm``,
``system.htm``, ``config.htm``, ``wifi.htm``) that link to one another and can
also receive form POSTs. Their exact markup is not published, so these are
**minimal but plausible** renderings: enough structure (a title, a live
status/config table, and a POST form back to ``/``) for a browser or a scraper
to make sense of, without pretending to be byte-faithful to the firmware's UI.

Machine clients read the XML feeds, not these pages; the HTML exists for human
inspection and for clients that POST to the legacy page URLs.
"""

from __future__ import annotations

from html import escape

from virtualcyberq.core.state import DeviceState, ProbeState
from virtualcyberq.core.units import encode_temp, seconds_to_hms

__all__ = [
    "LEGACY_HTM_PAGES",
    "render_config_htm",
    "render_control_htm",
    "render_index_html",
    "render_legacy_page",
    "render_system_htm",
    "render_wifi_htm",
]

#: The legacy ``*.htm`` page names the device links to (PROTOCOL 2).
LEGACY_HTM_PAGES: tuple[str, ...] = (
    "index.htm",
    "control.htm",
    "system.htm",
    "config.htm",
    "wifi.htm",
)

_STATUS_LABELS: dict[int, str] = {
    0: "OK",
    1: "HIGH",
    2: "LOW",
    3: "DONE",
    4: "ERROR",
    5: "HOLD",
    6: "ALARM",
    7: "SHUTDOWN",
}


def _probe_temp_cell(probe: ProbeState) -> str:
    """Return a probe's displayed temperature cell (tenths-degF or ``OPEN``)."""
    if not probe.connected:
        return encode_temp(None)
    return encode_temp(probe.temp)


def _probe_status_label(probe: ProbeState) -> str:
    """Return a human-readable status label for a probe."""
    code = 4 if not probe.connected else int(probe.status)
    return _STATUS_LABELS.get(code, str(code))


def _row(label: str, value: str) -> str:
    """Render one ``<tr>`` two-column table row with escaped content."""
    return f"    <tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"


def _page(title: str, body_rows: list[str], extra: str = "") -> str:
    """Wrap ``body_rows`` in a minimal HTML document with a shared reboot form.

    Args:
        title: The page/table title.
        body_rows: Pre-rendered ``<tr>`` rows for the main table.
        extra: Optional extra HTML inserted after the table (e.g. a form).

    Returns:
        A complete, minimal HTML document string.
    """
    nav = " | ".join(f'<a href="/{name}">{escape(name)}</a>' for name in LEGACY_HTM_PAGES)
    reboot_form = (
        '  <form method="post" action="/">\n'
        '    <input type="hidden" name="REBOOT" value="1">\n'
        '    <button type="submit">Reboot Device</button>\n'
        "  </form>"
    )
    rows = "\n".join(body_rows)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>CyberQ WiFi - {escape(title)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{escape(title)}</h1>\n"
        f"  <nav>{nav}</nav>\n"
        "  <table>\n"
        f"{rows}\n"
        "  </table>\n"
        f"{extra}\n"
        f"{reboot_form}\n"
        "</body>\n"
        "</html>\n"
    )


def render_index_html(state: DeviceState) -> str:
    """Render the root ``/`` **Control Status** HTML page.

    Args:
        state: The device state to display.

    Returns:
        A minimal HTML document showing the live pit/food status and output.
    """
    rows: list[str] = [
        _row("Output %", str(int(state.output_percent))),
        _row("Timer", seconds_to_hms(state.timer.remaining_s)),
    ]
    for tag, probe in (
        ("Cook", state.cook),
        ("Food1", state.food1),
        ("Food2", state.food2),
        ("Food3", state.food3),
    ):
        name = f"{tag} ({probe.name})"
        rows.append(
            _row(
                name,
                f"{_probe_temp_cell(probe)} tenthsF [{_probe_status_label(probe)}]",
            )
        )
    return _page("Control Status", rows)


def render_control_htm(state: DeviceState) -> str:
    """Render the legacy ``control.htm`` cook/control settings page."""
    ctl = state.control
    rows = [
        _row("Cook Set (tenthsF)", encode_temp(state.cook.set)),
        _row("Timeout Action", str(int(ctl.timeout_action))),
        _row("Cook Hold (tenthsF)", str(int(ctl.cookhold))),
        _row("Alarm Dev (tenthsF)", str(int(ctl.alarmdev))),
        _row("Cook Ramp", str(int(ctl.cook_ramp))),
        _row("Open Detect", str(int(ctl.opendetect))),
        _row("Cycle Time (s)", str(int(ctl.cyctime))),
        _row("Prop Band (tenthsF)", str(int(ctl.propband))),
    ]
    form = (
        '  <form method="post" action="/">\n'
        "    <label>Cook Set (F) "
        '<input type="text" name="COOK_SET"></label>\n'
        "    <label>Prop Band (F) "
        '<input type="text" name="PROPBAND"></label>\n'
        "    <label>Cycle Time (s) "
        '<input type="text" name="CYCTIME"></label>\n'
        '    <button type="submit">Save</button>\n'
        "  </form>"
    )
    return _page("Control Setup", rows, form)


def render_system_htm(state: DeviceState) -> str:
    """Render the legacy ``system.htm`` display/beeper settings page."""
    sys = state.system
    rows = [
        _row("Menu Scrolling", str(int(sys.menu_scrolling))),
        _row("LCD Backlight (%)", str(int(sys.lcd_backlight))),
        _row("LCD Contrast (%)", str(int(sys.lcd_contrast))),
        _row("Deg Units", str(int(sys.deg_units))),
        _row("Alarm Beeps", str(int(sys.alarm_beeps))),
        _row("Key Beeps", str(int(sys.key_beeps))),
    ]
    return _page("System Setup", rows)


def render_config_htm(state: DeviceState) -> str:
    """Render the legacy ``config.htm`` overview page (probe names/setpoints)."""
    rows: list[str] = []
    for tag, probe in (
        ("Cook", state.cook),
        ("Food1", state.food1),
        ("Food2", state.food2),
        ("Food3", state.food3),
    ):
        rows.append(_row(f"{tag} Name", probe.name))
        rows.append(_row(f"{tag} Set (tenthsF)", encode_temp(probe.set)))
    rows.append(_row("Firmware", state.fwver))
    return _page("Configuration", rows)


def render_wifi_htm(state: DeviceState) -> str:
    """Render the legacy ``wifi.htm`` network settings page."""
    wifi = state.wifi
    rows = [
        _row("IP", wifi.ip),
        _row("Netmask", wifi.nm),
        _row("Gateway", wifi.gw),
        _row("DNS", wifi.dns),
        _row("WiFi Mode", str(int(wifi.wifimode))),
        _row("DHCP", str(int(wifi.dhcp))),
        _row("SSID", wifi.ssid),
        _row("Encryption", str(int(wifi.wifi_enc))),
        _row("HTTP Port", str(int(wifi.http_port))),
        _row("MAC", wifi.mac),
    ]
    return _page("WIFI Setup", rows)


def render_legacy_page(name: str, state: DeviceState) -> str:
    """Render a legacy ``*.htm`` page by URL name.

    Args:
        name: The page name (with or without a leading ``/``), e.g.
            ``"control.htm"`` or ``"/wifi.htm"``. ``index.htm`` and any
            unrecognized page fall back to the root Control Status page.
        state: The device state to display.

    Returns:
        The rendered HTML document for the requested page.
    """
    page = name.lstrip("/").lower()
    if page == "control.htm":
        return render_control_htm(state)
    if page == "system.htm":
        return render_system_htm(state)
    if page == "config.htm":
        return render_config_htm(state)
    if page == "wifi.htm":
        return render_wifi_htm(state)
    return render_index_html(state)
