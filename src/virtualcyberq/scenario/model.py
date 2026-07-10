# SPDX-License-Identifier: BSD-3-Clause
"""Pydantic scenario schema (DESIGN section 10).

A scenario declares:

* metadata (``name``, ``description``),
* a starting ``seed`` / ``speed`` / ``persona``,
* an ``initial`` block (``state`` fragment + ``profile`` block), and
* a ``timeline`` of time-ordered steps, each of which runs ``at`` a simulated
  time and does exactly one of: ``set`` state, ``profile`` change, ``fault``
  inject, ``time`` op, or ``assert``.

Time literals accept ``s`` / ``m`` / ``h`` combinations (``3h30m``, ``600``,
``90s``). Temperatures are whole-degF in ``profile`` and ``*_f`` asserts, and
tenths-degF when writing raw state (mirroring the wire's dual representation).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "AssertStep",
    "FaultStep",
    "InitialSpec",
    "ProfileStep",
    "Scenario",
    "SetStep",
    "TimeStep",
    "TimelineStep",
    "parse_duration",
]

_DUR_RE = re.compile(r"(?P<val>\d+(?:\.\d+)?)(?P<unit>[smh])", re.IGNORECASE)
_UNIT_S = {"s": 1.0, "m": 60.0, "h": 3600.0}


def parse_duration(value: str | int | float) -> float:
    """Parse a duration literal to seconds.

    Accepts a bare number (seconds) or a compound ``s``/``m``/``h`` literal such
    as ``"3h30m"``, ``"90s"``, ``"20m"``, or ``"250"``.

    Args:
        value: The duration literal (str) or a numeric second count.

    Returns:
        The duration in seconds as a float.

    Raises:
        ValueError: If a string literal cannot be parsed.
    """
    if isinstance(value, bool):
        raise ValueError("duration must not be a bool")
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text:
        raise ValueError("empty duration")
    try:
        return float(text)  # bare number of seconds
    except ValueError:
        pass
    total = 0.0
    pos = 0
    matched = False
    for m in _DUR_RE.finditer(text):
        if m.start() != pos:
            raise ValueError(f"invalid duration literal: {value!r}")
        total += float(m.group("val")) * _UNIT_S[m.group("unit").lower()]
        pos = m.end()
        matched = True
    if not matched or pos != len(text):
        raise ValueError(f"invalid duration literal: {value!r}")
    return total


class InitialSpec(BaseModel):
    """The ``initial`` block: a raw state fragment and/or a cook profile."""

    state: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None


class SetStep(BaseModel):
    """A ``set`` step: write raw device-state fields (tenths-degF for temps)."""

    at: float = 0.0
    set: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _coerce_at(cls, data: Any) -> Any:
        return _coerce_at(data)


class ProfileStep(BaseModel):
    """A ``profile`` step: swap the pit and/or food profiles mid-run."""

    at: float = 0.0
    profile: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _coerce_at(cls, data: Any) -> Any:
        return _coerce_at(data)


class FaultStep(BaseModel):
    """A ``fault`` step: inject (or clear) a fault at a timeline point."""

    at: float = 0.0
    fault: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _coerce_at(cls, data: Any) -> Any:
        return _coerce_at(data)


class TimeStep(BaseModel):
    """A ``time`` step: a clock op (``{scale: 600}`` / ``{freeze: true}`` ...)."""

    at: float = 0.0
    time: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _coerce_at(cls, data: Any) -> Any:
        return _coerce_at(data)


class AssertStep(BaseModel):
    """An ``assert`` step: a predicate over device/sim/time state at ``at``."""

    at: float = 0.0
    assert_: dict[str, Any] = Field(..., alias="assert")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_at(cls, data: Any) -> Any:
        return _coerce_at(data)


#: A timeline entry is exactly one of the concrete step kinds.
TimelineStep = SetStep | ProfileStep | FaultStep | TimeStep | AssertStep


def _coerce_at(data: Any) -> Any:
    """Normalize a raw step dict's ``at`` field from a duration literal to seconds."""
    if isinstance(data, dict) and "at" in data:
        data = dict(data)
        data["at"] = parse_duration(data["at"])
    return data


def _classify_step(raw: dict[str, Any]) -> TimelineStep:
    """Build the concrete step model from a raw timeline dict."""
    if "set" in raw:
        return SetStep.model_validate(raw)
    if "profile" in raw:
        return ProfileStep.model_validate(raw)
    if "fault" in raw:
        return FaultStep.model_validate(raw)
    if "time" in raw:
        return TimeStep.model_validate(raw)
    if "assert" in raw:
        return AssertStep.model_validate(raw)
    raise ValueError(f"timeline step has no known action: {raw!r}")


class Scenario(BaseModel):
    """A full declarative scenario (DESIGN section 10)."""

    name: str
    description: str | None = None
    seed: int = 0
    speed: float = 0.0
    persona: str | None = None
    initial: InitialSpec = Field(default_factory=InitialSpec)
    timeline: list[TimelineStep] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _build_timeline(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("timeline"), list):
            data = dict(data)
            steps = []
            for raw in data["timeline"]:
                if isinstance(raw, dict):
                    steps.append(_classify_step(raw))
                else:
                    steps.append(raw)
            data["timeline"] = steps
        return data

    def sorted_timeline(self) -> list[TimelineStep]:
        """Return the timeline stably sorted by ``at`` (same-``at`` order kept)."""
        return sorted(self.timeline, key=lambda s: s.at)
