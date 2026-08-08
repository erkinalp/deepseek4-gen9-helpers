# Contributor guide

Read `docs/BOUNDARY.md` first. Everything below follows from it.

## Hard rules

**Do not implement G9XC here.** The protocol lives in
`ram-coffers/gen9-cluster/gen9_cluster/protocol.py`. `docs/G9XC_CONTRACT.md` is
a mirror for deployment reasoning and is allowed to be wrong; the core is not.
If a deployment need requires a wire change, change the core and update the
mirror afterwards.

**Do not reimplement placement.** Shelves, layers, experts, coffer tiers and
throughput weighting are the core planner's job. This repository decides which
boards exist; the core decides what goes on them.

**Generated config must be accepted by the core unchanged.** No post-processing
of `gen_fleet_config.py` output, no fields the core will ignore.
`tests/test_fleet_config.py` asserts the round trip against a real checkout.

**One inventory schema.** `examples/fleet_inventory.csv` defines it. A second,
subtly different schema somewhere else is how a fleet ends up with two
disagreeing sources of truth. Add columns there; derive everything else.

## Hardware claims

Say which of these a statement is, every time:

* **measured** — a number `g9-probe` produced on that board, in that
  configuration;
* **estimated** — derived by the core from CU counts, clocks and bandwidth;
* **assumed** — the V4 Pro configuration, and anything not yet run on the
  hardware in question.

Never write a procedure as though it has been executed unless it has. No console,
devkit or salvage board has run any of this. If you validate something on real
hardware, say exactly what you validated, on which board, at which firmware.

Cite sources inline for anything that came from outside — firmware lists, board
pinouts, power figures, community measurements — and note when a figure is one
person's single-board measurement rather than a vendor specification. Add the
citation to `docs/REFERENCES.md` too.

## Scripts

* **Standard library only.** These run on consoles and salvage boards where
  installing anything is a chore. `numpy` is the core's dependency, not ours.
* **Idempotent.** Re-running an installer converges; it does not duplicate.
* **Fail loudly.** Validate arguments up front, name the offending row or unit,
  exit non-zero. A script that silently skips a node is worse than one that
  refuses to run.
* **`set -euo pipefail`** in shell, and quote everything.

## Safety

* Anything destructive defaults to **dry-run**, and a real destructive action
  against the entire inventory is **refused** — the caller must narrow with
  `--shelf`, `--rack`, `--sku` or `--unit-id`. Keep it that way when adding
  actions.
* Power and electrical documentation is engineering guidance, not a guarantee.
  Keep the per-node fusing requirement, the bench-first procedure, and the
  "measure before you wire anything" warnings prominent. Never soften a warning
  about mains-side work.
* **No credentials anywhere** — not in the inventory, not in command templates,
  not in examples. The `command` backends exist precisely so secrets stay in the
  environment the operator's own tooling reads.
* Example inventories use RFC 1918 addresses and obviously fake MACs.

## Tests

Run both forms before sending anything:

```bash
python3 -m unittest discover -s tests -t .
GEN9_CLUSTER=../ram-coffers/gen9-cluster python3 -m unittest discover -s tests -t .
```

Tests that touch the network must use real sockets — a real UDP receiver for the
WoL packet, real node worker subprocesses for the fleet tests. Do not mock
`sendto` and call it tested. Tests that need a core checkout skip cleanly
without one; tests that would silently pass without exercising anything should
not exist.
