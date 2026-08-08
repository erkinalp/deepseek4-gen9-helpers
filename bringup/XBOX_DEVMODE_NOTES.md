# Bringing up an Xbox Series X/S as a G9XC node

> **Untested here.** No Xbox has run any of this. The memory budgets below come
> from Microsoft's published Dev Mode limits and are the numbers the planner
> uses; verify them on your own console and firmware before planning a fleet
> around them.

## What Dev Mode gives you, and what it does not

A retail Series X or S can be switched into **Developer Mode** and run
self-published code. That is the whole reason these consoles are in this project
— but the sandbox is much tighter than a PS5 running Linux:

* **No Linux.** Code runs inside the console's own sandbox, not on a kernel you
  control. There is no `amdgpu`, no RADV, no ROCm — the GFX1013-style Vulkan
  path that PS5 nodes use does not exist here.
* **A hard memory ceiling.** Dev Mode partitions memory: roughly **5 GB** for a
  title and about **1 GB** for an app. That ceiling, not the console's 10/16 GB
  of GDDR6, is what the unit can actually hold. Set `devmode_app=true` in the
  inventory for an app-partition unit; the planner then budgets ~1 GB for it
  instead of ~5 GB, and places accordingly.
* **The GPU is not usable from here today.** `gen9-cluster` has a `d3d12`
  backend *name* and no D3D12 kernel behind it. A Dev Mode Xbox is therefore
  **`cpu-avx2`** in the inventory. Do not set `backend=d3d12` — the node will
  refuse it rather than silently run something else.

So an Xbox in Dev Mode is a Zen 2 CPU with a 5 GB coffer. That is a genuinely
useful thing to have in a fleet of this shape — 52 of 1359 billion parameters
activate per token, so most of the fleet's job is *holding* weights and
streaming them — but it is not what the box's spec sheet suggests.

## Series X vs Series S

Both have 8 Zen 2 cores. The difference the planner cares about is memory:
Series X splits its 16 GB into a fast 10 GB @ 560 GB/s and a slower 6 GB @
336 GB/s; Series S has 10 GB, 8 of it fast. Under Dev Mode the sandbox budget
dominates either way, which is why two consoles with very different GPUs end up
looking similar in a plan.

## GDK

`xbox-gdk` in the inventory means a full GDK title on a devkit, not retail Dev
Mode: a bigger memory budget and a real path to the GPU. If you have devkits,
use that runtime — but the D3D12 compute backend still has to be written before
the GPU does anything, so today it changes the memory budget and nothing else.

## Procedure, per console

1. **Record it in the inventory first**, with `devmode_app` set correctly. The
   difference between a 1 GB and a 5 GB unit is the difference between a plan
   that fits and one that does not.
2. **Enable Developer Mode** through Microsoft's own activation flow. That
   requires a developer account and is per-console; budget for it before
   ordering forty consoles.
3. **Fixed address** on the compute VLAN, by DHCP reservation.
4. **Deploy the node worker** into the sandbox as a title/app. There is no
   `systemd` here, so `bringup/g9-node@.service` does not apply; the console's
   own lifecycle starts and stops it.
5. **Measure it.** `g9-probe` on the CPU path, written back to the inventory.
   Sandboxed CPU throughput is not the same as bare-metal Zen 2 throughput, and
   the plan should use the real number.
6. **Never fail a shelf host onto an Xbox** you are not sure of: Dev Mode can
   be interrupted by the console's own UI in ways a Linux box cannot.

## Power

Xbox network wake uses the console's own protocol, not a plain WoL magic packet.
`power/wol.py` therefore skips Xbox rows unless you pass `--force`, and the
supported path is switched power (`power/power_cycle.py`).

**Xbox boards are the exception to the rack build.** `rack/RACK_HARDWARE_SPEC.md`
puts PS5 and BC-250 boards bare on a common 12 V bus, because both are
documented single-12 V-input designs. We have not characterised the Series X/S
board's connector or rails, so do not wire one to a bus on the strength of
anything in this repository: measure the stock supply's outputs under load
first, and if a 12 V-only feed turns out not to be possible, leave the console
assembled and give it a switched mains outlet. That is a cheap concession —
Dev Mode nodes are CPU-only, memory-starved and the lowest-value rows in the
fleet, so spending a rack outlet on one costs almost nothing.

Dev Mode also runs the console's own thermal management, which is one fewer
thing to build and one fewer thing you can tune: there is no `gpu_ghz_cap`
equivalent you can enforce from outside, and no systemd to restart. Expect to
recover a wedged Xbox by cutting its power.
