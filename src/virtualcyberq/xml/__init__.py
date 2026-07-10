# SPDX-License-Identifier: BSD-3-Clause
"""Device wire layer: XML/HTML serializers and the POST parser.

This package renders a :class:`~virtualcyberq.core.state.DeviceState` into the
exact byte shape a physical CyberQ WiFi unit emits on its local HTTP service
(``status.xml`` / ``all.xml`` / ``config.xml`` and the HTML pages), and parses
inbound ``application/x-www-form-urlencoded`` POST bodies back into validated
device writes.

Everything here is **pure and framework-agnostic** -- no FastAPI/Flask/Starlette
imports. The web adapter layer (:mod:`virtualcyberq.web`) is the only place that
knows about HTTP transport; it calls these functions to produce response bodies
and to apply writes.
"""

from __future__ import annotations

from virtualcyberq.xml.allxml import render_all
from virtualcyberq.xml.configxml import render_config
from virtualcyberq.xml.html_pages import (
    LEGACY_HTM_PAGES,
    render_config_htm,
    render_control_htm,
    render_index_html,
    render_legacy_page,
    render_system_htm,
    render_wifi_htm,
)
from virtualcyberq.xml.post_parse import parse_and_apply, parse_form_body
from virtualcyberq.xml.status import render_status

__all__ = [
    "LEGACY_HTM_PAGES",
    "parse_and_apply",
    "parse_form_body",
    "render_all",
    "render_config",
    "render_config_htm",
    "render_control_htm",
    "render_index_html",
    "render_legacy_page",
    "render_status",
    "render_system_htm",
    "render_wifi_htm",
]
