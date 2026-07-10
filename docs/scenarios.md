# Scenario file format & cookbook

A **scenario** is a declarative description of a cook and everything that happens
to it: the starting seed, the initial device state and cook profile, and a
time-ordered `timeline` of things to do (change state, swap a profile, inject a
fault, drive the clock, or assert an expectation). Scenarios are how you say
"cook a 13 lb brisket at 250 °F, disconnect a probe at 3½ h, throw a burst of
HTTP 500s at 4 h, and assert the brisket is done by 8 h" **without hand-tuning
ODEs or wall-clock timing** — and, because everything runs off one seeded RNG
and one virtual clock, the run is byte-for-byte reproducible.

Scenarios are validated by a Pydantic model (`virtualcyberq.scenario.model`) and
driven by `ScenarioRunner`, which advances the virtual clock to each step's time
and applies it. The **same** scenario is accepted by:

- the CLI: `virtual-cyberq --scenario brisket_with_flaky_wifi` (a builtin name,
  a file path, or inline YAML);
- the admin API: `POST /__admin/scenario/load`;
- the pytest fixtures: `@pytest.mark.cyberq(scenario="flaky_wifi")`;
- the harness: `VirtualCyberQ(scenario=...)` / `cq.load_scenario(...)`.

Builtin scenarios live in `src/virtualcyberq/scenario/builtin/` and are loadable
by bare name. This document mirrors DESIGN section 10.

---

## Top-level shape

```yaml
name: brisket_with_flaky_wifi     # required, unique-ish label
description: >                     # optional, free text
  What this scenario exercises.
seed: 42                          # RNG seed for deterministic replay (default 0)
speed: 600                        # clock accel: sim-sec per wall-sec (default 0 = frozen)
persona: "3.1"                    # firmware persona: "1.7" | "2.3" | "3.1" | "4.08"

initial:                          # starting conditions (see below)
  state: { ... }
  profile: { ... }

timeline:                         # time-ordered list of steps (see below)
  - at: 0m
    set: { ... }
  - at: 20m
    assert: { ... }
```

