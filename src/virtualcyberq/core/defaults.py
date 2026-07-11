# SPDX-License-Identifier: BSD-3-Clause
"""Factory defaults and shipped demo values (single source of truth).

Two reset modes exist (per DESIGN section 9 admin API and PROTOCOL section 12):

* :func:`factory_state` -- the verified BBQ Guru factory defaults, with generic
  probe labels (``Cook``/``Food1``/``Food2``/``Food3``) and factory setpoints.
* :func:`demo_state` -- the shipped illustrative values (Big Green Egg / Chicken
  Quarters 155 / Beef Brisket 180 / Pork Chop 160). These are demo seeds, NOT
  factory defaults.

Every temperature constant here is expressed as internal tenths-of-degF.
"""

from __future__ import annotations

from virtualcyberq.core.enums import (
    DegUnits,
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
)
from virtualcyberq.core.state import (
    ControlConfig,
    DeviceState,
    ProbeState,
    SmtpConfig,
    SystemConfig,
    TimerState,
    WifiConfig,
)

__all__ = [
    # firmware / persona
    "DEFAULT_FWVER",
    # demo values
    "DEMO_COOK_NAME",
    "DEMO_FOOD1_NAME",
    "DEMO_FOOD1_SET",
    "DEMO_FOOD2_NAME",
    "DEMO_FOOD2_SET",
    "DEMO_FOOD3_NAME",
    "DEMO_FOOD3_SET",
    "FACTORY_ALARMDEV",
    "FACTORY_ALARM_BEEPS",
    "FACTORY_COOKHOLD",
    # control defaults (tenths-degF unless noted)
    "FACTORY_COOK_SET",
    "FACTORY_CYCTIME",
    "FACTORY_FOOD_SET",
    # system defaults
    "FACTORY_LCD_BACKLIGHT",
    "FACTORY_LCD_CONTRAST",
    "FACTORY_PROPBAND",
    "demo_state",
    # builders
    "factory_control",
    "factory_smtp",
    "factory_state",
    "factory_system",
    "factory_wifi",
]

# --- Firmware persona -------------------------------------------------------
# The validated real unit reports firmware 1.7; personas: 1.7 / 2.3 / 3.1 / 4.08 (Cloud).
DEFAULT_FWVER = "1.7"

# --- Verified factory defaults (tenths-degF for temperatures) ---------------
FACTORY_COOK_SET = 2750  # 275.0 degF
FACTORY_FOOD_SET = 1800  # 180.0 degF (all three food probes)
FACTORY_COOKHOLD = 2000  # 200.0 degF
FACTORY_ALARMDEV = 500  # 50.0 degF
FACTORY_PROPBAND = 300  # 30.0 degF (verified on a real v1.7 unit)
FACTORY_CYCTIME = 6  # seconds

# --- Verified factory system defaults ---------------------------------------
FACTORY_LCD_BACKLIGHT = 50  # percent
FACTORY_LCD_CONTRAST = 10  # percent
FACTORY_ALARM_BEEPS = 3

# --- Verified factory hot-spot WiFi defaults --------------------------------
FACTORY_WIFI_IP = "192.168.101.10"
FACTORY_WIFI_NM = "255.255.255.0"
FACTORY_WIFI_GW = "192.168.101.1"
FACTORY_WIFI_DNS = "192.168.101.1"
FACTORY_WIFI_SSID = "CyberQ"
FACTORY_WIFI_KEY = "1234abcdef"
FACTORY_WIFI_MAC = "00:1E:C0:00:00:00"  # BBQ Guru OUI prefix
FACTORY_HTTP_PORT = 80
# Observed on a real v1.7 unit (our WifiMode/WifiEnc enum codes differ; these are
# the raw wire values the device actually reports).
FACTORY_WIFIMODE = 1
FACTORY_DHCP = 1
FACTORY_WIFI_ENC = 1

# --- Verified factory SMTP defaults -----------------------------------------
FACTORY_SMTP_HOST = "smtp.hostname.com"
FACTORY_SMTP_PORT = 0
FACTORY_SMTP_TO = "destination@someplace.com"
FACTORY_SMTP_FROM = "source@someplace.com"
FACTORY_SMTP_SUBJ = "Temperature Controller Status E-Mail"

# --- Factory (generic) probe labels -----------------------------------------
FACTORY_COOK_NAME = "Cook"
FACTORY_FOOD1_NAME = "Food1"
FACTORY_FOOD2_NAME = "Food2"
FACTORY_FOOD3_NAME = "Food3"

