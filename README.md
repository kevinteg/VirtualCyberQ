# VirtualCyberQ

**A high-fidelity, open-source virtual/emulated [BBQ Guru CyberQ WiFi](https://www.bbqguru.com/) device — in modern Python (3.8+).**

VirtualCyberQ is a drop-in stand-in for a physical CyberQ WiFi temperature
controller. It serves the *exact* device-facing XML/HTTP API a real unit
exposes — backed by a physically-plausible thermal simulation of a pit and its
meat — plus a completely separate **control/admin API** that lets tests
deterministically drive state, load scenarios, scale simulated time, and inject
faults.

The goal: an external CyberQ **api-proxy / client repo** (e.g. `ha_cyberq`,
`CyberQInterface`) can point at VirtualCyberQ **unchanged** and cannot tell it
apart from real hardware on the fidelity plane — while both this repo's tests
and that repo's tests can puppeteer physics and failures through a separate
control plane. That makes it the recommended way to develop CyberQ clients
without the discontinued hardware.

---

## The two-plane model

The single most important design decision is a strict separation between two
planes over one shared simulation. The **core** (state model, thermal engine,
control loop, virtual clock, seeded RNG, fault registry, XML serializers) is
framework-agnostic and imports **no** web framework.

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

Everything runs off one **injectable virtual clock** and one **seeded RNG**, so
the same seed + same scenario produces a byte-identical output stream — the
property that makes it usable in CI.

---

## Quickstart

### Install

```bash
pip install -e '.[dev]'      # from a checkout, with dev tooling
# or, once released:
pip install virtual-cyberq
```

### Run it

```bash
virtual-cyberq
# device  -> http://localhost:8080   admin -> http://localhost:9000/__admin/docs
```

Common options (all optional):

```bash
virtual-cyberq \
  --device-port 8080 --admin-port 9000 \
  --seed 42 --speed 600 \
  --scenario brisket_with_flaky_wifi \
  --persona 3.1
```

`--speed` is the clock acceleration (simulated seconds per wall-second; `0`
freezes for manual stepping). `--scenario` takes a builtin name, a path, or an
inline YAML scenario.

### Docker

```bash
docker run --rm -p 8080:8080 -p 9000:9000 ghcr.io/kevinteg/virtualcyberq --seed 42
```

or with compose (maps both ports, sets env config, adds a healthcheck):

```bash
docker compose -f docker/docker-compose.yml up
```

The image is the recommended path for client authors who lack the discontinued
hardware.

---

## Point your CyberQ client at it

Configure your CyberQ client / api-proxy to talk to:

> **`http://localhost:8080`**

That plane is a byte-faithful CyberQ WiFi: `GET /status.xml`, `GET /all.xml`,
`GET /config.xml`, the root HTML page, and form-`POST /` writes — `nutcstatus` /
`nutcallstatus` XML, temperatures in **tenths of °F**, the literal string `OPEN`
for an open probe, the exact 0–7 status enums, and no authentication (matching
the hardware). Nothing from the admin plane leaks onto it.

```bash
curl http://localhost:8080/status.xml
```

Fidelity is exact: for a factory unit with no probes plugged in, `status.xml` and
`all.xml` are **byte-identical** to a real firmware-1.7 CyberQ WiFi (CRLF line
endings, trailing spaces, no trailing newline included), and the response headers
match (`Content-Type: text/xml`, `Cache-Control: no-cache`, `Connection: close`,
no `Server`).

---

## Choose a firmware version

Real units differ slightly by firmware. Pick which one to emulate:

```bash
virtual-cyberq --list-personas          # 1.7 [verified], 2.3, 3.1 [documented]
virtual-cyberq --firmware 3.1           # emulate firmware 3.1 (default: 1.7)
```

At runtime, switch or query via the admin plane
(`GET /__admin/personas`, `POST /__admin/persona`) or a scenario's `persona:`
field. **Firmware 1.7** is byte-verified against real hardware; **2.3 / 3.1** add
the documented behavioral difference (a SHUTDOWN timeout turns the blower off
instead of dropping the setpoint to 32 °F) and otherwise reuse the 1.7 wire
format pending a capture of those versions.

---

## The control / admin API

The control plane is a JSON + OpenAPI API, namespaced under `/__admin` on a
**different port** (`:9000` by default). Interactive docs (Swagger UI):

> **http://localhost:9000/__admin/docs**  ·  spec at `/__admin/openapi.json`

It lets you read/drive full device + sim state, load scenarios, advance / scale
/ freeze simulated time, inject and clear faults, seed the RNG,
snapshot/restore, and inspect a WireMock-style request journal (so a proxy repo
can assert exactly what its client sent). A few examples:

```bash
curl http://localhost:9000/__admin/health
curl http://localhost:9000/__admin/state
curl -X POST http://localhost:9000/__admin/time/advance -d '{"seconds": 3600}' -H 'content-type: application/json'
curl -X POST http://localhost:9000/__admin/faults       -d '{"id":"http.error","params":{"status":500},"count":2}' -H 'content-type: application/json'
```

The same operations are available in-process via the typed `AdminClient` and
directly on the `Simulation` object, so tests need not go through HTTP. See
[`examples/`](examples/) for `run_local.py`, `drive_a_cook.py`, and
`inject_faults.py`.

---

## Use it in your test suite (pytest plugin)

Installing the package auto-registers a pytest plugin (via the `pytest11` entry
point) that provides fixtures to **any** repo — including an external
api-proxy repo. Enable it in that repo with **one line** in `conftest.py`:

```python
# conftest.py
pytest_plugins = ["virtualcyberq.testing.pytest_plugin"]
```

Then write tests against a real virtual device with **ephemeral ports** and a
**frozen, deterministic clock**:

```python
import httpx

def test_proxy_reads_pit_temp(cyberq, cyberq_url):
    cyberq.sim.set_pit_temp_f(225.0)
    r = httpx.get(f"{cyberq_url}/status.xml")
    assert r.status_code == 200
    assert "<COOK_TEMP>2250</COOK_TEMP>" in r.text        # tenths-degF on the wire

@pytest.mark.cyberq(seed=7, scenario="flaky_wifi")
def test_proxy_survives_500s(cyberq, cyberq_url):
    cyberq.admin.faults.inject("http.error", status=500, count=2)
    ...  # assert your proxy retries / degrades gracefully
```

Available fixtures: `cyberq` (function-scoped harness), `cyberq_session`
(session-scoped shared server), `cyberq_url` (device base URL), `cyberq_admin`
(`AdminClient`). A ready-to-copy starter is
[`examples/proxy_repo_conftest.py`](examples/proxy_repo_conftest.py).

---

## Documentation

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture, state model, control law, fault catalog, admin API.
- [`docs/CYBERQ_PROTOCOL.md`](docs/CYBERQ_PROTOCOL.md) — the verified XML/HTTP wire contract.
- [`docs/scenarios.md`](docs/scenarios.md) — scenario file format + cookbook.
- Admin plane: OpenAPI/Swagger at `/__admin/docs`. Device plane: documented by the XSD schemas in `docs/`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the dev setup, the lint/type/test
loop, and the hard rule that `core/` stays framework-agnostic. Changes are
tracked in [`CHANGELOG.md`](CHANGELOG.md).

## License

[BSD-3-Clause](LICENSE). Every source file carries an SPDX header.
