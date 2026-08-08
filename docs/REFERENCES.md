# References

Sources behind the hardware claims in this repository. Where a figure is quoted
it is attributed; where nothing is attributed, the claim is our own reasoning
and should be treated as untested.

## PS5 under Linux

* ps5-linux / ps5-linux-loader — <https://github.com/ps5-linux/ps5-linux-loader>
  Supported models and firmware list, and the M.2 support matrix, are taken
  from its README.
* "Mesa & AMDGPU Linux Driver See Patches For The Sony PS5 GPU", Phoronix —
  <https://www.phoronix.com/news/Mesa-AMDGPU-PS5-Patches>
  Upstreaming of GFX1013 support: the ADDRLIB addition in Mesa, the Cyan
  Skillfish PCI id in amdgpu, and the DCN 2.01 display fix.
* LLVM AMDGPU processor table (gfx1013) —
  <https://llvm.org/docs/AMDGPUUsage.html#processors>

## BC-250 and the salvage boards

* AMD BC250 community documentation — <https://elektricm.github.io/amd-bc250-docs/>
  Board specifications: Zen 2 6c/12t, 24 of 40 CUs exposed by factory firmware,
  16 GB GDDR6 unified at ~448 GB/s on a 256-bit bus, Linux-only GPU support,
  BIOS memory-split guidance.
* akandr/bc250 — <https://github.com/akandr/bc250>
  A worked MoE-inference deployment on this exact silicon, and the source of
  several claims used here: ROCm userspace not shipping GFX1013 support and
  Vulkan being the only usable GPU compute path in that configuration; the GTT
  cap and `ttm.pages_limit` kernel bottlenecks; the 40-CU unlock and its 1.32×
  median generation speed-up; the roofline measurement (~357 GB/s streaming
  bandwidth, ~3901 GFLOP/s FP32, ridge point ~10.9 FLOP/byte) establishing that
  decode is bandwidth-bound; power figures (~101 W at 24 CU vs ~116 W at 40 CU).
  All of those are that author's single-board measurements, not vendor figures.
* "AMD RADV Driver Adds Support For The PS5-Derived BC-250", Phoronix —
  <https://www.phoronix.com/news/AMD-RADV-PS5-BC-250>

## ROCm on gfx1013

* ROCm documentation and its supported-GPU list, for what is and is not a
  tuned target — <https://rocm.docs.amd.com/>
* The specific failure mode — libraries whose build scripts assume a higher gfx
  capability tier and therefore either omit the target or fall back to reduced
  paths — was described to us by the project owner and matches the community
  reports above.

## Xbox Series X/S Developer Mode

* Microsoft's Xbox developer documentation for retail Developer Mode, including
  the memory available to a title versus an app —
  <https://learn.microsoft.com/en-us/windows/uwp/xbox-apps/>
  The ~5 GB game / ~1 GB app split the planner budgets against comes from there.

## The core

* `ram-coffers` — <https://github.com/erkinalp/ram-coffers>
  The portable inference core. `gen9-cluster/docs/G9XC.md` is the normative
  protocol; `gen9-cluster/docs/GEN9_SPLITTING.md` the placement arithmetic;
  `gen9-cluster/docs/REFERENCES.md` the model-side citations (DeepSeek, MLA,
  FP8, and the consumer-hardware inference work this design borrows from).
* `kimi-k3-ps3-helpers` — the previous generation of this split, and the
  structural model for this repository.
