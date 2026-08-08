# Bringing up a PS5 as a G9XC node

> **Untested here.** Nothing in this file has been executed on a PlayStation 5
> by the people who wrote it. It is assembled from the public `ps5-linux`
> project and the upstream kernel/Mesa work, and is a procedure to verify
> console-by-console, not a guarantee. Treat every step as "check this on one
> unit before doing it to forty".

## What is actually possible

A PS5 does not run arbitrary code on its own. Linux gets on there through the
[`ps5-linux-loader`](https://github.com/ps5-linux/ps5-linux-loader) exploit
chain, which is firmware-version-locked. As of the project's README the
supported set is **PS5 Phat and Slim** on:

| Firmware | M.2 support |
|---|---|
| 3.00, 3.10, 3.20, 3.21 | no |
| 4.00, 4.02, 4.03, 4.50, 4.51 | yes |
| 5.00, 5.02, 5.10, 5.50 | yes |
| 6.00, 6.02, 6.50 | yes |
| 7.20, 7.40, 7.60, 7.61 | yes |

Three consequences the deployment side has to live with:

1. **Check the firmware before you buy.** A console on an unsupported firmware
   is not a node, and firmware cannot be rolled back. This is the single most
   important acceptance criterion in `rack/BURN_IN_CHECKLIST.md`.
2. **PS5 Pro is not on that list.** The `ps5-pro` SKU exists in the planner
   because the hardware exists, not because a Linux path for it is known here.
   Do not plan a fleet around Pro units until you have one booting.
3. **A PS5 node does not boot by itself.** The chain starts from the console's
   own UI, so a power cut means somebody re-runs it. Plan for that: PS5 nodes
   should be *expert holders*, not shelf hosts, so that losing one costs a
   re-load and not a KV cache. The planner does not know this — set it up in
   the inventory by placing hosts on salvage boards where you can.

## GPU

The GPU is GFX1013 ("Cyan Skillfish" family), reached with **amdgpu + RADV**.
Kernel and Mesa support was upstreamed in pieces; a recent Mesa is required
(the ADDRLIB commit adding more GFX1013 GPUs is the relevant one). For our
purposes:

* **Vulkan compute (RADV) is the default backend** for `ps5*` SKUs. That is what
  `gen9-cluster` compiles `kernels/expert.comp` for.
* **ROCm is opt-in and must be measured.** See `ROCM_GFX1013_NOTES.md`.
* Set `backend=vulkan` in the inventory, or leave it blank and let the node
  pick; set it to `cpu-avx2` if the GPU path is not up yet on that unit. A
  CPU-only PS5 is still a perfectly good 13 GiB coffer.

## Procedure, per console

1. **Record it first.** Add the row to the inventory CSV — `unit_id`, `sku`,
   `host`, `mac`, `shelf`, `rack`, `slot`, `pdu`, `pdu_outlet` — before
   touching the console. A unit that exists on the shelf but not in the CSV is
   a unit nobody will power-cycle correctly at 3 a.m.
2. **Fixed address.** Give the console a DHCP reservation on the compute VLAN.
   The inventory records an address; that address has to keep meaning the same
   console.
3. **Boot Linux** with `ps5-linux-loader` per its own instructions for your
   firmware. Prefer the M.2-supported firmwares: an internal SSD is what makes
   the `ssd` coffer tier real, and without it the planner's NVMe overflow tier
   has nowhere to go.
4. **Verify the GPU** before trusting it:
   ```bash
   ls /sys/class/drm/card*/device/vendor
   vulkaninfo --summary | head -40      # expect RADV, GFX1013
   ```
   If `vulkaninfo` does not show a RADV device, this unit is `cpu-avx2` in the
   inventory until it does. Do not set `backend=vulkan` hopefully.
5. **Install the node service** (see `install_node.sh`), pointing it at a
   `gen9-cluster` checkout and the deployment config generated for this fleet.
6. **Measure it.** `g9-probe` writes `measured_gemv_gflops` back into the
   inventory. Estimated throughput is fine for a catalogue console on a known
   backend; it is not fine for anything with a downbin.
7. **Record the damage.** Whatever this unit lost — CUs, cores, a clock cap
   after a fan swap, a memory package — goes in the CSV with a `reasons` entry.
   The planner reads only effective numbers, so an unrecorded fault becomes a
   mysteriously slow shelf instead of a line in the plan.

## Power and thermals

In the rack build the board comes out of its case and off its ADP-400DR, and
runs from a fused drop on a common 12 V bus — the console PSU is a 372 W
single-rail +12 V supply feeding the board through spade terminals, so the
board itself only ever wanted 12 V. **Bench-test each board on a
current-limited supply before it goes anywhere near the bus**, and read
`rack/RACK_HARDWARE_SPEC.md` §"The 12 V bus" and `rack/BURN_IN_CHECKLIST.md`
§1a first; per-drop fusing is not optional.

Once the plastic is gone you also own the cooling duct. The console's heatsink
was designed around a specific blower and shroud; either keep and feed that
blower, or reproduce the airflow path deliberately. A bare board with a fan
pointed at it measures fine for ten minutes and throttles for the rest of its
life.

These consoles were designed to run a game for a few hours, not a
memory-bandwidth-saturating kernel continuously. Sustained decode keeps GDDR6
and the APU near their limits far longer than any game does. Re-paste, clean,
and expect to cap clocks (`gpu_ghz_cap` in the inventory) rather than let a
unit throttle unpredictably — a *declared* cap is planned around; a thermal
throttle just makes one shelf mysteriously slow.
