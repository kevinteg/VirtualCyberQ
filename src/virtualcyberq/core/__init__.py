# SPDX-License-Identifier: BSD-3-Clause
"""Framework-agnostic core: state, enums, units, defaults, clock, RNG, validation.

Nothing under ``core`` may import a web framework (fastapi/flask/starlette/
uvicorn); the boundary is enforced by import-linter in CI. This ``__init__``
re-exports only the data-layer types built in the first phase (state, enums,
units, defaults, clock, RNG, validation). Simulation/thermal/control/faults are
imported directly from their modules by consumers once they exist.
"""

from __future__ import annotations

from virtualcyberq.core.clock import VirtualClock
from virtualcyberq.core.defaults import (
    DEFAULT_FWVER,
    demo_state,
    factory_control,
    factory_smtp,
    factory_state,
    factory_system,
    factory_wifi,
)
from virtualcyberq.core.enums import (
    DegUnits,
    Dhcp,
    OnOff,
    RampSource,
    StatusCode,
    TimeoutAction,
    WifiEnc,
    WifiMode,
)
from virtualcyberq.core.rng import SeededRNG
from virtualcyberq.core.state import (
    ControlConfig,
    DeviceState,
    ProbeState,
    SimState,
    SmtpConfig,
    SystemConfig,
    TimerState,
    WifiConfig,
)
from virtualcyberq.core.units import (
    OPEN,
    decode_temp,
    encode_temp,
    float_to_tenths,
    hms_to_seconds,
    parse_input_temp,
    seconds_to_hms,
    tenths_to_float,
)
from virtualcyberq.core.validation import (
    CANONICAL_23_KEYS,
    READONLY_KEYS,
    SMTP_KEYS,
    WIFI_KEYS,
    WRITABLE_PARAMS,
    ParamKind,
    ParamSpec,
    ValidationResult,
    WriteMode,
    is_readonly,
    is_writable,
    validate_write,
)

__all__ = [
    "CANONICAL_23_KEYS",
    # defaults
    "DEFAULT_FWVER",
    # units
    "OPEN",
    "READONLY_KEYS",
    "SMTP_KEYS",
    "WIFI_KEYS",
    "WRITABLE_PARAMS",
    "ControlConfig",
    "DegUnits",
    "DeviceState",
    "Dhcp",
    "OnOff",
    "ParamKind",
    "ParamSpec",
    # state
    "ProbeState",
    "RampSource",
    "SeededRNG",
    "SimState",
    "SmtpConfig",
    # enums
    "StatusCode",
    "SystemConfig",
    "TimeoutAction",
    "TimerState",
    "ValidationResult",
    # clock / rng
    "VirtualClock",
    "WifiConfig",
    "WifiEnc",
    "WifiMode",
    # validation
    "WriteMode",
    "decode_temp",
    "demo_state",
    "encode_temp",
    "factory_control",
    "factory_smtp",
    "factory_state",
    "factory_system",
    "factory_wifi",
    "float_to_tenths",
    "hms_to_seconds",
    "is_readonly",
    "is_writable",
    "parse_input_temp",
    "seconds_to_hms",
    "tenths_to_float",
    "validate_write",
]
