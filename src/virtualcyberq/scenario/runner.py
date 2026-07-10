# SPDX-License-Identifier: BSD-3-Clause
"""Drive a :class:`Simulation` deterministically along a scenario timeline.

The :class:`ScenarioRunner` loads a :class:`~virtualcyberq.scenario.model.Scenario`,
applies its ``initial`` block (seed, persona, state, profile), then walks the
``timeline`` in time order. For each step it advances the virtual clock to the
step's ``at`` time (deterministic ``sim.advance``) and applies the step's action:

* ``set``     -- write raw device-state fields (tenths-degF for temps),
* ``profile`` -- swap the pit / food profiles,
* ``fault``   -- inject a fault (or clear one),
* ``time``    -- a clock op (scale/freeze/resume/advance),
* ``assert``  -- evaluate a predicate over device/sim/time state, raising
  :class:`AssertionFailure` on mismatch.

Everything is deterministic under a fixed seed + identical advances.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from virtualcyberq.core.enums import (
    DegUnits,
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
)
from virtualcyberq.core.faults import Fault
from virtualcyberq.core.profiles import (
    CookProfile,
    MeatProfile,
    PitProfile,
    meat_profile_for_cut,
)
from virtualcyberq.core.simulation import Simulation
from virtualcyberq.scenario.model import (
    AssertStep,
    FaultStep,
    ProfileStep,
    Scenario,
    SetStep,
    TimelineStep,
    TimeStep,
)

__all__ = [
    "BUILTIN_DIR",
    "AssertionFailure",
    "ScenarioRunner",
    "builtin_names",
    "load_builtin",
    "load_scenario",
]

#: Directory holding the shipped builtin scenarios.
BUILTIN_DIR = Path(__file__).parent / "builtin"


class AssertionFailure(AssertionError):
    """Raised when a scenario ``assert`` step's predicate does not hold."""


# --------------------------------------------------------------------- loading
def load_scenario(source: Any) -> Scenario:
    """Load a :class:`Scenario` from a dict, YAML/JSON text, or a file path.

    Args:
        source: A parsed dict, a YAML/JSON string, or a filesystem path.

    Returns:
        The validated :class:`Scenario`.
    """
    if isinstance(source, Scenario):
        return source
    if isinstance(source, dict):
        return Scenario.model_validate(source)
    if isinstance(source, Path):
        return Scenario.model_validate(yaml.safe_load(source.read_text()))
    if isinstance(source, str):
        # A path if it exists, else treat as inline YAML/JSON text.
        candidate = Path(source)
        if candidate.exists():
            return Scenario.model_validate(yaml.safe_load(candidate.read_text()))
        return Scenario.model_validate(yaml.safe_load(source))
    raise TypeError(f"unsupported scenario source: {type(source)!r}")


def builtin_names() -> tuple[str, ...]:
    """Return the names of the shipped builtin scenarios (without extension)."""
    if not BUILTIN_DIR.is_dir():
        return ()
    return tuple(sorted(p.stem for p in BUILTIN_DIR.glob("*.yaml")))


def load_builtin(name: str) -> Scenario:
    """Load a shipped builtin scenario by name (with or without ``.yaml``).

    Raises:
        FileNotFoundError: If no builtin with that name exists.
    """
    stem = name[:-5] if name.endswith(".yaml") else name
    path = BUILTIN_DIR / f"{stem}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no builtin scenario: {name!r}")
    return load_scenario(path)


