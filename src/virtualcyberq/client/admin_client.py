# SPDX-License-Identifier: BSD-3-Clause
"""Typed control-plane client (DESIGN section 11).

:class:`AdminClient` speaks the ``/__admin`` JSON API over httpx, or -- when
constructed with a :class:`~virtualcyberq.core.simulation.Simulation` -- drives
the simulation directly in-process (no HTTP). Both modes expose the same
namespaced helpers:

* ``client.state()``                     -> a :class:`StateView` of device state.
* ``client.time.advance/scale/freeze/resume``
* ``client.faults.inject/list/clear``
* ``client.probes.disconnect/reconnect``
* ``client.rng.seed``
* ``client.scenario.load/step/stop``
* ``client.snapshot()`` / ``client.restore(blob)``
* ``client.requests(limit=, path=)``

The in-process mode is the fast path for this repo's own tests; the HTTP mode is
what an external api-proxy repo would use against a running server.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING, Any, cast

from virtualcyberq.web.admin_app import ADMIN_PREFIX

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

    from virtualcyberq.core.simulation import Simulation

__all__ = [
    "AdminClient",
    "FaultsNamespace",
    "ProbeView",
    "ProbesNamespace",
    "RngNamespace",
    "ScenarioNamespace",
    "StateView",
    "TimeNamespace",
]

_STATUS_NAMES = (
    "OK",
    "HIGH",
    "LOW",
    "DONE",
    "ERROR",
    "HOLD",
    "ALARM",
    "SHUTDOWN",
)


def _status_name(code: int) -> str:
    """Map a status integer 0..7 to its name (``DONE`` etc.)."""
    return _STATUS_NAMES[code] if 0 <= code < len(_STATUS_NAMES) else str(code)


class ProbeView:
    """A read-only view of one probe from a state snapshot.

    Attributes are ``name`` (str), ``temp`` (tenths-degF int or ``None``),
    ``temp_f`` (whole-degF float or ``None``), ``set`` (tenths-degF int),
    ``status`` (name string, e.g. ``"DONE"``), ``status_code`` (int), and
    ``connected`` (bool).
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._d = data
        self.name: str = data.get("name", "")
        self.temp: int | None = data.get("temp")
        self.set: int = data.get("set", 0)
        self.status_code: int = int(data.get("status", 0))
        self.status: str = _status_name(self.status_code)
        self.connected: bool = bool(data.get("connected", True))

    @property
    def temp_f(self) -> float | None:
        """The temperature in whole degF, or ``None`` for an open probe."""
        return None if self.temp is None else self.temp / 10.0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProbeView(name={self.name!r}, temp={self.temp}, status={self.status})"


class StateView:
    """A structured, read-only view over a device-state snapshot dict.

    Exposes ``cook`` / ``food1`` / ``food2`` / ``food3`` as :class:`ProbeView`,
    plus ``output_percent``, ``fwver``, and the raw ``control`` / ``system`` /
    ``timer`` dicts. ``raw`` is the underlying plain dict.
    """

    def __init__(
        self,
        state: dict[str, Any],
        sim: dict[str, Any] | None = None,
        time: dict[str, Any] | None = None,
    ) -> None:
        self.raw = state
        self.sim = sim or {}
        self.time = time or {}
        self.cook = ProbeView(state["cook"])
        self.food1 = ProbeView(state["food1"])
        self.food2 = ProbeView(state["food2"])
        self.food3 = ProbeView(state["food3"])
        self.output_percent: int = int(state.get("output_percent", 0))
        self.fwver: str = state.get("fwver", "")
        self.control: dict[str, Any] = state.get("control", {})
        self.system: dict[str, Any] = state.get("system", {})
        self.timer: dict[str, Any] = state.get("timer", {})

    def probe(self, name: str) -> ProbeView:
        """Return one probe view by id (``cook``/``food1``/``food2``/``food3``)."""
        return cast(ProbeView, getattr(self, name))


# --------------------------------------------------------------------- backend
class _Backend:
    """Abstract transport backend (HTTP or in-process)."""

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        raise NotImplementedError

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        raise NotImplementedError

    def delete(self, path: str) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        pass


