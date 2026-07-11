# Changelog

All notable changes to VirtualCyberQ are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-07-10

Initial release.

### Added

- **Device plane (`:8080`)** — byte-faithful CyberQ WiFi wire contract:
  `GET /status.xml` (`<nutcstatus>`), `GET /all.xml` and `GET /config.xml`
  (`<nutcallstatus>`), the root HTML "Control Status" page, legacy `*.htm`
  pages, form-`POST /` writes, and a tolerant `POST /status.xml`. Temperatures
  in tenths-of-°F, the `OPEN` sentinel for open probes, the 0–7 status enums,
  and no authentication — matching the hardware.
- **Framework-agnostic core** — `DeviceState`, thermal pit + meat models with
  the stall, the proportional-band (P-band) blower control law, an injectable
  `VirtualClock` (freeze / advance / scale), a single `SeededRNG`, and the XML
  serializers. Imports no web framework (enforced by import-linter).
- **Control plane (`:9000`)** — JSON + OpenAPI admin API under `/__admin`
  (Swagger UI at `/__admin/docs`): state read/patch, reset, snapshot/restore,
  time freeze/advance/scale, RNG seeding, probe disconnect/reconnect, fault
  inject/list/clear, scenario load/step/stop, persona/profile, a WireMock-style
  request journal, metrics, and server-side asserts.
- **Fault-injection catalog** — network (`net.unreachable`, `net.blackhole`,
  `net.latency`, `net.conn_cap`, `net.keepalive_drop`), HTTP (`http.error`,
  `http.truncate`, `http.malformed`, `http.wrong_content_type`,
  `http.slowloris`), sensor (`probe.open`, `probe.short`, `sensor.noise`,
  `sensor.drift`, `sensor.stuck`, `sensor.spike`), and power
  (`power.brownout`, `power.reboot`). All seed-deterministic.
- **Scenarios** — declarative YAML timeline format with `set` / `profile` /
  `fault` / `time` / `assert` steps; builtin `brisket_with_flaky_wifi` and
  `flaky_wifi`.
- **Test harness** — the in-process `VirtualCyberQ` context manager (ephemeral
  ports, frozen clock) and a pytest plugin (`cyberq`, `cyberq_session`,
  `cyberq_url`, `cyberq_admin` fixtures + a `@pytest.mark.cyberq` marker),
  registered via the `pytest11` entry point for use in downstream repos.
- **Typed control client** — `AdminClient`, usable over HTTP (`base_url=`) or
  in-process (`sim=`).
- **CLI** — the `virtual-cyberq` console script.
- **Packaging & ops** — Python 3.10+; PEP 621 `pyproject.toml` (hatchling),
  Docker image and `docker-compose.yml`, and GitHub Actions for CI (matrix
  3.10–3.13: ruff, ruff-format, mypy `--strict`, import-linter, pytest +
  coverage), GHCR image publishing on tag, and PyPI release via trusted
  publishing on `v*` tags.
- **Docs** — `README.md`, `CONTRIBUTING.md`, `docs/DESIGN.md`,
  `docs/CYBERQ_PROTOCOL.md`, `docs/scenarios.md`, and example scripts under
  `examples/`.

### Calibrated against a real unit (firmware 1.7)

The XML serializers and factory defaults were corrected against captured
`status.xml` / `all.xml` / `config.xml` dumps from a real CyberQ WiFi:

- Comment block moved **inside** the root element and reduced to the real 2-line
  form (plus the per-feed "this is similar to …" lead comment on all/config);
  3-space indentation; **`status.xml` no longer emits `FAN_SHORTED`** on 1.7.
- `<WIFI>` `<MAC>` now sits right after `<SSID>`.
- Factory defaults fixed: **`FWVER` 1.7**, **`PROPBAND` 300** (30 °F, was 25),
  **`KEY_BEEPS` off**, SMTP block (`smtp.hostname.com`, port 0, generic to/from),
  `WIFIMODE`/`DHCP`/`WIFI_ENC` = 1.
- `tests/wire/` now enforces a **byte-for-byte golden contract** against these
  captured (LF-canonicalized, network-field-sanitized) fixtures — no longer
  `xfail`.

### Notes / known limitations

- **Thermal constants are provisional.** The pit ramp, overshoot (~25–30 °F on a
  cold start to a low-and-slow target), the ~5–7 °F steady-state proportional
  droop, and the meat/stall curves are physically plausible but not yet
  calibrated against a real unit. They are all tunable via the profiles; the
  DESIGN §6.1 integral-bias option (to hold at setpoint with ~10 % output) is
  documented but not yet enabled.
- **Line endings canonicalized to LF.** The captured dumps suggest the real unit
  emits CRLF (`\r\n`) with trailing spaces on some lines; the serializers emit
  clean LF. This is a one-line change if exact byte-for-byte CRLF is desired
  (confirm with `curl -s http://<ip>/status.xml | xxd | head`).
- **`HEAD` on unknown paths / methods** return a minimal `text/html` body rather
  than a FastAPI JSON error, so the device plane can't be fingerprinted as an
  emulator; the real unit's exact `HEAD`/error behavior is not documented.

[Unreleased]: https://github.com/kevinteg/VirtualCyberQ/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/kevinteg/VirtualCyberQ/releases/tag/v0.1.0