# --------------------------------------------------------------------- runner
class ScenarioRunner:
    """Drives a :class:`Simulation` through a scenario's timeline deterministically.

    Args:
        sim: The :class:`Simulation` to drive.
        scenario: The :class:`Scenario` to run.
        apply_initial: Whether to apply the scenario's ``initial`` block (seed,
            persona, state, profile) on construction. Defaults to ``True``.
    """

    def __init__(self, sim: Simulation, scenario: Scenario, *, apply_initial: bool = True) -> None:
        self._sim = sim
        self._scenario = scenario
        self._steps: list[TimelineStep] = scenario.sorted_timeline()
        self._index = 0
        if apply_initial:
            self.apply_initial()

    @property
    def scenario(self) -> Scenario:
        """The scenario being run."""
        return self._scenario

    @property
    def index(self) -> int:
        """The number of timeline steps applied so far."""
        return self._index

    @property
    def total_steps(self) -> int:
        """The total number of timeline steps."""
        return len(self._steps)

    @property
    def done(self) -> bool:
        """``True`` when every timeline step has run."""
        return self._index >= len(self._steps)

    # ------------------------------------------------------------ initial block
    def apply_initial(self) -> None:
        """Apply seed, persona, initial state fragment, and initial profile."""
        self._sim.seed(self._scenario.seed)
        if self._scenario.persona:
            self._sim.set_persona(self._scenario.persona)
        initial = self._scenario.initial
        if initial.profile:
            self._sim.set_profile(_build_cook_profile(initial.profile))
        if initial.state:
            _apply_state_fragment(self._sim, initial.state)

    # ------------------------------------------------------------ stepping
    def step(self) -> bool:
        """Advance to and apply the next timeline step.

        Advances the simulation clock to the step's ``at`` time (if it is ahead
        of the current sim time), then applies the step.

        Returns:
            ``True`` if a step was applied; ``False`` if the timeline is done.
        """
        if self.done:
            return False
        step = self._steps[self._index]
        self._advance_to(step.at)
        # Advance the cursor before applying so a failed ``assert`` (which raises
        # :class:`AssertionFailure`) still moves past the step -- a retrying
        # stepper continues rather than re-running the same failing step.
        self._index += 1
        self._apply_step(step)
        return True

    def run(self) -> None:
        """Run every remaining timeline step to completion."""
        while self.step():
            pass

    def _advance_to(self, at_s: float) -> None:
        """Advance the sim clock forward to ``at_s`` (never backward)."""
        delta = at_s - self._sim.now()
        if delta > 0:
            self._sim.advance(delta)

    def _apply_step(self, step: TimelineStep) -> None:
        """Dispatch one timeline step to its handler."""
        if isinstance(step, SetStep):
            _apply_state_fragment(self._sim, step.set)
        elif isinstance(step, ProfileStep):
            self._sim.set_profile(_build_cook_profile(step.profile))
        elif isinstance(step, FaultStep):
            self._apply_fault(step.fault)
        elif isinstance(step, TimeStep):
            self._apply_time(step.time)
        elif isinstance(step, AssertStep):
            evaluate_predicate(self._sim, step.assert_, raise_on_fail=True)

    def _apply_fault(self, spec: dict[str, Any]) -> None:
        """Inject or clear a fault from a timeline ``fault`` spec."""
        fault_id = spec["id"]
        if spec.get("clear"):
            self._sim.faults.clear(fault_id)
            return
        self._sim.faults.inject(fault_from_spec(spec))

    def _apply_time(self, spec: dict[str, Any]) -> None:
        """Apply a timeline ``time`` op."""
        if "scale" in spec:
            self._sim.set_speed(float(spec["scale"]))
        if spec.get("freeze"):
            self._sim.freeze()
        if "resume" in spec:
            val = spec["resume"]
            self._sim.resume(None if val in (True, None) else float(val))
        if "advance" in spec:
            from virtualcyberq.scenario.model import parse_duration

            self._sim.advance(parse_duration(spec["advance"]))


# --------------------------------------------------------------------- helpers
def fault_from_spec(spec: dict[str, Any]) -> Fault:
    """Build a :class:`Fault` from a scenario/admin fault spec dict."""
    return Fault(
        id=spec["id"],
        enabled=spec.get("enabled", True),
        probability=float(spec.get("probability", 1.0)),
        scope=list(spec.get("scope", ["*"])),
        duration_s=spec.get("duration_s"),
        count=spec.get("count"),
        params=dict(spec.get("params", {})),
    )


def _build_cook_profile(spec: dict[str, Any]) -> CookProfile:
    """Build a :class:`CookProfile` from a scenario ``profile`` block."""
    pit = _build_pit_profile(spec.get("pit"))
    return CookProfile(
        pit=pit,
        food1=_build_meat_profile(spec.get("food1")),
        food2=_build_meat_profile(spec.get("food2")),
        food3=_build_meat_profile(spec.get("food3")),
    )


