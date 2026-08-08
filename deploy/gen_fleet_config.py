#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Turn a fleet inventory CSV into the JSON gen9-cluster plans against.

    python3 deploy/gen_fleet_config.py \
        --inventory examples/fleet_inventory.csv -o /tmp/fleet.json

With ``--plan`` it goes one step further and calls the core planner, writing the
per-console deployment config that ``g9 serve`` consumes. That needs a
``ram-coffers`` checkout on ``PYTHONPATH`` (or ``--gen9`` / ``$GEN9_CLUSTER``);
without one it stops after the fleet JSON, which is the part this repo owns.

The split is deliberate. Placement arithmetic belongs to the core repo, which
can be tested without hardware; this repo only turns "what is physically on the
shelves" into the core's input format.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventory import Unit, fleet_json, load_inventory, unmeasured  # noqa: E402


def _import_gen9(explicit: Optional[str]):
    """Import ``gen9_cluster`` from an explicit path, the env, or the path."""
    candidate = explicit or os.environ.get("GEN9_CLUSTER")
    if candidate:
        sys.path.insert(0, str(Path(candidate).expanduser().resolve()))
    import gen9_cluster  # noqa: F401
    return gen9_cluster


def _filter(units: Sequence[Unit], shelf: Optional[str],
            skus: Optional[Sequence[str]]) -> List[Unit]:
    selected = list(units)
    if shelf:
        selected = [u for u in selected if u.shelf == shelf]
        if not selected:
            raise SystemExit(f"no units on shelf {shelf!r}")
    if skus:
        wanted = set(skus)
        selected = [u for u in selected if u.sku in wanted]
        if not selected:
            raise SystemExit(f"no units with sku in {sorted(wanted)}")
    return selected


def _warn_unmeasured(units: Sequence[Unit]) -> None:
    guessed = unmeasured(units)
    if not guessed:
        return
    print(f"warning: {len(guessed)} unit(s) have no measured throughput; the "
          f"plan will estimate them:", file=sys.stderr)
    for unit in guessed:
        why = "rocm backend" if unit.backend == "rocm" else "downbinned"
        print(f"  {unit.unit_id} ({unit.sku}, {why}) — run g9-probe on it",
              file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", required=True, help="fleet CSV")
    parser.add_argument("-o", "--out", required=True,
                        help="fleet JSON to write")
    parser.add_argument("--shelf", help="only units with this shelf label")
    parser.add_argument("--sku", action="append",
                        help="only these SKUs (repeatable)")
    parser.add_argument("--plan", metavar="CONFIG",
                        help="also run the core planner and write the "
                             "per-console deployment config here")
    parser.add_argument("--gen9", help="path to ram-coffers/gen9-cluster")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--shelf-size", type=int, default=22)
    args = parser.parse_args(argv)

    units = _filter(load_inventory(args.inventory), args.shelf, args.sku)
    Path(args.out).write_text(json.dumps(fleet_json(units), indent=2) + "\n")
    print(f"{len(units)} unit(s) -> {args.out}")
    _warn_unmeasured(units)

    if not args.plan:
        return 0

    try:
        _import_gen9(args.gen9)
    except ImportError:
        print("cannot import gen9_cluster; pass --gen9 /path/to/ram-coffers/"
              "gen9-cluster or set $GEN9_CLUSTER. The fleet JSON above is "
              "still valid.", file=sys.stderr)
        return 2

    from gen9_cluster.inventory import deployment_config, load_fleet, units \
        as fleet_units
    from gen9_cluster.model import profile_for
    from gen9_cluster.planner import PlanningError, describe_plan, plan_split

    fleet = load_fleet(Path(args.out))
    profile = profile_for(args.model)
    try:
        plan = plan_split(profile, fleet_units(fleet),
                          context_tokens=args.context,
                          shelf_size=args.shelf_size)
    except PlanningError as exc:
        print(f"cannot place {args.model} on this fleet: {exc}",
              file=sys.stderr)
        return 1
    Path(args.plan).write_text(
        json.dumps(deployment_config(plan, fleet), indent=2) + "\n")
    print("\n".join(describe_plan(plan, per_console=False)))
    print(f"\ndeployment config -> {args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
