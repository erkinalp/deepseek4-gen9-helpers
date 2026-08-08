# Bringing up the salvage boards: 4700S, 4800S, BC-250

> **Untested here.** No board of any of these kinds has run this stack in the
> environment that produced this repo. Everything below is assembled from
> public community documentation, cited inline; verify per board.

These are the same silicon as the consoles, sold as bare desktop hardware after
failing console binning or after a mining deployment was scrapped. They are the
*easiest* part of a mixed fleet to operate, because they are ordinary PCs: real
BIOS, real Linux, real Wake-on-LAN, no exploit chain, no sandbox. If you can
choose where the shelf hosts live, put them here.

## AMD 4700S / 4800S desktop kits

Console SoCs with the GPU fused off, sold as a board with 16 GB of GDDR6 as
*system* memory. In this project they are CPU nodes with an unusually fast
memory subsystem for a CPU — which is exactly what expert streaming wants.

They are not two revisions of one product, and the inventory must not treat them
as interchangeable: the **4700S is a PS5 "Ariel" die** on a mini-ITX board with
SATA storage only and a slot that is x16 mechanically but **PCIe 2.0 x4**
electrically, while the **4800S is an Xbox Series X die** on mATX at 4.0 GHz
with an M.2 and a **PCIe 4.0 x4** slot.

* `backend=cpu-avx2`. There is no GPU to select; the planner's SKU entry already
  reflects a fused-off GPU, so do not "fix" it with `cu_enabled_override`.
* GDDR6 as system memory has high bandwidth and high latency: 92.9 GB/s copy at
  145 ns, measured by Tom's Hardware on a retail 4700S. The AVX2 expert kernel
  is bandwidth-bound and does fine; anything latency-sensitive will not.
* Record cores lost to binning as `cpu_cores_disabled` with a `reasons` entry.
* On the 4700S, the cold tier is a SATA SSD. There is no M.2, and the slot may
  not be spent on a carrier card, so plan for ~0.55 GB/s rather than an NVMe.

**Putting a Radeon in the slot does not make one of these a small PS5.** The
card can only run experts resident in its own VRAM: pulling them from the
board's GDDR6 crosses an x4 link at ~2 GB/s (4700S) or ~7.9 GB/s (4800S), where
a console reads its own memory at 448. The core has no way to express a tier
whose bandwidth depends on which backend reads it, so there is no SKU for a
GPU-equipped kit and inventory should not invent one.

## BC-250

An ASRock Rack mining blade built around the same Cyan Skillfish / GFX1013 APU
family: Zen 2 (6c/12t), 16 GB GDDR6 unified, ~448 GB/s on paper. Community
documentation for it is unusually good — see
[elektricM/amd-bc250-docs](https://elektricm.github.io/amd-bc250-docs/) and
[akandr/bc250](https://github.com/akandr/bc250), the latter being a worked
example of exactly our workload (MoE inference over Vulkan) on this board.

Things that repository establishes and that directly shape how we treat these
boards:

* **Vulkan is the GPU path.** ROCm's userspace libraries do not ship GFX1013
  support, and OpenCL/rusticl was not usable in that configuration. Vulkan via
  RADV was the only working GPU compute path found. Set `backend=vulkan`.
* **Factory firmware exposes 24 of the die's 40 CUs.** A community kernel patch
  re-enables the rest, measured at a **1.32× median generation speed-up**. Two
  inventory consequences:
  - stock board: `cu_enabled_override=24`;
  - patched board: `cu_enabled_override=40`, plus a `reasons` note saying which
    patch, because the next person to look at the shelf will ask.
* **Decode is memory-bandwidth-bound, not compute-bound.** A roofline
  measurement on that board put peak streaming bandwidth at ~357 GB/s against
  448 GB/s of paper bandwidth, with the ridge point at ~10.9 FLOP/byte — all
  decode quantizations sit on the bandwidth-bound side. This is why the CU
  unlock helps prefill more than generation, and it is the single best argument
  for measuring rather than deriving throughput from CU counts.
* **Two kernel memory limits will stop you before the GPU does.** The amdgpu GTT
  cap and TTM's `pages_limit` both have to be raised before a large working set
  fits; get these right before concluding a board is too small.
* **Clocks are governed by a userspace `oberon-governor`-style daemon**, and the
  unlocked configuration draws noticeably more power (~116 W vs ~101 W median in
  that setup) while self-throttling a few percent lower. Cooling is the
  binding constraint, not silicon.
* **Linux only.** There is no Windows GPU driver for this board.

### Suggested per-board procedure

1. Record the board in the inventory, with `cu_enabled_override` matching the
   firmware/patch state it is actually in.
2. Flash the BIOS the community docs recommend, and set the memory split. A
   dynamic/small GPU carve-out lets the GPU grow into the unified pool, which is
   what a weight-streaming workload wants; a large static split just strands
   memory.
3. Raise the GTT cap and `ttm.pages_limit` to cover the full 16 GiB, then
   confirm with a large allocation before believing it.
4. `vulkaninfo --summary` must show RADV on GFX1013. If it does not, the board
   is `cpu-avx2` in the inventory until it does.
5. Enable WoL in BIOS and with `ethtool -s <iface> wol g`; these boards are the
   ones `power/wol.py` can genuinely wake.
6. `g9-probe` and write the measurement back. On this hardware especially, a
   derived figure is worth very little — the same board differs by 1.3× between
   two firmware states.
7. Land it on a fused 12 V drop, not an improvised supply. The board takes
   direct 12 V on a PCIe 8-pin (J1000) with no ATX PS_ON circuitry at all, so a
   plain ATX PSU has to have PS_ON jumpered to ground and then runs its fans at
   full speed forever; a proper bus drop with a switchable channel is both
   quieter and remotely recoverable. Set AUTO_PWRON1 to pins 1-2 so the board
   comes up when its drop is energised. See `rack/RACK_HARDWARE_SPEC.md`.
8. Cool it properly and continuously, with airflow *through* the fin stack. The
   stock heatsink is a passive front-to-back fin stack designed for pressurised
   rack airflow — it is the limiter, not the fans — and the backplate GDDR6
   wants pads and its own air. These ran in ventilated mining racks; they do not
   tolerate a desk.

## Why these boards matter to the plan

A shelf built from salvage boards is boring in all the right ways: it boots by
itself after a power cut, it takes a magic packet, it has a real filesystem for
the NVMe coffer tier, its GPU path is a stock Mesa away, and it was designed for
a rack chassis and a 12 V bus in the first place — no transplant, no ducting to
rebuild, no case to throw away. The consoles are where the density is; the
salvage boards are where the *hosts* should be.
