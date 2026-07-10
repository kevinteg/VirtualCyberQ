# SPDX-License-Identifier: BSD-3-Clause
"""Device state model (DESIGN section 4).

State is a tree of ``@dataclass``es rooted at :class:`DeviceState`. All
temperatures are stored internally as ``int`` tenths-of-degF (``3343`` == 334.3
degF), matching the wire format exactly so serialization is a straight copy. An
open probe is ``temp=None``, which serializes to the literal string ``OPEN``.

:class:`SimState` is a parallel structure holding the *physical* variables that
never appear on the wire (fire intensity, lid state, fuel, per-probe moisture,
timeout flags). The control loop reads :class:`SimState` and writes the visible
:class:`DeviceState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from virtualcyberq.core.enums import (
    DegUnits,
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
)

__all__ = [
    "ControlConfig",
    "DeviceState",
    "ProbeState",
    "SimState",
    "SmtpConfig",
    "SystemConfig",
    "TimerState",
    "WifiConfig",
]


@dataclass
class ProbeState:
    """A single temperature probe (the pit ``cook`` probe or a food probe).

    Attributes:
        name: Probe label, <=16 chars.
        temp: Current temperature in tenths-degF, or ``None`` for an open probe
            (serializes to ``OPEN``).
        set: Target setpoint in tenths-degF.
        status: The probe's :class:`StatusCode`.
        connected: When ``False`` the probe reads ``OPEN`` with status ERROR.
    """

    name: str
    temp: int | None
    set: int
    status: StatusCode = StatusCode.OK
    connected: bool = True


@dataclass
class ControlConfig:
    """The ``<CONTROL>`` block. Whole-degF on POST input, tenths on read-back.

    Attributes:
        timeout_action: Action fired when the cook timer expires.
        cookhold: Pit setpoint applied on HOLD timeout, tenths-degF (2000=200.0).
        alarmdev: Deviation-alarm band, tenths-degF (500=50.0); input 10..100 degF.
        cook_ramp: Which food probe drives cook-and-hold ramp-down.
        opendetect: Open-lid detection on/off.
        cyctime: Fan PWM period in seconds, 4..10.
        propband: Proportional band, tenths-degF (250=25.0); input 5..100 degF.
    """

    timeout_action: TimeoutAction = TimeoutAction.NO_ACTION
    cookhold: int = 2000
    alarmdev: int = 500
    cook_ramp: RampSource = RampSource.OFF
    opendetect: OnOff = OnOff.ON
    cyctime: int = 6
    propband: int = 250


@dataclass
class SystemConfig:
    """The ``<SYSTEM>`` block (display + beeper preferences).

    Attributes:
        menu_scrolling: Main-screen auto-scroll on/off.
        lcd_backlight: Display brightness percent, 0..100.
        lcd_contrast: Display contrast percent, 0..100.
        deg_units: LCD unit (Celsius/Fahrenheit); wire temps stay tenths-degF.
        alarm_beeps: Beeps per alarm, 0..5 (0=off).
        key_beeps: Keypress chirp on/off.
    """

    menu_scrolling: OnOff = OnOff.OFF
    lcd_backlight: int = 50
    lcd_contrast: int = 10
    deg_units: DegUnits = DegUnits.FAHRENHEIT
    alarm_beeps: int = 3
    key_beeps: OnOff = OnOff.ON


@dataclass
class WifiConfig:
    """The ``<WIFI>`` block. ``mac`` is read-only.

    Attributes:
        ip: Device IP address (dotted-quad string).
        nm: Netmask string.
        gw: Gateway string.
        dns: DNS server string.
        wifimode: Radio mode integer (see :class:`WifiMode`).
        dhcp: DHCP on/off integer (see :class:`Dhcp`).
        ssid: Network name.
        wifi_enc: Encryption type integer (see :class:`WifiEnc`).
        wifi_key: Network key/password (cleartext on the wire).
        http_port: Web server TCP port.
        mac: Device MAC address (read-only).
    """

    ip: str
    nm: str
    gw: str
    dns: str
    wifimode: int
    dhcp: int
    ssid: str
    wifi_enc: int
    wifi_key: str
    http_port: int = 80
    mac: str = "00:04:A3:00:00:00"


@dataclass
class SmtpConfig:
    """The ``<SMTP>`` block (email-alert configuration).

    Attributes:
        host: Mail server host.
        port: Mail server TCP port (0 = disabled/unset).
        user: Auth username.
        pwd: Auth password (cleartext on the wire).
        to: Recipient address.
        frm: From address.
        subj: Subject line.
        alert: Alert enable/interval (0=off; else minutes).
    """

    host: str
    port: int
    user: str
    pwd: str
    to: str
    frm: str
    subj: str
    alert: int = 0


@dataclass
class TimerState:
    """The cook countdown timer.

    Attributes:
        remaining_s: Remaining whole seconds; serialized ``HH:MM:SS`` as
            ``TIMER_CURR``.
        running: Whether the timer is actively counting down.
        status: The timer's :class:`StatusCode`.
    """

    remaining_s: int = 0
    running: bool = False
    status: StatusCode = StatusCode.OK


@dataclass
class DeviceState:
    """The full visible device state (everything the wire can expose).

    Attributes:
        cook: The pit probe.
        food1: Food probe 1.
        food2: Food probe 2.
        food3: Food probe 3.
        timer: The cook timer.
        control: The ``<CONTROL>`` config block.
        system: The ``<SYSTEM>`` config block.
        wifi: The ``<WIFI>`` config block.
        smtp: The ``<SMTP>`` config block.
        fwver: Firmware persona string ("1.7"|"2.3"|"3.1"|"4.08").
        output_percent: Fan duty 0..100, READ-ONLY (computed by the control loop).
        fan_shorted: Fan short-circuit flag, READ-ONLY.
    """

    cook: ProbeState
    food1: ProbeState
    food2: ProbeState
    food3: ProbeState
    timer: TimerState
    control: ControlConfig
    system: SystemConfig
    wifi: WifiConfig
    smtp: SmtpConfig
    fwver: str = "3.1"
    output_percent: int = 0
    fan_shorted: bool = False

    def probes(self) -> list[ProbeState]:
        """Return the probes in wire order: ``[cook, food1, food2, food3]``."""
        return [self.cook, self.food1, self.food2, self.food3]

    def food_probes(self) -> list[ProbeState]:
        """Return the three food probes in order: ``[food1, food2, food3]``."""
        return [self.food1, self.food2, self.food3]


@dataclass
class SimState:
    """Hidden physical variables that never appear on the wire (DESIGN 4).

    The control loop reads these and writes the visible :class:`DeviceState`.

    Attributes:
        fire: Ignition intensity, 0.0..1.0 (lags fan duty).
        lid_open: Whether the lid is currently detected open.
        fuel_remaining: Remaining fuel budget, 0.0..1.0 (decays with duty).
        cook_armed: Whether the deviation alarm has armed (pit reached setpoint).
        timeout_hold_active: A HOLD timeout has retargeted the pit to COOKHOLD.
        timeout_shutdown_active: A SHUTDOWN timeout has forced the fan off.
        meat_moisture: Per-probe evaporative-cooling budget keyed by probe id
            ("food1"/"food2"/"food3"), 0.0..1.0; depletion releases the stall.
        phase: Slow-PWM phase clock, 0..cyctime seconds.
    """

    fire: float = 0.0
    lid_open: bool = False
    fuel_remaining: float = 1.0
    cook_armed: bool = False
    timeout_hold_active: bool = False
    timeout_shutdown_active: bool = False
    meat_moisture: dict[str, float] = field(
        default_factory=lambda: {"food1": 1.0, "food2": 1.0, "food3": 1.0}
    )
    phase: float = 0.0
