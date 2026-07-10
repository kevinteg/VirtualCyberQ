# SPDX-License-Identifier: BSD-3-Clause
"""Power fault handlers (DESIGN section 8, power category).

Power faults mutate sim/device state during a physics step. They model the
device *disappearing* for a window (unreachable at the transport layer) and then
returning with configuration either reset to factory defaults or persisted.

Because "the device is offline" must also gate the device-plane HTTP surface,
the offline window is exposed to the web adapter via a shared flag the
:class:`~virtualcyberq.core.simulation.Simulation` reads
(:attr:`SimState.power_offline` is not part of the core-data contract, so the
offline window is tracked here on the fault itself and surfaced through
:meth:`Simulation.is_powered`).

Catalog entries:

* ``power.brownout`` -- device disappears ``duration_s`` seconds, returns with
  config reset to defaults OR persisted.
* ``power.reboot`` -- a clean reboot: unavailable briefly, timer/state resume per
  persistence.

The handler's job each tick is to (a) mark the fault's offline window and (b) at
the moment power returns, optionally reset device config. The registry's normal
``duration_s`` auto-expiry ends the outage.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from virtualcyberq.core.rng import SeededRNG

if TYPE_CHECKING:  # pragma: no cover
    from virtualcyberq.core.faults import Fault, FaultRegistry
    from virtualcyberq.core.state import DeviceState, SimState

__all__ = ["is_power_offline", "register"]

#: Default outage windows (seconds) when a fault omits ``duration_s``.
_DEFAULT_BROWNOUT_S = 10.0
_DEFAULT_REBOOT_S = 5.0


def register(registry: FaultRegistry) -> None:
    """Register the power handlers on ``registry``."""
    registry.register_sim_handler("power.brownout", _brownout)
    registry.register_sim_handler("power.reboot", _reboot)


def _brownout(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Mark the device offline for the outage window; reset config on return.

    Params:
        reset: ``True`` to reset config to factory defaults when power returns;
            ``False`` (default) to persist state across the outage.
    """
    _mark_offline(fault)
    if fault.duration_s is None:
        fault.duration_s = _DEFAULT_BROWNOUT_S


def _reboot(
    fault: Fault,
    state: DeviceState,
    sim: SimState,
    rng: SeededRNG,
    dt: float,
) -> None:
    """Mark the device offline for a brief clean-reboot window.

    Params:
        reset: ``True`` to reset config to factory defaults on return; ``False``
            (default) to resume persisted state.
    """
    _mark_offline(fault)
    if fault.duration_s is None:
        fault.duration_s = _DEFAULT_REBOOT_S


def _mark_offline(fault: Fault) -> None:
    """Flag this fault as an active power-outage window (read by the sim)."""
    fault.params["_power_offline"] = True


def is_power_offline(fault: Fault) -> bool:
    """Return ``True`` if ``fault`` currently represents a power outage window."""
    return fault.id in ("power.brownout", "power.reboot") and bool(
        fault.params.get("_power_offline")
    )


def wants_reset(fault: Fault) -> bool:
    """Return ``True`` if a power fault should reset config to factory on return."""
    value = fault.params.get("reset", False)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)
