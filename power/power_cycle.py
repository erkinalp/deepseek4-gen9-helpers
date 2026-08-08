#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Out-of-band power control for fleet units, keyed off the inventory.

Wake-on-LAN cannot recover a hung unit, and on a PS5 or an Xbox it is not a boot
path at all — cutting and restoring power is the only thing that always works.
This maps ``(pdu, pdu_outlet)`` from the inventory onto a pluggable backend that
drives your actual power controller. In the rack build that pair names a 12 V
bus controller and one fused, switchable drop (``rack/RACK_HARDWARE_SPEC.md``);
on a bench of stock consoles it names a PDU and an outlet. This script does not
care which — it only substitutes the pair into your template. Nothing
vendor-specific is bundled: the backends are ``dry-run`` (print only) and
``command`` (run a templated shell command per channel).

    # see what would happen
    python3 power/power_cycle.py --inventory examples/fleet_inventory.csv \
        --shelf s01 --action cycle --backend dry-run

    # drive a real controller through your own CLI. Keep credentials in the
    # environment your template reads; never in the inventory or in this repo.
    python3 power/power_cycle.py --inventory examples/fleet_inventory.csv \
        --unit-id ps5-003 --action cycle --backend command \
        --cmd 'mypdu --host {pdu} --outlet {outlet} --{action}'

Actions: ``on``, ``off``, ``cycle`` (off, wait ``--settle`` seconds, on).

A power cut is not free for this workload: every console holds shards that the
coordinator loaded over G9XC, and a unit that comes back has to be re-loaded
before it is useful. Cycling a shelf *host* additionally destroys the MLA KV
cache for its layers, which ends any in-flight generation. Prefer restarting the
node service (``systemctl restart g9-node``) when the unit is merely wedged.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "deploy"))

from inventory import Unit, load_inventory  # noqa: E402


def _select(units: Sequence[Unit], shelf: Optional[str], rack: Optional[str],
            sku: Optional[str], unit_id: Optional[str]) -> List[Unit]:
    selected = list(units)
    if shelf:
        selected = [u for u in selected if u.shelf == shelf]
    if rack:
        selected = [u for u in selected if u.rack == rack]
    if sku:
        selected = [u for u in selected if u.sku == sku]
    if unit_id:
        selected = [u for u in selected if u.unit_id == unit_id]
    return selected


def _run_command(template: str, unit: Unit, action: str) -> None:
    if not unit.pdu or not unit.pdu_outlet:
        raise ValueError(f"{unit.unit_id}: no pdu/pdu_outlet in inventory")
    cmd = template.format(pdu=unit.pdu, outlet=unit.pdu_outlet, action=action,
                          unit=unit.unit_id, host=unit.host, sku=unit.sku)
    subprocess.run(shlex.split(cmd), check=True)


def apply_action(unit: Unit, action: str, backend: str, cmd: str,
                 settle: float) -> None:
    steps = ["off", "on"] if action == "cycle" else [action]
    for index, step in enumerate(steps):
        if backend == "dry-run":
            print(f"[dry-run] {unit.unit_id}: {step} "
                  f"(pdu={unit.pdu} outlet={unit.pdu_outlet})")
        elif backend == "command":
            _run_command(cmd, unit, step)
            print(f"{unit.unit_id}: {step}")
        else:
            raise ValueError(f"unknown backend {backend!r}")
        if action == "cycle" and index == 0:
            time.sleep(settle)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--shelf")
    ap.add_argument("--rack")
    ap.add_argument("--sku")
    ap.add_argument("--unit-id")
    ap.add_argument("--action", required=True, choices=("on", "off", "cycle"))
    ap.add_argument("--backend", default="dry-run",
                    choices=("dry-run", "command"))
    ap.add_argument("--cmd", default="",
                    help="command template for --backend command; fields: "
                         "{pdu} {outlet} {action} {unit} {host} {sku}")
    ap.add_argument("--settle", type=float, default=8.0,
                    help="seconds between off and on for --action cycle")
    args = ap.parse_args(argv)

    if args.backend == "command" and not args.cmd:
        ap.error("--backend command requires --cmd")

    units = _select(load_inventory(args.inventory), args.shelf, args.rack,
                    args.sku, args.unit_id)
    if not units:
        ap.error("no units matched the filters")

    narrowed = any((args.shelf, args.rack, args.sku, args.unit_id))
    if args.backend != "dry-run" and args.action in ("off", "cycle") \
            and not narrowed:
        ap.error("refusing to power off the entire inventory; narrow with "
                 "--shelf/--rack/--sku/--unit-id, or use --backend dry-run")

    for unit in units:
        apply_action(unit, args.action, args.backend, args.cmd, args.settle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