class _HttpBackend(_Backend):
    """Talks to a running admin server over httpx."""

    def __init__(
        self, base_url: str, *, timeout: float = 30.0, client: httpx.Client | None = None
    ) -> None:
        import httpx

        self._base = base_url.rstrip("/")
        self._own = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def _url(self, path: str) -> str:
        return f"{self._base}{path}"

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        r = self._client.get(self._url(path), params=params)
        r.raise_for_status()
        if not r.content:
            return None
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            return r.text
        return r.json()

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        r = self._client.post(self._url(path), json=json)
        r.raise_for_status()
        return r.json() if r.content else None

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        r = self._client.patch(self._url(path), json=json)
        r.raise_for_status()
        return r.json() if r.content else None

    def delete(self, path: str) -> Any:
        r = self._client.delete(self._url(path))
        r.raise_for_status()
        return None

    def close(self) -> None:
        if self._own:
            self._client.close()


class _DirectBackend(_Backend):
    """Drives a :class:`Simulation` directly, mirroring the admin routes.

    Reuses the same helper functions the FastAPI admin app calls, so behavior is
    identical to the HTTP path without the network hop.
    """

    def __init__(self, sim: Simulation, journal: Any = None) -> None:
        self._sim = sim
        if journal is None:
            from virtualcyberq.web.server import RequestJournal

            journal = RequestJournal()
        self._journal = journal
        # A single runner slot, like the admin app.
        self._runner: Any = None

    # The direct backend implements the admin surface by dispatching on path.
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        from virtualcyberq.core.simulation import _to_plain

        sim = self._sim
        if path == f"{ADMIN_PREFIX}/state":
            return {
                "state": _to_plain(sim.state),
                "sim": _to_plain(sim.sim_state),
                "time": {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen},
            }
        if path == f"{ADMIN_PREFIX}/time":
            return {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen}
        if path == f"{ADMIN_PREFIX}/rng":
            return {"seed": sim.rng.current_seed, "draws": sim.rng.draws}
        if path == f"{ADMIN_PREFIX}/faults":
            return [_to_plain(f) for f in sim.faults.list()]
        if path == f"{ADMIN_PREFIX}/requests":
            limit = int((params or {}).get("limit", 100))
            fpath = (params or {}).get("path")
            return self._journal.entries(limit=limit, path=fpath)
        if path == f"{ADMIN_PREFIX}/scenario":
            r = self._runner
            if r is None:
                return {"name": None, "step": 0, "total_steps": 0, "done": True}
            return {
                "name": r.scenario.name,
                "step": r.index,
                "total_steps": r.total_steps,
                "done": r.done,
            }
        if path == f"{ADMIN_PREFIX}/health":
            return {"status": "ok", "uptime": 0.0, "sim_time": sim.now()}
        if path == f"{ADMIN_PREFIX}/metrics":
            fmt = (params or {}).get("format", "json")
            reqs = self._journal.total
            fired = self._journal.total_fired
            if fmt == "prometheus":
                return (
                    f"virtualcyberq_requests_total {reqs}\n"
                    f"virtualcyberq_faults_fired_total {fired}\n"
                    f"virtualcyberq_errors_total 0\n"
                    f"virtualcyberq_sim_time_seconds {sim.now()}\n"
                )
            return {"requests": reqs, "faults_fired": fired, "errors": 0, "sim_time": sim.now()}
        if path.startswith(f"{ADMIN_PREFIX}/probes/"):
            probe = path.rsplit("/", 1)[-1]
            return _to_plain(sim.read(probe))
        raise KeyError(f"unhandled GET {path}")

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        from virtualcyberq.core.simulation import _to_plain
        from virtualcyberq.scenario import (
            ScenarioRunner,
            load_builtin,
            load_scenario,
        )
        from virtualcyberq.scenario.runner import (
            _build_cook_profile,
            evaluate_predicate,
            fault_from_spec,
        )

        sim = self._sim
        body = json or {}
        if path == f"{ADMIN_PREFIX}/time/advance":
            sim.advance(float(body["seconds"]))
            return {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen}
        if path == f"{ADMIN_PREFIX}/time/scale":
            sim.set_speed(float(body["factor"]))
            return {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen}
        if path == f"{ADMIN_PREFIX}/time/freeze":
            sim.freeze()
            return {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen}
        if path == f"{ADMIN_PREFIX}/time/resume":
            sim.resume(body.get("speed"))
            return {"now_s": sim.now(), "speed": sim.clock.speed, "frozen": sim.clock.frozen}
        if path == f"{ADMIN_PREFIX}/rng/seed":
            sim.seed(int(body["seed"]))
            return {"seed": sim.rng.current_seed, "draws": sim.rng.draws}
        if path == f"{ADMIN_PREFIX}/faults":
            injected = sim.faults.inject(fault_from_spec(body))
            return _to_plain(injected)
        if path == f"{ADMIN_PREFIX}/state/reset":
            sim.reset(body.get("mode", "factory"))
            return _to_plain(sim.state)
        if path == f"{ADMIN_PREFIX}/state/snapshot":
            import uuid

            return {"snapshot_id": uuid.uuid4().hex, "blob": sim.snapshot()}
        if path == f"{ADMIN_PREFIX}/state/restore":
            sim.restore(body["blob"])
            return _to_plain(sim.state)
        if path == f"{ADMIN_PREFIX}/persona":
            return {"fwver": sim.set_persona(body["fwver"])}
        if path == f"{ADMIN_PREFIX}/profile":
            spec = {k: v for k, v in body.items() if v is not None}
            sim.set_profile(_build_cook_profile(spec))
            return _to_plain(sim.state)
        if path == f"{ADMIN_PREFIX}/assert":
            ok, detail = evaluate_predicate(sim, body["predicate"])
            return {"ok": ok, "detail": detail}
        if path == f"{ADMIN_PREFIX}/scenario/load":
            if body.get("name") is not None:
                scenario = load_builtin(body["name"])
            elif body.get("scenario") is not None:
                scenario = load_scenario(body["scenario"])
            else:
                scenario = load_scenario(body["yaml"])
            self._runner = ScenarioRunner(sim, scenario)
            return {"name": scenario.name, "total_steps": self._runner.total_steps}
        if path == f"{ADMIN_PREFIX}/scenario/step":
            if self._runner is None:
                raise RuntimeError("no scenario loaded")
            self._runner.step()
            return {"step": self._runner.index, "done": self._runner.done}
        if path == f"{ADMIN_PREFIX}/scenario/stop":
            self._runner = None
            return None
        if path.endswith("/disconnect"):
            probe = path.split("/")[-2]
            sim.disconnect_probe(probe)
            if body.get("duration_s") is not None:
                from virtualcyberq.core.faults import Fault

                sim.faults.inject(
                    Fault(id="probe.open", duration_s=body["duration_s"], params={"probe": probe})
                )
            return _to_plain(sim.read(probe))
        if path.endswith("/reconnect"):
            probe = path.split("/")[-2]
            sim.reconnect_probe(probe)
            return _to_plain(sim.read(probe))
        raise KeyError(f"unhandled POST {path}")

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        from virtualcyberq.core.simulation import _to_plain
        from virtualcyberq.scenario.runner import _apply_state_fragment

        if path == f"{ADMIN_PREFIX}/state":
            _apply_state_fragment(self._sim, json)
            return _to_plain(self._sim.state)
        raise KeyError(f"unhandled PATCH {path}")

    def delete(self, path: str) -> Any:
        if path == f"{ADMIN_PREFIX}/faults":
            self._sim.faults.clear_all()
            return None
        if path.startswith(f"{ADMIN_PREFIX}/faults/"):
            self._sim.faults.clear(path.rsplit("/", 1)[-1])
            return None
        if path == f"{ADMIN_PREFIX}/requests":
            self._journal.clear()
            return None
        raise KeyError(f"unhandled DELETE {path}")


