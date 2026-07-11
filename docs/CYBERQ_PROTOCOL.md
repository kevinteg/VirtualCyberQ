# CyberQ WiFi — HTTP/XML Protocol Reference

**Authoritative specification for the VirtualCyberQ virtual device.**

This document describes the local HTTP/XML "web service" exposed by the BBQ Guru **CyberQ WiFi** temperature controller and the temperature-regulation behavior our virtual device must faithfully reproduce. It is a reverse-engineering reference compiled from the official BBQ Guru user guides, multiple independent open-source client integrations, and this project's own templates.

Reference firmware family: **CyberQ WiFi, firmware v1.7 through v2.3 / 3.1** (the "WIFI CONTROL 2.0" hardware). The later **CyberQ Cloud** is a *different* product with a cloud-only API and is out of scope except where noted in §13.

Every non-obvious claim carries a confidence tag:

- **[V]** — VERIFIED in a cited source (see §14 for URLs).
- **[I]** — INFERRED by expert reasoning; not directly published. Treat as a modeling choice.

> **Verified against a real CyberQ WiFi (firmware 1.7), 2026-07-10.** Captured `status.xml` / `all.xml` / `config.xml` dumps confirmed and corrected several details this document originally inferred:
> - The temperature comment block lives **inside** the root element (after `<nutcstatus>` / `<nutcallstatus>`), as **two** lines (`…should be in F.  you can send tenths F with a decimal place, ex: 123.5`), not three; `all.xml` and `config.xml` additionally open with a `<!--this is similar to …-->` lead comment. Indentation is 3 spaces per level.
> - `status.xml` on firmware 1.7 does **not** include a `FAN_SHORTED` element.
> - In `<WIFI>`, `<MAC>` appears **immediately after `<SSID>`** (before `WIFI_ENC`).
> - Factory defaults observed: `COOK_SET` 275, `FOOD*_SET` 180, `COOKHOLD` 200, `ALARMDEV` 50, **`PROPBAND` 300 (30 °F, not 25)**, `CYCTIME` 6, `TIMEOUT_ACTION` 0, `OPENDETECT` 1, `DEG_UNITS` 1, `ALARM_BEEPS` 3, **`KEY_BEEPS` 0**, `LCD_BACKLIGHT` 50, `LCD_CONTRAST` 10, `MENU_SCROLLING` 0; probe names `Cook`/`Food1`/`Food2`/`Food3`; `WIFIMODE`/`DHCP`/`WIFI_ENC` = 1; SMTP host `smtp.hostname.com`, port 0.
> - Wire line endings appear to be CRLF with occasional trailing spaces (the emulator canonicalizes to LF).

---

## Table of Contents