| Field         | Type           | Default | Meaning                                                        |
|---------------|----------------|---------|----------------------------------------------------------------|
| `name`        | string         | —       | Scenario label (required).                                     |
| `description` | string         | `null`  | Free-form description.                                         |
| `seed`        | int            | `0`     | Seeds *all* randomness (faults, sensor noise) for replay.      |
| `speed`       | float          | `0.0`   | Clock acceleration. `0` freezes (manual/`advance` stepping).   |
| `persona`     | string         | `null`  | Firmware persona to emulate.                                   |
| `initial`     | object         | `{}`    | Starting `state` fragment and/or cook `profile`.              |
| `timeline`    | list of steps  | `[]`    | Time-ordered actions (see [Steps](#timeline-steps)).           |

### `initial`

```yaml
initial:
  state:                                  # a raw DeviceState fragment (tenths-degF for temps)
    control: { propband: 25, cyctime: 6, alarmdev: 50, cook_ramp: FOOD1 }
    system:  { deg_units: FAHRENHEIT }
  profile:                                # the cook definition (whole-degF for *_f)
    pit:   { start_f: 70, ambient_f: 70, cook_set_f: 250 }
    food1: { cut: brisket,          set_f: 203, mass_lb: 13, wrapped: false }
    food2: { cut: chicken_quarters, set_f: 175, mass_lb: 0.7 }
    food3: { disconnected: true }         # emits OPEN / STATUS=4
```

- `state` is applied like a `PATCH /__admin/state`: enums accept their names
  (`FOOD1`, `FAHRENHEIT`) or integers; temperatures written into raw state are
  **tenths-°F** (mirroring the wire).
- `profile.pit` sets the initial/ambient temperature and the pit setpoint in
  **whole °F** (`*_f`).
- `profile.foodN` picks a `cut` (drives `tau_meat`, stall params, target),
  a `set_f` target in whole °F, an optional `mass_lb`, and `wrapped: true`
  (Texas-crutch — shortens/eliminates the stall). `disconnected: true` starts
  the probe OPEN. Known cuts include `brisket`, `pork_butt`, `ribs`,
  `whole_chicken`, `chicken_quarters` (see `core/profiles.py`).

---

## Timeline steps

Every step has an `at` time and **exactly one** action key. Steps run in `at`
order; steps sharing the same `at` run in listed order.

### Time literals

`at` (and `duration_s` where noted) accept a number of seconds **or** a string
with `s` / `m` / `h` suffixes, combinable: `30s`, `20m`, `3h`, `3h30m`.

### `set` — write raw device state

```yaml
- at: 0m
  set: { cook: { set: 2500 } }     # tenths-degF when writing state directly
```

Writes a `DeviceState` fragment directly (bypassing wire rules), same semantics
as `initial.state`. Temperatures here are **tenths-°F**.

### `profile` — swap the cook mid-run

```yaml
- at: 2h
  profile:
    food2: { cut: ribs, set_f: 195, mass_lb: 3 }
```

Replaces the pit and/or food profiles partway through a run.

### `fault` — inject (or clear) a fault

```yaml
- at: 3h30m
  fault: { id: probe.open, params: { probe: food2 }, duration_s: 600 }

- at: 4h
  fault: { id: http.error, params: { status: 500 }, probability: 1.0, count: 5 }
```

Injects a fault with the shared shape (`id`, optional `probability`, `scope`,
`duration_s`, `count`, and fault-specific `params`). Faults auto-expire on
`duration_s` / `count`, or you can clear one explicitly with
`fault: { id: <id>, clear: true }`. See DESIGN section 8 for the full catalog.

### `time` — drive the clock

```yaml
- at: 1h
  time: { scale: 60 }      # change acceleration to 60x from here on
- at: 1h
  time: { freeze: true }   # freeze; { resume: true } to un-freeze
```

### `assert` — check an expectation

```yaml
- at: 3h
  assert:                            # brisket entering the stall
    food1_temp_f: { ">=": 150, "<=": 170 }

- at: 8h
  assert:
    food1_status: DONE
    food1_temp_f: { ">=": 200 }
```

Predicates are evaluated against device/sim/time state at the step's `at`. A
temperature predicate can be an exact value or a comparison object with
`">="`, `"<="`, `">"`, `"<"`, `"=="` keys (combinable for a range). Status
fields accept a name (`DONE`) or a code. Common predicate keys:
`pit_temp_f`, `food1_temp_f` / `food2_temp_f` / `food3_temp_f`,
`output_percent`, `cook_status`, `food1_status` (etc.), and `timer_status`.
A failing assert raises during a scenario run (and surfaces via
`POST /__admin/assert`).

> **Two temperature conventions, on purpose.** Raw `set` / `initial.state`
> writes use **tenths-°F** (the wire representation); `profile` `*_f` fields and
> `*_temp_f` asserts use **whole °F**. This mirrors the real device's
> dual representation and keeps the distinction explicit and testable.

---

## Cookbook

### 1. Minimal steady hold (great for a smoke test)

```yaml
name: steady_225
seed: 0
speed: 600
initial:
  profile:
    pit:   { start_f: 70, ambient_f: 70, cook_set_f: 225 }
    food1: { cut: pork_butt, set_f: 203, mass_lb: 8 }
timeline:
  - at: 20m
    assert: { pit_temp_f: { ">=": 210, "<=": 240 } }
```

### 2. Brisket through the stall (a full cook with asserts)

The shipped `brisket_with_flaky_wifi` builtin: a 13 lb brisket + two chicken
quarters at 250 °F, a mid-cook probe disconnect, a burst of HTTP 500s, and a
stall assertion — deterministic under `seed: 42`. Load it with
`virtual-cyberq --scenario brisket_with_flaky_wifi`.

### 3. Congested / flaky WiFi (client resilience)

The shipped `flaky_wifi` builtin drives a steady 225 °F pit while layering
`net.latency`, probabilistic `http.error` 500s, a brief `net.blackhole`, and a
short `power.brownout` — to exercise a client's retry/degradation paths under
`seed: 7`:

```yaml
- at: 30m
  fault: { id: net.latency, params: { mean_ms: 800, jitter_ms: 400 }, duration_s: 600 }
- at: 45m
  fault: { id: http.error, params: { status: 500 }, probability: 0.5, count: 4 }
- at: 1h
  fault: { id: net.blackhole, duration_s: 15 }
- at: 1h30m
  fault: { id: power.brownout, duration_s: 20, params: { reset: false } }
```

### 4. Probe drama (sensor faults)

```yaml
name: probe_drama
seed: 3
speed: 300
initial:
  profile:
    pit:   { start_f: 70, cook_set_f: 225 }
    food1: { cut: whole_chicken, set_f: 165, mass_lb: 5 }
timeline:
  - at: 30m
    fault: { id: sensor.noise, params: { probe: food1, sigma_f: 2.0 } }
  - at: 45m
    fault: { id: probe.open, params: { probe: food1 }, duration_s: 300 }
  - at: 50m
    assert: { food1_status: ERROR }        # OPEN while disconnected
  - at: 55m
    assert: { food1_status: OK }           # recovered after duration
```

### 5. Timer expiry & cook-and-hold

```yaml
name: timeout_hold
seed: 0
speed: 600
initial:
  state:
    control: { timeout_action: HOLD, cookhold: 2000 }   # tenths-degF (200.0)
  profile:
    pit: { start_f: 70, cook_set_f: 275 }
timeline:
  - at: 0m
    set: { timer: { remaining_s: 1800, running: true } }
  - at: 40m
    assert: { timer_status: HOLD }         # timer expired, pit retargeted to COOKHOLD
```

---

## Running a scenario

```bash
# CLI (builtin name, file path, or inline)
virtual-cyberq --scenario brisket_with_flaky_wifi --speed 600

# Admin API
curl -X POST http://localhost:9000/__admin/scenario/load \
     -H 'content-type: application/json' \
     -d '{"name": "flaky_wifi"}'
curl -X POST http://localhost:9000/__admin/scenario/step   # advance one step
```

```python
# In a test (pytest plugin)
@pytest.mark.cyberq(seed=42, scenario="brisket_with_flaky_wifi")
def test_client_survives_the_cook(cyberq, cyberq_url):
    ...
```

See `docs/DESIGN.md` (sections 6, 8, 10) for the physics, the fault catalog, and
the design rationale.