# ------------------------------------------------------------------ namespaces
class TimeNamespace:
    """``client.time`` -- clock ops (DESIGN section 7)."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    def now(self) -> dict[str, Any]:
        """Return ``{now_s, speed, frozen}``."""
        return cast("dict[str, Any]", self._b.get(f"{ADMIN_PREFIX}/time"))

    def advance(self, seconds: float) -> dict[str, Any]:
        """Advance the simulation by ``seconds`` simulated seconds."""
        return cast(
            "dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/time/advance", {"seconds": seconds})
        )

    def scale(self, factor: float) -> dict[str, Any]:
        """Set the clock acceleration factor."""
        return cast(
            "dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/time/scale", {"factor": factor})
        )

    def freeze(self) -> dict[str, Any]:
        """Freeze the clock (speed -> 0)."""
        return cast("dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/time/freeze", {}))

    def resume(self, speed: float | None = None) -> dict[str, Any]:
        """Resume ticking at ``speed`` (or the pre-freeze speed)."""
        return cast("dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/time/resume", {"speed": speed}))


class FaultsNamespace:
    """``client.faults`` -- inject/list/clear faults (DESIGN section 8)."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    def inject(self, id: str, **kwargs: Any) -> dict[str, Any]:
        """Inject a fault. Fault-specific knobs go in ``params`` or as kwargs.

        Convenience: kwargs that are not fault-record fields (``enabled``,
        ``probability``, ``scope``, ``duration_s``, ``count``, ``params``) are
        folded into ``params`` (e.g. ``inject("http.error", status=500)``).
        """
        record_fields = {"enabled", "probability", "scope", "duration_s", "count", "params"}
        body: dict[str, Any] = {"id": id}
        params: dict[str, Any] = dict(kwargs.pop("params", {}) or {})
        for k, v in kwargs.items():
            if k in record_fields:
                body[k] = v
            else:
                params[k] = v
        if params:
            body["params"] = params
        return cast("dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/faults", body))

    def list(self) -> builtins.list[dict[str, Any]]:
        """List the active faults."""
        return cast("builtins.list[dict[str, Any]]", self._b.get(f"{ADMIN_PREFIX}/faults"))

    def clear(self, id: str | None = None) -> None:
        """Clear one fault by id, or all faults when ``id`` is ``None``."""
        if id is None:
            self._b.delete(f"{ADMIN_PREFIX}/faults")
        else:
            self._b.delete(f"{ADMIN_PREFIX}/faults/{id}")