# --- Shipped demo values (NOT factory) --------------------------------------
DEMO_COOK_NAME = "Big Green Egg"
DEMO_FOOD1_NAME = "Chicken Quarters"
DEMO_FOOD1_SET = 1550  # 155.0 degF
DEMO_FOOD2_NAME = "Beef Brisket"
DEMO_FOOD2_SET = 1800  # 180.0 degF
DEMO_FOOD3_NAME = "Pork Chop"
DEMO_FOOD3_SET = 1600  # 160.0 degF


def factory_control() -> ControlConfig:
    """Build a :class:`ControlConfig` with verified factory defaults."""
    return ControlConfig(
        timeout_action=TimeoutAction.NO_ACTION,
        cookhold=FACTORY_COOKHOLD,
        alarmdev=FACTORY_ALARMDEV,
        cook_ramp=RampSource.OFF,
        opendetect=OnOff.ON,
        cyctime=FACTORY_CYCTIME,
        propband=FACTORY_PROPBAND,
    )


def factory_system() -> SystemConfig:
    """Build a :class:`SystemConfig` with verified factory defaults."""
    return SystemConfig(
        menu_scrolling=OnOff.OFF,
        lcd_backlight=FACTORY_LCD_BACKLIGHT,
        lcd_contrast=FACTORY_LCD_CONTRAST,
        deg_units=DegUnits.FAHRENHEIT,
        alarm_beeps=FACTORY_ALARM_BEEPS,
        key_beeps=OnOff.OFF,
    )


def factory_wifi() -> WifiConfig:
    """Build a :class:`WifiConfig` with the verified factory hot-spot defaults."""
    return WifiConfig(
        ip=FACTORY_WIFI_IP,
        nm=FACTORY_WIFI_NM,
        gw=FACTORY_WIFI_GW,
        dns=FACTORY_WIFI_DNS,
        wifimode=FACTORY_WIFIMODE,
        dhcp=FACTORY_DHCP,
        ssid=FACTORY_WIFI_SSID,
        wifi_enc=FACTORY_WIFI_ENC,
        wifi_key=FACTORY_WIFI_KEY,
        http_port=FACTORY_HTTP_PORT,
        mac=FACTORY_WIFI_MAC,
    )


def factory_smtp() -> SmtpConfig:
    """Build a :class:`SmtpConfig` with verified factory SMTP defaults."""
    return SmtpConfig(
        host=FACTORY_SMTP_HOST,
        port=FACTORY_SMTP_PORT,
        user="",
        pwd="",
        to=FACTORY_SMTP_TO,
        frm=FACTORY_SMTP_FROM,
        subj=FACTORY_SMTP_SUBJ,
        alert=0,
    )


def _factory_probe(name: str, set_tenths: int) -> ProbeState:
    """Build a connected probe with no reading yet (temp=None) at ``set_tenths``."""
    return ProbeState(name=name, temp=None, set=set_tenths, status=StatusCode.OK)


def factory_state(fwver: str = DEFAULT_FWVER) -> DeviceState:
    """Build a full :class:`DeviceState` at verified factory defaults.

    Probes carry generic labels (``Cook``/``Food1``/...), factory setpoints, and
    start disconnected (``temp=None`` -> ``OPEN``) until physics runs.

    Args:
        fwver: Firmware persona string.

    Returns:
        A fresh factory-default :class:`DeviceState`.
    """
    return DeviceState(
        cook=_factory_probe(FACTORY_COOK_NAME, FACTORY_COOK_SET),
        food1=_factory_probe(FACTORY_FOOD1_NAME, FACTORY_FOOD_SET),
        food2=_factory_probe(FACTORY_FOOD2_NAME, FACTORY_FOOD_SET),
        food3=_factory_probe(FACTORY_FOOD3_NAME, FACTORY_FOOD_SET),
        timer=TimerState(),
        control=factory_control(),
        system=factory_system(),
        wifi=factory_wifi(),
        smtp=factory_smtp(),
        fwver=fwver,
        output_percent=0,
        fan_shorted=False,
    )


def demo_state(fwver: str = DEFAULT_FWVER) -> DeviceState:
    """Build a :class:`DeviceState` seeded with the shipped demo values.

    Same config blocks as :func:`factory_state`, but with the illustrative probe
    names and food setpoints (Big Green Egg / Chicken Quarters 155 / Beef
    Brisket 180 / Pork Chop 160). These are demo seeds, not factory defaults.

    Args:
        fwver: Firmware persona string.

    Returns:
        A fresh demo-seeded :class:`DeviceState`.
    """
    state = factory_state(fwver=fwver)
    state.cook.name = DEMO_COOK_NAME
    state.food1.name = DEMO_FOOD1_NAME
    state.food1.set = DEMO_FOOD1_SET
    state.food2.name = DEMO_FOOD2_NAME
    state.food2.set = DEMO_FOOD2_SET
    state.food3.name = DEMO_FOOD3_NAME
    state.food3.set = DEMO_FOOD3_SET
    return state
