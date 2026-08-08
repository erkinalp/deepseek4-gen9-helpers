# Which backend runs where

What to put in the inventory's `backend` column, and why. "Works" here means
"there is a code path in `gen9-cluster` and a plausible driver stack"; it does
**not** mean anyone has run it on that hardware. Nothing in this table has been
validated on a physical console.

| SKU | Runtime | Default | GPU compute | Notes |
|---|---|---|---|---|
| `ps5`, `ps5-slim` | `ps5-linux` | `vulkan` | RADV on GFX1013 | Firmware-locked boot chain; see `bringup/PS5_LINUX_NOTES.md` |
| `ps5-pro` | `ps5-linux` | `cpu-avx2` | unknown | No known Linux boot path; the SKU exists because the hardware does |
| `xbox-series-x/s` | `xbox-devmode` | `cpu-avx2` | **none** | No `d3d12` kernel exists; sandbox caps memory at ~5 GB (game) or ~1 GB (app) |
| `xbox-series-x/s` | `xbox-gdk` | `cpu-avx2` | **none today** | GDK could reach D3D12; the compute kernel is unwritten |
| `amd-4700s` (PS5 die), `amd-4800s` (Series X die) | `salvage-linux` | `cpu-avx2` | GPU fused off | GDDR6 as system memory: 92.9 GB/s at 145 ns. A card in the slot reaches board memory over PCIe 2.0 x4 / 4.0 x4, so it is not a GPU node |
| `bc-250` | `salvage-linux` | `vulkan` | RADV on GFX1013 | Best-documented GPU path in the fleet; ROCm userspace coverage is the problem, not the driver |
| `host-sim` | `host-sim` | `cpu-avx2` | n/a | Loopback simulation |

## `cpu-avx2`

Zen 2 AVX2/FMA. Available on every unit here, since every one of them is Zen 2.
This is the honest default whenever a GPU stack is not up: the node keeps
holding its shards and serving them, just more slowly. Never a wrong answer,
often the only one.

## `vulkan`

RADV compute shaders (`kernels/expert.comp`), the default GPU path for GFX1013.
Requires a recent Mesa. Verify before declaring it:

```bash
vulkaninfo --summary | head -40    # expect RADV, GFX1013
```

If that command does not show a RADV device, the unit is `cpu-avx2` in the
inventory. Declaring a backend the node cannot reach does not make it faster; it
makes the plan wrong.

## `rocm`

Opt-in, per node, and must be accompanied by a measurement. See
`bringup/ROCM_GFX1013_NOTES.md` for the full picture: Debian ROCm builds do run,
but library coverage for gfx1013 is uneven — some libraries miss the target and
others silently fall back to lower-capability paths — and community work on the
BC-250 found Vulkan to be the only usable GPU compute path in their
configuration. The core's HIP kernel deliberately avoids rocBLAS/Tensile and
hipBLASLt for exactly this reason, and marks ROCm throughput as assumed until
measured.

## `d3d12`

A backend *name* with no kernel behind it. Do not put it in an inventory: the
core will refuse it rather than quietly run something else. Writing a D3D12
compute path is the single change that would make Xbox GPUs useful here.

## Choosing, in practice

1. Leave `backend` blank and let the node pick, if you trust the unit.
2. Otherwise declare the one you have verified with `vulkaninfo`/`rocminfo`.
3. Measure it: `g9-probe --backend X --write-fleet ... --unit-id ...`.
4. If two backends are available on a unit, measure both and keep the faster,
   recording the loser's number in `reasons`.

Mixed backends within a shelf are fine and expected — placement is weighted by
measured throughput, so a faster node simply receives more experts.
