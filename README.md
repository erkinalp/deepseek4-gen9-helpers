# ds4-ps5-xbox4-helpers

Hardware-specific deployment tooling for running DeepSeek V4 Pro across a fleet
of PlayStation 5, Xbox Series X/S and salvage-silicon boards, using the portable
inference core in [`ram-coffers/gen9-cluster`](https://github.com/erkinalp/ram-coffers).

The core knows how to split a model across heterogeneous consoles and how to
talk G9XC between them. It does not know that `ps5-003` lost a GDDR6 package,
which fused bus channel switches it, which firmware versions can boot Linux at
all, or how to get air through a bare console board bolted to a tray. That is
what lives here.

**Nothing in this repository has been run on a physical console, devkit or
salvage board.** The tooling is exercised against loopback node workers; the
hardware procedures are procedures to *verify*, not reports of something that
worked. See `docs/BOUNDARY.md` for how measured, estimated and assumed are kept
apart.

## Layout

| | |
|---|---|
| `bringup/` | Getting one physical board to the point of running a node worker: PS5 Linux, Xbox Dev Mode, salvage Linux, the ROCm-on-GFX1013 situation, the systemd unit and its installer |
| `deploy/` | Inventory → fleet JSON → deployment config → running fleet, plus preflight validation |
| `power/` | Wake-on-LAN and out-of-band power control, keyed off the inventory |
| `rack/` | Chassis, the 12 V bus, cooling, network isolation, burn-in |
| `docs/` | The boundary, the G9XC contract this depends on, the backend matrix, references |
| `examples/` | The inventory schema by example, and a loopback fleet |
| `tests/` | Standard library only; the interesting ones need a core checkout |

## Hardware

Nine SKUs, all Zen 2, all with the same basic problem — a lot of fast memory and
not much of it.

* **PS5 / PS5 Slim** — Linux via the public loader, firmware-locked. Vulkan/RADV
  on GFX1013 is the practical GPU path.
* **PS5 Pro** — modelled, but no known Linux boot path. CPU-only placeholder.
* **Xbox Series X / S** — Developer Mode only. Not Linux, ~5 GB (game) or ~1 GB
  (app), and no GPU compute path exists today: `d3d12` is a name with no kernel
  behind it.
* **AMD 4700S / 4800S** — console silicon on a desktop board with the GPU fused
  off (PS5 Ariel and Series X respectively; different harvests, not revisions).
  CPU-only, GDDR6 as system memory at a measured 92.9 GB/s. A card in the slot
  does not help: both boards are x4 electrically.
* **BC-250** — ex-mining blade, PS5-derived GFX1013 with 16 GB unified GDDR6.
  The best-documented GPU path here, and the only family designed for a rack
  from the start.

Every one of these is a downbinned part by design, and a real fleet adds its own
losses on top — a dead memory package, a fused-off core, a depopulated channel,
a clock capped to hold a temperature. The inventory records what a *specific*
board lost; the core's planner reads only the resulting effective numbers and
rebalances instead of refusing. `docs/BACKEND_MATRIX.md` says what to declare
where.

## Using it

Start from the inventory. It is the single source of truth: fleet JSON, plans,
deployment configs, wake lists and power maps are all derived from it, and
nothing is maintained in two places.

```bash
# 1. describe what is on the shelves
cp examples/fleet_inventory.csv fleet.csv && $EDITOR fleet.csv

# 2. check it before it costs you a trip to the rack
python3 deploy/check_fleet.py --inventory fleet.csv \
    --gen9 ../ram-coffers/gen9-cluster

# 3. generate core-compatible fleet JSON and a plan
python3 deploy/gen_fleet_config.py --inventory fleet.csv -o fleet.json \
    --plan deployment.json --gen9 ../ram-coffers/gen9-cluster

# 4. install the worker on a Linux node (PS5 or salvage board)
sudo ./bringup/install_node.sh --unit-id ps5-001 \
    --core /opt/ram-coffers --config /etc/g9-node/deployment.json

# 5. operate
./deploy/start_shelf.sh --inventory fleet.csv --shelf s01 --action restart
python3 power/wol.py --inventory fleet.csv --sku bc-250
python3 power/power_cycle.py --inventory fleet.csv --unit-id bc250-001 \
    --action cycle --backend command --cmd 'mybus {pdu} {outlet} {action}'
```

No hardware yet? The whole path runs on loopback, with real node workers
speaking real G9XC over real sockets:

```bash
./deploy/start_fleet_local.sh --core ../ram-coffers \
    --inventory examples/local_sim_inventory.csv
```

## Measure, don't guess

A node with no `measured_gemv_gflops` is planned around an estimate derived from
CU counts and bandwidth. That is fine for a catalogue console on a known
backend; it is not fine for anything downbinned, and it is not fine at all for
ROCm, where gfx1013 library coverage is uneven enough that the estimate is
fiction. `gen_fleet_config.py` warns about those nodes by name, and
`check_fleet.py --require-measured` turns the warning into an error for
production inventories.

```bash
python3 -m gen9_cluster probe --backend vulkan \
    --write-fleet fleet.json --unit-id bc250-001
```

Measure *after* the thermal soak, not before — see `rack/BURN_IN_CHECKLIST.md`.

## Tests

```bash
python3 -m unittest discover -s tests -t .          # standalone
GEN9_CLUSTER=../ram-coffers/gen9-cluster \
    python3 -m unittest discover -s tests -t .      # + the round trip
```

The second form is the one that matters: it feeds this repository's generated
JSON to the core's `load_fleet`, plans it, serves it with real node workers, and
talks G9XC to them. Standard library only, no build step.

## Licence

AGPL-3.0-or-later, matching `ram-coffers`.
