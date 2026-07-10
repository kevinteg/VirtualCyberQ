# SPDX-License-Identifier: BSD-3-Clause
"""The ``virtual-cyberq`` command-line entry point (DESIGN section 11).

Starts the device plane and admin plane on two ports over one shared
:class:`~virtualcyberq.core.simulation.Simulation`, optionally seeded, speed-
scaled, persona-set, and pre-loaded with a scenario::

    virtual-cyberq --device-port 8080 --admin-port 9000 --seed 42 \\
                   --scenario brisket_with_flaky_wifi --speed 600
"""

from __future__ import annotations

import argparse
import sys

from virtualcyberq.core.simulation import Simulation
from virtualcyberq.scenario import ScenarioRunner, load_builtin, load_scenario
from virtualcyberq.web.server import run_servers

__all__ = ["build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for ``virtual-cyberq``."""
    parser = argparse.ArgumentParser(
        prog="virtual-cyberq",
        description="Run a high-fidelity virtual BBQ Guru CyberQ WiFi device.",
    )
    parser.add_argument(
        "--device-port",
        type=int,
        default=8080,
        help="Device-plane TCP port (default: 8080).",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        default=9000,
        help="Admin/control-plane TCP port (default: 9000).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address for both planes (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for deterministic fault/noise replay (default: 0).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Clock acceleration (sim-seconds per wall-second; 0 freezes).",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="A builtin scenario name or a path/inline scenario to preload.",
    )
    parser.add_argument(
        "--persona",
        default=None,
        help='Firmware persona to emulate (e.g. "1.7", "2.3", "3.1").',
    )
    parser.add_argument(
        "--no-tick",
        action="store_true",
        help="Disable the background physics tick loop (manual stepping only).",
    )
    return parser


def _load_scenario_onto(sim: Simulation, source: str) -> ScenarioRunner:
    """Resolve a scenario source (builtin name or path/inline) and load it."""
    if "\n" not in source and "/" not in source and not source.endswith(".yaml"):
        try:
            scenario = load_builtin(source)
        except FileNotFoundError:
            scenario = load_scenario(source)
    else:
        scenario = load_scenario(source)
    return ScenarioRunner(sim, scenario)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
    """
    args = build_parser().parse_args(argv)

    sim = Simulation(seed=args.seed, speed=args.speed)
    if args.persona:
        sim.set_persona(args.persona)
    if args.scenario:
        try:
            _load_scenario_onto(sim, args.scenario)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: could not load scenario {args.scenario!r}: {exc}", file=sys.stderr)
            return 2

    print(
        f"VirtualCyberQ device -> http://{args.host}:{args.device_port}  "
        f"admin -> http://{args.host}:{args.admin_port}/__admin/docs  "
        f"(seed={args.seed}, speed={args.speed})",
        file=sys.stderr,
    )
    try:
        run_servers(
            sim,
            device_port=args.device_port,
            admin_port=args.admin_port,
            host=args.host,
            tick=not args.no_tick,
        )
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