class ProbesNamespace:
    """``client.probes`` -- probe disconnect/reconnect."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    def get(self, probe: str) -> ProbeView:
        """Read one probe as a :class:`ProbeView`."""
        return ProbeView(self._b.get(f"{ADMIN_PREFIX}/probes/{probe}"))

    def disconnect(self, probe: str, duration_s: float | None = None) -> ProbeView:
        """Force a probe OPEN (optionally for ``duration_s`` seconds)."""
        data = self._b.post(f"{ADMIN_PREFIX}/probes/{probe}/disconnect", {"duration_s": duration_s})
        return ProbeView(data)

    def reconnect(self, probe: str) -> ProbeView:
        """Reconnect a probe."""
        return ProbeView(self._b.post(f"{ADMIN_PREFIX}/probes/{probe}/reconnect", {}))


class RngNamespace:
    """``client.rng`` -- seed/inspect the RNG."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    def seed(self, seed: int) -> dict[str, Any]:
        """Reseed all randomness."""
        return cast("dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/rng/seed", {"seed": seed}))

    def status(self) -> dict[str, Any]:
        """Return ``{seed, draws}``."""
        return cast("dict[str, Any]", self._b.get(f"{ADMIN_PREFIX}/rng"))


class ScenarioNamespace:
    """``client.scenario`` -- load/step/stop scenarios (DESIGN section 10)."""

    def __init__(self, backend: _Backend) -> None:
        self._b = backend

    def load(
        self,
        name: str | None = None,
        *,
        scenario: dict[str, Any] | None = None,
        yaml: str | None = None,
    ) -> dict[str, Any]:
        """Load a builtin (``name``) or an inline scenario (``scenario``/``yaml``)."""
        return cast(
            "dict[str, Any]",
            self._b.post(
                f"{ADMIN_PREFIX}/scenario/load",
                {"name": name, "scenario": scenario, "yaml": yaml},
            ),
        )

    def step(self) -> dict[str, Any]:
        """Advance to the next scenario step."""
        return cast("dict[str, Any]", self._b.post(f"{ADMIN_PREFIX}/scenario/step", {}))

    def stop(self) -> None:
        """Stop / clear the active scenario."""
        self._b.post(f"{ADMIN_PREFIX}/scenario/stop", {})

    def status(self) -> dict[str, Any]:
        """Return the current scenario progress."""
        return cast("dict[str, Any]", self._b.get(f"{ADMIN_PREFIX}/scenario"))