1. [Overview](#1-overview)
2. [HTTP Endpoints](#2-http-endpoints)
3. [Temperature & Value Encoding](#3-temperature--value-encoding)
4. [`status.xml` Schema](#4-statusxml-schema)
5. [`all.xml` Schema](#5-allxml-schema)
6. [`config.xml` Schema](#6-configxml-schema)
7. [POST Update Parameter Catalog](#7-post-update-parameter-catalog)
8. [Enumerations & Status Codes](#8-enumerations--status-codes)
9. [Control & Regulation Behavior](#9-control--regulation-behavior)
10. [Pseudocode Control Loop](#10-pseudocode-control-loop)
11. [Timer Semantics](#11-timer-semantics)
12. [Factory Defaults](#12-factory-defaults)
13. [CyberQ Cloud Differences](#13-cyberq-cloud-differences)
14. [Confidence & Sources](#14-confidence--sources)

---

## 1. Overview

The CyberQ WiFi is a charcoal/pit temperature controller with:

- **One pit ("cook") probe** and a **fan/blower output** it modulates to hold the pit at a setpoint.
- **Three food probes** (FOOD1, FOOD2, FOOD3), each with its own name, setpoint, and done alarm.
- A **countdown cook timer** with a configurable expiry action.
- A tiny embedded **HTTP/1.x server on TCP port 80** (configurable via `HTTP_PORT`). **[V]**

The device is controlled locally over the LAN via an **XML-over-HTTP "web service"**:

- **Reads** are `GET` requests for three XML feeds: `/status.xml`, `/all.xml`, `/config.xml`. **[V]**
- **Writes** are `application/x-www-form-urlencoded` `POST` requests carrying `KEY=value&KEY2=value2&…` bodies. **[V]**

Key protocol properties our virtual device must honor:

- **No authentication.** No Basic/Digest auth, no token, no cookie, no session. Anyone with network reach can read all XML (including `WIFI_KEY` and `SMTP_PWD` in cleartext) and POST changes. **[V]**
- **No JSON, no SSL/TLS.** Plain HTTP only; the unit "does not support SSL Web communication." **[V]**
- **Two distinct XML root elements:** `<nutcstatus>` for `status.xml`; `<nutcallstatus>` for `all.xml` and `config.xml`. Clients navigate by root name, so these must be exact. **[V]**
- **All temperatures are integers in tenths of a degree** (e.g. `3343` = 334.3°). Open probes report the literal string `OPEN`. **[V]**
- **Minimal error reporting.** Success is HTTP `200 OK`; there is no structured error body and no per-field validation feedback. Out-of-range or misspelled keys are silently ignored/clamped by the device — range enforcement is done client-side by libraries. **[V/I]**
- **Fragile under fast/concurrent polling.** Community integrations recommend not polling faster than every few seconds (some as slow as ~5 min) and report malformed/`–` responses when the server is hammered; effectively single-connection-at-a-time. **[V]**

---

## 2. HTTP Endpoints

| Path | Method | Content-Type (response / request) | Root element | Purpose |
|---|---|---|---|---|
| `/status.xml` | GET | `text/xml` | `<nutcstatus>` | Fast, minimal live status: temps, statuses, output %, timer, a few control values. Recommended polling target — serves much faster than the HTML page. **[V]** |
| `/all.xml` | GET | `text/xml` | `<nutcallstatus>` | Live status **plus** per-probe names and setpoints. **[V]** |
| `/config.xml` | GET | `text/xml` | `<nutcallstatus>` | Superset of `all.xml` **plus** `SYSTEM` / `CONTROL` / `WIFI` / `SMTP` config blocks (and `FWVER`, `WIFI.MAC`). **[V]** |
| `/` (root) | GET | `text/html` | — (HTML) | Main "Control Status" HTML UI page. **[V]** |
| `/` (root) | POST | request: `application/x-www-form-urlencoded` | — | **The update mechanism.** URL-encoded `key=value&…` body writes settings. Returns `200`. **[V]** |
| `/index.htm`, `/control.htm`, `/system.htm`, `/config.htm`, `/wifi.htm` (legacy page URLs) | GET / POST | `text/html` / form-encoded | — (HTML) | Linked HTML config pages. Some clients POST page-grouped params to these instead of `/`. **[V]** |
| `/status.xml` | POST (tolerant) | form-encoded | — | Some clients POST here with a throwaway `IGNOREDTAG` param as a cache-buster to force a fresh read. Device tolerates it. **[V]** |

### 2.1 POST routing rules our virtual device should implement

- **Accept form-encoded POST at `/`** and at the legacy `*.htm` page URLs; apply any recognized keys, **ignore unknown keys gracefully**, then return `200`. **[V]**
- **All settable variables can be written in a single POST to `/`** regardless of which HTML page "owns" them (the reverse-engineering finding). **[V]**
- **Tolerate POST to `/status.xml`** with an `IGNOREDTAG` cache-buster. **[V]**
- Partial POSTs are fine — send only the keys you want to change. **[V]**

### 2.2 Reboot and factory reset

- **Reboot:** a "Reboot Device" button at the bottom of each HTML config page. Mechanically this is another `POST /`; the exact reboot key name is **not published in any source** — treat the reboot POST body as **[I]**. Reboot is recommended after WiFi/port changes. **[V]** (button exists) / **[I]** (exact key).
- **Factory reset (EEPROM reset):** **hardware-only** — hold all 4 arrow keys ~5 s. There is **no HTTP factory-reset endpoint**. **[V]**

### 2.3 HTTP server quirks

- Response `Content-Type` for the XML feeds is `text/xml`. **[V]** The real device may send a bare `text/xml` with no charset. **[I]**
- POST request headers used by the reference client: `Content-type: application/x-www-form-urlencoded`, `Accept: text/plain`. **[V]**
- Prefers `Connection: close` (HTTP/1.0-style, no reliable keep-alive); no chunked transfer encoding (small responses framed with `Content-Length` or connection close). **[I]**
- Very few sockets — effectively single-connection-at-a-time; can return truncated/`–` responses under aggressive/concurrent polling. **[V]** (fragility) / **[I]** (exact socket cap).
- `Server:` header string not captured in any source; likely terse or absent. **[I]**
- Browsers auto-prepend `http://www.` — enter the bare IP. Client-side gotcha, not a server header. **[V]**

---

## 3. Temperature & Value Encoding

The device embeds these rules verbatim as XML comments in every feed (reproduced in this project's templates): **[V]**

```
<!--all temperatures are displayed in tenths F, regardless of setting of unit-->
<!--all temperatures sent by browser to unit should be in F.  you can send-->
<!--tenths F with a decimal place, ex: 123.5-->
```

### 3.1 Read side (XML output)

| Rule | Detail | Conf. |
|---|---|---|
| Unit on the wire | **Integer tenths of °F**, always — even when `DEG_UNITS=0` (Celsius). `3343` → 334.3 °F. Divide by 10 to display. | **[V]** |
| Celsius mode | The LCD/UI shows °C, but XML values remain tenths-of-°F ("regardless of setting of unit"). Consumers convert F→C themselves. There is no °C XML variant. | **[V]** statement / **[I]** no °C variant |
| Setpoints & bands in XML | `COOK_SET`, `FOOD*_SET`, `PROPBAND`, `ALARMDEV`, `COOKHOLD` also read back in **tenths °F** (`4000`=400.0, `500`=50.0, `2000`=200.0). | **[V]** |
| Open probe sentinel | An unplugged / open-circuit probe's `*_TEMP` element carries the literal string **`OPEN`** (not a number), and its `*_STATUS` = `4` (ERROR). Emit the string, not `0`. | **[V]** |
| Decode robustness | Parse temp as `float(value)/10.0` inside a try/except; on `ValueError` keep the raw string — this is how the `OPEN` sentinel survives numeric parsing. | **[V]** |

### 3.2 Write side (POST input) — the dual-representation gotcha

| Rule | Detail | Conf. |
|---|---|---|
| Browser → device | Send temperatures **in whole °F** (the HTML forms show Prop Band `30`, Alarm Dev `50`, Cook Hold `200`). You **may** also send tenths with a decimal point, e.g. `123.5`. | **[V]** |
| Dual representation | The same logical value has **two representations**: whole-°F (or decimal) on *input*, tenths-°F on *readback*. E.g. you POST `PROPBAND=30`, it reads back `<COOK_PROPBAND>500</COOK_PROPBAND>` if 50, or `300` if 30 — see the caveat below. **This is the single most error-prone part of the API.** | **[V]** read / **[V]** write-whole-°F |
| Community note | Write behavior is "inconsistent with the temp values so some tweaking may be needed." | **[V]** |
| Practical client range guard | Open-source clients clamp writable temps to **32–475 °F** (stored 320–4750 as tenths). This is a client guard, not a device-published limit. | **[V]** |

> **Encoding-consistency caveat [I].** The documented factory `PROPBAND` default is **25 °F**, which as tenths is `250`. This project's current seed values (`propband=500`, `alarmdev=500`, `cookhold=2000`) mix conventions — `500` tenths = 50.0 °F, `2000` tenths = 200.0 °F. Our virtual device should pick one internal convention (tenths-°F everywhere, matching the wire) and convert on POST input. Document whichever convention the code uses.

### 3.3 Timer format

- `TIMER_CURR` (read) and settable `COOK_TIMER` / `_COOK_TIMER` (write) are strings `HH:MM:SS`, validated by clients with `^(\d{2}):(\d{2}):(\d{2})$`. **[V]**
- In POST bodies the colons are URL-encoded as `%3A`. **[V]**
- Both key spellings should be accepted on write; `_COOK_TIMER` is the URL-encoded variant, and clients set **both** for the change to stick. **[V]**

---

## 4. `status.xml` Schema

**Root element:** `<nutcstatus>` (flat, no nested containers). This is the fast, volatile-only feed the web UI AJAX-polls ~1/sec. **[V]**

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `OUTPUT_PERCENT` | Fan/blower output duty. **Read-only** — computed by the controller, never settable. `*` on the LCD indicates energized. | int 0–100 | `100` |
| `TIMER_CURR` | Countdown timer remaining. **Read-only.** | `HH:MM:SS` | `00:00:00` |
| `COOK_TEMP` | Pit temperature. | tenths °F, or `OPEN` | `3343` |
| `FOOD1_TEMP` | Food probe 1 temperature. | tenths °F, or `OPEN` | `823` |
| `FOOD2_TEMP` | Food probe 2 temperature. | tenths °F, or `OPEN` | `OPEN` |
| `FOOD3_TEMP` | Food probe 3 temperature. | tenths °F, or `OPEN` | `OPEN` |
| `COOK_STATUS` | Pit status code. | int (see §8.1) | `0` |
| `FOOD1_STATUS` | Food 1 status code. | int (see §8.1) | `0` |
| `FOOD2_STATUS` | Food 2 status code. | int (see §8.1) | `4` |
| `FOOD3_STATUS` | Food 3 status code. | int (see §8.1) | `4` |
| `TIMER_STATUS` | Timer status code. | int (see §8.1) | `0` |
| `DEG_UNITS` | Display unit. | `0`=°C, `1`=°F | `1` |
| `COOK_CYCTIME` | Fan cycle time (PWM period). | int seconds (4–10) | `6` |
| `COOK_PROPBAND` | Proportional band. | tenths °F (`500`=50.0) | `500` |
| `COOK_RAMP` | Ramp source. | `0`=OFF,`1`=FOOD1,`2`=FOOD2,`3`=FOOD3 | `0` |
| `FAN_SHORTED` | Fan short-circuit detected. **Read-only.** (Seen in some clients as `FAN_SHORT`.) | bool int `0`/`1` | `0` |

> `FAN_SHORTED` is exposed by some clients (e.g. Home Assistant "Fan short" binary sensor, ioBroker). Include it for fidelity. **[V]** (field exists) / **[I]** (exact spelling `FAN_SHORTED` vs `FAN_SHORT`).

### Example `status.xml`

```xml
<!--all temperatures are displayed in tenths F, regardless of setting of unit-->
<!--all temperatures sent by browser to unit should be in F.  you can send-->
<!--tenths F with a decimal place, ex: 123.5-->
<nutcstatus>
  <OUTPUT_PERCENT>100</OUTPUT_PERCENT>
  <TIMER_CURR>00:00:00</TIMER_CURR>
  <COOK_TEMP>3343</COOK_TEMP>
  <FOOD1_TEMP>823</FOOD1_TEMP>
  <FOOD2_TEMP>OPEN</FOOD2_TEMP>
  <FOOD3_TEMP>OPEN</FOOD3_TEMP>
  <COOK_STATUS>0</COOK_STATUS>
  <FOOD1_STATUS>0</FOOD1_STATUS>
  <FOOD2_STATUS>4</FOOD2_STATUS>
  <FOOD3_STATUS>4</FOOD3_STATUS>
  <TIMER_STATUS>0</TIMER_STATUS>
  <DEG_UNITS>1</DEG_UNITS>
  <COOK_CYCTIME>6</COOK_CYCTIME>
  <COOK_PROPBAND>500</COOK_PROPBAND>
  <COOK_RAMP>0</COOK_RAMP>
</nutcstatus>
```

---

## 5. `all.xml` Schema

**Root element:** `<nutcallstatus>`. Adds `<COOK>` and `<FOOD1/2/3>` container nodes (name + setpoint + temp + status) while keeping the flat status/control fields as siblings. **[V]**

### Container nodes

| Container | Child elements | Notes |
|---|---|---|
| `<COOK>` | `COOK_NAME`, `COOK_TEMP`, `COOK_SET`, `COOK_STATUS` | Pit probe. |
| `<FOOD1>` | `FOOD1_NAME`, `FOOD1_TEMP`, `FOOD1_SET`, `FOOD1_STATUS` | Food probe 1. |
| `<FOOD2>` | `FOOD2_NAME`, `FOOD2_TEMP`, `FOOD2_SET`, `FOOD2_STATUS` | Food probe 2. |
| `<FOOD3>` | `FOOD3_NAME`, `FOOD3_TEMP`, `FOOD3_SET`, `FOOD3_STATUS` | Food probe 3. |

### Element reference

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `*_NAME` | Probe label. | string, ≤16 chars | `Big Green Egg` |
| `*_TEMP` | Current temperature. | tenths °F, or `OPEN` | `3343` |
| `*_SET` | Target setpoint. | tenths °F | `4000` (=400.0 °F) |
| `*_STATUS` | Status code. | int (see §8.1) | `0` |
| `OUTPUT_PERCENT` | Fan output. Read-only. | int 0–100 | `100` |
| `TIMER_CURR` | Timer remaining. Read-only. | `HH:MM:SS` | `00:00:00` |
| `TIMER_STATUS` | Timer status code. | int | `0` |
| `DEG_UNITS` | Display unit. | `0`/`1` | `1` |
| `COOK_CYCTIME` | Fan cycle time. | int s | `6` |
| `COOK_PROPBAND` | Proportional band. | tenths °F | `500` |
| `COOK_RAMP` | Ramp source. | `0`–`3` | `0` |

### Example `all.xml`

```xml
<nutcallstatus>
  <COOK>
    <COOK_NAME>Big Green Egg</COOK_NAME>
    <COOK_TEMP>3343</COOK_TEMP>
    <COOK_SET>4000</COOK_SET>
    <COOK_STATUS>0</COOK_STATUS>
  </COOK>
  <FOOD1>
    <FOOD1_NAME>Chicken Quarters</FOOD1_NAME>
    <FOOD1_TEMP>1220</FOOD1_TEMP>
    <FOOD1_SET>1550</FOOD1_SET>
    <FOOD1_STATUS>0</FOOD1_STATUS>
  </FOOD1>
  <FOOD2>
    <FOOD2_NAME>Beef Brisket</FOOD2_NAME>
    <FOOD2_TEMP>OPEN</FOOD2_TEMP>
    <FOOD2_SET>1800</FOOD2_SET>
    <FOOD2_STATUS>4</FOOD2_STATUS>
  </FOOD2>
  <FOOD3>
    <FOOD3_NAME>Pork Chop</FOOD3_NAME>
    <FOOD3_TEMP>OPEN</FOOD3_TEMP>
    <FOOD3_SET>1600</FOOD3_SET>
    <FOOD3_STATUS>4</FOOD3_STATUS>
  </FOOD3>
  <OUTPUT_PERCENT>100</OUTPUT_PERCENT>
  <TIMER_CURR>00:00:00</TIMER_CURR>
  <TIMER_STATUS>0</TIMER_STATUS>
  <DEG_UNITS>1</DEG_UNITS>
  <COOK_CYCTIME>6</COOK_CYCTIME>
  <COOK_PROPBAND>500</COOK_PROPBAND>
  <COOK_RAMP>0</COOK_RAMP>
</nutcallstatus>
```

---

## 6. `config.xml` Schema

**Root element:** `<nutcallstatus>` (superset of `all.xml`). Contains the same `COOK`/`FOOD1`/`FOOD2`/`FOOD3` containers and status/control siblings, **plus** four config blocks and firmware version. **[V]**

### 6.1 `<SYSTEM>` block

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `MENU_SCROLLING` | Main-screen auto-scroll. | `0`=OFF, `1`=ON | `1` |
| `LCD_BACKLIGHT` | Display brightness. | int % (0–100) | `47` |
| `LCD_CONTRAST` | Display contrast. | int % (0–100) | `10` |
| `DEG_UNITS` | Display unit. | `0`=°C, `1`=°F | `1` |
| `ALARM_BEEPS` | Beeps per alarm. | int 0–5 (`0`=OFF) | `3` |
| `KEY_BEEPS` | Keypress chirp. | `0`=OFF, `1`=ON | `1` |

### 6.2 `<CONTROL>` block

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `TIMEOUT_ACTION` | Action when timer hits `00:00:00`. | enum `0`–`3` (see §8.4) | `0` |
| `COOKHOLD` | Pit setpoint applied on timer expiry when action=HOLD. | tenths °F | `2000` (=200.0 °F) |
| `ALARMDEV` | Pit deviation alarm band (± from setpoint). | tenths °F in XML; **whole °F on POST** | `500` (=50 °F) |
| `COOK_RAMP` | Ramp/cook-and-hold source. | `0`=OFF,`1`=FOOD1,`2`=FOOD2,`3`=FOOD3 | `0` |
| `OPENDETECT` | Open-lid detection. | `0`=OFF, `1`=ON | `1` |
| `CYCTIME` | Fan cycle time (PWM period). | int seconds (4–10) | `6` |
| `PROPBAND` | Proportional band. | tenths °F in XML; **whole °F on POST** | `500` (=50 °F) |

### 6.3 `<WIFI>` block

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `IP` | Device IP address. | dotted-quad string | `10.0.1.30` |
| `NM` | Netmask. | string | `255.255.255.0` |
| `GW` | Gateway. | string | `10.0.1.1` |
| `DNS` | DNS server. | string | `10.0.1.1` |
| `WIFIMODE` | Radio mode. | enum (see §8.5) | `0` |
| `DHCP` | DHCP on/off. | `0`=static, `1`=DHCP | `0` |
| `SSID` | Network name. | string | `my CYBERQ Wifi` |
| `WIFI_ENC` | Encryption type. | enum (see §8.5) | `6` |
| `WIFI_KEY` | Network key/password. | string (cleartext) | `1234abcdef` |
| `HTTP_PORT` | Web server TCP port. | int | `80` |
| `MAC` | Device MAC address. **Read-only.** | string | `00:04:A3:xx:xx:xx` |

### 6.4 `<SMTP>` block

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `SMTP_HOST` | Mail server host. | string | `mail.cyberqmail.com` |
| `SMTP_PORT` | Mail server TCP port. | int (`0`=disabled/unset) | `587` |
| `SMTP_USER` | Auth username. | string | `user@cyberqmail.com` |
| `SMTP_PWD` | Auth password. | string (cleartext) | `1234abcdef` |
| `SMTP_TO` | Recipient address. | string | `dest@example.com` |
| `SMTP_FROM` | From address. | string | `user@cyberqmail.com` |
| `SMTP_SUBJ` | Subject line. | string | `CyberQ Status Report` |
| `SMTP_ALERT` | Alert enable / interval. | `0`=OFF; else minutes interval | `0` |

### 6.5 `<FWVER>`

| Element | Meaning | Type / Encoding | Example |
|---|---|---|---|
| `FWVER` | Firmware version string. **Read-only.** Clients may branch on this (WiFi vs Cloud). | string | `2.3` |

### Example `config.xml` (abridged)

```xml
<nutcallstatus>
  <COOK> <COOK_NAME>Big Green Egg</COOK_NAME> <COOK_TEMP>3343</COOK_TEMP> <COOK_SET>4000</COOK_SET> <COOK_STATUS>0</COOK_STATUS> </COOK>
  <FOOD1> <FOOD1_NAME>Chicken Quarters</FOOD1_NAME> <FOOD1_TEMP>1220</FOOD1_TEMP> <FOOD1_SET>1550</FOOD1_SET> <FOOD1_STATUS>0</FOOD1_STATUS> </FOOD1>
  <FOOD2> <FOOD2_NAME>Beef Brisket</FOOD2_NAME> <FOOD2_TEMP>OPEN</FOOD2_TEMP> <FOOD2_SET>1800</FOOD2_SET> <FOOD2_STATUS>4</FOOD2_STATUS> </FOOD2>
  <FOOD3> <FOOD3_NAME>Pork Chop</FOOD3_NAME> <FOOD3_TEMP>OPEN</FOOD3_TEMP> <FOOD3_SET>1600</FOOD3_SET> <FOOD3_STATUS>4</FOOD3_STATUS> </FOOD3>
  <OUTPUT_PERCENT>100</OUTPUT_PERCENT>
  <TIMER_CURR>00:00:00</TIMER_CURR>
  <TIMER_STATUS>0</TIMER_STATUS>
  <SYSTEM>
    <MENU_SCROLLING>1</MENU_SCROLLING>
    <LCD_BACKLIGHT>47</LCD_BACKLIGHT>
    <LCD_CONTRAST>10</LCD_CONTRAST>
    <DEG_UNITS>1</DEG_UNITS>
    <ALARM_BEEPS>0</ALARM_BEEPS>
    <KEY_BEEPS>0</KEY_BEEPS>
  </SYSTEM>
  <CONTROL>
    <TIMEOUT_ACTION>0</TIMEOUT_ACTION>
    <COOKHOLD>2000</COOKHOLD>
    <ALARMDEV>500</ALARMDEV>
    <COOK_RAMP>0</COOK_RAMP>
    <OPENDETECT>1</OPENDETECT>
    <CYCTIME>6</CYCTIME>
    <PROPBAND>500</PROPBAND>
  </CONTROL>
  <WIFI>
    <IP>10.0.1.30</IP>
    <NM>255.255.255.0</NM>
    <GW>10.0.1.1</GW>
    <DNS>10.0.1.1</DNS>
    <WIFIMODE>0</WIFIMODE>
    <DHCP>0</DHCP>
    <SSID>my CYBERQ Wifi</SSID>
    <WIFI_ENC>6</WIFI_ENC>
    <WIFI_KEY>1234abcdef</WIFI_KEY>
    <HTTP_PORT>80</HTTP_PORT>
    <MAC>00:04:A3:00:00:00</MAC>
  </WIFI>
  <SMTP>
    <SMTP_HOST>mail.cyberqmail.com</SMTP_HOST>
    <SMTP_PORT>587</SMTP_PORT>
    <SMTP_USER>user@cyberqmail.com</SMTP_USER>
    <SMTP_PWD>1234abcdef</SMTP_PWD>
    <SMTP_TO>dest@example.com</SMTP_TO>
    <SMTP_FROM>user@cyberqmail.com</SMTP_FROM>
    <SMTP_SUBJ>CyberQ Status Report</SMTP_SUBJ>
    <SMTP_ALERT>0</SMTP_ALERT>
  </SMTP>
  <FWVER>2.3</FWVER>
</nutcallstatus>
```

---

## 7. POST Update Parameter Catalog

**Request:** `POST /` (or a legacy `*.htm`), body `application/x-www-form-urlencoded`: `KEY=value&KEY2=value2&…`. Values URL-encoded (spaces → `+`/`%20`, timer colons → `%3A`). Partial POSTs are accepted. **[V]**

### 7.1 The canonical 23-key writable allow-list

These are the keys the firmware accepts, per the reference client's validated allow-list. Temperature inputs are **whole °F** (decimal-tenths allowed). **[V]**

| Key | Meaning | Type | Valid range (input) | Factory default | Conf. |
|---|---|---|---|---|---|
| `COOK_NAME` | Pit/cook label | string | ≤16 chars | `Cook` (blank) | **[V]** ≤16 / **[I]** default |
| `COOK_SET` | Pit target temp | number °F | 32–475 °F (0–246 °C) | **275 °F** | **[V]** |
| `FOOD1_NAME` | Food 1 label | string | ≤16 chars | `Food1` | **[V]**/**[I]** |
| `FOOD1_SET` | Food 1 target | number °F | 32–475 °F | **180 °F** | **[V]** |
| `FOOD2_NAME` | Food 2 label | string | ≤16 chars | `Food2` | **[V]**/**[I]** |
| `FOOD2_SET` | Food 2 target | number °F | 32–475 °F | 180 °F | **[V]** |
| `FOOD3_NAME` | Food 3 label | string | ≤16 chars | `Food3` | **[V]**/**[I]** |
| `FOOD3_SET` | Food 3 target | number °F | 32–475 °F | 180 °F | **[V]** |
| `COOK_TIMER` | Countdown timer | `HH:MM:SS` (`%3A`) | up to `99:59:59` | `00:00:00` | **[V]** |
| `_COOK_TIMER` | Countdown timer (URL-encoded variant; set with `COOK_TIMER`) | `HH:MM:SS` | up to `99:59:59` | `00:00:00` | **[V]** |
| `COOKHOLD` | Pit setpoint after timer expiry (when action=HOLD) | number °F | 32–475 °F | **200 °F** | **[V]** |
| `TIMEOUT_ACTION` | Timer-expiry action | enum int | 0–3 (see §8.4) | **0 (No Action)** | **[V]** |
| `ALARMDEV` | Pit alarm deviation (± from setpoint) | number °F | **10–100 °F** | **50 °F** | **[V]** |
| `COOK_RAMP` | Ramp/cook-and-hold source | enum int | 0–3 | **0 (Off)** | **[V]** |
| `OPENDETECT` | Open-lid detect | bool int | 0/1 | **1 (On)** | **[V]** |
| `CYCTIME` | Fan cycle time | int seconds | **4–10 s** | **6 s** | **[V]** |
| `PROPBAND` | Proportional band | number °F | **5–100 °F** | **25 °F** (docs; "30 works well") | **[V]** |
| `MENU_SCROLLING` | Main-screen auto-scroll | bool int | 0/1 | **0 (Off)** | **[V]** |
| `LCD_BACKLIGHT` | Display backlight | int % | 0–100 | **50 %** | **[V]** |
| `LCD_CONTRAST` | Display contrast | int % | 0–100 | **10 %** | **[V]** |
| `DEG_UNITS` | Units | enum int | 0=°C, 1=°F | **1 (°F)** | **[V]** |
| `ALARM_BEEPS` | Beeps per alarm | int | 0–5 (0=Off) | **3** | **[V]** |
| `KEY_BEEPS` | Keypress chirp | bool int | 0/1 | **1 (On)** | **[V]** |

> **Range-conflict note [I]:** one client guards `CYCTIME` at the wider `1–30 s`; the BBQ Guru docs and the reference client say **4–10 s**. Our virtual device should prefer **4–10 s** to mimic real firmware.

### 7.2 WIFI / SMTP writable keys

The HTML "WIFI Setup" and "Email Alerts" pages submit via the same POST-to-root form, so the `config.xml` element names are also writable. These are **not** in the reference client's validated allow-list (that library deliberately omits them), so the exact POST key spellings are inferred to equal the `config.xml` element names. **[I]** (high confidence for settability; lower for exact wire spelling).

- **WIFI:** `IP, NM, GW, DNS, WIFIMODE, DHCP, SSID, WIFI_ENC, WIFI_KEY, HTTP_PORT`. WiFi changes require a **power cycle** to take effect. **[V]**
- **SMTP:** `SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PWD, SMTP_TO, SMTP_FROM, SMTP_SUBJ, SMTP_ALERT`.

### 7.3 Read-only keys (never settable)

`OUTPUT_PERCENT`, `TIMER_CURR`, all `*_TEMP`, all `*_STATUS`, `FAN_SHORTED`, `FWVER`, `MAC`. Our virtual device must reject/ignore attempts to write these. **[V]**

### 7.4 Error / validation behavior on write

- Success = HTTP `200 OK`. Any non-200 is treated as failure by clients. **[V]**
- **No structured error XML/JSON**, no per-field feedback. Out-of-range or misspelled keys are **silently ignored/clamped**, not rejected with a message. **[V/I]**
- Range enforcement is done **client-side** by the libraries, not by the device. Malformed state surfaces only as `OPEN` temps, `4/ERROR` statuses, or truncated `–` responses under overload. **[V]**

---

## 8. Enumerations & Status Codes

### 8.1 Status codes — `COOK_STATUS`, `FOOD1_STATUS`, `FOOD2_STATUS`, `FOOD3_STATUS`, `TIMER_STATUS`

Two independent reverse-engineered integrations agree on this 8-value table (index = XML integer). **[V]**

| Int | Meaning | Notes |
|---|---|---|
| 0 | OK | Normal. |
| 1 | HIGH | Pit above setpoint by ≥ `ALARMDEV`. |
| 2 | LOW | Pit below setpoint by ≥ `ALARMDEV`. |
| 3 | DONE | Food probe reached its setpoint. |
| 4 | ERROR | Probe open/unplugged/damaged → LCD shows `OPEN`, `*_TEMP` = `OPEN`. |
| 5 | HOLD | Timer HOLD timeout retargeted the pit to `COOKHOLD`. |
| 6 | ALARM | Timer ALARM timeout. |
| 7 | SHUTDOWN | Timer SHUTDOWN timeout. |

### 8.2 `DEG_UNITS` **[V]**

| Int | Meaning |
|---|---|
| 0 | Celsius |
| 1 | Fahrenheit |

### 8.3 `COOK_RAMP` **[V]**

| Int | Meaning |
|---|---|
| 0 | Off / None |
| 1 | Food 1 |
| 2 | Food 2 |
| 3 | Food 3 |

### 8.4 `TIMEOUT_ACTION` **[V]**

| Int | Meaning | LCD label |
|---|---|---|
| 0 | No Action | `NO ACTN` (default) |
| 1 | Hold | `HOLD` |
| 2 | Alarm | `ALARM` |
| 3 | Shutdown | `SHDN` |

### 8.5 Boolean / count enums

| Field | Values | Conf. |
|---|---|---|
| `OPENDETECT` | 0=Off, 1=On | **[V]** |
| `MENU_SCROLLING` | 0=Off, 1=On | **[V]** |
| `KEY_BEEPS` | 0=Off, 1=On | **[V]** |
| `ALARM_BEEPS` | 0–5 (0=Off, then 1–5 beeps) | **[V]** |
| `FAN_SHORTED` | 0=OK, 1=short detected | **[V]** field / **[I]** semantics |
| `SMTP_ALERT` | 0=Off; else minutes interval | **[V]** field / **[I]** exact 0/1 vs interval |

### 8.6 WiFi enums (integer maps INFERRED — need a real-device dump to confirm)

The `<WIFI>` fields exist **[V]**, but no code integration models the WiFi enums with a lookup table, so the integer→label maps are **[I]**.

**`WIFIMODE`** **[I]** (project default `0`):

| Int | Meaning |
|---|---|
| 0 | Infrastructure (join a router) |
| 1 | Ad-hoc / Hot-spot (device is its own AP) |

**`DHCP`** **[I]** (project default `0`):

| Int | Meaning |
|---|---|
| 0 | Off (static IP — hot-spot mode) |
| 1 | On (obtain IP from router — infrastructure mode) |

**`WIFI_ENC`** **[I]** (project default `6`; only the *set* of supported types — None, WEP40/WEP, WPA, WPA2 — is verified):

| Int | Meaning (INFERRED) |
|---|---|
| 0 | None / Open |
| 1 | WEP-64 (WEP40) |
| 2 | WEP-128 |
| 3 | WPA-PSK (TKIP) |
| 4 | WPA-PSK (AES) |
| 5 | WPA2-PSK (TKIP) |
| 6 | WPA2-PSK (AES) ← matches project default |

> To pin down the exact WiFi/SMTP integer maps, dump `config.xml` from a physical unit while toggling each menu option.

---

## 9. Control & Regulation Behavior

The CyberQ is a **proportional (P-band) blower controller with time-proportioned (slow-PWM) fan pulsing** — not a full PID (though firmware ≥ v2.0 advertises an undocumented "adaptive" algorithm layered on top). **[V]**

### 9.1 Proportional band + cycle time → `OUTPUT_PERCENT`

- **`PROPBAND`** — "the range of temperatures over which the fan will pulse." Default **25 °F** (docs also say "30 degrees generally works well"); adjustable **5–100 °F**. Smaller band → reaches setpoint faster but more startup overshoot. **[V]**
- **`CYCTIME`** — "the number of seconds between fan pulses"; the PWM period. Default **6 s**, adjustable **4–10 s**. **[V]**

**The proportional law (key formula).** BBQ Guru documents the band as a straight line from pit error to duty. Worked example (setpoint 225 °F, PROPBAND 25 °F): *below 200 → full on; above 225 → full off; at 212.5 → 50 %.* The band sits **entirely below** the setpoint: **[V]** (endpoints + midpoint) / **[I]** (linear interpolation between them).

```
error          = COOK_SET - COOK_TEMP          # positive when pit is too cold
OUTPUT_PERCENT = clamp( 100 * error / PROPBAND , 0 , 100 )
```

Check (PROPBAND=25): error ≥ 25 → 100 %; error ≤ 0 (at/above setpoint) → 0 %; error = 12.5 → 50 %.

- **`OUTPUT_PERCENT` is read-only** — "not changeable by the user… simply a display of the output percentage of the control." Range 0–100; `*` on LCD when energized. **[V]**
- **Time-proportioning** — the fan is on/off, so `OUTPUT_PERCENT` is realized as a duty cycle over each `CYCTIME` window: **[I]**

```
on_time_this_cycle  = CYCTIME * OUTPUT_PERCENT/100
off_time_this_cycle = CYCTIME - on_time_this_cycle
```

- **No documented minimum floor**; output can sit at 0 %. Max 100 %. The **damper** is a mechanical airflow limiter — not in the API; ignore it or fold it into thermal gain. **[V]** (damper is manual) / **[I]** (no floor).
- **Adaptive control [I]:** firmware ≥ v2.0 adds undocumented integral/lead terms so real units converge with less steady-state droop than pure-P (pure-P settles slightly *below* setpoint because output→0 exactly at setpoint). Optionally add a small integral term to remove the droop; label it a modeling choice.

### 9.2 `COOKHOLD` (cook-and-hold)

The pit setpoint that `COOK_SET` is **reset to** when the timer expires, if `TIMEOUT_ACTION` = HOLD. Default **200 °F**. **[V]** (See §11.)

### 9.3 `COOK_RAMP` (ramp / cook-and-hold ramp-down)

Selects a food probe to drive a gradual pit-temperature reduction. **[V]** behavior / **[I]** exact curve.

- **Behavior [V]:** "gradually lowers the pit temperature to the food set point when the food is within approximately **30°** of being done," then "holds the pit temperature slightly above your food set point as long as there is fuel." Default OFF.
- **Simulatable curve [I]:** compute an `effective_cook_set` on the fly (the device does **not** overwrite stored `COOK_SET`):

```
if COOK_RAMP != OFF and probe[COOK_RAMP].connected:
    food = probe[COOK_RAMP]
    gap  = food.SET - food.TEMP
    RAMP_WINDOW = 30                       # deg, VERIFIED
    if gap <= 0:
        effective_cook_set = food.SET + HOLD_MARGIN     # "slightly above", ~5-10F [I]
    elif gap < RAMP_WINDOW:
        frac = gap / RAMP_WINDOW           # 1.0 at 30 out, 0.0 at done
        effective_cook_set = (food.SET + HOLD_MARGIN) + frac * (COOK_SET - (food.SET + HOLD_MARGIN))
    else:
        effective_cook_set = COOK_SET
```

### 9.4 `OPENDETECT` (open-lid detection)

Default **ON**. **[V]** behavior / **[I]** exact trigger threshold.

- **Behavior [V]:** detects a lid-open and **minimizes blower running** during it so the pit recovers without overshoot. Also active at startup: limits the rate of temperature rise to prevent over-firing (a 250 °F startup can take ~20–30 min).
- **Trigger heuristic [I]:** infer lid-open from a sudden pit-temperature drop rate (fast negative dT/dt below setpoint). While "open," force `OUTPUT_PERCENT = 0` and suppress the LOW deviation alarm; exit when temperature stabilizes/recovers.

### 9.5 `ALARMDEV` (deviation alarm)

Pit deviation band, ± from the pit setpoint. Settable **10–100 °F**, default **50 °F**. **[V]**

- **Above** setpoint by ≥ `ALARMDEV` → alarm + "COOK TEMP HIGH" → `COOK_STATUS = 1 (HIGH)`. **[V]**
- **Below** setpoint by ≥ `ALARMDEV` → alarm + "COOK TEMP LOW" → `COOK_STATUS = 2 (LOW)`. **[V]**
- **Critical gating rule [V]:** the deviation alarm is **suppressed during warm-up** — it only arms *after* the pit has first reached (near) the setpoint. This prevents a cold pit rising to setpoint from constantly alarming.
- Food probes have **no** HIGH/LOW deviation — only DONE (see §9.6). **[I]** (deviation is documented solely against the pit).

### 9.6 `*_STATUS` transition rules

**COOK_STATUS [V] rules / [I] code mapping:**
- `4 (ERROR)` if pit probe open.
- `1 (HIGH)` if armed and `COOK_TEMP - COOK_SET ≥ ALARMDEV`.
- `2 (LOW)` if armed and `COOK_SET - COOK_TEMP ≥ ALARMDEV` (suppress while open-lid).
- `5 (HOLD)` when a HOLD timeout has retargeted the pit to `COOKHOLD`.
- `0 (OK)` otherwise (including the entire warm-up phase).

**FOODn_STATUS [V] rules:**
- `4 (ERROR)` if that probe is open (`*_TEMP` = `OPEN`).
- `3 (DONE)` when `FOOD_TEMP ≥ FOOD_SET` — "FOOD DONE" blinks and the beeper sounds. Setting the setpoint *below* the current temp fires DONE immediately.
- `0 (OK)` while below setpoint.

**TIMER_STATUS** — see §11.

**OUTPUT_PERCENT** — not a status enum; a 0–100 int recomputed every control tick (§9.1).

---

## 10. Pseudocode Control Loop

All temperatures internally in tenths per the wire convention; shown here in whole degrees for clarity. Constants tagged `[V]`/`[I]` are verified/inferred respectively.

```text
CONSTANTS
  RAMP_WINDOW    = 30     # deg,  [V]
  HOLD_MARGIN    = 5      # deg above food set while ramp-holding, [I]
  OPEN_DROP_RATE = 8      # deg/sample drop that trips open-lid, [I]
  # PROPBAND, CYCTIME, ALARMDEV, COOKHOLD, TIMEOUT_ACTION, COOK_RAMP,
  # OPENDETECT come from the CONTROL config.

STATE
  cook_armed  = False    # deviation alarm arms only after first reaching setpoint [V gating]
  open_lid    = False
  timer_running = (TIMER_CURR > 0)
  timer_expired = False
  timeout_hold_active = False
  timeout_shutdown_active = False
  phase = 0.0            # PWM phase clock 0..CYCTIME

# ---- runs every simulation tick (dt seconds) ----
def control_tick(dt):
    read COOK_TEMP, FOOD1..3_TEMP from thermal model

    # 1. cook timer
    if timer_running:
        TIMER_CURR -= dt
        if TIMER_CURR <= 0:
            TIMER_CURR = 0; timer_running = False; timer_expired = True
            apply_timeout_action()

    # 2. effective pit setpoint (ramp overrides COOK_SET, computed on the fly)
    target = COOK_SET
    if COOK_RAMP != OFF and probe[COOK_RAMP].connected:
        food = probe[COOK_RAMP]
        gap = food.SET - food.TEMP
        if   gap <= 0:          target = food.SET + HOLD_MARGIN
        elif gap < RAMP_WINDOW: f = gap/RAMP_WINDOW
                                target = (food.SET+HOLD_MARGIN) + f*(COOK_SET-(food.SET+HOLD_MARGIN))
        else:                   target = COOK_SET

    # 3. open-lid detect
    if OPENDETECT and (dTemp/dt <= -OPEN_DROP_RATE) and COOK_TEMP < target:
        open_lid = True
    if open_lid and (pit stable/recovering for a few ticks):
        open_lid = False

    # 4. proportional output  ([V] law: 100*error/PROPBAND clamped 0..100)
    error = target - COOK_TEMP                         # positive = too cold
    OUTPUT_PERCENT = clamp(round(100.0*error/PROPBAND), 0, 100)
    if timeout_shutdown_active: OUTPUT_PERCENT = 0     # v2.3 SHDN forces fan off
    if open_lid:                OUTPUT_PERCENT = 0     # blower paused during lid-open

    # 5. time-proportion the blower over CYCTIME (slow-PWM)
    phase = (phase + dt) % CYCTIME
    blower_on = (phase < CYCTIME * OUTPUT_PERCENT/100.0)
    # feed blower_on into the thermal model (fan on -> heat added)

    # 6. cook / deviation alarm status
    if not cook_armed and COOK_TEMP >= target - ALARMDEV:  # "gets near setpoint"
        cook_armed = True                                  # [V] gating
    if   probe[COOK].disconnected:                     COOK_STATUS = ERROR(4)
    elif cook_armed and COOK_TEMP-COOK_SET >= ALARMDEV:  COOK_STATUS = HIGH(1); sound_alarm()
    elif cook_armed and COOK_SET-COOK_TEMP >= ALARMDEV and not open_lid:
                                                       COOK_STATUS = LOW(2);  sound_alarm()
    elif timeout_hold_active:                          COOK_STATUS = HOLD(5)
    else:                                              COOK_STATUS = OK(0)

    # 7. food done status
    for i in [FOOD1, FOOD2, FOOD3]:
        if   probe[i].disconnected:         probe[i].STATUS = ERROR(4)
        elif probe[i].TEMP >= probe[i].SET: probe[i].STATUS = DONE(3); sound_alarm()
        else:                               probe[i].STATUS = OK(0)

    # 8. timer status
    if   not timer_expired:            TIMER_STATUS = OK(0)
    elif TIMEOUT_ACTION == HOLD:       TIMER_STATUS = HOLD(5)
    elif TIMEOUT_ACTION == ALARM:      TIMER_STATUS = ALARM(6)
    elif TIMEOUT_ACTION == SHUTDOWN:   TIMER_STATUS = SHUTDOWN(7)
    else:                              TIMER_STATUS = OK(0)

def apply_timeout_action():
    if   TIMEOUT_ACTION == HOLD:      COOK_SET = COOKHOLD; timeout_hold_active = True
    elif TIMEOUT_ACTION == SHUTDOWN: timeout_shutdown_active = True   # v2.3: fan off
                                     # (v1.7 variant: COOK_SET = 32F instead)
    elif TIMEOUT_ACTION == ALARM:    pass       # control unchanged, just alarms
    # NO_ACTION: nothing
    # any alarm/hold/shutdown state clears when a key is pressed (simulate via API "clear")

def sound_alarm():   # honor ALARM_BEEPS count; any keypress/clear silences and clears
    ...
```

---

## 11. Timer Semantics

- The **cook timer counts down** from the user-set value (`COOK_TIMER`, max `99:59:59`). `TIMER_CURR` is the live remaining time (`HH:MM:SS`, read-only). **[V]**
- When `TIMER_CURR` reaches `00:00:00`, the configured `TIMEOUT_ACTION` fires. **[V]**

### 11.1 `TIMEOUT_ACTION` effects at expiry

| Value | Name | Control action at expiry | Display / beeper |
|---|---|---|---|
| 0 | NO ACTN | none | none |
| 1 | HOLD | `COOK_SET` ← `COOKHOLD` | "TIMEOUT HOLD" flashes until a key clears it; beeps at `ALARM_BEEPS` count |
| 2 | ALARM | none (temp control unchanged) | "TIMEOUT ALARM" flashes; beeps in groups of `ALARM_BEEPS` until a key press |
| 3 | SHDN (Shutdown) | **fan output off** (v2.3/3.1) | "TIMEOUT SHDN" flashes; continuous beeps until cleared |

**Firmware difference [V]:** in **v1.7**, SHUTDOWN sets `COOK_SET` to **32 °F** (lets the fire die via an unreachably-low setpoint). In **v2.3/3.1**, SHUTDOWN **turns the fan output off** directly. Pick per the firmware being emulated.

### 11.2 `TIMER_STATUS` transitions **[I]** (using the shared status enum; precise values not individually documented)

| Condition | TIMER_STATUS |
|---|---|
| Timer idle / set to `00:00:00` | `0 (OK)` |
| Counting down (> 0) | `0 (OK)` |
| Expired, action = HOLD | `5 (HOLD)` while hold active/flashing |
| Expired, action = ALARM | `6 (ALARM)` |
| Expired, action = SHUTDOWN | `7 (SHUTDOWN)` |
| Expired, action = NO ACTN | `0 (OK)` (some units may report `3 (DONE)` — DONE-vs-OK here is inferred) |
| Key press / clear | back to `0 (OK)` |

### 11.3 Write semantics

- Set both `COOK_TIMER` and `_COOK_TIMER` (URL-encoded, colons as `%3A`) for the change to stick. **[V]**
- Format validated with `^(\d{2}):(\d{2}):(\d{2})$`. **[V]**

---

## 12. Factory Defaults

### 12.1 Verified device defaults (BBQ Guru docs)

| Field | Default | Conf. |
|---|---|---|
| `COOK_SET` | 275 °F | **[V]** |
| `FOOD1_SET` / `FOOD2_SET` / `FOOD3_SET` | 180 °F | **[V]** |
| `COOKHOLD` | 200 °F | **[V]** |
| `TIMEOUT_ACTION` | 0 (No Action) | **[V]** |
| `ALARMDEV` | 50 °F | **[V]** |
| `COOK_RAMP` | 0 (Off) | **[V]** |
| `OPENDETECT` | 1 (On) | **[V]** |
| `CYCTIME` | 6 s | **[V]** |
| `PROPBAND` | 25 °F (docs; "30 works well") | **[V]** |
| `MENU_SCROLLING` | 0 (Off) | **[V]** |
| `LCD_BACKLIGHT` | 50 % | **[V]** |
| `LCD_CONTRAST` | 10 % | **[V]** |
| `DEG_UNITS` | 1 (°F) | **[V]** |
| `ALARM_BEEPS` | 3 | **[V]** |
| `KEY_BEEPS` | 1 (On) | **[V]** |
| `HTTP_PORT` | 80 | **[V]** |
| Hot-spot SSID | `my CYBERQ Wifi` | **[V]** |
| Hot-spot `WIFI_ENC` | WEP40 | **[V]** |
| Hot-spot `WIFI_KEY` | `1234abcdef` | **[V]** |
| Hot-spot default IP | `192.168.101.10` | **[V]** |
| `SMTP_HOST` | `mail.cyberqmail.com` | **[V]** |
| `SMTP_PORT` | 587 | **[V]** |
| `SMTP_SUBJ` | `CyberQ Status Report` | **[V]** |
| `SMTP_ALERT` | 0 | **[V]** |

### 12.2 Probe name defaults

Real factory probe-name strings are not published; a bare device typically ships with generic labels (`Cook`, `Food1`, `Food2`, `Food3`). **[I]** This project's templates seed demo values (`Big Green Egg`, `Chicken Quarters`, `Beef Brisket`, `Pork Chop`) for illustration — those are **not** factory defaults.

---

## 13. CyberQ Cloud Differences

The **CyberQ Cloud** is a later, separate product (latest firmware **4.08**; discontinued) and does **not** expose this local XML API for normal control: **[V]**

- **No local control API** — everything goes through the cloud (sharemycook.com), an account-based service reachable from anywhere on the internet. The `status.xml`/`all.xml`/`config.xml` feeds are not used for ongoing control. **[V]**
- **Local hot-spot only for setup** — the Cloud still uses a hot-spot at `192.168.101.10` for initial Wi-Fi provisioning, not as an ongoing control API. **[V]**
- **Different transport** — integrations that support both models talk to the **local XML endpoints for the WiFi model** but use the **cloud service (REST/alias layer) for the Cloud model**. The exact Cloud API shape is not publicly documented; do **not** assume `nutcstatus`/`nutcallstatus` apply to the Cloud device. **[V]** (behavioral) / **[I]** (exact Cloud API).

**Bottom line:** everything in §§1–12 is specific to the **CyberQ WiFi** (v1.7 through v2.3/3.1). Our virtual device implements the WiFi model. A "Cloud-mode" shim is optional and out of scope for the core spec.

---

## 14. Confidence & Sources

### 14.1 VERIFIED (multi-source, cited)

- **Endpoint set** (`/status.xml`, `/all.xml`, `/config.xml` GET; POST-to-`/`; tolerant POST to `status.xml`), **root elements** `nutcstatus` / `nutcallstatus`, **content-type** `text/xml`, **no auth**, **no JSON/SSL**.
- **Tenths-of-°F encoding**; browser sends whole-°F (decimal-tenths allowed); **`OPEN` probe sentinel** + status `4/ERROR`.
- **8-value status enum** (0–7), **`DEG_UNITS`**, **`COOK_RAMP`**, **`TIMEOUT_ACTION`**, **`OPENDETECT`**, **`MENU_SCROLLING`**, **`KEY_BEEPS`**, **`ALARM_BEEPS`** enums.
- **23-key writable allow-list**; read-only keys (`OUTPUT_PERCENT`, `TIMER_*`, `*_TEMP`, `*_STATUS`, `FAN_SHORTED`, `FWVER`, `MAC`).
- **CONTROL/SYSTEM ranges & defaults**; **proportional law** endpoints/midpoint (below-band = 100 %, at-setpoint = 0 %, midpoint = 50 %); `OUTPUT_PERCENT` read-only.
- **Behaviors:** cook-and-hold, ramp (~30° window), open-lid detect, alarm-deviation with warm-up gating, timer + `TIMEOUT_ACTION` (incl. v1.7-vs-v2.3 SHUTDOWN difference), reboot-button, no HTTP factory-reset.
- **CyberQ Cloud has no local control API.**

**Source URLs:**
- CyberQ WiFi User Guide, Firmware v2.3/3.1 (PDF): https://www.bbqguru.com/wp-content/uploads/2023/02/CyberQ-Firmware-V2.3-USER-GUIDE.pdf
- CyberQ WiFi User Guide, Firmware v1.7 rev 3 (PDF): https://www.bbqguru.com/wp-content/uploads/2023/02/CyberQ-WiFi-Firmware-V1.7-USER-GUIDE-rev-3.pdf
- CyberQ WiFi User Guide, Firmware v2.2 rev 6 (PDF): https://www.bbqguru.com/wp-content/uploads/2023/02/CyberQ-WiFi-Firmware-V2.2-USER-GUIDE-rev-6.pdf
- BBQ Guru KB — CyberQ pages (PROPBAND=25, CYCTIME=6, 200/225/212.5 example): http://kb.bbqguru.com/help/cyberq-pages
- CyberQInterface source (writable allow-list, lookup tables, HTTP construction): https://github.com/thebrilliantidea/CyberQInterface/blob/master/cyberqinterface/cyberqinterface.py
- CyberQInterface docs — API: https://cyberqinterface.readthedocs.io/en/latest/API.html · XML examples: https://cyberqinterface.readthedocs.io/en/latest/XMLs.html · module source: https://cyberqinterface.readthedocs.io/en/latest/_modules/cyberqinterface.html
- ha_cyberq (Home Assistant integration; `_STATUS_VALUES`, `/10.0` decode, ranges, page-URL POSTs, `FWVER`/`MAC`, WiFi vs Cloud): https://github.com/jchonig/ha_cyberq
- CloudSMA PowerShell/Azure writeup (root `nutcstatus`, `/10` decode): https://www.cloudsma.com/2018/05/bbq-powershell-azure-log-analytics/
- ioBroker forum (field list, tenths-F, `IGNOREDTAG` cache-buster POST, `FAN_SHORTED`): https://forum.iobroker.net/topic/39279/daten-von-cyberq-auslesen
- SmartThings community thread (server behavior, polling fragility): https://community.smartthings.com/t/bbq-guru-cyberq-temp-controller/34954
- Home Assistant CyberQ WiFi thread (float/10 decode, write inconsistency): https://community.home-assistant.io/t/bbq-guru-cyberq-wi-fi-configuration/761814
- Home Assistant CyberQ Cloud & Wi-Fi integration thread: https://community.home-assistant.io/t/cyberq-bbq-guru-cyberq-cloud-and-wi-fi-integration/815570
- CyberQ Cloud KB: https://kb.bbqguru.com/help/cyberq-cloud
- ManualsLib CyberQ Wi-Fi: https://www.manualslib.com/manual/1476789/Bbq-Guru-Cyberq-Wi-Fi.html
- AmazingRibs CyberQ WiFi review (deviation-alarm example, open-lid, adaptive learning): https://amazingribs.com/thermometers/bbq-guru-cyberq-wifi-review/
- Local project files: `VirtualCyberQ/app/templates/{status,all,config}.xml`, `VirtualCyberQ/app/views.py`, `VirtualCyberQ/status.py`

> The BBQ Brethren "Super Nerdy" web-service thread (https://www.bbq-brethren.com/threads/cyberq-wifi-web-service-info-super-nerdy.132610/) is the original reverse-engineering source but returned HTTP 403 to automated fetchers; its content was independently corroborated by the CyberQInterface docs, ha_cyberq source, the ioBroker forum, and the CloudSMA blog, so protocol claims above are marked VERIFIED where those independent sources agree.

### 14.2 INFERRED (needs a real-device capture to confirm)

- **Exact reboot POST key** (the "Reboot Device" button body).
- **WIFI/SMTP POST key spellings** (inferred to equal the `config.xml` element names; not in any validated allow-list).
- **Integer maps for `WIFIMODE`, `DHCP`, `WIFI_ENC`, `SMTP_ALERT`** (semantics only inferred; project defaults `0`/`0`/`6`/`0`).
- **Exact `FAN_SHORTED` vs `FAN_SHORT` spelling** and its precise semantics; whether a shorted (vs open) food probe has a distinct sentinel string (no source shows one other than `OPEN` → ERROR).
- **`TIMER_STATUS` precise per-action values** (mapped to the shared 5/6/7 codes by reasoning, not documented individually).
- **Proportional-band interpolation** between the three published points (linear is the standard, consistent reading).
- **Adaptive-control internals** (integral/lead terms), **open-lid trigger threshold and hold time**, **ramp `HOLD_MARGIN`** — qualitative behavior verified, exact constants not published.
- **HTTP wire specifics** — `Server:` header string, keep-alive/`Connection: close`, chunked-vs-Content-Length framing, exact concurrent-connection cap — no raw HTTP capture available in sources.
- **`CYCTIME` device limit** — 4–10 s (docs/reference client) vs 1–30 s (one client's looser guard); prefer 4–10 s for fidelity.

> To close the inferred gaps, capture a live `config.xml` and raw HTTP exchange from a physical CyberQ WiFi while (a) toggling each WiFi encryption/mode menu, (b) unplugging a probe, (c) pressing the Reboot button, and (d) letting a timer expire under each `TIMEOUT_ACTION`. That set of captures resolves every remaining INFERRED item.
