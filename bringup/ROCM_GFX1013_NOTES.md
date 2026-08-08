# ROCm on GFX1013: opt-in, per node, and always measured

The short version: **Vulkan/RADV is the default GPU path for every GFX1013 unit
in this fleet.** ROCm is supported as an opt-in per-node backend, and any node
declaring it must also declare a measured throughput.

## Why it is not the default

Debian's ROCm packaging does build and run on this hardware, so "ROCm doesn't
work on gfx1013" is too strong. What is true is that coverage is uneven:

* Some ROCm libraries have no gfx1013 support at all.
* Some work at a *reduced capability level* relative to the target's actual
  generation, because their build scripts assume a higher gfx tier and select
  code paths on that assumption.

The tuned-kernel layer is the part that suffers — rocBLAS/Tensile and hipBLASLt
carry per-architecture tuned kernels and gfx1013 is not among the architectures
they are tuned for. Independent community work on the closely related BC-250
board reached the stronger conclusion that ROCm's userspace libraries do not
ship GFX1013 support at all, and that Vulkan was the only usable GPU compute
path in that configuration ([akandr/bc250](https://github.com/akandr/bc250)).

Both can be true at once, on different distributions and different ROCm
versions. That is exactly the situation where a fleet planner must not guess.

## What the stack does about it

1. **`kernels/expert_hip.hip` depends on no tuned library.** It is a hand-written
   HIP GEMV that builds with `hipcc --offload-arch=gfx1013` and calls into
   nothing from rocBLAS, Tensile or hipBLASLt. The unreliable layer is precisely
   the layer it does not use.
2. **`ComputeBackend.ROCM.throughput_is_assumed` is true.** A ROCm node's
   throughput is never derived from CU counts and clocks; the planner marks it
   as estimated and says so in the plan.
3. **The inventory wants a measurement.** `deploy/gen_fleet_config.py` warns for
   every ROCm node without `measured_gemv_gflops`, and
   `deploy/check_fleet.py --require-measured` turns that warning into an error
   for a production plan.

## Qualifying a ROCm node

```bash
rocminfo | grep -i gfx            # expect gfx1013
hipcc --offload-arch=gfx1013 -O3 -o /tmp/t kernels/expert_hip.hip
python3 -m gen9_cluster probe --backend rocm \
    --write-fleet fleet.json --unit-id bc250-001
```

Then compare against the same board on Vulkan:

```bash
python3 -m gen9_cluster probe --backend vulkan \
    --write-fleet fleet.json --unit-id bc250-001
```

Keep whichever is faster *on that unit*, and write the loser's number in the
`reasons` column so the next person does not repeat the experiment. Mixed
backends within a shelf are fine — the planner weights placement by measured
throughput, so a faster node simply gets more experts.

## What would change this recommendation

A gfx1013-aware ROCm build — vendor or community — with working tuned libraries
would make ROCm the better default, since the HIP kernel could then hand the
GEMV to a tuned implementation instead of doing it by hand. If you have one,
say so in the node's `reasons` and let the measurement decide.