def _build_pit_profile(spec: dict[str, Any] | None) -> PitProfile:
    """Build a :class:`PitProfile` from a ``pit`` spec (whole-degF fields)."""
    if not spec:
        return PitProfile()
    fields = {k: v for k, v in spec.items() if hasattr(PitProfile, k)}
    return PitProfile(**fields)


def _build_meat_profile(spec: dict[str, Any] | None) -> MeatProfile | None:
    """Build a :class:`MeatProfile` from a ``foodN`` spec, honoring ``cut``.

    ``{disconnected: true}`` yields an unplugged probe; ``{cut: brisket, ...}``
    seeds per-cut defaults with overrides.
    """
    if not spec:
        return None
    if spec.get("disconnected"):
        return MeatProfile(connected=False)
    cut = spec.get("cut")
    if cut:
        profile = meat_profile_for_cut(
            cut,
            set_f=spec.get("set_f"),
            mass_lb=spec.get("mass_lb"),
            wrapped=bool(spec.get("wrapped", False)),
        )
        if "start_f" in spec:
            profile.start_f = float(spec["start_f"])
        return profile
    fields = {k: v for k, v in spec.items() if hasattr(MeatProfile, k)}
    return MeatProfile(**fields)


# --- raw state writes (tenths-degF for temps; bypasses wire validation) ------
def _apply_state_fragment(sim: Simulation, fragment: dict[str, Any]) -> None:
    """Apply a raw device-state fragment (DESIGN 10 ``set`` / initial state).

    Understands both nested blocks (``{cook: {set: 2500}}``, ``{control:
    {propband: 25}}``) and flat convenience keys (``pit_temp_f``, ``cook_set_f``,
    ``food1_temp_f``). Nested temperature values are tenths-degF; ``*_f``
    convenience keys are whole-degF.
    """
    state = sim.state
    for key, value in fragment.items():
        if key in ("cook", "food1", "food2", "food3"):
            _apply_probe_fragment(getattr(state, key), value)
        elif key == "control":
            _apply_control_fragment(state.control, value)
        elif key == "system":
            _apply_system_fragment(state.system, value)
        elif key == "timer":
            _apply_timer_fragment(state, value)
        elif key == "pit_temp_f":
            sim.set_pit_temp_f(float(value))
        elif key == "cook_set_f":
            sim.set_pit_set_f(float(value))
        elif key in ("food1_temp_f", "food2_temp_f", "food3_temp_f"):
            sim.set_food_temp_f(key.split("_")[0], float(value))
        elif key == "fwver":
            sim.set_persona(str(value))
        elif key == "output_percent":
            state.output_percent = int(value)


def _apply_probe_fragment(probe: Any, value: dict[str, Any]) -> None:
    """Apply a raw probe fragment (``temp``/``set`` are tenths-degF)."""
    if "temp" in value:
        probe.temp = None if value["temp"] is None else int(value["temp"])
    if "set" in value:
        probe.set = int(value["set"])
    if "name" in value:
        probe.name = str(value["name"])
    if "status" in value:
        probe.status = StatusCode(int(value["status"]))
    if "connected" in value:
        probe.connected = bool(value["connected"])


def _apply_control_fragment(control: Any, value: dict[str, Any]) -> None:
    """Apply a raw ``control`` fragment (temps tenths; enums by name or int)."""
    for k, v in value.items():
        if k == "timeout_action":
            control.timeout_action = _enum(TimeoutAction, v)
        elif k == "cook_ramp":
            control.cook_ramp = _enum(RampSource, v)
        elif k == "opendetect":
            control.opendetect = _enum(OnOff, v)
        elif k in ("cookhold", "alarmdev", "propband"):
            setattr(control, k, int(v))
        elif k == "cyctime":
            control.cyctime = int(v)


