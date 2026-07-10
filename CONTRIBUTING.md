# Contributing to VirtualCyberQ

Thanks for helping build a faithful virtual CyberQ! This guide covers the dev
environment, the lint/type/test loop, the architectural rules that keep the
project honest, and how to add the two things people extend most often: a
**fault** and a **scenario**.

## Development setup

VirtualCyberQ targets **Python 3.8+** and uses a `src/` layout with
[hatchling](https://hatch.pypa.io/) as the build backend.

```bash
git clone https://github.com/kevinteg/VirtualCyberQ
cd VirtualCyberQ
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

`.[dev]` installs `pytest`, `pytest-asyncio`, `hypothesis`, `coverage`, `ruff`,
`mypy`, and `import-linter`.

## The lint / type / test loop

Run the same checks CI runs, in order:

```bash
ruff check .                 # lint + import sorting
ruff format --check .        # formatting
mypy                         # strict type checking (config in pyproject.toml)
lint-imports                 # import-linter: enforce the core/ boundary (see below)
pytest --cov=virtualcyberq   # tests with coverage (target >= 90% on core/)
```

`ruff format` (without `--check`) fixes formatting in place.

## Architectural rules (please read)

1. **`core/` is framework-agnostic — it imports NO web framework, ever.** Not
   `fastapi`, not `flask`, not `starlette`, not `uvicorn`. The physics and state
   must be drivable from a CLI, a notebook, or a test with zero HTTP. This is
   enforced in CI by an [import-linter](https://import-linter.readthedocs.io/)
   contract (declared in `pyproject.toml` under `[tool.importlinter]`); a
   violating PR fails the build. The web layer under `web/` is a thin adapter.

2. **One internal temperature representation.** Temperatures are stored as
   **integer tenths-of-°F** (e.g. `3343` == 334.3 °F), matching the wire. An
   open probe is `temp=None` and serializes to the literal string `OPEN`. The
   whole-°F-in / tenths-°F-out duality of the real API is centralized in
   `core/units.py` — do the conversion there, not ad hoc.

3. **Determinism.** No code reads the wall clock directly — everything runs off
   the injectable `VirtualClock`, and all randomness flows through the single
   `SeededRNG`. Same seed + same scenario ⇒ identical XML stream and request
   journal. Keep it that way; it is what makes the emulator usable in CI.

4. **Fidelity vs. inference.** Anything not verified against a real device is
   labeled a **modeling choice** and lives behind a tunable default (see
   `docs/CYBERQ_PROTOCOL.md`, which tags every claim `[V]` verified or `[I]`
   inferred, and DESIGN Appendix A). Don't silently harden an inferred behavior;
   label it and make it configurable.

5. **The device plane must stay indistinguishable from hardware.** No admin
   functionality, headers, or JSON may leak onto `:8080`.

## Adding a fault

Faults live in `core/faults/` so they are seed-deterministic and drivable
in-process; network/HTTP faults are *applied* by the device-plane ASGI
middleware (`web/device_faults.py`). To add one:

1. Add the `Fault` subclass / handler in the relevant module
   (`network.py`, `http.py`, `sensor.py`, or `power.py`) and register it in
   `core/faults/__init__.py`.
2. Use the shared `Fault` shape (`id`, `enabled`, `probability`, `scope`,
   `duration_s`, `count`, `params`) and consult the injected `SeededRNG` for any
   randomness so replays are identical.
3. Document it in the catalog (DESIGN section 8) and make it declarable as a
   scenario step.
4. Add a test under `tests/faults/` proving the effect **and** that two runs
   with the same seed are identical.

## Adding a scenario

Scenarios are declarative YAML validated by a Pydantic model
(`scenario/model.py`) and driven by `scenario/runner.py`. To ship one:

1. Write the YAML (see `docs/scenarios.md` for the format + cookbook) and drop
   it in `src/virtualcyberq/scenario/builtin/`.
2. Give it a `seed` so it is reproducible.
3. Add a test under `tests/scenario/` that runs it to completion with all its
   in-scenario `assert` steps passing.

## Commit style & sign-off

- Keep commits focused; write a clear subject line and explain the *why*.
- Sign off your commits (DCO) with `git commit -s`, certifying you have the
  right to submit the change under the project's BSD-3-Clause license.
- Every new `.py` file starts with `# SPDX-License-Identifier: BSD-3-Clause` on
  line 1, then `from __future__ import annotations`.
- Update `CHANGELOG.md` under `## [Unreleased]` for any user-visible change.

## Pull requests

Open a PR against `main`. CI runs the full matrix (Python 3.8–3.12): ruff, mypy,
import-linter, and pytest with coverage. Green CI + a review is required to
merge. Thanks again!
