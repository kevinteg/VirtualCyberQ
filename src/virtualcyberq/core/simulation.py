# SPDX-License-Identifier: BSD-3-Clause
"""The :class:`Simulation` -- the core public API (DESIGN 6.6 / section 6).

``Simulation`` is the single framework-agnostic object every plane drives. It
owns the visible :class:`DeviceState`, the hidden :class:`SimState`, the
:class:`VirtualClock`, the :class:`SeededRNG`, the :class:`FaultRegistry`, and
the thermal models. Physics is decoupled from HTTP entirely: the web layer only
reads/writes state and calls :meth:`step` / :meth:`advance`.

Determinism: with a fixed seed and identical ``advance`` calls the output stream
is byte-identical (explicit Euler with automatic sub-stepping, one seeded RNG,
one virtual clock; no wall-clock reads).
"""

from __future__ import annotations

import copy
from typing import Any, cast

from virtualcyberq.core.clock import VirtualClock
from virtualcyberq.core.control import (
    DEFAULT_CONSTANTS,
    ControlConstants,
    control_tick,
    effective_cook_set,
)
from virtualcyberq.core.defaults import demo_state, factory_state
from virtualcyberq.core.enums import StatusCode
from virtualcyberq.core.faults import Fault, FaultRegistry, RequestContext, RequestFaultDecision
from virtualcyberq.core.faults.power import is_power_offline, wants_reset
from virtualcyberq.core.profiles import CookProfile, MeatProfile, PitProfile
from virtualcyberq.core.rng import SeededRNG
from virtualcyberq.core.state import DeviceState, ProbeState, SimState
from virtualcyberq.core.thermal import MeatThermal, PitThermal
from virtualcyberq.core.units import (
    float_to_tenths,
    hms_to_seconds,
    tenths_to_float,
)
from virtualcyberq.core.validation import (
    WRITABLE_PARAMS,
    ParamKind,
    ValidationResult,
    WriteMode,
    validate_write,
)

__all__ = ["Simulation"]

#: Maximum sub-step size (simulated seconds) for Euler stability (DESIGN 6.6).
_MAX_SUBSTEP_S = 2.0

_FOOD_KEYS = ("food1", "food2", "food3")