class AdminClient:
    """Typed control-plane client -- HTTP or in-process.

    Construct with **one** of:

    * ``base_url`` -- talk to a running admin server over httpx, or
    * ``sim`` -- drive a :class:`~virtualcyberq.core.simulation.Simulation`
      directly (no HTTP).

    Args:
        base_url: The admin server base URL (e.g. ``http://127.0.0.1:9000``).
        sim: A :class:`Simulation` for in-process mode.
        timeout: HTTP timeout (HTTP mode only).
        client: An existing ``httpx.Client`` to reuse (HTTP mode only).
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        sim: Simulation | None = None,
        journal: Any = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        if (base_url is None) == (sim is None):
            raise ValueError("provide exactly one of base_url or sim")
        self._backend: _Backend
        if sim is not None:
            self._backend = _DirectBackend(sim, journal)
        else:
            assert base_url is not None
            self._backend = _HttpBackend(base_url, timeout=timeout, client=client)
        self.time = TimeNamespace(self._backend)
        self.faults = FaultsNamespace(self._backend)
        self.probes = ProbesNamespace(self._backend)
        self.rng = RngNamespace(self._backend)
        self.scenario = ScenarioNamespace(self._backend)

    # ---------------------------------------------------------------- top-level
    def health(self) -> dict[str, Any]:
        """Return the server liveness payload."""
        return cast("dict[str, Any]", self._backend.get(f"{ADMIN_PREFIX}/health"))

    def state(self) -> StateView:
        """Return a :class:`StateView` of the current device + sim state."""
        payload = self._backend.get(f"{ADMIN_PREFIX}/state")
        return StateView(payload["state"], payload.get("sim"), payload.get("time"))

    def patch_state(self, fragment: dict[str, Any]) -> dict[str, Any]:
        """Drive arbitrary state fields directly (bypassing wire rules)."""
        return cast("dict[str, Any]", self._backend.patch(f"{ADMIN_PREFIX}/state", fragment))

    def reset(self, mode: str = "factory") -> dict[str, Any]:
        """Reset device state to ``factory`` or ``demo`` defaults."""
        return cast(
            "dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/state/reset", {"mode": mode})
        )

    def snapshot(self) -> dict[str, Any]:
        """Return ``{snapshot_id, blob}`` capturing the full simulation."""
        return cast("dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/state/snapshot", {}))

    def restore(self, blob: dict[str, Any]) -> dict[str, Any]:
        """Restore a snapshot ``blob``."""
        return cast(
            "dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/state/restore", {"blob": blob})
        )

    def persona(self, fwver: str) -> dict[str, Any]:
        """Switch the firmware persona."""
        return cast(
            "dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/persona", {"fwver": fwver})
        )

    def profile(self, **spec: Any) -> dict[str, Any]:
        """Set the pit + food profiles (a cook definition)."""
        return cast("dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/profile", spec))

    def assert_(self, predicate: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a server-side predicate; returns ``{ok, detail}``."""
        return cast(
            "dict[str, Any]", self._backend.post(f"{ADMIN_PREFIX}/assert", {"predicate": predicate})
        )

    def requests(self, *, limit: int = 100, path: str | None = None) -> list[dict[str, Any]]:
        """Return the recent request journal entries (WireMock-style)."""
        return cast(
            "list[dict[str, Any]]",
            self._backend.get(f"{ADMIN_PREFIX}/requests", {"limit": limit, "path": path}),
        )

    def metrics(self, fmt: str = "json") -> Any:
        """Return the metrics payload (``json`` or ``prometheus``)."""
        return self._backend.get(f"{ADMIN_PREFIX}/metrics", {"format": fmt})

    def close(self) -> None:
        """Release any owned HTTP resources."""
        self._backend.close()

    def __enter__(self) -> AdminClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
