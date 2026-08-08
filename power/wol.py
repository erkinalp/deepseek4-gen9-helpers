#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wake fleet units with Wake-on-LAN magic packets, keyed off the inventory.

    python3 power/wol.py --inventory examples/fleet_inventory.csv          # all
    python3 power/wol.py --inventory examples/fleet_inventory.csv --shelf s01
    python3 power/wol.py --inventory examples/fleet_inventory.csv --sku bc-250

Where WoL actually applies here:

* **Salvage boards** (4700S, 4800S, BC-250) are ordinary PCs. Enable WoL in the
  BIOS and with ``ethtool -s <iface> wol g``, and the magic packet works as it
  does anywhere else.
* **PS5 running Linux** is booted through an exploit chain from the console's
  own firmware, so it does not come up into Linux by itself. A magic packet is
  not a boot path for those; ``power/power_cycle.py`` plus the bring-up
  procedure is.
* **Xbox in Dev Mode** wakes over the network through its own protocol, not a
  plain magic packet. This script does not implement it and does not pretend to;
  use the PDU, or the console's own tooling.

So this is genuinely useful for the salvage half of a mixed fleet and honest
about the console half. It is best-effort either way: a hung unit, or one whose
outlet is off, will not answer.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from typing import List, Optional, Sequence

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "deploy"))

from inventory import Unit, load_inventory  # noqa: E402

#: SKUs that boot from a magic packet like a normal PC.
WOL_CAPABLE_SKUS = ("amd-4700s", "amd-4800s", "bc-250", "host-sim")


def magic_packet(mac: str) -> bytes:
    """Build the 102-byte WoL magic packet for ``mac`` (any common format)."""
    hexdigits = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(hexdigits) != 12:
        raise ValueError(f"invalid MAC: {mac!r}")
    try:
        payload = bytes.fromhex(hexdigits)
    except ValueError as exc:
        raise ValueError(f"invalid MAC: {mac!r}") from exc
    return b"\xff" * 6 + payload * 16


def wake(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


def select(units: Sequence[Unit], *, shelf: Optional[str] = None,
           rack: Optional[str] = None, sku: Optional[str] = None,
           unit_id: Optional[str] = None) -> List[Unit]:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--shelf")
    ap.add_argument("--rack")
    ap.add_argument("--sku")
    ap.add_argument("--unit-id")
    ap.add_argument("--broadcast", default="255.255.255.255",
                    help="broadcast address for the compute subnet")
    ap.add_argument("--port", type=int, default=9)
    ap.add_argument("--force", action="store_true",
                    help="send to consoles too, which will not boot Linux "
                         "from a magic packet")
    ap.add_argument("--dry-run", action="store_true",
                    help="print who would be woken, send nothing")
    args = ap.parse_args(argv)

    units = select(load_inventory(args.inventory), shelf=args.shelf,
                   rack=args.rack, sku=args.sku, unit_id=args.unit_id)
    if not units:
        ap.error("no units matched the filters")

    sent = 0
    for unit in units:
        if unit.sku not in WOL_CAPABLE_SKUS and not args.force:
            print(f"skip {unit.unit_id}: {unit.sku} does not boot from a "
                  f"magic packet (use the PDU; --force to send anyway)",
                  file=sys.stderr)
            continue
        if not unit.mac:
            print(f"skip {unit.unit_id}: no MAC in inventory", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"would wake {unit.unit_id} ({unit.mac})")
        else:
            wake(unit.mac, args.broadcast, args.port)
            print(f"woke {unit.unit_id} ({unit.mac})")
        sent += 1
    if not sent:
        print("nothing sent", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
