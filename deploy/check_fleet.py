#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check a fleet inventory before it becomes a deployment.

Three layers of checking, each one optional so the cheap ones stay usable
without a `ram-coffers` checkout or a powered-on fleet:

1. **Always** — parse the CSV, and report what the fleet adds up to.
2. **``--gen9 PATH``** — cross-check every row against the real gen9-cluster
   hardware tables: SKU, runtime, whether that backend is even reachable on that
   sku/runtime pair, and how much each unit is actually worth after its downbin.
   This is the check that catches ``backend=vulkan`` on a Dev Mode Xbox.
3. **``--connect``** — open a TCP connection to each ``host:port``. Not a G9XC
   handshake: this repo does not speak the protocol (see ``docs/G9XC_CONTRACT``),
   it only answers "is something listening where the inventory says".

Exits non-zero on the first *error*; warnings are printed and counted. A partly
valid fleet is not a deployable one, so failing loudly beats proceeding.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory import Unit, load_inventory, unmeasured  # noqa: E402

GB = 1024 ** 3


def _load_gen9(path: Optional[str]):
    candidate = path or os.environ.get("GEN9_CLUSTER")
    if candidate:
        sys.path.insert(0, str(Path(candidate).expanduser().resolve()))
    from gen9_cluster import hardware
    return hardware


def check_against_core(units: Sequence[Unit], hardware) \
        -> Tuple[List[str], List[str]]:
    """Validate each row against the core's own SKU/runtime/backend tables."""
    errors: List[str] = []
    warnings: List[str] = []
    for unit in units:
        if unit.sku not in hardware.SKUS:
            errors.append(f"{unit.unit_id}: sku {unit.sku!r} is not in the "
                          f"core's SKU table")
            continue
        effective = load_unit(unit, hardware).effective()
        for warning in effective.warnings:
            warnings.append(f"{unit.unit_id}: {warning}")
        if effective.weight_bytes <= 0:
            errors.append(f"{unit.unit_id}: nothing left for weights after "
                          f"its downbin and runtime reservation")
    return errors, warnings


def load_unit(unit: Unit, hardware):
    """Build the core's ``ConsoleUnit`` for one inventory row."""
    downbin = hardware.Downbin(
        cu_disabled=unit.cu_disabled,
        cpu_cores_disabled=unit.cpu_cores_disabled,
        cpu_ghz_cap=unit.cpu_ghz_cap,
        gpu_ghz_cap=unit.gpu_ghz_cap,
        tier_losses=dict(unit.tier_losses),
        tier_bandwidth_scale=dict(unit.tier_bandwidth_scale),
        memory_budget_bytes=unit.memory_budget_bytes,
        reasons=unit.reasons)
    return hardware.ConsoleUnit(
        unit_id=unit.unit_id, sku=unit.sku,
        runtime=hardware.Runtime(unit.runtime),
        backend=(hardware.ComputeBackend(unit.backend)
                 if unit.backend else None),
        downbin=downbin,
        measured_gemv_gflops=unit.measured_gemv_gflops,
        devmode_app=unit.devmode_app,
        cu_enabled_override=unit.cu_enabled_override)


def probe_ports(units: Sequence[Unit], timeout: float) -> List[str]:
    """Report which units are not listening. Not a protocol handshake."""
    dead = []
    for unit in units:
        try:
            with socket.create_connection((unit.host, unit.port),
                                          timeout=timeout):
                pass
        except OSError as exc:
            dead.append(f"{unit.unit_id} ({unit.host}:{unit.port}): {exc}")
    return dead


def summarise(units: Sequence[Unit]) -> List[str]:
    by_sku: dict = {}
    by_shelf: dict = {}
    for unit in units:
        by_sku[unit.sku] = by_sku.get(unit.sku, 0) + 1
        by_shelf[unit.shelf or "(none)"] = \
            by_shelf.get(unit.shelf or "(none)", 0) + 1
    lines = [f"{len(units)} unit(s)"]
    for sku, count in sorted(by_sku.items()):
        lines.append(f"  {count:>4} x {sku}")
    lines.append("shelves: " + ", ".join(
        f"{name}={count}" for name, count in sorted(by_shelf.items())))
    damaged = [u for u in units if not u.is_pristine]
    lines.append(f"{len(damaged)} unit(s) carry a recorded downbin")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--gen9", help="path to ram-coffers/gen9-cluster, to check "
                                   "rows against the real hardware tables")
    ap.add_argument("--connect", action="store_true",
                    help="check that something is listening on each host:port")
    ap.add_argument("--timeout", type=float, default=2.0)
    ap.add_argument("--require-measured", action="store_true",
                    help="fail if a unit the planner cannot predict has no "
                         "measured_gemv_gflops")
    args = ap.parse_args(argv)

    try:
        units = load_inventory(args.inventory)
    except (OSError, ValueError) as exc:
        print(f"inventory is not usable: {exc}", file=sys.stderr)
        return 2
    print("\n".join(summarise(units)))

    errors: List[str] = []
    warnings: List[str] = []

    guessed = unmeasured(units)
    for unit in guessed:
        message = (f"{unit.unit_id}: no measured_gemv_gflops; the planner will "
                   f"estimate it")
        (errors if args.require_measured else warnings).append(message)

    if args.gen9 or os.environ.get("GEN9_CLUSTER"):
        try:
            hardware = _load_gen9(args.gen9)
        except ImportError as exc:
            print(f"cannot import gen9_cluster: {exc}", file=sys.stderr)
            return 2
        core_errors, core_warnings = check_against_core(units, hardware)
        errors += core_errors
        warnings += core_warnings
    else:
        print("\n(no --gen9/$GEN9_CLUSTER: skipping the checks that need the "
              "core's hardware tables)")

    if args.connect:
        for line in probe_ports(units, args.timeout):
            errors.append(f"not listening: {line}")

    for line in warnings:
        print(f"warning: {line}", file=sys.stderr)
    for line in errors:
        print(f"error: {line}", file=sys.stderr)
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
