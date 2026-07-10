# SPDX-License-Identifier: BSD-3-Clause
"""Declarative scenarios (DESIGN section 10).

A scenario is a YAML/JSON document with metadata, a starting ``seed``/``speed``/
``persona``, an ``initial`` state + profile, and a time-ordered ``timeline`` of
steps (``set`` / ``profile`` / ``fault`` / ``time`` / ``assert``). The
:class:`~virtualcyberq.scenario.model.Scenario` Pydantic model validates it and
the :class:`~virtualcyberq.scenario.runner.ScenarioRunner` drives a
:class:`~virtualcyberq.core.simulation.Simulation` deterministically along it.
"""

from __future__ import annotations

from virtualcyberq.scenario.model import (
    AssertStep,
    FaultStep,
    InitialSpec,
    ProfileStep,
    Scenario,
    SetStep,
    TimelineStep,
    TimeStep,
    parse_duration,
)
from virtualcyberq.scenario.runner import (
    AssertionFailure,
    ScenarioRunner,
    builtin_names,
    load_builtin,
    load_scenario,
)

__all__ = [
    "AssertStep",
    "AssertionFailure",
    "FaultStep",
    "InitialSpec",
    "ProfileStep",
    "Scenario",
    "ScenarioRunner",
    "SetStep",
    "TimeStep",
    "TimelineStep",
    "builtin_names",
    "load_builtin",
    "load_scenario",
    "parse_duration",
]
