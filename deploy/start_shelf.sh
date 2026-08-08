#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Start, stop, restart or query the node workers of one shelf over ssh.
#
#   ./deploy/start_shelf.sh --inventory examples/fleet_inventory.csv \
#       --shelf s01 --action restart
#
# A shelf is the expert fan-out group: the consoles a token's routed experts are
# spread across. Restarting one shelf at a time is the granularity that matters,
# because a shelf's host holds the MLA KV cache for its layers — bouncing the
# whole fleet at once throws away every in-flight generation.
#
# Xbox Dev Mode nodes are skipped: no ssh, no systemd.
set -euo pipefail

INVENTORY=""
SHELF=""
RACK=""
ACTION="status"
SSH_USER="${G9_SSH_USER:-root}"
SSH_OPTS="${G9_SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=5}"
DRY_RUN=0

usage() { sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --inventory) INVENTORY="$2"; shift 2 ;;
        --shelf)     SHELF="$2"; shift 2 ;;
        --rack)      RACK="$2"; shift 2 ;;
        --action)    ACTION="$2"; shift 2 ;;
        --user)      SSH_USER="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=1; shift ;;
        -h|--help)   usage 0 ;;
        *) echo "unknown argument: $1" >&2; usage 2 ;;
    esac
done

die() { echo "start_shelf: $*" >&2; exit 1; }

[ -n "$INVENTORY" ] || die "--inventory is required"
case "$ACTION" in
    start|stop|restart|status) ;;
    *) die "--action must be start, stop, restart or status" ;;
esac
if [ -z "$SHELF" ] && [ -z "$RACK" ] && [ "$ACTION" != "status" ]; then
    die "refusing to $ACTION the entire fleet; narrow with --shelf or --rack"
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# One line per unit: "unit_id host runtime". Selection lives in Python so that
# this script and the power tooling agree on what a shelf is.
ROWS="$(PYTHONPATH="$HERE" python3 -c '
import sys
from inventory import load_inventory
units = load_inventory(sys.argv[1])
shelf, rack = sys.argv[2] or None, sys.argv[3] or None
if shelf:
    units = [u for u in units if u.shelf == shelf]
if rack:
    units = [u for u in units if u.rack == rack]
if not units:
    sys.exit("no units matched")
for u in units:
    print(u.unit_id, u.host, u.runtime)
' "$INVENTORY" "$SHELF" "$RACK")"

FAILED=0
while read -r unit host runtime; do
    [ -n "$unit" ] || continue
    case "$runtime" in
        xbox-devmode|xbox-gdk)
            echo "skip $unit: $runtime has no ssh/systemd; the console starts \
the worker itself (bringup/XBOX_DEVMODE_NOTES.md)" >&2
            continue ;;
    esac
    cmd="systemctl $ACTION g9-node@$unit"
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "[dry-run] $SSH_USER@$host: $cmd"
        continue
    fi
    printf '%-16s ' "$unit"
    # $cmd expands on the node, which is the point: %i is this unit's id.
    # SC2086 on $SSH_OPTS is deliberate, it is a list of options.
    # shellcheck disable=SC2086,SC2029
    if ! ssh $SSH_OPTS "$SSH_USER@$host" "$cmd" 2>&1 | tail -1; then
        echo "  FAILED"
        FAILED=$((FAILED + 1))
    fi
done <<< "$ROWS"

if [ "$FAILED" -gt 0 ]; then
    echo "$FAILED node(s) failed to $ACTION" >&2
    exit 1
fi
