# Where the boundary is

```
ram-coffers/gen9-cluster        portable core, retargeted at build time
  protocol (G9XC), transport, planner, dispatch, coordinators,
  node worker, CPU/Vulkan/HIP kernels, FP8
        │
        │  wire + config contract
        ▼
ds4-ps5-xbox4-helpers           hardware-specific, this repository
  bringup/   getting one physical unit to the point of running the worker
  deploy/    inventory → fleet JSON → deployment config → running fleet
  power/     WoL and out-of-band power, keyed off the inventory
  rack/      chassis, 12 V bus, cooling, network, burn-in
```

## What belongs on each side

| | core | here |
|---|---|---|
| G9XC framing, message types | ✅ | mirrored in `docs/G9XC_CONTRACT.md` for reference only |
| Placement arithmetic (shelves, layers, experts, coffers) | ✅ | never |
| SKU tables, downbin semantics, effective capability | ✅ | consumed; `deploy/check_fleet.py` validates rows *against* them |
| Kernels, FP8, dispatch, retries | ✅ | never |
| What a specific PS5 firmware can boot | | ✅ |
| Whether a given board's Vulkan stack works | | ✅ |
| Turning "what is on the shelves" into a fleet JSON | | ✅ |
| Starting, restarting and powering units | | ✅ |
| Chassis, 12 V bus, airflow, burn-in | | ✅ |

## The three rules that follow

**1. Do not fork the protocol.** If a deployment need cannot be met without a
wire change, the change goes into `ram-coffers` and the mirror here is updated
afterwards. A second implementation of G9XC in this repository would be a
version-skew bug generator, and this repo has no tests that could catch it.

**2. Config generated here must be accepted unchanged by the core.** The output
of `deploy/gen_fleet_config.py` is fed to `gen9_cluster.inventory.load_fleet`
verbatim — no post-processing, no fields the core will ignore. `tests/` asserts
the round trip when a core checkout is available, and skips otherwise.

**3. The inventory is the single source of truth.** Every other artefact —
fleet JSON, deployment config, WoL list, power map, the `--shelf` selector — is
derived from `examples/fleet_inventory.csv`'s schema. Nothing is maintained in
two places, because the second place is always the stale one.

## Measured, estimated, assumed

Three different epistemic states, kept distinct everywhere in both repos:

* **Measured** — a number produced by `g9-probe` on that unit, in that
  configuration. Written into the inventory. Trust it.
* **Estimated** — derived by the core from CU counts, clocks and bandwidth.
  Fine for a catalogue console on a known backend; the plan says it is an
  estimate. On GFX1013 the same board measured 1.3× apart between two firmware
  states, so an estimate is a starting point and not a result.
* **Assumed** — the DeepSeek V4 Pro configuration itself, which is extrapolated
  and stamped `ASSUMED CONFIGURATION` wherever it is used, and everything in
  `bringup/` that has not been run on the hardware in question.

**No physical console, devkit or salvage board has run any of this.** The core's
tests run on a host; the helper tooling here is tested against loopback node
workers. Anything in this repository that reads like a procedure is a procedure
to *verify*, not a report of something that worked.
