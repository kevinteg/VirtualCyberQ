# SPDX-License-Identifier: BSD-3-Clause
"""Drive an accelerated brisket cook through the control plane.

This example uses the in-process test harness (:class:`VirtualCyberQ`) with a
**frozen clock**, so nothing depends on wall-clock time: we jump the simulation
forward in deterministic chunks via ``admin.time.advance(...)`` and watch the
pit warm up, the brisket climb through the stall, and the food probe reach
``DONE``. The same :class:`AdminClient` API works unchanged against a running
server (construct it with ``base_url=...`` instead of via the harness).

Run it with::

    python examples/drive_a_cook.py

Everything here is deterministic under ``seed=42`` -- re-running prints the same
temperatures.
"""

from __future__ import annotations

from virtualcyberq.testing import VirtualCyberQ

HOUR = 3600.0


def _fmt(temp_f: float | None) -> str:
    return "OPEN" if temp_f is None else f"{temp_f:6.1f} degF"


def main() -> int:
    """Run an accelerated brisket cook and print a timeline."""
    # Frozen clock (speed=0): we advance time explicitly and deterministically.
    with VirtualCyberQ(seed=42, speed=0.0) as cq:
        admin = cq.admin

        # Define the cook: 225 degF pit from a cold start, one 13 lb brisket on
        # FOOD1 targeting 203 degF, plus a chicken-quarter on FOOD2.
        admin.reset("factory")
        admin.patch_state({"cook": {"set": 2250}})  # tenths-degF setpoint
        admin.profile(
            pit={"start_f": 70, "ambient_f": 70, "cook_set_f": 225},
            food1={"cut": "brisket", "set_f": 203, "mass_lb": 13, "wrapped": False},
            food2={"cut": "chicken_quarters", "set_f": 175, "mass_lb": 0.7},
            food3={"disconnected": True},
        )

        print(f"{'sim time':>9}  {'pit':>12}  {'brisket':>12}  {'chicken':>12}  out%")
        print("-" * 62)

        # Advance in 30-minute steps for 12 simulated hours.
        for step in range(24):
            admin.time.advance(seconds=0.5 * HOUR)
            st = admin.state()
            hours = (step + 1) * 0.5
            print(
                f"{hours:6.1f} h  {_fmt(st.cook.temp_f):>12}  "
                f"{_fmt(st.food1.temp_f):>12}  {_fmt(st.food2.temp_f):>12}  "
                f"{st.output_percent:3d}"
            )
            if st.food1.status == "DONE":
                print(
                    f"\nBrisket DONE after ~{hours:.1f} simulated hours "
                    f"at {_fmt(st.food1.temp_f).strip()}."
                )
                break

        # Snapshot the finished cook so a bug report could reproduce it exactly.
        snap = admin.snapshot()
        print(f"\nsnapshot id: {snap['snapshot_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
