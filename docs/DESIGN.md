# VirtualCyberQ — Architecture & Design

A high-fidelity, open-source **virtual/emulated BBQ Guru CyberQ WiFi** device, written in modern
Python (3.8+). VirtualCyberQ is a drop-in stand-in for a physical CyberQ WiFi unit: it serves the
exact device-facing XML/HTTP API a real unit exposes, backed by a physically-plausible thermal
simulation engine, plus an out-of-band control/admin API that lets tests deterministically drive
state, load scenarios, scale simulated time, and inject faults.

The design goal is that **an external CyberQ API-proxy/client repo (e.g. `ha_cyberq`,
`CyberQInterface`) can point at VirtualCyberQ unchanged** and cannot tell it apart from real
hardware on the fidelity plane — while this repo's own tests, and that external repo's tests, can
puppeteer physics and failures through a completely separate control plane.

---

## Table of contents

1. [Design principles: the two-plane architecture](#1-design-principles-the-two-plane-architecture)
2. [Framework recommendation: FastAPI vs Flask](#2-framework-recommendation-fastapi-vs-flask)
3. [Package / module layout](#3-package--module-layout)
4. [Device state model](#4-device-state-model)
5. [The wire contract (device plane)](#5-the-wire-contract-device-plane)
6. [Simulation engine: thermal model & control loop](#6-simulation-engine-thermal-model--control-loop)
7. [Time model: real-time and accelerated](#7-time-model-real-time-and-accelerated)
8. [Fault-injection catalog & API](#8-fault-injection-catalog--api)
9. [Control/admin API endpoint surface](#9-controladmin-api-endpoint-surface)
10. [Scenario / config file format](#10-scenario--config-file-format)
11. [Client / test-harness & pytest fixtures](#11-client--test-harness--pytest-fixtures)
12. [Testing strategy](#12-testing-strategy)
13. [Packaging, CI, licensing](#13-packaging-ci-licensing)
14. [Prioritized "extra useful features"](#14-prioritized-extra-useful-features)
15. [Appendix A: verified enums, encodings, ranges, defaults](#appendix-a-verified-enums-encodings-ranges-defaults)
16. [Appendix B: build phasing](#appendix-b-build-phasing)

---

## 1. Design principles: the two-plane architecture

The single most important architectural decision is a strict separation between two "planes":

- **Device plane (fidelity plane).** Serves *only* the real CyberQ surface: `GET /status.xml`,
  `GET /all.xml`, `GET /config.xml`, the root HTML page, and form-POST writes to `/` (plus legacy
  `*.htm` page URLs and a tolerant `POST /status.xml`). It emits `nutcstatus`/`nutcallstatus` XML,
  temperatures in tenths-of-°F, the literal string `OPEN` for open probes, and the exact status
  enums. It is unauthenticated by default (matching the hardware). **No admin functionality leaks
  onto this plane** — a client must not be able to tell it is talking to an emulator.

- **Control plane (admin plane).** A separate JSON/OpenAPI HTTP API on a **different port**
  (device on `:8080`, admin on `:9000` by default), *and* an equivalent in-process Python API.
  This is where all the power lives: read/drive full device state, load scenarios, advance / scale
  / freeze simulated time, inject and clear faults, seed the RNG, snapshot/restore, and inspect a
  request journal.

Underneath both planes sits the **framework-agnostic core**: the device state model, the thermal
simulation engine, the control loop, the virtual clock, the RNG, the fault registry, and the XML
serializers. The core has **zero dependency on any web framework** — it is plain Python that could
be driven by a CLI, a notebook, a test, or any HTTP server. The web layer is a thin adapter.

```
                        ┌───────────────────────────────────────────────┐
   CyberQ clients  ───▶ │  DEVICE PLANE  (:8080)                          │
   (ha_cyberq,          │  GET /status.xml /all.xml /config.xml, /        │
    CyberQInterface,    │  POST / (+ *.htm, /status.xml)   [XML, no auth] │
    proxy-repo tests)   └───────────────────┬───────────────────────────┘
                                            │  reads/writes DeviceState
                        ┌───────────────────▼───────────────────────────┐
   Tests / CI      ───▶ │  CORE (framework-agnostic)                      │
   (this repo &         │  DeviceState · ThermalSim · ControlLoop ·       │
    proxy repo)         │  VirtualClock · SeededRNG · FaultRegistry ·     │
                        │  XML serializers · ScenarioRunner               │
                        └───────────────────▲───────────────────────────┘
                                            │  drives/inspects
                        ┌───────────────────┴───────────────────────────┐
   Tests / operators ─▶ │  CONTROL PLANE (:9000)   [JSON, OpenAPI]        │
                        │  /__admin/state /time /faults /scenario /rng …  │
                        └───────────────────────────────────────────────┘
```

Everything the emulator does uses one **injectable virtual clock** and one **seeded RNG**, so the
same seed + same scenario produces a byte-identical output stream — the property that makes it
usable in CI.

---

## 2. Framework recommendation: FastAPI vs Flask

**Recommendation: FastAPI** for the web adapters (device plane + control plane), with the core
simulation engine kept strictly framework-agnostic so the choice is reversible and never leaks into
the physics.

### Comparison

| Concern | Flask | FastAPI | Verdict |
|---|---|---|---|
| Serving raw XML strings & HTML at fixed routes (device plane) | Trivial (`Response(xml, mimetype="text/xml")`) | Trivial (`Response(content=xml, media_type="text/xml")`) | Tie — both fine |
| Form-POST parsing (`application/x-www-form-urlencoded`) | `request.form` | `Form(...)` / raw body parse | Tie |
| **Control plane: typed JSON API + validation** | Manual (marshmallow/hand-rolled) | **Built-in via Pydantic** — request/response models, validation, coercion for free | **FastAPI** |
| **OpenAPI docs for the admin API** (a hard requirement) | Add-on (flask-smorest / apispec), extra wiring | **Auto-generated** Swagger UI + `/openapi.json` out of the box | **FastAPI** |
| Async support (fault latency, blackhole/timeout without blocking a worker) | Sync/WSGI; blocking `sleep` ties up a worker | **Native async/await** — latency & connection-hold faults are natural | **FastAPI** |
| In-process embedding for pytest | `app.test_client()` (in-proc, WSGI) | `TestClient`/`httpx` in-proc, or `uvicorn` in a thread | Tie (both embeddable) |
| Fidelity quirks (Connection: close, custom `Server:` header, truncated bodies, connection caps) | Doable via `after_request` / raw responses | Doable via middleware / `StreamingResponse` / raw ASGI | Slight edge FastAPI (ASGI middleware + streaming gives finer control over partial/slow responses) |
| Maturity / footprint | Very small, ubiquitous | Small, modern, ubiquitous | Tie |
| Existing repo | Current stub is Flask (Py2-era) | — | Migration cost is small; the stub has ~no real logic to port |

### Rationale

The **device plane is boring** — three GETs returning static-shaped XML and a permissive form POST
— and either framework serves it in a few lines. The deciding factor is the **control plane**,
which is a real modern JSON API and where two hard requirements live: **auto-generated OpenAPI
docs** and **non-blocking latency/hold faults**. FastAPI gives Pydantic-validated request/response
models and Swagger UI for free (satisfying the OpenAPI deliverable with zero extra machinery), and
its native async makes "add 3s latency," "hold the connection open (slow-loris)," and "blackhole
for N seconds" express cleanly without starving a worker pool.

Because the **core is framework-agnostic**, this is a low-risk bet: if FastAPI ever became a
liability, swapping in Flask/Starlette/aiohttp touches only `web/` and none of the physics or state
code. The core imports **no** web framework, ever.

> **Hard rule:** `core/` must never `import fastapi` (or flask, or starlette). Enforced by a lint
> check in CI (`grep`/import-linter) so the boundary can't rot.

Runtime: served by **uvicorn** (ASGI). Two app instances (device, admin) are mounted on two ports
from one process, sharing one `Simulation` object.

---

## 3. Package / module layout

```
VirtualCyberQ/
├── pyproject.toml                 # PEP 621 build, deps, tool config (replaces setup.py/.cfg)
├── README.md                      # quickstart, docker, "point your client here"
├── CONTRIBUTING.md                # dev setup, test/lint, PR flow, DCO/sign-off
├── LICENSE                        # BSD-3-Clause (matches existing setup.py "BSD New")
├── CHANGELOG.md
├── docs/
│   ├── DESIGN.md                  # (this document)
│   ├── protocol.md                # the verified XML/HTTP wire contract + field tables
│   ├── admin-api.md               # generated from the FastAPI OpenAPI spec
│   ├── scenarios.md               # scenario file format + cookbook
│   └── cyberq_status.xsd          # XSD schemas: the fidelity contract (nutcstatus/nutcallstatus)
│   └── cyberq_config.xsd
├── src/
│   └── virtualcyberq/
│       ├── __init__.py            # version, top-level exports (Simulation, VirtualCyberQ)
│       │
│       ├── core/                  # ── framework-agnostic; imports NO web framework ──
│       │   ├── __init__.py
│       │   ├── state.py           # DeviceState, ProbeState, dataclasses + enums
│       │   ├── enums.py           # StatusCode, RampSource, TimeoutAction, DegUnits, WifiEnc…
│       │   ├── defaults.py        # factory defaults + demo seed values (single source of truth)
│       │   ├── units.py           # tenths<->float encode/decode, OPEN sentinel, HH:MM:SS
│       │   ├── clock.py           # VirtualClock (freeze/advance/scale), monotonic driver
│       │   ├── rng.py             # SeededRNG wrapper (one seed feeds everything)
│       │   ├── validation.py      # writable-param allow-list, ranges, clamp/reject modes
│       │   ├── control.py         # CyberQ control law (P-band, cyctime, ramp, opendetect,
│       │   │                      #   timeout/hold/shutdown, alarmdev, status transitions)
│       │   ├── thermal.py         # pit + meat first-order thermal models, stall, lid-open
│       │   ├── profiles.py        # PitProfile, MeatProfile, ramp specifications
│       │   ├── simulation.py      # Simulation: owns state+clock+rng+sim; step(dt); the CORE API
│       │   └── faults/
│       │       ├── __init__.py    # FaultRegistry, Fault base, activation gates, seed-aware
│       │       ├── network.py     # unreachable/blackhole, latency, conn-cap
│       │       ├── http.py        # 500/503/404/400, truncated/malformed body, wrong headers
│       │       ├── sensor.py      # probe open/short, noise, drift, stuck-at, spikes
│       │       └── power.py       # brownout/reboot (defaults-reset vs persisted)
│       │
│       ├── xml/                   # ── serializers: DeviceState -> exact wire XML/HTML ──
│       │   ├── __init__.py
│       │   ├── status.py          # <nutcstatus>
│       │   ├── allxml.py          # <nutcallstatus> (status + names/setpoints)
│       │   ├── configxml.py       # <nutcallstatus> superset (+SYSTEM/CONTROL/WIFI/SMTP/FWVER)
│       │   ├── html_pages.py      # root "Control Status" page + *.htm config pages
│       │   └── post_parse.py      # parse form body -> validated writes (the POST dispatch)
│       │
│       ├── web/                   # ── FastAPI adapters (thin) ──
│       │   ├── __init__.py
│       │   ├── device_app.py      # device-plane FastAPI app (XML/HTML routes, form POST)
│       │   ├── device_faults.py   # ASGI middleware applying network/http faults per-request
│       │   ├── admin_app.py       # control-plane FastAPI app (JSON, OpenAPI)
│       │   ├── admin_models.py    # Pydantic request/response schemas
│       │   └── server.py          # build+run both apps on two ports over one Simulation
│       │
│       ├── scenario/              # ── declarative scenarios ──
│       │   ├── __init__.py
│       │   ├── model.py           # Pydantic scenario schema (steps, timeline, asserts)
│       │   ├── runner.py          # ScenarioRunner: drives Simulation along a timeline
│       │   └── builtin/           # shipped scenarios (brisket.yaml, flaky_wifi.yaml, …)
│       │
│       ├── client/                # ── Python control-plane client ──
│       │   ├── __init__.py
│       │   └── admin_client.py    # AdminClient: typed wrapper over the /__admin API
│       │
│       ├── testing/               # ── reusable test harness (public API) ──
│       │   ├── __init__.py
│       │   ├── harness.py         # VirtualCyberQ context manager (in-proc, ephemeral ports)
│       │   └── pytest_plugin.py   # pytest fixtures, registered as an entry point
│       │
│       └── cli.py                 # `virtual-cyberq` entrypoint (argparse/typer)
│
├── examples/
│   ├── run_local.py               # start device+admin, print URLs
│   ├── drive_a_cook.py            # use AdminClient to run an accelerated brisket
│   ├── inject_faults.py           # latency/500/probe-open demo
│   └── proxy_repo_conftest.py     # copy-paste conftest for an EXTERNAL api-proxy repo
│
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml         # device :8080 + admin :9000, healthcheck, env config
│
├── tests/
│   ├── conftest.py
│   ├── unit/                      # core: units, clock, control law, thermal, faults, validation
│   ├── wire/                      # golden-file XML byte-compat vs captured real-device fixtures
│   ├── contract/                  # run real CyberQInterface/ha_cyberq parsers against us
│   ├── faults/                    # each fault behaves as specified & is seed-deterministic
│   ├── scenario/                  # scenario runner + builtin scenarios
│   └── fixtures/
│       ├── real_status.xml        # captured real-device XML (regression golden files)
│       ├── real_all.xml
│       └── real_config.xml
└── .github/
    └── workflows/
        ├── ci.yml                 # lint + type + test matrix (3.8–3.12), coverage
        ├── docker.yml             # build/push image on tag
        └── release.yml            # build sdist/wheel, publish to PyPI on tag (trusted publishing)
```

Notes:

- `src/` layout (not top-level package) so tests run against the installed wheel and packaging bugs
  surface early.
- The current stub's `status.py` / `timer.py` / `app/views.py` map onto `core/state.py` +
  `core/clock.py` + `xml/post_parse.py`; the Python-2 idioms (`urllib.unquote`, integer `/`,
  `datetime.today()`) are dropped in favor of `urllib.parse.unquote`, `//`, and the injectable
  `VirtualClock`.

---

## 4. Device state model

State is a tree of frozen-by-convention `@dataclass`es rooted at `DeviceState`. **All temperatures
are stored internally in tenths-of-°F integers** (e.g. `3343` == 334.3 °F), matching the wire
format exactly, so serialization is a straight copy and there is one canonical representation. An
open probe is represented by `temp=None`, which serializes to the literal `OPEN`.

```python
# core/enums.py  (values are the on-wire integers)
class StatusCode(IntEnum):
    OK=0; HIGH=1; LOW=2; DONE=3; ERROR=4; HOLD=5; ALARM=6; SHUTDOWN=7

class RampSource(IntEnum):   OFF=0; FOOD1=1; FOOD2=2; FOOD3=3
class TimeoutAction(IntEnum): NO_ACTION=0; HOLD=1; ALARM=2; SHUTDOWN=3
class DegUnits(IntEnum):     CELSIUS=0; FAHRENHEIT=1
class OnOff(IntEnum):        OFF=0; ON=1
```

```python
# core/state.py
@dataclass
class ProbeState:
    name: str                       # <=16 chars
    temp: Optional[int]             # tenths-°F, or None => "OPEN"
    set:  int                       # tenths-°F setpoint (COOK/FOODn)
    status: StatusCode = StatusCode.OK
    connected: bool = True          # False => temp serializes as OPEN, status=ERROR

@dataclass
class ControlConfig:                # <CONTROL> block; whole-°F on input, tenths in readback
    timeout_action: TimeoutAction = TimeoutAction.NO_ACTION
    cookhold: int   = 2000          # tenths-°F (200.0)
    alarmdev: int   = 500           # tenths-°F (50.0); input range 10..100 whole-°F
    cook_ramp: RampSource = RampSource.OFF
    opendetect: OnOff = OnOff.ON
    cyctime: int    = 6             # seconds, 4..10
    propband: int   = 250           # tenths-°F (25.0); input range 5..100 whole-°F

@dataclass
class SystemConfig:                 # <SYSTEM>
    menu_scrolling: OnOff = OnOff.OFF
    lcd_backlight: int = 50         # 0..100 %
    lcd_contrast:  int = 10         # 0..100 %
    deg_units: DegUnits = DegUnits.FAHRENHEIT
    alarm_beeps: int = 3            # 0..5
    key_beeps: OnOff = OnOff.ON

@dataclass
class WifiConfig:                   # <WIFI>
    ip:str; nm:str; gw:str; dns:str
    wifimode:int; dhcp:int; ssid:str
    wifi_enc:int; wifi_key:str; http_port:int = 80; mac:str = "00:04:A3:00:00:00"

@dataclass
class SmtpConfig:                   # <SMTP>
    host:str; port:int; user:str; pwd:str
    to:str; frm:str; subj:str; alert:int = 0

@dataclass
class TimerState:
    remaining_s: int = 0            # counts down; serialized HH:MM:SS as TIMER_CURR
    running: bool = False
    status: StatusCode = StatusCode.OK

@dataclass
class DeviceState:
    fwver: str = "3.1"              # persona: "1.7" | "2.3" | "3.1" | "4.08" (Cloud)
    output_percent: int = 0         # 0..100, READ-ONLY (computed by control loop)
    cook:  ProbeState
    food1: ProbeState
    food2: ProbeState
    food3: ProbeState
    timer: TimerState
    control: ControlConfig
    system: SystemConfig
    wifi:   WifiConfig
    smtp:   SmtpConfig

    def probes(self) -> list[ProbeState]:  # [cook, food1, food2, food3]
        ...
```

A parallel **`SimState`** (in `thermal.py`) holds the *physical* variables that never appear on the
wire — `fire` (0..1 ignition intensity), per-probe `meat_moisture` budgets, `lid_open`,
`fuel_remaining`, `cook_armed` (deviation-alarm gating), `timeout_hold_active`,
`timeout_shutdown_active`. The control loop reads `SimState`, writes the visible `DeviceState`.

Factory defaults and the shipped demo values (Big Green Egg / Chicken Quarters / Beef Brisket /
Pork Chop) live in **`core/defaults.py`** as the single source of truth (closing the current stub's
"move magic variables to a defaults file" TODO). See [Appendix A](#appendix-a-verified-enums-encodings-ranges-defaults).

---

## 5. The wire contract (device plane)

This is the compatibility contract. It must be reproduced exactly; it is verified against
`CyberQInterface`, `ha_cyberq`, and captured real-device dumps. Full field tables live in
`docs/protocol.md`; the load-bearing rules:

### Endpoints

| Path | Method | Purpose | Root element | Content-Type |
|---|---|---|---|---|
| `/status.xml` | GET | Fast live status (temps + statuses). | `<nutcstatus>` | `text/xml` |
| `/all.xml` | GET | status + names + setpoints. | `<nutcallstatus>` | `text/xml` |
| `/config.xml` | GET | all.xml **plus** SYSTEM/CONTROL/WIFI/SMTP/FWVER. | `<nutcallstatus>` | `text/xml` |
| `/` | GET | HTML "Control Status" page. | HTML | `text/html` |
| `/` | POST | **Update mechanism** — `application/x-www-form-urlencoded` `KEY=value&…`. | page/empty | — |
| `/index.htm`, `/control.htm`, `/system.htm`, `/config.htm`, `/wifi.htm` | GET/POST | Legacy HTML config pages; POST accepted here too. | HTML | `text/html` |
| `/status.xml` | POST | **Tolerant** — accept form POST (e.g. `IGNOREDTAG` cache-buster), apply known keys, 200. | XML | `text/xml` |

- **No `/reboot`, no JSON, no factory-reset endpoint.** Reboot is a form POST to `/` with a reboot
  flag (exact key undocumented; the emulator accepts a small set and treats brownout/reboot as an
  admin-plane concern too).
- **No authentication** by default (trust-the-LAN). An optional strict-auth mode exists but is off
  for fidelity.

### Encoding rules (load-bearing)

- **Temperatures on the wire are integers in tenths of a degree** in the current `DEG_UNITS`
  (`3343` → 334.3). `COOK_SET`, `FOOD*_SET`, `PROPBAND`, `ALARMDEV`, `COOKHOLD` are also tenths on
  read-back.
- **Writes come in whole °F** on the HTML form / POST (`PROPBAND=30`, `ALARMDEV=50`,
  `COOK_SET=225`), optionally with a decimal (`123.5`). This **dual representation (whole-°F in,
  tenths-°F out) is the single most error-prone part of the API** — `units.py` centralizes it.
- **Open/disconnected probe** → the `*_TEMP` element carries the literal string `OPEN` (not a
  number) and `*_STATUS` = `4` (ERROR).
- **Timer** fields are `HH:MM:SS`; POST colons URL-encoded `%3A`; both `COOK_TIMER` and
  `_COOK_TIMER` accepted.
- **Status codes** 0–7 = OK/HIGH/LOW/DONE/ERROR/HOLD/ALARM/SHUTDOWN (used by every `*_STATUS`).

### POST write surface

23-key canonical allow-list (matches `CyberQInterface.validParameters`):
`COOK_NAME, COOK_SET, FOOD1_NAME, FOOD1_SET, FOOD2_NAME, FOOD2_SET, FOOD3_NAME, FOOD3_SET,
_COOK_TIMER, COOK_TIMER, COOKHOLD, TIMEOUT_ACTION, ALARMDEV, COOK_RAMP, OPENDETECT, CYCTIME,
PROPBAND, MENU_SCROLLING, LCD_BACKLIGHT, LCD_CONTRAST, DEG_UNITS, ALARM_BEEPS, KEY_BEEPS`
plus the WIFI/SMTP config keys (`IP, NM, GW, DNS, WIFIMODE, DHCP, SSID, WIFI_ENC, WIFI_KEY,
HTTP_PORT` and `SMTP_*`). **Read-only, never settable:** `OUTPUT_PERCENT`, `TIMER_CURR`, all
`*_TEMP`, all `*_STATUS`, `FAN_SHORTED`, `FWVER`, `MAC`. Partial POSTs are legal; **unknown keys
are silently ignored**; out-of-range values are clamped (lenient mode) or ignored — the real device
gives no structured error, so neither do we (unless `strict` mode is enabled).

The serializers preserve the device's verbatim XML comment block ("all temperatures are displayed
in tenths F, regardless of setting of unit…") because real clients have been seen to depend on the
exact document shape.

---

## 6. Simulation engine: thermal model & control loop

The engine is a set of continuous first-order ODEs stepped by an explicit integrator. It is
**decoupled from HTTP** entirely: `Simulation.step(dt_sim_seconds)` advances physics; the web layer
never computes physics, it only reads/writes `DeviceState`. Grounded in researched real-world ramp,
stall, overshoot, and lid-open behavior; all specific time constants are **tunable parameters** with
sane defaults (see [Appendix A](#appendix-a-verified-enums-encodings-ranges-defaults)).

### 6.1 Control law (drives `OUTPUT_PERCENT`) — verified

The CyberQ is a **proportional-band blower controller with time-proportioned (slow-PWM) fan
pulsing**, not a full PID. The proportional band sits entirely *below* the setpoint:

```python
error = effective_cook_set - cook_temp           # tenths-°F, positive = too cold
duty  = clamp(error / propband + bias, 0.0, 1.0)  # bias optional PI term (see below)
output_percent = round(100 * duty)
```

Verified against BBQ Guru's worked example (set 225 °F, PROPBAND 25 °F): below 200 → 100 %, above
225 → 0 %, at 212.5 → 50 %. Defaults `PROPBAND=25 °F`, `CYCTIME=6 s`. The duty cycle *is* what the
manual calls "output %"; the on/off fan pulse within each `CYCTIME` window is animated only near
real-time speed (see §7). An optional small integral **bias** term removes the pure-P steady-state
droop for lifelike long holds; it is labeled a modeling choice and defaults to a tiny value so the
pit idles around ~10 % output at 225 °F (matching the manual's "output % around 10%" tip).

### 6.2 Pit thermal model — first-order, asymmetric

```python
# ignition dynamics (S-curve start / lag): fire lags duty with TAU_FIRE (~3 min)
fire     += (duty - fire) / TAU_FIRE * dt
T_drive   = T_amb + fire * (T_fire_max - T_amb)          # target the fire drives toward
tau       = TAU_UP if T_drive > cook_temp else TAU_DOWN  # asymmetric: heat fast, cool slow
cook_temp += (T_drive - cook_temp) / tau * dt
```

Defaults fit to verified anecdotes (single medium/large kamado, 10 CFM fan): `T_amb=70 °F`,
`T_fire_max=700 °F`, `TAU_UP≈12 min`, `TAU_HOLD≈20 min`, `TAU_DOWN≈90 min`, `TAU_FIRE≈3 min`,
`T_LAG≈4 min` dead-time at start. These reproduce the verified targets: ~15–20 min from a light to
225 °F, highest ramp rate *mid-ramp* (not at start), 5–20 °F overshoot for low-and-slow (up to
30–50 °F for high targets) decaying over `TAU_DOWN`, and ±5–10 °F settling in ~15–25 min. Larger
`PROPBAND` → less oscillation/slower; smaller → faster/more overshoot (verified direction).

### 6.3 Meat model + the stall — verified phenomenon, tunable parameters

Each food probe follows Newton's law toward pit temperature with its own long `tau_meat`, minus a
temperature-gated **evaporative-cooling sink** that produces the classic **stall** plateau at
150–170 °F, then releases as a per-cut "moisture budget" depletes (post-stall climb to done):

```python
drive = (cook_temp - meat_temp) / tau_meat
q     = evap_term(profile, meat_temp)   # bell-curve gated on the 150-170°F band; depletes moisture
meat_temp += (drive - q) * dt
if meat_temp >= meat_set: probe.status = StatusCode.DONE
```

Per-cut defaults (`tau_meat`, `evap_gain`, `stall_hours`, `target`) for brisket / pork butt / ribs /
whole chicken / chicken quarters live in **`profiles.py`**. A `wrapped` flag scales the moisture
budget down (Texas-crutch shortens/eliminates the stall). Sanity target for a 13–14 lb brisket at
225 °F pit: ~150 °F in ~3–4 h, stall ~155–165 °F for ~4 h, climb to 203 °F over ~2–3 h → ~10–12 h
total.

### 6.4 Feature behaviors (verified) folded into the control loop each tick

- **Deviation alarm (`ALARMDEV`).** Above setpoint by ≥ ALARMDEV → `COOK_STATUS=HIGH(1)`; below →
  `LOW(2)`. **Gated:** the LOW alarm is *suppressed during warm-up* and arms only after the pit
  first reaches near setpoint (`cook_armed`). Food probes have no HIGH/LOW — only `DONE(3)`.
- **Timer + `TIMEOUT_ACTION`.** Counts down to `00:00:00`, then: `HOLD` → `COOK_SET←COOKHOLD`,
  `TIMER_STATUS=HOLD(5)`; `ALARM` → control unchanged, `ALARM(6)`; `SHUTDOWN` → fan off (v2.3+) or
  `COOK_SET=32 °F` (v1.7 persona), `SHUTDOWN(7)`; `NO_ACTION` → stays `OK(0)`. A clear/keypress
  (admin action) returns to `OK`.
- **`COOK_RAMP` (cook-and-hold).** When the selected food is within ~30 °F of its setpoint, the
  *effective* pit setpoint is gradually lowered toward "slightly above food set" (`HOLD_MARGIN`
  ~5–10 °F). Computed on-the-fly; the stored `COOK_SET` is **not** overwritten (unlike HOLD).
- **`OPENDETECT` (open-lid).** A fast negative dT/dt trips `lid_open`; while open, force
  `OUTPUT_PERCENT=0` and suppress the LOW alarm; exit when temperature recovers/stabilizes.
- **Fuel exhaustion.** A `fuel_remaining` budget decays with duty; when spent, `T_drive→T_amb`
  regardless of duty (the "output 80–100 % for a long time = out of charcoal" signature).
- **Fan short** → `FAN_SHORTED=1`.

### 6.5 Profiles

A **profile** is the declarative spec that drives a cook: an initial pit state + optional pit
setpoint program, and up to **3 food-probe profiles** (cut type → `tau_meat`, stall params, target,
mass, `wrapped`). Profiles are what §6.2/§6.3 consume and are set via scenarios or the admin API.
They exist so a test can say "cook a brisket + two chicken quarters" without hand-tuning ODEs.

### 6.6 Integrator

Explicit Euler with **automatic sub-stepping**: `step(dt_sim)` splits into `N` sub-steps so each is
`<< min(tau)` (stability), which matters under heavy time acceleration (§7). All rates are expressed
per-second; the clock scales *how many sim-seconds pass per tick*, so **every curve shape (lag,
stall width, overshoot ratio, settling) is invariant under speed** — a 12 h brisket looks identical
whether played in 12 h, 12 min, or 12 s.

---

## 7. Time model: real-time and accelerated

One injectable **`VirtualClock`** drives all physics and all timers; **no code ever reads the wall
clock** directly (replacing the stub's `datetime.today()`). The clock has a single knob, `speed`:

- `speed = 1.0` → real time.
- `speed = 60` → 1 simulated minute per wall second.
- `speed = 0` (frozen) → time does not advance except via explicit `advance()`.

### Two drive modes

1. **Real-time / accelerated background loop.** A background async task ticks every
   `TICK_WALL_S` (default 100 ms) and calls `simulation.step(speed * dt_wall)`. This is the default
   for a running server so a client polling `status.xml` sees smooth, continuously-evolving values.

2. **Deterministic manual stepping.** Tests freeze the clock and call the admin
   `POST /__admin/time/advance {seconds}` (or the Python `sim.advance(seconds)`), which steps the
   simulation by exactly that many *simulated* seconds with sub-stepping. No wall-clock, no
   flakiness — same seed + same advances ⇒ identical output.

Because rates are per-second and durations are expressed via time constants, scaling `speed` is
shape-exact (§6.6). Under high acceleration the emulator reports the continuous **duty cycle** as
`OUTPUT_PERCENT` (never a meaningless 6-second flicker) and interpolates so any poll lands on a
smooth value.

Admin surface: `freeze`, `resume`, `scale {factor}`, `advance {seconds}`, `now`.

---

## 8. Fault-injection catalog & API

Faults live in the **core** (`core/faults/`) so they are seed-deterministic and drivable in-process;
the network/HTTP faults are *applied* by a thin device-plane ASGI middleware. Every fault is a
registered object with a common shape:

```python
@dataclass
class Fault:
    id: str                        # stable name, e.g. "http.error"
    enabled: bool = False
    probability: float = 1.0       # per-request/per-tick chance (uses the seeded RNG)
    scope: list[str] = ["*"]       # which device endpoints it applies to
    duration_s: float | None = None  # auto-expire after N simulated seconds
    count: int | None = None       # auto-expire after N activations
    params: dict = {}              # fault-specific knobs
```

Activation always consults the **single seeded RNG**, so a scenario replays identically. Faults
auto-clear on `duration`/`count` expiry, or via the admin `clear` calls.

### Catalog

| Fault id | Category | Effect | Key params |
|---|---|---|---|
| `net.unreachable` | network | Refuse connections (`ECONNREFUSED`) for a window. | `duration_s` |
| `net.blackhole` | network | Accept then hang silently (client timeout path). | `duration_s` |
| `net.latency` | network | Delay responses (fixed/jittered/distribution). | `mean_ms`, `jitter_ms`, `dist` |
| `net.conn_cap` | network | Cap concurrent connections; refuse beyond it (embedded-server EMFILE). | `max_conns` |
| `net.keepalive_drop` | network | Drop connection mid-stream. | `after_bytes` |
| `http.error` | http | Return 500/503/404/400 with (probabilistic) frequency. | `status`, `probability` |
| `http.truncate` | http | Cut the XML body mid-tag / early. | `at_byte`, `fraction` |
| `http.malformed` | http | Invalid entities, wrong root element, missing/extra fields, bad encoding. | `mode` |
| `http.wrong_content_type` | http | Serve XML as `text/plain`, mismatch charset, chunked vs length. | `content_type` |
| `http.slowloris` | http | Byte-drip a partial response. | `bytes_per_s` |
| `probe.open` | sensor | Force a probe to `OPEN` + `STATUS=4` (on command or schedule). | `probe`, `duration_s` |
| `probe.short` | sensor | Set `FAN_SHORTED=1` / probe short. | `probe` |
| `sensor.noise` | sensor | Additive Gaussian noise on a probe reading. | `probe`, `sigma_f` |
| `sensor.drift` | sensor | Slow bias/drift over time. | `probe`, `f_per_hour` |
| `sensor.stuck` | sensor | Freeze a probe at a value. | `probe`, `value_f` |
| `sensor.spike` | sensor | Occasional out-of-range spike/quantization glitch. | `probe`, `magnitude_f` |
| `power.brownout` | power | Device disappears T seconds, returns with config reset to defaults OR persisted. | `duration_s`, `reset` |
| `power.reboot` | power | Clean reboot: unavailable briefly, `TIMER`/state resume per persistence. | `reset` |

Admin surface: inject one (`POST /__admin/faults`), list active (`GET /__admin/faults`), clear one
(`DELETE /__admin/faults/{id}`), clear all (`DELETE /__admin/faults`). Faults are also declarable as
scenario steps (§10).

---

## 9. Control/admin API endpoint surface

The control plane is JSON + OpenAPI (Swagger UI at `/__admin/docs`, spec at
`/__admin/openapi.json`). All paths are namespaced under `/__admin`. Requests/responses are
Pydantic-validated. The same operations are available in-process via `AdminClient` and directly on
the `Simulation` object (so tests need not go through HTTP).

| Method & path | Purpose | Body / params | Returns |
|---|---|---|---|
| `GET /__admin/health` | Liveness. | — | `{status, uptime}` |
| `GET /__admin/state` | Full device + sim state (visible + physical). | — | `DeviceState` + `SimState` JSON |
| `PATCH /__admin/state` | Drive any state field directly (bypass wire rules). | partial state JSON | new state |
| `POST /__admin/state/reset` | Reset to factory (or demo) defaults. | `{mode: factory\|demo}` | state |
| `POST /__admin/state/snapshot` | Dump full state for later restore. | — | `{snapshot_id, blob}` |
| `POST /__admin/state/restore` | Restore a snapshot blob. | `{blob}` | state |
| `GET /__admin/probes/{probe}` | Read one probe (cook/food1..3). | — | `ProbeState` |
| `POST /__admin/probes/{probe}/disconnect` | Force probe OPEN. | `{duration_s?}` | probe |
| `POST /__admin/probes/{probe}/reconnect` | Reconnect probe. | — | probe |
| `GET /__admin/time` | Current sim time, speed, frozen? | — | `{now_s, speed, frozen}` |
| `POST /__admin/time/advance` | Step sim by N simulated seconds. | `{seconds}` | `{now_s}` |
| `POST /__admin/time/scale` | Set acceleration factor. | `{factor}` | `{speed}` |
| `POST /__admin/time/freeze` | Freeze clock (speed→0). | — | `{frozen:true}` |
| `POST /__admin/time/resume` | Resume at previous/`{speed}`. | `{speed?}` | `{speed}` |
| `GET /__admin/faults` | List active faults. | — | `[Fault]` |
| `POST /__admin/faults` | Inject a fault. | `Fault` JSON | `Fault` |
| `DELETE /__admin/faults/{id}` | Clear one fault. | — | `204` |
| `DELETE /__admin/faults` | Clear all faults. | — | `204` |
| `GET /__admin/rng` | Current seed & draw count. | — | `{seed, draws}` |
| `POST /__admin/rng/seed` | Seed/reseed all randomness. | `{seed}` | `{seed}` |
| `GET /__admin/scenario` | Current scenario + progress. | — | `{name, step, done}` |
| `POST /__admin/scenario/load` | Load & start a scenario. | scenario JSON/YAML or `{name}` | `{name}` |
| `POST /__admin/scenario/step` | Advance to next scenario step. | — | `{step}` |
| `POST /__admin/scenario/stop` | Stop/clear the scenario. | — | `204` |
| `POST /__admin/profile` | Set pit + food profiles (cook definition). | profiles JSON | profiles |
| `POST /__admin/persona` | Switch firmware persona (field-set/behavior). | `{fwver}` | `{fwver}` |
| `GET /__admin/requests` | Request journal (ring buffer): method, path, body, ts, fault fired. | `?limit&path` | `[Request]` |
| `DELETE /__admin/requests` | Clear the request journal. | — | `204` |
| `GET /__admin/metrics` | Counters (requests, faults, errors); Prometheus format available. | `?format` | metrics |
| `POST /__admin/assert` | Server-side assertion helper (state/probe/time predicates). | `{predicate}` | `{ok, detail}` |

The **request journal** (WireMock-style) is what lets the external api-proxy repo assert *what its
client actually sent* (e.g. "posted `COOK_SET=225` to `/`"), which is invaluable for verifying proxy
behavior without a real device.

---

## 10. Scenario / config file format

Scenarios are declarative YAML (or JSON) validated by a Pydantic model. A scenario has: metadata, a
starting `seed`, an initial `state`/`profile`, and a `timeline` of time-ordered `steps`. Each step
runs `at` a simulated time and does one of: `set` state, `profile` change, `fault` inject/clear,
`time` op, or `assert`. Steps with the same `at` run in order. The runner advances the virtual clock
to each step's time (deterministically) and applies it.

```yaml
# examples: docs/scenarios.md ; shipped in scenario/builtin/
name: brisket_with_flaky_wifi
description: >
  13 lb brisket + two chicken quarters at 250°F, a mid-cook probe disconnect,
  a burst of HTTP 500s, and a stall assertion. Deterministic under seed 42.
seed: 42
speed: 600                      # 1 wall-sec = 10 sim-min (override per-run)
persona: "3.1"                  # firmware persona

initial:
  state:
    control: { propband: 25, cyctime: 6, alarmdev: 50, cook_ramp: FOOD1 }
    system:  { deg_units: FAHRENHEIT }
  profile:
    pit:   { start_f: 70, ambient_f: 70, cook_set_f: 250 }
    food1: { cut: brisket,          set_f: 203, mass_lb: 13, wrapped: false }
    food2: { cut: chicken_quarters, set_f: 175, mass_lb: 0.7 }
    food3: { disconnected: true }   # emits OPEN / STATUS=4

timeline:
  - at: 0m
    set: { cook: { set: 2500 } }    # tenths-°F when writing state directly

  - at: 20m
    assert:                          # pit should have reached the band by now
      pit_temp_f: { ">=": 240, "<=": 260 }

  - at: 3h
    assert:                          # brisket entering the stall
      food1_temp_f: { ">=": 150, "<=": 170 }

  - at: 3h30m
    fault: { id: probe.open, params: { probe: food2 }, duration_s: 600 }

  - at: 4h
    fault: { id: http.error, params: { status: 500 }, probability: 1.0, count: 5 }

  - at: 8h
    assert:
      food1_status: DONE
      food1_temp_f: { ">=": 200 }
```

Time literals accept `s`/`m`/`h` (`3h30m`). Temperatures are whole-°F in `profile`/`*_f` asserts and
tenths-°F when writing raw state (mirroring the real wire's dual representation, kept explicit so the
distinction is testable). The same schema is accepted by `POST /__admin/scenario/load`, the CLI
(`--scenario brisket.yaml`), and the pytest fixtures.

A separate lightweight **server config** file / env vars set ports, default persona, default seed,
tick rate, auth mode, and log format — kept distinct from scenarios.

---

## 11. Client / test-harness & pytest fixtures

### In-process harness (context manager)

```python
from virtualcyberq.testing import VirtualCyberQ

with VirtualCyberQ(seed=42, speed=0) as cq:      # frozen clock, ephemeral ports
    cq.load_scenario("brisket_with_flaky_wifi")
    device_url = cq.device_url                    # e.g. http://127.0.0.1:53411
    admin      = cq.admin                         # AdminClient (or direct sim calls)

    admin.time.advance(seconds=3*3600)            # jump to the stall, deterministically
    admin.probes.disconnect("food2")
    admin.faults.inject(id="http.error", status=500, count=3)

    resp = httpx.get(f"{device_url}/status.xml")  # your client / proxy hits the DEVICE plane
    assert "<COOK_TEMP>" in resp.text
    assert admin.state().food1.status == "DONE"   # assert via control plane
```

`VirtualCyberQ` runs both apps in-thread (uvicorn in a daemon thread) over one `Simulation`, binds
ephemeral ports, and tears down cleanly. `cq.admin` also exposes the `Simulation` directly
(`cq.sim`) for zero-HTTP puppeteering (`cq.sim.probe_disconnect("food2")`).

### Pytest plugin (registered via entry point)

Installing the package auto-provides fixtures in **any** repo (including an external api-proxy repo):

```python
# available fixtures (from virtualcyberq.testing.pytest_plugin):
#   cyberq             -> function-scoped VirtualCyberQ (frozen clock, seed from marker/param)
#   cyberq_session     -> session-scoped server (shared, faster)
#   cyberq_url         -> device base URL string
#   cyberq_admin       -> AdminClient handle

def test_proxy_reads_pit_temp(cyberq, cyberq_url):
    cyberq.sim.set_pit_temp_f(225.0)
    r = httpx.get(f"{cyberq_url}/status.xml")
    assert r.status_code == 200
    # COOK_TEMP is tenths-°F:
    assert "<COOK_TEMP>2250</COOK_TEMP>" in r.text

@pytest.mark.cyberq(seed=7, scenario="flaky_wifi")
def test_proxy_survives_500s(cyberq, cyberq_url):
    cyberq.admin.faults.inject(id="http.error", status=500, count=2)
    ...  # assert the proxy retries / degrades gracefully
```

An external repo enables it with one line in `conftest.py` (`pytest_plugins =
["virtualcyberq.testing.pytest_plugin"]`); `examples/proxy_repo_conftest.py` is a copy-paste
starter.

### CLI & Docker

```bash
virtual-cyberq --device-port 8080 --admin-port 9000 --seed 42 --scenario brisket.yaml --speed 600
docker run -p 8080:8080 -p 9000:9000 ghcr.io/kevinteg/virtualcyberq --seed 42
```

`docker-compose.yml` maps both ports, sets env config, and adds a healthcheck hitting
`/__admin/health`. The image is the recommended way for client authors (e.g. `ha_cyberq`
contributors) who lack the discontinued hardware.

---

## 12. Testing strategy

Layered, and all deterministic (frozen clock + fixed seed):

1. **Unit (`tests/unit/`).** `units.py` (tenths↔float, OPEN, HH:MM:SS round-trips), the control law
   against the verified P-band points (200/212.5/225), thermal ramp targets, stall duration,
   deviation-alarm gating, timeout/ramp/opendetect transitions, validation clamp/reject, and
   fault-object seed determinism.

2. **Wire / golden-file (`tests/wire/`).** Serialize known states and assert **byte-for-byte** (or
   XSD-valid + field-equal) against **captured real-device fixtures** (`tests/fixtures/real_*.xml`).
   This is the fidelity contract; it guards against regressions in the wire shape (root element
   names, comment block, tenths encoding, `OPEN`).

3. **Contract (`tests/contract/`).** Run the **real external parsers** against the emulator:
   parse our XML with `CyberQInterface` (lxml objectify) and `ha_cyberq`'s decoders; POST via their
   client code and assert our state changed. If these libraries parse us cleanly and their writes
   land, we are a faithful stand-in.

4. **Fault (`tests/faults/`).** Each fault produces its specified effect (latency measured,
   truncated body is truncated, 500 returned at the right probability under a fixed seed,
   brownout removes/returns the device) and is reproducible across two runs with the same seed.

5. **Scenario (`tests/scenario/`).** Every shipped builtin scenario runs to completion with all its
   in-scenario asserts passing; snapshot/restore round-trips.

6. **Property-based (Hypothesis).** Fuzz POST bodies and state writes: no crash, invariants hold
   (temps stay valid tenths ints or `OPEN`, statuses stay in 0–7, `OUTPUT_PERCENT` in 0–100).

7. **Determinism meta-test.** Same seed + same scenario ⇒ identical journal + identical XML stream
   hash; a nightly job runs it twice and diffs.

Tooling: `pytest`, `pytest-asyncio`, `hypothesis`, `coverage` (target ≥90 % on `core/`), `httpx`
for in-proc HTTP.

---

## 13. Packaging, CI, licensing

### `pyproject.toml` (PEP 621; replaces `setup.py`/`setup.cfg`)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "virtual-cyberq"
version = "0.1.0"
description = "High-fidelity virtual/emulated BBQ Guru CyberQ WiFi device with thermal simulation, fault injection, and an out-of-band control API."
readme = "README.md"
requires-python = ">=3.8"
license = { text = "BSD-3-Clause" }
authors = [{ name = "Kevin Tegtmeier", email = "kevin@tegtmeier.me" }]
keywords = ["cyberq", "bbqguru", "bbq", "emulator", "simulator", "test", "fake-device"]
classifiers = [
  "License :: OSI Approved :: BSD License",
  "Programming Language :: Python :: 3.8",
  "Programming Language :: Python :: 3.9",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Framework :: Pytest",
  "Topic :: Software Development :: Testing :: Mocking",
]
dependencies = [
  "fastapi>=0.100",
  "uvicorn[standard]>=0.23",
  "pydantic>=2",
  "pyyaml>=6",
  "httpx>=0.24",
]

[project.optional-dependencies]
dev  = ["pytest>=7", "pytest-asyncio", "hypothesis", "coverage", "ruff", "mypy", "import-linter"]
docs = ["mkdocs", "mkdocs-material"]

[project.scripts]
virtual-cyberq = "virtualcyberq.cli:main"

[project.entry-points.pytest11]
virtualcyberq = "virtualcyberq.testing.pytest_plugin"

[project.urls]
Homepage = "https://github.com/kevinteg/VirtualCyberQ"
Issues   = "https://github.com/kevinteg/VirtualCyberQ/issues"

[tool.ruff]
target-version = "py38"
line-length = 100

[tool.mypy]
python_version = "3.8"
strict = true
```

### GitHub Actions

- **`ci.yml`** (on push/PR): matrix `python-version: [3.8, 3.9, 3.10, 3.11, 3.12]` ×
  `os: [ubuntu-latest]` (plus macOS on main). Steps: `ruff check` (lint+format), `mypy --strict`,
  `import-linter` (enforce **`core/` imports no web framework**), `pytest` with coverage, upload
  coverage. Fail the build if `core/` gains a framework import.
- **`docker.yml`** (on tag): build multi-arch image, push to GHCR.
- **`release.yml`** (on `v*` tag): build sdist+wheel with hatchling, publish to PyPI via
  **trusted publishing (OIDC)** — no stored token. Optionally attach the XSDs and example scenarios.

### Licensing & docs

- **`LICENSE`: BSD-3-Clause** — matches the existing `setup.py` "BSD New" declaration. Every source
  file carries an SPDX header (`# SPDX-License-Identifier: BSD-3-Clause`).
- **`README.md`**: what it is, the two-plane model, 3-line quickstart (docker + "point your client
  at `:8080`"), the admin API teaser, and the pytest-plugin one-liner.
- **`CONTRIBUTING.md`**: dev env (`pip install -e .[dev]`), how to run lint/type/test, the
  `core/`-stays-framework-agnostic rule, how to add a fault or a scenario, commit style, and DCO
  sign-off. Note the fidelity-vs-inference convention: anything not verified against a real device
  is labeled and lives behind tunable defaults.
- **Docs site** (`mkdocs`): `protocol.md` (wire contract + field tables), the auto-generated admin
  OpenAPI (`admin-api.md`), and `scenarios.md` (format + cookbook). The **device plane is documented
  by XSD** (`docs/cyberq_*.xsd`) rather than OpenAPI, because it is XML; the **admin plane is
  documented by OpenAPI/Swagger**.

---

## 14. Prioritized "extra useful features"

Ordered by value-to-effort for a virtual-device implementation:

1. **Request journal + server-side asserts (§9).** Highest leverage: lets any proxy repo verify
   exactly what its client sent, no hardware needed.
2. **Golden-file / contract tests against captured real XML (§12).** Turns "faithful" from a claim
   into a guarantee; also gives every downstream repo trustworthy regression fixtures.
3. **Firmware-version personas** (`1.7` / `2.3` / `3.1` / `4.08`-Cloud): switch field-set and
   behavior (e.g. v1.7 SHUTDOWN sets `COOK_SET=32 °F` vs v2.3 fan-off; `FWVER`/`MAC` presence).
   Real clients branch on `FWVER`.
4. **Record & replay.** Import a captured real-device `status.xml` stream (or a client's POST
   sequence) and replay it verbatim as a scenario — bootstraps fixtures without hardware.
5. **State snapshot/restore** (already in the admin API) — reproduce any reported bug from a JSON
   blob.
6. **Multi-device fleet mode.** Run N virtual units on N ports for integration tests of multi-unit
   setups.
7. **mDNS/zeroconf + fake discovery responder.** So clients' auto-discovery flows can find the
   emulator.
8. **Web dashboard on the admin port.** Eyeball the cook, drag temps, click faults during manual
   testing.
9. **Configurable HTTP quirks.** Match the real firmware's `Server:` header, `Connection: close`,
   no-chunking, low connection cap — plus latency profiles ("congested wifi", "flaky AP").
10. **Strict/lenient fidelity switch.** Lenient (clamp, ignore unknowns) by default for fidelity;
    strict rejects invalid writes for negative-path testing once real behavior is characterized.
11. **Cloud-mode shim.** Emulate the CyberQ Cloud alias/REST layer `ha_cyberq` supports, so both
    code paths are testable.
12. **Optional TLS / auth toggle.** Off by default (fidelity), on for testing a hardened proxy.
13. **Property-based test hooks (Hypothesis)** exported for downstream client-parser fuzzing.

---

## Appendix A: verified enums, encodings, ranges, defaults

**Encoding.** Temps on the wire are **integer tenths-of-°F** in the current `DEG_UNITS`
(`3343`→334.3). Writes arrive in **whole °F** (decimal allowed). Open probe → literal `OPEN` +
`STATUS=4`. Timer `HH:MM:SS` (`%3A` when POSTed).

**Enums (value = wire integer).**

| Enum | Values |
|---|---|
| Status (`*_STATUS`) | 0 OK · 1 HIGH · 2 LOW · 3 DONE · 4 ERROR · 5 HOLD · 6 ALARM · 7 SHUTDOWN |
| `DEG_UNITS` | 0 Celsius · 1 Fahrenheit |
| `COOK_RAMP` | 0 Off · 1 Food1 · 2 Food2 · 3 Food3 |
| `TIMEOUT_ACTION` | 0 No Action · 1 Hold · 2 Alarm · 3 Shutdown |
| `OPENDETECT`/`MENU_SCROLLING`/`KEY_BEEPS` | 0 Off · 1 On |

**Ranges (input, whole °F where temperature).** `COOK_SET`/`FOOD*_SET`/`COOKHOLD` 32–475 °F ·
`ALARMDEV` 10–100 °F · `PROPBAND` 5–100 °F · `CYCTIME` 4–10 s (firmware; some clients allow 1–30) ·
`ALARM_BEEPS` 0–5 · `LCD_BACKLIGHT`/`LCD_CONTRAST` 0–100 % · `COOK_TIMER` ≤ 99:59:59 ·
names ≤ 16 chars.

**Verified factory defaults.** `COOK_SET` 275 °F · `FOOD*_SET` 180 °F · `CYCTIME` 6 s ·
`PROPBAND` 25 °F · `ALARMDEV` 50 °F · `COOKHOLD` 200 °F · `TIMEOUT_ACTION` No Action ·
`COOK_RAMP` Off · `OPENDETECT` On · `DEG_UNITS` °F · `ALARM_BEEPS` 3 · `KEY_BEEPS` On ·
`LCD_BACKLIGHT` 50 % · `LCD_CONTRAST` 10 % · `MENU_SCROLLING` Off · hot-spot WiFi enc WEP40, key
`1234abcdef`, IP `192.168.101.10`, port 80; SMTP `mail.cyberqmail.com:587`.

**Demo seed values (shipped, not factory).** Cook "Big Green Egg" · Food1 "Chicken Quarters" 155 °F
· Food2 "Beef Brisket" 180 °F · Food3 "Pork Chop" 160 °F.

**Thermal defaults (tunable, inferred; fit to verified anecdotes).** `T_amb` 70 °F · `T_fire_max`
700 °F · `TAU_UP` 12 min · `TAU_HOLD` 20 min · `TAU_DOWN` 90 min · `TAU_FIRE` 3 min · `T_LAG` 4 min ·
stall band 150–170 °F · per-cut `tau_meat`/`stall_hours`: brisket 360 min/4 h, pork butt 330 min/3.5 h,
ribs 180 min/0.75 h, whole chicken 105 min/~0, chicken quarters 55 min/0 · lid-open drop ~60 °F,
`tau_open` 4 min. All exposed as parameters; anything not verified against real hardware is labeled a
modeling choice.

**Inference caveats (need a real-device dump to pin).** Exact integer maps for `WIFIMODE`, `DHCP`,
`WIFI_ENC`, `SMTP_ALERT`; the exact reboot POST key; the shorted-food-probe sentinel; whether
`CYCTIME` device limit is 4–10 or 1–30; the precise `TIMER_STATUS` code assignments.

---

## Appendix B: build phasing

1. **Core + wire (MVP).** `state`, `enums`, `defaults`, `units`, XML serializers, POST parse; device
   FastAPI app serving byte-faithful `status/all/config.xml` from static state + accepting writes.
   Golden-file + contract tests green. This alone is a drop-in stand-in.
2. **Simulation.** `clock`, `rng`, `control` law, `thermal` pit model, timer/timeout, status
   transitions; real-time background loop; time-accelerated stepping.
3. **Control plane.** Admin FastAPI app, `AdminClient`, `testing` harness + pytest plugin, request
   journal.
4. **Faults.** Registry + middleware; the full catalog; determinism tests.
5. **Scenarios + meat/stall profiles.** Scenario model/runner, builtin scenarios, per-cut thermal.
6. **Polish.** Docker/compose, docs site, personas, record/replay, dashboard, PyPI release.
