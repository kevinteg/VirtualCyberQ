# SPDX-License-Identifier: BSD-3-Clause
"""The control-plane (admin) FastAPI app (DESIGN section 9).

Every route is namespaced under ``/__admin``; Swagger UI is at ``/__admin/docs``
and the OpenAPI spec at ``/__admin/openapi.json``. All operations drive the same
shared :class:`~virtualcyberq.core.simulation.Simulation` that the device plane
serves, so a test can puppeteer physics/time/faults out-of-band while a client
polls the device surface.

The endpoint surface mirrors the DESIGN section 9 table exactly: health,
state get/patch/reset/snapshot/restore, probes disconnect/reconnect, time
advance/scale/freeze/resume/now, faults CRUD, rng seed, scenario load/step/stop,
profile, persona, requests journal, metrics, and assert.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from fastapi import Body, FastAPI, HTTPException, Query, Response

from virtualcyberq.core.faults import Fault
from virtualcyberq.core.personas import PERSONAS, get_persona
from virtualcyberq.core.simulation import _to_plain  # JSON-friendly serializer
from virtualcyberq.scenario import (
    ScenarioRunner,
    load_builtin,
    load_scenario,
)
from virtualcyberq.scenario.runner import (
    _apply_state_fragment,
    _build_cook_profile,
    evaluate_predicate,
    fault_from_spec,
)
from virtualcyberq.web.admin_models import (
    AdvanceRequest,
    AssertRequest,
    AssertResponse,
    FaultModel,
    HealthResponse,
    MetricsResponse,
    PersonaRequest,
    PersonaResponse,
    ProbeDisconnectRequest,
    ProfileRequest,
    ResetRequest,
    RestoreRequest,
    ResumeRequest,
    RngResponse,
    ScaleRequest,
    ScenarioLoadRequest,
    ScenarioStatusResponse,
    SeedRequest,
    SnapshotResponse,
    StepResponse,
    TimeResponse,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from virtualcyberq.core.simulation import Simulation
    from virtualcyberq.web.server import RequestJournal

__all__ = ["ADMIN_PREFIX", "build_admin_app"]

#: The admin URL prefix (all admin routes live under it).
ADMIN_PREFIX = "/__admin"

_PROBES = ("cook", "food1", "food2", "food3")


def build_admin_app(
    sim: Simulation,
    *,
    journal: RequestJournal | None = None,
    started_at: float | None = None,
) -> FastAPI:
    """Build the control-plane FastAPI app over a shared simulation.

    Args:
        sim: The shared :class:`~virtualcyberq.core.simulation.Simulation`.
        journal: The request journal shared with the device app (for the
            ``/__admin/requests`` and metrics endpoints).
        started_at: The wall-clock start time (for ``/health`` uptime); defaults
            to now.

    Returns:
        A configured :class:`fastapi.FastAPI` admin app with Swagger at
        ``/__admin/docs`` and the spec at ``/__admin/openapi.json``.
    """
    boot = started_at if started_at is not None else time.time()
    app = FastAPI(
        title="VirtualCyberQ Admin API",
        description="Out-of-band control plane for the virtual CyberQ device.",
        version="0.1.0",
        docs_url=f"{ADMIN_PREFIX}/docs",
        redoc_url=f"{ADMIN_PREFIX}/redoc",
        openapi_url=f"{ADMIN_PREFIX}/openapi.json",
    )
    app.state.sim = sim
    app.state.journal = journal
    # Mutable holder for the active scenario runner (rebound on load/stop).
    runner_holder: dict[str, ScenarioRunner | None] = {"runner": None}
    metrics = {"errors": 0}

    # ------------------------------------------------------------------ health
    @app.get(f"{ADMIN_PREFIX}/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", uptime=time.time() - boot, sim_time=sim.now())

    # ------------------------------------------------------------------- state
    @app.get(f"{ADMIN_PREFIX}/state", tags=["state"])
    async def get_state() -> dict[str, Any]:
        return {
            "state": _to_plain(sim.state),
            "sim": _to_plain(sim.sim_state),
            "time": {
                "now_s": sim.now(),
                "speed": sim.clock.speed,
                "frozen": sim.clock.frozen,
            },
        }

    @app.patch(f"{ADMIN_PREFIX}/state", tags=["state"])
    async def patch_state(fragment: dict[str, Any] = Body(...)) -> dict[str, Any]:
        _apply_state_fragment(sim, fragment)
        return _to_plain(sim.state)  # type: ignore[return-value]

    @app.post(f"{ADMIN_PREFIX}/state/reset", tags=["state"])
    async def reset_state(req: ResetRequest) -> dict[str, Any]:
        try:
            sim.reset(req.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_plain(sim.state)  # type: ignore[return-value]

    @app.post(f"{ADMIN_PREFIX}/state/snapshot", response_model=SnapshotResponse, tags=["state"])
    async def snapshot() -> SnapshotResponse:
        return SnapshotResponse(snapshot_id=uuid.uuid4().hex, blob=sim.snapshot())

    @app.post(f"{ADMIN_PREFIX}/state/restore", tags=["state"])
    async def restore(req: RestoreRequest) -> dict[str, Any]:
        try:
            sim.restore(req.blob)
        except (KeyError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"bad blob: {exc}") from exc
        return _to_plain(sim.state)  # type: ignore[return-value]

    # ------------------------------------------------------------------ probes
    @app.get(f"{ADMIN_PREFIX}/probes/{{probe}}", tags=["probes"])
    async def get_probe(probe: str) -> dict[str, Any]:
        try:
            return _to_plain(sim.read(probe))  # type: ignore[return-value]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post(f"{ADMIN_PREFIX}/probes/{{probe}}/disconnect", tags=["probes"])
    async def disconnect_probe(
        probe: str,
        req: ProbeDisconnectRequest | None = None,
    ) -> dict[str, Any]:
        req = req or ProbeDisconnectRequest()
        try:
            sim.disconnect_probe(probe)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if req.duration_s is not None:
            sim.faults.inject(
                Fault(id="probe.open", duration_s=req.duration_s, params={"probe": probe})
            )
        return _to_plain(sim.read(probe))  # type: ignore[return-value]

    @app.post(f"{ADMIN_PREFIX}/probes/{{probe}}/reconnect", tags=["probes"])
    async def reconnect_probe(probe: str) -> dict[str, Any]:
        try:
            sim.reconnect_probe(probe)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _to_plain(sim.read(probe))  # type: ignore[return-value]

    # -------------------------------------------------------------------- time
    @app.get(f"{ADMIN_PREFIX}/time", response_model=TimeResponse, tags=["time"])
    async def get_time() -> TimeResponse:
        return TimeResponse(now_s=sim.now(), speed=sim.clock.speed, frozen=sim.clock.frozen)

    @app.post(f"{ADMIN_PREFIX}/time/advance", response_model=TimeResponse, tags=["time"])
    async def advance_time(req: AdvanceRequest) -> TimeResponse:
        sim.advance(req.seconds)
        return TimeResponse(now_s=sim.now(), speed=sim.clock.speed, frozen=sim.clock.frozen)

    @app.post(f"{ADMIN_PREFIX}/time/scale", response_model=TimeResponse, tags=["time"])
    async def scale_time(req: ScaleRequest) -> TimeResponse:
        sim.set_speed(req.factor)
        return TimeResponse(now_s=sim.now(), speed=sim.clock.speed, frozen=sim.clock.frozen)

    @app.post(f"{ADMIN_PREFIX}/time/freeze", response_model=TimeResponse, tags=["time"])
    async def freeze_time() -> TimeResponse:
        sim.freeze()
        return TimeResponse(now_s=sim.now(), speed=sim.clock.speed, frozen=sim.clock.frozen)

    @app.post(f"{ADMIN_PREFIX}/time/resume", response_model=TimeResponse, tags=["time"])
    async def resume_time(
        req: ResumeRequest | None = None,
    ) -> TimeResponse:
        req = req or ResumeRequest()
        sim.resume(req.speed)
        return TimeResponse(now_s=sim.now(), speed=sim.clock.speed, frozen=sim.clock.frozen)

    # ------------------------------------------------------------------ faults
    @app.get(f"{ADMIN_PREFIX}/faults", response_model=list[FaultModel], tags=["faults"])
    async def list_faults() -> list[FaultModel]:
        return [FaultModel(**_to_plain(f)) for f in sim.faults.list()]  # type: ignore[arg-type]

    @app.post(f"{ADMIN_PREFIX}/faults", response_model=FaultModel, tags=["faults"])
    async def inject_fault(model: FaultModel) -> FaultModel:
        fault = fault_from_spec(model.model_dump())
        injected = sim.faults.inject(fault)
        return FaultModel(**_to_plain(injected))  # type: ignore[arg-type]

    @app.delete(f"{ADMIN_PREFIX}/faults/{{fault_id}}", status_code=204, tags=["faults"])
    async def clear_fault(fault_id: str) -> Response:
        sim.faults.clear(fault_id)
        return Response(status_code=204)

    @app.delete(f"{ADMIN_PREFIX}/faults", status_code=204, tags=["faults"])
    async def clear_all_faults() -> Response:
        sim.faults.clear_all()
        return Response(status_code=204)

    # --------------------------------------------------------------------- rng
    @app.get(f"{ADMIN_PREFIX}/rng", response_model=RngResponse, tags=["rng"])
    async def get_rng() -> RngResponse:
        return RngResponse(seed=sim.rng.current_seed, draws=sim.rng.draws)

    @app.post(f"{ADMIN_PREFIX}/rng/seed", response_model=RngResponse, tags=["rng"])
    async def set_seed(req: SeedRequest) -> RngResponse:
        sim.seed(req.seed)
        return RngResponse(seed=sim.rng.current_seed, draws=sim.rng.draws)

    # ---------------------------------------------------------------- scenario
    @app.get(f"{ADMIN_PREFIX}/scenario", response_model=ScenarioStatusResponse, tags=["scenario"])
    async def scenario_status() -> ScenarioStatusResponse:
        runner = runner_holder["runner"]
        if runner is None:
            return ScenarioStatusResponse(name=None, step=0, total_steps=0, done=True)
        return ScenarioStatusResponse(
            name=runner.scenario.name,
            step=runner.index,
            total_steps=runner.total_steps,
            done=runner.done,
        )

    @app.post(f"{ADMIN_PREFIX}/scenario/load", tags=["scenario"])
    async def scenario_load(req: ScenarioLoadRequest) -> dict[str, Any]:
        try:
            if req.name is not None:
                scenario = load_builtin(req.name)
            elif req.scenario is not None:
                scenario = load_scenario(req.scenario)
            elif req.yaml is not None:
                scenario = load_scenario(req.yaml)
            else:
                raise HTTPException(status_code=400, detail="no scenario source")
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runner = ScenarioRunner(sim, scenario)
        runner_holder["runner"] = runner
        return {"name": scenario.name, "total_steps": runner.total_steps}

    @app.post(f"{ADMIN_PREFIX}/scenario/step", response_model=StepResponse, tags=["scenario"])
    async def scenario_step() -> StepResponse:
        runner = runner_holder["runner"]
        if runner is None:
            raise HTTPException(status_code=409, detail="no scenario loaded")
        runner.step()
        return StepResponse(step=runner.index, done=runner.done)

    @app.post(f"{ADMIN_PREFIX}/scenario/stop", status_code=204, tags=["scenario"])
    async def scenario_stop() -> Response:
        runner_holder["runner"] = None
        return Response(status_code=204)

    # ----------------------------------------------------------------- profile
    @app.post(f"{ADMIN_PREFIX}/profile", tags=["profile"])
    async def set_profile(req: ProfileRequest) -> dict[str, Any]:
        spec = {k: v for k, v in req.model_dump().items() if v is not None}
        sim.set_profile(_build_cook_profile(spec))
        return _to_plain(sim.state)  # type: ignore[return-value]

    # ----------------------------------------------------------------- persona
    @app.get(f"{ADMIN_PREFIX}/personas", tags=["persona"])
    async def list_personas() -> dict[str, Any]:
        current = get_persona(sim.state.fwver)
        return {
            "current": current.fwver,
            "personas": [
                {
                    "fwver": p.fwver,
                    "label": p.label,
                    "verified": p.verified,
                    "shutdown_fan_off": p.shutdown_fan_off,
                    "notes": p.notes,
                }
                for p in PERSONAS.values()
            ],
        }

    @app.post(f"{ADMIN_PREFIX}/persona", response_model=PersonaResponse, tags=["persona"])
    async def set_persona(req: PersonaRequest) -> PersonaResponse:
        return PersonaResponse(fwver=sim.set_persona(req.fwver))

    # ---------------------------------------------------------------- requests
    @app.get(f"{ADMIN_PREFIX}/requests", tags=["requests"])
    async def get_requests(
        limit: int = Query(default=100, ge=1, le=10000),
        path: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        if journal is None:
            return []
        return journal.entries(limit=limit, path=path)

    @app.delete(f"{ADMIN_PREFIX}/requests", status_code=204, tags=["requests"])
    async def clear_requests() -> Response:
        if journal is not None:
            journal.clear()
        return Response(status_code=204)

    # ----------------------------------------------------------------- metrics
    @app.get(f"{ADMIN_PREFIX}/metrics", tags=["metrics"])
    async def get_metrics(
        format: str = Query(default="json"),
    ) -> Response:
        reqs = journal.total if journal is not None else 0
        fired = journal.total_fired if journal is not None else 0
        if format == "prometheus":
            body = (
                f"virtualcyberq_requests_total {reqs}\n"
                f"virtualcyberq_faults_fired_total {fired}\n"
                f"virtualcyberq_errors_total {metrics['errors']}\n"
                f"virtualcyberq_sim_time_seconds {sim.now()}\n"
            )
            return Response(content=body, media_type="text/plain")
        payload = MetricsResponse(
            requests=reqs,
            faults_fired=fired,
            errors=metrics["errors"],
            sim_time=sim.now(),
        )
        return Response(content=payload.model_dump_json(), media_type="application/json")

    # ------------------------------------------------------------------ assert
    @app.post(f"{ADMIN_PREFIX}/assert", response_model=AssertResponse, tags=["assert"])
    async def do_assert(req: AssertRequest) -> AssertResponse:
        try:
            ok, detail = evaluate_predicate(sim, req.predicate)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return AssertResponse(ok=ok, detail=detail)

    return app
