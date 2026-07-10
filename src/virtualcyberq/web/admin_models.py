# SPDX-License-Identifier: BSD-3-Clause
"""Pydantic v2 request/response models for the control-plane admin API.

These models validate and shape the JSON on the ``/__admin`` surface (DESIGN
section 9). They are deliberately permissive where the admin plane must accept
arbitrary state fragments (``PATCH /__admin/state``) and strict where the shape
is well-defined (time ops, fault records, rng seed).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "AdvanceRequest",
    "AssertRequest",
    "AssertResponse",
    "FaultModel",
    "HealthResponse",
    "MetricsResponse",
    "OkResponse",
    "PersonaRequest",
    "PersonaResponse",
    "ProbeDisconnectRequest",
    "ProfileRequest",
    "RequestRecordModel",
    "ResetRequest",
    "RestoreRequest",
    "ResumeRequest",
    "RngResponse",
    "ScaleRequest",
    "ScenarioLoadRequest",
    "ScenarioStatusResponse",
    "SeedRequest",
    "SnapshotResponse",
    "StatePatchRequest",
    "StepResponse",
    "TimeResponse",
]


class OkResponse(BaseModel):
    """Generic success envelope."""

    ok: bool = True
    detail: str | None = None


class HealthResponse(BaseModel):
    """``GET /__admin/health`` payload."""

    status: str = "ok"
    uptime: float = Field(..., description="Seconds since the server started.")
    sim_time: float = Field(..., description="Current simulated time (seconds).")


class TimeResponse(BaseModel):
    """``GET /__admin/time`` and the time-op responses."""

    now_s: float
    speed: float
    frozen: bool


class AdvanceRequest(BaseModel):
    """``POST /__admin/time/advance`` body."""

    seconds: float = Field(..., ge=0.0)


class ScaleRequest(BaseModel):
    """``POST /__admin/time/scale`` body."""

    factor: float = Field(..., ge=0.0)


class ResumeRequest(BaseModel):
    """``POST /__admin/time/resume`` body (speed optional)."""

    speed: float | None = Field(default=None, ge=0.0)


class SeedRequest(BaseModel):
    """``POST /__admin/rng/seed`` body."""

    seed: int


class RngResponse(BaseModel):
    """``GET /__admin/rng`` payload."""

    seed: int
    draws: int


class ResetRequest(BaseModel):
    """``POST /__admin/state/reset`` body."""

    mode: str = Field(default="factory", pattern="^(factory|demo)$")


class RestoreRequest(BaseModel):
    """``POST /__admin/state/restore`` body."""

    blob: dict[str, Any]


class SnapshotResponse(BaseModel):
    """``POST /__admin/state/snapshot`` payload."""

    snapshot_id: str
    blob: dict[str, Any]


class FaultModel(BaseModel):
    """A :class:`~virtualcyberq.core.faults.Fault` on the wire (DESIGN section 8)."""

    id: str
    enabled: bool = True
    probability: float = 1.0
    scope: list[str] = Field(default_factory=lambda: ["*"])
    duration_s: float | None = None
    count: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    activations: int = 0
    started_s: float = 0.0


class ProbeDisconnectRequest(BaseModel):
    """``POST /__admin/probes/{probe}/disconnect`` body."""

    duration_s: float | None = Field(default=None, ge=0.0)


class PersonaRequest(BaseModel):
    """``POST /__admin/persona`` body."""

    fwver: str


class PersonaResponse(BaseModel):
    """``POST /__admin/persona`` payload."""

    fwver: str


class ProfileRequest(BaseModel):
    """``POST /__admin/profile`` body: a cook definition (pit + food profiles).

    Fields mirror the scenario ``profile`` block; each food maps to a cut name or
    a raw meat-profile fragment. Values are whole-degF (the profile convention).
    """

    pit: dict[str, Any] | None = None
    food1: dict[str, Any] | None = None
    food2: dict[str, Any] | None = None
    food3: dict[str, Any] | None = None


class ScenarioLoadRequest(BaseModel):
    """``POST /__admin/scenario/load`` body: either a builtin ``name`` or inline.

    Provide ``name`` to load a shipped builtin, or ``scenario`` with an inline
    scenario document (already-parsed dict). ``yaml`` accepts raw YAML/JSON text.
    """

    name: str | None = None
    scenario: dict[str, Any] | None = None
    yaml: str | None = None


class ScenarioStatusResponse(BaseModel):
    """``GET /__admin/scenario`` payload."""

    name: str | None = None
    step: int = 0
    total_steps: int = 0
    done: bool = True


class StepResponse(BaseModel):
    """``POST /__admin/scenario/step`` payload."""

    step: int
    done: bool


class AssertRequest(BaseModel):
    """``POST /__admin/assert`` body: a predicate over device/sim/time state.

    The predicate is a dict of ``target -> comparator`` where ``target`` is a
    dotted path (e.g. ``food1_temp_f``, ``pit_temp_f``, ``food1_status``,
    ``sim_time``) and the comparator is either a literal (equality) or a mapping
    of comparison operators (``{">=": 150, "<=": 170}``).
    """

    predicate: dict[str, Any]


class AssertResponse(BaseModel):
    """``POST /__admin/assert`` payload."""

    ok: bool
    detail: str


class MetricsResponse(BaseModel):
    """``GET /__admin/metrics`` payload (JSON form)."""

    requests: int
    faults_fired: int
    errors: int
    sim_time: float


class RequestRecordModel(BaseModel):
    """One entry from the request journal (``GET /__admin/requests``)."""

    method: str
    path: str
    body: str | None = None
    ts: float
    fired: list[str] = Field(default_factory=list)


class StatePatchRequest(BaseModel):
    """``PATCH /__admin/state`` body: an arbitrary partial state fragment.

    Accepts a free-form nested dict that mirrors the :class:`DeviceState`
    structure (or the flat convenience keys ``pit_temp_f`` / ``food1_temp_f`` /
    ``cook_set_f``). Applied best-effort, bypassing wire validation.
    """

    model_config = {"extra": "allow"}