def _apply_system_fragment(system: Any, value: dict[str, Any]) -> None:
    """Apply a raw ``system`` fragment."""
    for k, v in value.items():
        if k == "deg_units":
            system.deg_units = _enum(DegUnits, v)
        elif k in ("menu_scrolling", "key_beeps"):
            setattr(system, k, _enum(OnOff, v))
        elif k in ("lcd_backlight", "lcd_contrast", "alarm_beeps"):
            setattr(system, k, int(v))


def _apply_timer_fragment(state: Any, value: dict[str, Any]) -> None:
    """Apply a raw ``timer`` fragment."""
    if "remaining_s" in value:
        state.timer.remaining_s = int(value["remaining_s"])
        state.timer.running = state.timer.remaining_s > 0
    if "running" in value:
        state.timer.running = bool(value["running"])
    if "status" in value:
        state.timer.status = StatusCode(int(value["status"]))


def _enum(enum_cls: Any, value: Any) -> Any:
    """Coerce ``value`` (an int or a member name) to ``enum_cls``."""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        return enum_cls[value.strip().upper()]
    return enum_cls(int(value))


# --- assertion evaluation ----------------------------------------------------
_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}

_STATUS_NAMES = {s.name: int(s.value) for s in StatusCode}


def resolve_target(sim: Simulation, target: str) -> Any:
    """Resolve a predicate target (e.g. ``pit_temp_f``, ``food1_status``).

    Supported targets:

    * ``sim_time`` / ``now_s`` -- simulated seconds.
    * ``output_percent`` -- fan duty.
    * ``pit_temp_f`` / ``food{1,2,3}_temp_f`` -- whole-degF temperature (``None``
      for an open probe).
    * ``pit_set_f`` / ``food{1,2,3}_set_f`` -- whole-degF setpoints.
    * ``pit_status`` / ``cook_status`` / ``food{1,2,3}_status`` / ``timer_status``
      -- integer status code.
    """
    state = sim.state
    if target in ("sim_time", "now_s"):
        return sim.now()
    if target == "output_percent":
        return state.output_percent
    if target == "timer_status":
        return int(state.timer.status.value)
    probe_map = {
        "pit": state.cook,
        "cook": state.cook,
        "food1": state.food1,
        "food2": state.food2,
        "food3": state.food3,
    }
    for prefix, probe in probe_map.items():
        if target == f"{prefix}_temp_f":
            return None if probe.temp is None else probe.temp / 10.0
        if target == f"{prefix}_set_f":
            return probe.set / 10.0
        if target == f"{prefix}_status":
            return int(probe.status.value)
    raise KeyError(f"unknown assert target: {target!r}")


def _coerce_expected(expected: Any) -> Any:
    """Coerce an expected literal, mapping status names (``DONE``) to ints."""
    if isinstance(expected, str) and expected.upper() in _STATUS_NAMES:
        return _STATUS_NAMES[expected.upper()]
    return expected


def evaluate_predicate(
    sim: Simulation, predicate: dict[str, Any], *, raise_on_fail: bool = False
) -> tuple[bool, str]:
    """Evaluate an assert predicate over the current simulation state.

    Args:
        sim: The simulation to read.
        predicate: Mapping of ``target -> literal`` (equality) or
            ``target -> {comparator: value, ...}``.
        raise_on_fail: When ``True``, raise :class:`AssertionFailure` on the first
            failed clause instead of returning ``(False, detail)``.

    Returns:
        ``(ok, detail)`` -- ``ok`` is ``True`` when every clause holds; ``detail``
        describes the first failure (or ``"ok"``).
    """
    for target, spec in predicate.items():
        actual = resolve_target(sim, target)
        clauses = spec.items() if isinstance(spec, dict) else [("==", spec)]
        for op, expected in clauses:
            exp = _coerce_expected(expected)
            comparator = _COMPARATORS.get(op)
            if comparator is None:
                raise ValueError(f"unknown comparator: {op!r}")
            ok = actual is not None and comparator(actual, exp)
            if not ok:
                detail = f"{target} ({actual!r}) failed {op} {exp!r}"
                if raise_on_fail:
                    raise AssertionFailure(detail)
                return False, detail
    return True, "ok"
