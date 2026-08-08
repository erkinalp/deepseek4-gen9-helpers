#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Bring up a whole simulated fleet on this machine, on loopback, from a fleet
# JSON. Every node is a real node worker speaking real G9XC over a real socket —
# only the hardware is missing. This is how you exercise a deployment before any
# console exists, and how the tests in tests/ run.
#
#   ./deploy/start_fleet_local.sh --core /path/to/ram-coffers \
#       --inventory examples/fleet_inventory.csv
#
# Ctrl-C stops everything. Logs go to --logdir (default /tmp/g9-fleet).
set -euo pipefail

CORE="${GEN9_CLUSTER:-}"
INVENTORY=""
FLEET=""
LOGDIR="/tmp/g9-fleet"
MODEL="deepseek-tiny"
CONTEXT=1024
SHELF_SIZE=4

usage() { sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --core)       CORE="$2"; shift 2 ;;
        --inventory)  INVENTORY="$2"; shift 2 ;;
        --fleet)      FLEET="$2"; shift 2 ;;
        --logdir)     LOGDIR="$2"; shift 2 ;;
        --model)      MODEL="$2"; shift 2 ;;
        --context)    CONTEXT="$2"; shift 2 ;;
        --shelf-size) SHELF_SIZE="$2"; shift 2 ;;
        -h|--help)    usage 0 ;;
        *) echo "unknown argument: $1" >&2; usage 2 ;;
    esac
done

die() { echo "start_fleet_local: $*" >&2; exit 1; }

[ -n "$CORE" ] || die "--core /path/to/ram-coffers (or \$GEN9_CLUSTER)"
[ -d "$CORE/gen9-cluster/gen9_cluster" ] || die "$CORE is not a ram-coffers checkout"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE_DIR="$CORE/gen9-cluster"

mkdir -p "$LOGDIR"
FLEET="${FLEET:-$LOGDIR/fleet.json}"
CONFIG="$LOGDIR/deployment.json"

if [ -n "$INVENTORY" ]; then
    echo "== inventory -> fleet json"
    python3 "$HERE/gen_fleet_config.py" --inventory "$INVENTORY" --out "$FLEET"
elif [ ! -f "$FLEET" ]; then
    die "give --inventory to generate a fleet, or --fleet pointing at one"
fi

# A simulated fleet on loopback must not inherit the inventory's real addresses:
# 10.0.0.x is somebody's actual network. Rewrite every node onto 127.0.0.1 with
# a distinct port.
echo "== rewriting addresses onto loopback"
python3 - "$FLEET" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path))
entries = doc["fleet"] if isinstance(doc, dict) else doc
for index, entry in enumerate(entries):
    entry["host"] = "127.0.0.1"
    entry["port"] = 19713 + index
json.dump({"fleet": entries}, open(path, "w"), indent=2)
print(f"{len(entries)} node(s) on 127.0.0.1:19713+")
PY

echo "== planning"
(cd "$CORE_DIR" && python3 -m gen9_cluster plan "$FLEET" --model "$MODEL" \
    --context "$CONTEXT" --shelf-size "$SHELF_SIZE" --config "$CONFIG")

echo "== starting node workers"
PIDS=()
cleanup() {
    echo
    echo "stopping ${#PIDS[@]} node(s)"
    for pid in "${PIDS[@]:-}"; do
        if [ -n "$pid" ]; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Start one worker per node that the plan actually placed something on. A node
# with no section in the config would exit immediately and make the log noisy.
UNITS="$(python3 -c '
import json, sys
print("\n".join(sorted(json.load(open(sys.argv[1]))["nodes"])))' "$CONFIG")"

for unit in $UNITS; do
    log="$LOGDIR/$unit.log"
    (cd "$CORE_DIR" && python3 -m gen9_cluster serve "$CONFIG" "$unit" \
        --host 127.0.0.1 >"$log" 2>&1) &
    PIDS+=("$!")
done
echo "${#PIDS[@]} worker(s) started; logs in $LOGDIR"

sleep 3
echo "== health"
(cd "$CORE_DIR" && python3 -m gen9_cluster health "$FLEET" --model "$MODEL" \
    --context "$CONTEXT" --shelf-size "$SHELF_SIZE") || \
    echo "health check failed; see $LOGDIR/*.log" >&2

echo
echo "fleet is up. Ctrl-C to stop."
wait