class Simulation:
    """The core simulation: owns all state and advances physics deterministically.

    Args:
        state: Initial :class:`DeviceState`; defaults to factory defaults.
        seed: RNG seed for reproducible fault activation and sensor noise.
        speed: Initial clock speed (sim-seconds per wall-second; ``0`` freezes).
        constants: Tunable control constants.
        pit: Optional initial :class:`PitProfile` for the thermal model.
    """

    def __init__(
        self,
        state: DeviceState | None = None,
        *,
        seed: int = 0,
        speed: float = 1.0,
        constants: ControlConstants = DEFAULT_CONSTANTS,
        pit: PitProfile | None = None,
    ) -> None:
        self._state: DeviceState = state if state is not None else factory_state()
        self._sim = SimState()
        self._clock = VirtualClock(speed=speed)
        self._rng = SeededRNG(seed)
        self._faults = FaultRegistry(self._clock, self._rng)
        self._constants = constants
        self._max_substep_s = _MAX_SUBSTEP_S

        pit_profile = (
            pit if pit is not None else PitProfile(cook_set_f=tenths_to_float(self._state.cook.set))
        )
        self._pit = PitThermal.from_profile(pit_profile)
        self._meats: dict[str, MeatThermal | None] = {
            "food1": None,
            "food2": None,
            "food3": None,
        }
        self._prev_cook_temp_tenths: int | None = None
        self._sync_probe_from_pit()

    # ------------------------------------------------------------------ time
    @property
    def clock(self) -> VirtualClock:
        """The shared :class:`VirtualClock`."""
        return self._clock

    @property
    def rng(self) -> SeededRNG:
        """The shared :class:`SeededRNG`."""
        return self._rng

    @property
    def faults(self) -> FaultRegistry:
        """The :class:`FaultRegistry` (inject/list/clear/query faults)."""
        return self._faults

    def now(self) -> float:
        """Return the current simulated time in seconds."""
        return self._clock.now()

    def set_speed(self, speed: float) -> float:
        """Set the clock acceleration factor. Returns the new speed."""
        return self._clock.scale(speed)

    def freeze(self) -> None:
        """Freeze the clock (speed -> 0); physics advances only via :meth:`advance`."""
        self._clock.freeze()

    def resume(self, speed: float | None = None) -> float:
        """Resume ticking at ``speed`` (or the pre-freeze speed). Returns speed."""
        return self._clock.resume(speed)

    def seed(self, seed: int) -> None:
        """Reseed the RNG (and reset its draw counter) for reproducibility."""
        self._rng.seed(seed)

    # --------------------------------------------------------------- stepping
    def step(self, dt_sim_seconds: float) -> None:
        """Advance physics by ``dt_sim_seconds`` with automatic sub-stepping.

        Splits the step so each sub-step is ``<= _MAX_SUBSTEP_S`` (Euler
        stability under heavy time acceleration, DESIGN 6.6). Each sub-step runs
        the pit + meat thermal models, the control law, and the sensor/power
        faults, then advances the clock. Does **not** itself scale by clock
        speed -- callers pass already-scaled sim-seconds.

        Args:
            dt_sim_seconds: Simulated seconds to integrate (>= 0).

        Raises:
            ValueError: If ``dt_sim_seconds`` is negative.
        """
        if dt_sim_seconds < 0:
            raise ValueError("dt_sim_seconds must be non-negative")
        if dt_sim_seconds == 0:
            return

        remaining = float(dt_sim_seconds)
        substeps = max(1, int(-(-remaining // self._max_substep_s)))  # ceil
        dt = remaining / substeps
        for _ in range(substeps):
            self._substep(dt)

    def advance(self, seconds: float) -> float:
        """Deterministically advance the clock and physics by ``seconds``.

        Works even when frozen (the deterministic test/admin entry point). Steps
        the simulation by exactly ``seconds`` of simulated time.

        Args:
            seconds: Simulated seconds to advance (>= 0).

        Returns:
            The new simulated time in seconds.
        """
        self.step(seconds)
        return self._clock.now()

    def tick_wall(self, dt_wall_seconds: float) -> float:
        """Advance by ``dt_wall_seconds`` of wall time scaled by the clock speed.

        The real-time/accelerated background-loop entry point. Returns the number
        of simulated seconds that elapsed.
        """
        # step() advances the clock by the sim-seconds it integrates, so scale
        # the wall delta by the current speed and hand it straight to step().
        dt_sim = dt_wall_seconds * self._clock.speed
        self.step(dt_sim)
        return dt_sim

    def _substep(self, dt: float) -> None:
        """Run one integrator sub-step: physics, control, faults, clock."""
        offline = self._powered_off_faults()
        if offline:
            # Device is in a power-outage window: freeze physics, advance clock,
            # expire faults (so the outage window ends). Config reset happens
            # when the outage clears (handled below on the next non-offline tick).
            self._clock.advance(dt)
            self._faults.tick()
            self._maybe_apply_power_return(offline)
            return

        # 1. Pit thermal: fire is driven by last tick's output duty.
        duty = self._state.output_percent / 100.0
        pit_temp_f = self._pit.step(duty, dt)
        self._sim.fire = self._pit.fire
        self._sim.fuel_remaining = self._pit.fuel_remaining
        self._sim.lid_open = self._pit.lid_open
        self._state.cook.temp = float_to_tenths(pit_temp_f)

        # 2. Meat thermals.
        for key in _FOOD_KEYS:
            meat = self._meats[key]
            probe = getattr(self._state, key)
            if meat is None or not probe.connected:
                continue
            meat_temp_f = meat.step(pit_temp_f, dt)
            probe.temp = float_to_tenths(meat_temp_f)
            self._sim.meat_moisture[key] = meat.moisture

        # 3. Control law (statuses, output, timer, ramp, open-lid).
        control_tick(
            self._state,
            self._sim,
            dt,
            self._prev_cook_temp_tenths,
            self._constants,
        )
        # Keep the pit thermal's lid flag in sync with the control decision.
        if self._sim.lid_open and not self._pit.lid_open:
            self._pit.open_lid()
        elif not self._sim.lid_open and self._pit.lid_open:
            self._pit.close_lid()
        self._prev_cook_temp_tenths = self._state.cook.temp

        # 4. Sensor/power faults mutate the visible readings post-control.
        self._faults.apply_sim_faults(self._state, self._sim, dt)

        # 5. Advance time + expire duration-based faults.
        self._clock.advance(dt)
        self._faults.tick()

    # ----------------------------------------------------------------- power
    def _powered_off_faults(self) -> list[Fault]:
        """Return active power-outage faults, if any."""
        return [f for f in self._faults.list() if is_power_offline(f)]

    def _maybe_apply_power_return(self, offline: list[Fault]) -> None:
        """When a power outage has just expired, optionally reset config."""
        for fault in offline:
            # tick() expired it AND it requested a config reset on power return
            if self._faults.get(fault.id) is None and wants_reset(fault):
                self._reset_to(factory_state(fwver=self._state.fwver))

    def is_powered(self) -> bool:
        """Return ``True`` if the device is reachable (no active power outage).

        The device-plane adapter checks this to emulate the unit disappearing
        during a ``power.brownout`` / ``power.reboot`` window.
        """
        return not self._powered_off_faults()

    # ----------------------------------------------------------- fault query
    def query_request_faults(self, ctx: RequestContext) -> RequestFaultDecision:
        """Return the network/http fault decision for a device-plane request.

        Thin pass-through to :meth:`FaultRegistry.query_request` so the web
        middleware has a single object to call.
        """
        return self._faults.query_request(ctx)

    # -------------------------------------------------------------- accessors
    @property
    def state(self) -> DeviceState:
        """The live visible :class:`DeviceState` (mutated in place by physics)."""
        return self._state

    @property
    def sim_state(self) -> SimState:
        """The live hidden :class:`SimState` (physical variables)."""
        return self._sim

    def read(self, probe: str) -> ProbeState:
        """Return one probe by id (``cook``/``food1``/``food2``/``food3``).

        Raises:
            KeyError: If ``probe`` is not a known probe id.
        """
        name = probe.lower()
        if name not in ("cook", *_FOOD_KEYS):
            raise KeyError(f"unknown probe: {probe!r}")
        return cast("ProbeState", getattr(self._state, name))

    def effective_cook_set_tenths(self) -> int:
        """Return the current effective pit setpoint (COOK_RAMP applied), tenths."""
        return effective_cook_set(self._state, self._constants)

    # ------------------------------------------------------------------ write
    def apply_write(
        self, key: str, value: object, mode: WriteMode = WriteMode.LENIENT
    ) -> ValidationResult:
        """Validate + apply one wire write (``KEY=value``) to device state.

        Routes through :func:`validate_write` (allow-list, ranges, clamp/reject)
        and :mod:`units` (whole-degF -> tenths for temperatures), then mutates the
        appropriate :class:`DeviceState` field. Read-only and unknown keys are
        rejected/ignored per ``mode``.

        Args:
            key: The POST key (e.g. ``"COOK_SET"``).
            value: The submitted value (string or number).
            mode: Lenient (clamp/ignore) or strict (reject).

        Returns:
            The :class:`ValidationResult`; when ``accepted`` the state has been
            updated.
        """
        result = validate_write(key, value, mode)
        if not result.accepted:
            return result
        self._apply_validated(key, result.value)
        return result

    def _apply_validated(self, key: str, value: object) -> None:
        """Apply an already-validated value to the correct state field."""
        spec = WRITABLE_PARAMS[key]
        # Temperatures come back in whole degF -> convert to internal tenths.
        if spec.kind is ParamKind.TEMP_F:
            # A validated TEMP_F value is always numeric (whole-degF int/float).
            tenths = float_to_tenths(float(cast("float", value)))
            self._apply_temp(key, tenths)
        elif spec.kind is ParamKind.TIMER:
            self._apply_timer(str(value))
        else:
            self._apply_scalar(key, value)

    def _apply_temp(self, key: str, tenths: int) -> None:
        """Route a validated temperature (tenths) to its target field."""
        if key == "COOK_SET":
            self._state.cook.set = tenths
        elif key == "FOOD1_SET":
            self._state.food1.set = tenths
        elif key == "FOOD2_SET":
            self._state.food2.set = tenths
        elif key == "FOOD3_SET":
            self._state.food3.set = tenths
        elif key == "COOKHOLD":
            self._state.control.cookhold = tenths
        elif key == "ALARMDEV":
            self._state.control.alarmdev = tenths
        elif key == "PROPBAND":
            self._state.control.propband = tenths

    def _apply_timer(self, hms: str) -> None:
        """Set the cook timer from an ``HH:MM:SS`` string and start it."""
        seconds = hms_to_seconds(hms)
        if seconds is None:
            return
        self._state.timer.remaining_s = seconds
        self._state.timer.running = seconds > 0
        if seconds > 0:
            self._state.timer.status = StatusCode.OK
            self._sim.timeout_hold_active = False
            self._sim.timeout_shutdown_active = False

    def _apply_scalar(self, key: str, value: object) -> None:
        """Route a validated INT/ENUM value to its target field."""
        from virtualcyberq.core.enums import (
            DegUnits,
            OnOff,
            RampSource,
            TimeoutAction,
        )

        # A validated INT/ENUM value is always numeric here.
        ivalue = int(cast("float", value))
        ctrl = self._state.control
        sysc = self._state.system
        wifi = self._state.wifi
        smtp = self._state.smtp
        if key == "COOK_NAME":
            self._state.cook.name = str(value)
        elif key == "FOOD1_NAME":
            self._state.food1.name = str(value)
        elif key == "FOOD2_NAME":
            self._state.food2.name = str(value)
        elif key == "FOOD3_NAME":
            self._state.food3.name = str(value)
        elif key == "TIMEOUT_ACTION":
            ctrl.timeout_action = TimeoutAction(ivalue)
        elif key == "COOK_RAMP":
            ctrl.cook_ramp = RampSource(ivalue)
        elif key == "OPENDETECT":
            ctrl.opendetect = OnOff(ivalue)
        elif key == "CYCTIME":
            ctrl.cyctime = ivalue
        elif key == "MENU_SCROLLING":
            sysc.menu_scrolling = OnOff(ivalue)
        elif key == "LCD_BACKLIGHT":
            sysc.lcd_backlight = ivalue
        elif key == "LCD_CONTRAST":
            sysc.lcd_contrast = ivalue
        elif key == "DEG_UNITS":
            sysc.deg_units = DegUnits(ivalue)
        elif key == "ALARM_BEEPS":
            sysc.alarm_beeps = ivalue
        elif key == "KEY_BEEPS":
            sysc.key_beeps = OnOff(ivalue)
        elif key == "IP":
            wifi.ip = str(value)
        elif key == "NM":
            wifi.nm = str(value)
        elif key == "GW":
            wifi.gw = str(value)
        elif key == "DNS":
            wifi.dns = str(value)
        elif key == "WIFIMODE":
            wifi.wifimode = ivalue
        elif key == "DHCP":
            wifi.dhcp = ivalue
        elif key == "SSID":
            wifi.ssid = str(value)
        elif key == "WIFI_ENC":
            wifi.wifi_enc = ivalue
        elif key == "WIFI_KEY":
            wifi.wifi_key = str(value)
        elif key == "HTTP_PORT":
            wifi.http_port = ivalue
        elif key == "SMTP_HOST":
            smtp.host = str(value)
        elif key == "SMTP_PORT":
            smtp.port = ivalue
        elif key == "SMTP_USER":
            smtp.user = str(value)
        elif key == "SMTP_PWD":
            smtp.pwd = str(value)
        elif key == "SMTP_TO":
            smtp.to = str(value)
        elif key == "SMTP_FROM":
            smtp.frm = str(value)
        elif key == "SMTP_SUBJ":
            smtp.subj = str(value)
        elif key == "SMTP_ALERT":
            smtp.alert = ivalue

    # ---------------------------------------------------------- convenience
    def set_pit_temp_f(self, temp_f: float) -> None:
        """Force the pit temperature to ``temp_f`` degF (thermal + wire in sync)."""
        self._pit.temp_f = float(temp_f)
        self._state.cook.temp = float_to_tenths(temp_f)
        self._prev_cook_temp_tenths = self._state.cook.temp

    def set_food_temp_f(self, probe: str, temp_f: float) -> None:
        """Force a food probe's temperature to ``temp_f`` degF.

        Args:
            probe: ``"food1"``/``"food2"``/``"food3"``.
            temp_f: The temperature to set in whole degF.

        Raises:
            KeyError: If ``probe`` is not a food probe id.
        """
        if probe not in _FOOD_KEYS:
            raise KeyError(f"unknown food probe: {probe!r}")
        getattr(self._state, probe).temp = float_to_tenths(temp_f)
        meat = self._meats[probe]
        if meat is not None:
            meat.temp_f = float(temp_f)

    def set_pit_set_f(self, set_f: float) -> None:
        """Set the pit setpoint (COOK_SET) in whole degF."""
        self._state.cook.set = float_to_tenths(set_f)

    def clear_alarms(self) -> None:
        """Clear latched timeout/alarm state (emulates an admin/keypress clear)."""
        self._sim.timeout_hold_active = False
        self._sim.timeout_shutdown_active = False
        self._state.timer.status = StatusCode.OK
        self._state.timer.running = self._state.timer.remaining_s > 0

    def disconnect_probe(self, probe: str) -> None:
        """Force a probe OPEN (temp=None, STATUS=ERROR)."""
        p = self.read(probe)
        p.connected = False
        p.temp = None
        p.status = StatusCode.ERROR

    def reconnect_probe(self, probe: str) -> None:
        """Reconnect a probe; physics repopulates its reading next tick."""
        p = self.read(probe)
        p.connected = True
        p.status = StatusCode.OK

    # ----------------------------------------------------------- profiles
    def set_profile(self, profile: CookProfile) -> None:
        """Load a full :class:`CookProfile` (pit + up to 3 food profiles).

        Rebuilds the thermal models, resets the hidden physical state, and syncs
        the visible probe temps/setpoints from the profile. Names and setpoints
        already on the device are preserved unless the profile overrides them.
        """
        self._pit = PitThermal.from_profile(profile.pit)
        self._state.cook.set = float_to_tenths(profile.pit.cook_set_f)
        self._sim = SimState()
        self._prev_cook_temp_tenths = None
        for key, meat_profile in profile.foods().items():
            self.set_food_profile(key, meat_profile)
        self._sync_probe_from_pit()

    def set_food_profile(self, probe: str, profile: MeatProfile | None) -> None:
        """Set (or clear) one food probe's :class:`MeatProfile`.

        Args:
            probe: ``"food1"``/``"food2"``/``"food3"``.
            profile: The meat profile, or ``None`` to leave the probe as-is.

        Raises:
            KeyError: If ``probe`` is not a food probe id.
        """
        if probe not in _FOOD_KEYS:
            raise KeyError(f"unknown food probe: {probe!r}")
        if profile is None:
            return
        p: ProbeState = getattr(self._state, probe)
        p.set = float_to_tenths(profile.set_f)
        if profile.cut is not None:
            p.name = profile.cut
        if not profile.connected:
            p.connected = False
            p.temp = None
            p.status = StatusCode.ERROR
            self._meats[probe] = None
            return
        p.connected = True
        meat = MeatThermal.from_profile(profile)
        self._meats[probe] = meat
        p.temp = float_to_tenths(meat.temp_f)
        self._sim.meat_moisture[probe] = meat.moisture

    def set_persona(self, fwver: str) -> str:
        """Switch the firmware persona (affects e.g. SHUTDOWN behavior).

        Args:
            fwver: Firmware version string (e.g. ``"1.7"``/``"2.3"``/``"3.1"``).

        Returns:
            The new firmware version.
        """
        self._state.fwver = str(fwver)
        return self._state.fwver

    # ----------------------------------------------------------- reset/state
    def reset(self, mode: str = "factory") -> DeviceState:
        """Reset to ``"factory"`` or ``"demo"`` defaults. Returns the new state.

        Raises:
            ValueError: If ``mode`` is not ``"factory"`` or ``"demo"``.
        """
        fwver = self._state.fwver
        if mode == "factory":
            self._reset_to(factory_state(fwver=fwver))
        elif mode == "demo":
            self._reset_to(demo_state(fwver=fwver))
        else:
            raise ValueError("mode must be 'factory' or 'demo'")
        return self._state

    def _reset_to(self, state: DeviceState) -> None:
        """Replace device state and rebuild the derived thermal/sim state."""
        self._state = state
        self._sim = SimState()
        self._pit = PitThermal.from_profile(PitProfile(cook_set_f=tenths_to_float(state.cook.set)))
        self._meats = {"food1": None, "food2": None, "food3": None}
        self._prev_cook_temp_tenths = None
        self._faults.clear_all()
        self._sync_probe_from_pit()

    def _sync_probe_from_pit(self) -> None:
        """Seed the pit probe reading from the thermal model's current temp."""
        self._state.cook.temp = float_to_tenths(self._pit.temp_f)
        self._prev_cook_temp_tenths = self._state.cook.temp

    # -------------------------------------------------------- snapshot/restore
    def snapshot(self) -> dict[str, Any]:
        """Serialize the full simulation to a plain, JSON-friendly ``dict``.

        Captures device state, hidden sim state, clock, RNG, thermal models, and
        active faults so :meth:`restore` reproduces the run exactly.
        """
        return {
            "state": _to_plain(self._state),
            "sim": _to_plain(self._sim),
            "clock": {"now": self._clock.now(), "speed": self._clock.speed},
            "rng": {"seed": self._rng.current_seed, "draws": self._rng.draws},
            "pit": _to_plain(self._pit),
            "meats": {k: (_to_plain(v) if v is not None else None) for k, v in self._meats.items()},
            "faults": [_to_plain(f) for f in self._faults.list()],
            "prev_cook_temp_tenths": self._prev_cook_temp_tenths,
        }

    def restore(self, blob: dict[str, Any]) -> None:
        """Restore a :meth:`snapshot` blob, replacing all live state.

        Args:
            blob: A dict previously produced by :meth:`snapshot`.
        """
        self._state = _rebuild_device_state(blob["state"])
        self._sim = _rebuild_sim_state(blob["sim"])
        self._clock = VirtualClock(speed=blob["clock"]["speed"], start=blob["clock"]["now"])
        self._rng = SeededRNG(blob["rng"]["seed"])
        for _ in range(int(blob["rng"]["draws"])):
            self._rng.random()
        self._pit = _rebuild_pit(blob["pit"])
        self._meats = {
            k: (_rebuild_meat(v) if v is not None else None) for k, v in blob["meats"].items()
        }
        self._faults = FaultRegistry(self._clock, self._rng)
        for f in blob["faults"]:
            self._faults.inject(_rebuild_fault(f))
        self._prev_cook_temp_tenths = blob.get("prev_cook_temp_tenths")


# ------------------------------------------------------------- serialization
def _to_plain(obj: object) -> object:
    """Recursively convert dataclasses/enums to plain JSON-friendly values."""
    from dataclasses import fields, is_dataclass
    from enum import Enum

    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return int(obj.value) if isinstance(obj.value, int) else obj.value
    if isinstance(obj, dict):
        return {k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(v) for v in obj]
    return obj


def _rebuild_device_state(data: dict[str, Any]) -> DeviceState:
    """Rebuild a :class:`DeviceState` from a plain dict (deep copy of input)."""
    from virtualcyberq.core.enums import (
        DegUnits,
        OnOff,
        RampSource,
        TimeoutAction,
    )
    from virtualcyberq.core.state import (
        ControlConfig,
        SmtpConfig,
        SystemConfig,
        TimerState,
        WifiConfig,
    )

    d = copy.deepcopy(data)

    def probe(pd: dict[str, Any]) -> ProbeState:
        return ProbeState(
            name=pd["name"],
            temp=pd["temp"],
            set=pd["set"],
            status=StatusCode(pd["status"]),
            connected=pd["connected"],
        )

    ctrl = d["control"]
    sysc = d["system"]
    return DeviceState(
        cook=probe(d["cook"]),
        food1=probe(d["food1"]),
        food2=probe(d["food2"]),
        food3=probe(d["food3"]),
        timer=TimerState(
            remaining_s=d["timer"]["remaining_s"],
            running=d["timer"]["running"],
            status=StatusCode(d["timer"]["status"]),
        ),
        control=ControlConfig(
            timeout_action=TimeoutAction(ctrl["timeout_action"]),
            cookhold=ctrl["cookhold"],
            alarmdev=ctrl["alarmdev"],
            cook_ramp=RampSource(ctrl["cook_ramp"]),
            opendetect=OnOff(ctrl["opendetect"]),
            cyctime=ctrl["cyctime"],
            propband=ctrl["propband"],
        ),
        system=SystemConfig(
            menu_scrolling=OnOff(sysc["menu_scrolling"]),
            lcd_backlight=sysc["lcd_backlight"],
            lcd_contrast=sysc["lcd_contrast"],
            deg_units=DegUnits(sysc["deg_units"]),
            alarm_beeps=sysc["alarm_beeps"],
            key_beeps=OnOff(sysc["key_beeps"]),
        ),
        wifi=WifiConfig(**d["wifi"]),
        smtp=SmtpConfig(**d["smtp"]),
        fwver=d["fwver"],
        output_percent=d["output_percent"],
        fan_shorted=d["fan_shorted"],
    )


def _rebuild_sim_state(data: dict[str, Any]) -> SimState:
    """Rebuild a :class:`SimState` from a plain dict."""
    d = copy.deepcopy(data)
    return SimState(
        fire=d["fire"],
        lid_open=d["lid_open"],
        fuel_remaining=d["fuel_remaining"],
        cook_armed=d["cook_armed"],
        timeout_hold_active=d["timeout_hold_active"],
        timeout_shutdown_active=d["timeout_shutdown_active"],
        meat_moisture=dict(d["meat_moisture"]),
        phase=d["phase"],
    )


def _rebuild_pit(data: dict[str, Any]) -> PitThermal:
    """Rebuild a :class:`PitThermal` (and its profile) from a plain dict."""
    d = copy.deepcopy(data)
    profile = PitProfile(**d["profile"])
    return PitThermal(
        profile=profile,
        temp_f=d["temp_f"],
        fire=d["fire"],
        fuel_remaining=d["fuel_remaining"],
        lid_open=d["lid_open"],
        elapsed_s=d["elapsed_s"],
    )


def _rebuild_meat(data: dict[str, Any]) -> MeatThermal:
    """Rebuild a :class:`MeatThermal` (and its profile) from a plain dict."""
    d = copy.deepcopy(data)
    profile = MeatProfile(**d["profile"])
    return MeatThermal(profile=profile, temp_f=d["temp_f"], moisture=d["moisture"])


def _rebuild_fault(data: dict[str, Any]) -> Fault:
    """Rebuild a :class:`Fault` from a plain dict."""
    d = copy.deepcopy(data)
    return Fault(
        id=d["id"],
        enabled=d["enabled"],
        probability=d["probability"],
        scope=list(d["scope"]),
        duration_s=d["duration_s"],
        count=d["count"],
        params=dict(d["params"]),
        activations=d["activations"],
        started_s=d["started_s"],
    )
