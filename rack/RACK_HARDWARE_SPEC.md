# Rack, power, cooling and network specification

> **An engineering specification to review and measure against, not a validated
> build.** No rack described here has been assembled by the authors. Every
> electrical figure must be checked against the boards in front of you before
> anything is energised. Where a number is a *planning estimate* it says so; do
> not size a busbar or a fuse from an estimate.
>
> **This describes transplanting bare boards into rack chassis on a common 12 V
> DC bus.** Stock consumer cases and stock console PSUs are not used. That work
> involves mains-side equipment and dense DC distribution; if you are not
> comfortable specifying and fusing a 12 V bus, do not do it.

## Why not stock cases and stock PSUs

Stock consoles are shelf-mounted, not rack-mounted: no rails, no ears, no
front-to-back airflow, one AC cord and one C13 outlet per node. At fleet
density that is unworkable in three separate ways — a rack of consoles wastes
most of its volume on plastic, needs a PDU outlet and an AC cord per node, and
has each unit's cooling fighting its neighbour's exhaust.

Stripped down, the picture is much better, because all three hardware families
already terminate at **a single 12 V input**:

| Board | Input | Evidence |
|---|---|---|
| PS5 | **+12 V only**, via a pair of spade terminals from the internal ADP-400DR (372 W, 31 A, single rail, no standby rail) | [TechPowerUp teardown](https://www.techpowerup.com/review/playstation-5-power-supply-adp-400dr/); board-level 12 V injection is standard repair practice ([repair.wiki](https://www.repair.wiki/w/PS5_Standby_Boot_Sequence_%26_Consumption_Analysis)) |
| BC-250 | **Direct 12 V**, PCIe 8-pin (J1000), plus 12 V/PGOOD on J2000/J2001; auto-power-on jumper AUTO_PWRON1 pins 1-2; five-fan header *designed for rack chassis*; passive front-to-back fin stack designed for rack airflow | [BC250 pinouts](https://elektricm.github.io/amd-bc250-docs/hardware/pinouts/), [cooling](https://elektricm.github.io/amd-bc250-docs/hardware/cooling/) |
| Xbox Series X/S | internal Delta supply, board-side rails **not verified by us** | **measure before you wire anything** |

So the design is: **one rectifier shelf per rack producing 12 V, a busbar, and
individually fused drops to bare boards on trays.** One AC feed, one conversion
stage, and cooling that the chassis controls instead of the console's plastic.
The BC-250 was designed for exactly this and needs no persuasion; the consoles
have to be talked into it.

## The 12 V bus

**Source.** Either front-end rectifiers into a busbar (telecom/OCP-style
shelves are the obvious fit: hot-swap modules, N+1, remote sense, and a real
current monitor per module), or, at small scale, quality ATX/server PSUs used
as pure 12 V bricks. Whichever you pick:

* Size the bus to **measured** node draw plus a real margin, not to TDP and not
  to the table below. Then re-measure once the fleet runs the actual kernel:
  this workload saturates memory continuously and does not resemble any load
  the boards were binned against.
* **N+1 at least.** A rectifier failure that drops half a rack costs every
  shard on it, and re-loading a shelf is the expensive part of any recovery.
* **Remote sense, or short thick runs.** At 12 V, node current is 10–20 A and
  cable drop is not a rounding error. 16 AWG is the BC-250 documentation's
  minimum for its 8-pin alone; a tray drop should be heavier.
* Keep AC on one side of the rack, DC on the other, and never run them in the
  same bundle.

**Per-node protection is not optional.** Every drop gets its own fuse or
breaker, sized to that board, in an accessible position. A shorted board on an
unfused bus takes the whole rack down and possibly starts a fire. This is the
single most important sentence in this document.

**Per-node switching and metering.** A latching relay or an electronic-fuse
module per drop gives you what a switched PDU would have given you: remote
power-off for a hung node, and per-node current. `power/power_cycle.py`'s
`command` backend is designed to drive exactly this — point it at whatever
controls your bus, and record the channel in the inventory's `pdu` /
`pdu_outlet` fields (they name a bus controller and a channel here, not a mains
outlet). Per-node current is also the cheapest early warning that a board has
started thermal-throttling.

**Inrush.** Bringing a rack up simultaneously is an inrush event on both the AC
and DC sides. Stagger it: sequence the drops, or use `--settle` between groups.
The BC-250's AUTO_PWRON1 jumper means it starts the moment 12 V appears, so
sequencing must happen at the bus, not on the board.

### Console boards specifically

* **PS5.** The board takes 12 V at the PSU spade terminals. Feed those from the
  bus with appropriately sized lugs, keep the console's own DC-DC stages
  intact, and **verify polarity and standby behaviour on a bench supply
  before** connecting a board to the rack. The ADP-400DR has no standby rail,
  so the board's standby domain is derived on-board from the same 12 V — do not
  assume you need to synthesise anything extra, and do not assume you don't.
* **Xbox Series X/S.** We have not verified the board-side connector or rails.
  Do not wire an Xbox board to a bus on the strength of this document. Measure
  the stock supply's outputs under load, identify every rail and any
  power-good/enable signalling, and only then decide whether a 12 V-only feed
  is even possible. If it is not, that board stays in its stock enclosure and
  costs you a PDU outlet — which is an acceptable outcome, since Dev Mode nodes
  are CPU-only and low-value anyway (`docs/BACKEND_MATRIX.md`).
* **Never modify a stock console PSU.** Removing one and feeding the board from
  a properly fused bus is a defensible engineering decision. Rewiring,
  paralleling or bypassing the mains-side switching supply inside a sealed
  consumer device is not.

## Power: planning figures

Planning estimates for sizing an experiment, to be replaced with measured
per-node draw before final bus and fuse sizing.

| Board | Planning estimate, sustained | Basis |
|---|---|---|
| PS5 / Slim | ~200 W DC | ~225 W at the wall measured on a stock console; ~205 W DC after PSU efficiency ([TechPowerUp](https://www.techpowerup.com/review/playstation-5-power-supply-adp-400dr/)) |
| PS5 Pro | ~250 W DC | scaled from the above; unverified |
| Xbox Series X | ~200 W | stock console at the wall |
| Xbox Series S | ~90 W | stock console at the wall |
| BC-250 | 101 W @ 24 CU, 116 W @ 40 CU measured under LLM load; 220 W board TDP, 235 W observed peak | [community docs](https://elektricm.github.io/amd-bc250-docs/hardware/specifications/), [akandr/bc250](https://github.com/akandr/bc250) |
| 4700S / 4800S | ~100 W | CPU-only, GPU fused off |

Note how far the BC-250's *measured inference* draw sits below its TDP: sizing
that node from the 220 W nameplate would over-build the bus by roughly 2×.
Sizing it from 116 W and then unlocking the CUs would under-build it. Measure,
then size, then re-measure.

## Chassis and mounting

* **Trays, not shelves.** A 3U or 4U chassis with boards mounted on standoffs
  to a tray, cabled to the bus at the rear, and pulled forward for service.
  Sleds that come out without unracking the chassis pay for themselves the
  first week.
* **Board orientation is set by the heatsink.** The BC-250's fin stack runs
  front-to-back and is designed for pressurised rack airflow — mount it so the
  fins align with the chassis airflow, and it needs no fan of its own beyond
  the wall. The consoles' heatsinks were designed around a specific blower and
  duct; once the plastic is gone you own that duct. Either keep the console's
  blower and feed it from the bus, or build a shroud that reproduces the
  airflow path across the vapour chamber. Bare board plus a random fan is how
  you get a thermally throttled node that measures fine for ten minutes.
* **Fan wall.** High-static-pressure fans at the front, sealed to the tray so
  air goes through the heatsinks and not around them. The BC-250's five-fan
  2.54 mm header exists for chassis fan control; the boards cannot provide
  tachometer feedback to a plain ATX PSU, so fan control belongs to the chassis
  or to a small controller, not to the board.
* **Backplate VRAM.** GDDR6 packages on the reverse side need airflow too — the
  BC-250 documentation recommends 2 mm thermal pads onto the backplate and
  active air over it, and reports artefacts when VRAM runs hot. This workload
  is memory-bandwidth-bound, so the memory is under continuous load even when
  the APU is not.
* **Mechanical.** Bare boards on standoffs, torqued, with strain relief on
  every 12 V lug and no cable resting on a heatsink. Blank off unused U so the
  fan wall pressurises rather than short-circuits.
* **Label every board physically with its `unit_id`.** Out of their cases they
  are indistinguishable, and "the plan says `ps5-003` is slow" has to translate
  to a specific tray instantly.

## Cooling

* **Cap clocks rather than allowing throttling.** A *declared* cap
  (`gpu_ghz_cap` / `cpu_ghz_cap` in the inventory) is planned around; a thermal
  throttle just makes one shelf mysteriously slow. On GFX1013 the clock
  governor is a userspace daemon, so this is a configuration decision. The
  BC-250 documentation's own recommendation is instructive: cap at 1500 MHz,
  keep the 40-CU unlock, hold ~83 °C indefinitely — more sustained throughput
  than an uncapped board that throttles.
* **Re-paste everything.** These are second-hand boards, years old, badly
  stored. The transplant is the moment to do it, and it will never be cheaper.
* **Filter the intake and clean on a schedule.** Continuous operation in an
  unfiltered room is how a fleet degrades into a fleet of clock-capped units.
* **Thermal soak before you trust a number.** See `BURN_IN_CHECKLIST.md` §4;
  measurement before soak is a number the board cannot sustain.

## Network

* One **flat, isolated L2 segment** for compute. G9XC has no authentication and
  no encryption (`docs/G9XC_CONTRACT.md`), so reachability *is* the security
  model. No route to anything else.
* **1 GbE is the floor and usually the ceiling** on console boards, which is
  why the planner works so hard to keep expert fan-out shelf-local. Salvage
  boards may have faster NICs or usable PCIe; if they do, they are your shelf
  hosts.
* **No stateful firewall, no NAT, no per-connection shaping** in the path.
  Connections are long-lived and multiplexed; anything reaping idle connections
  becomes intermittent, hard-to-diagnose shelf failures.
* **Jumbo frames** where the switch supports them: `LOAD_SHARD` bodies are
  large and dominate restart cost.
* **DHCP reservations** for every board, so an inventory address keeps meaning
  the same tray.
* Management, bus control and compute on **separate VLANs**.

## Safety

* Per-node fusing on the DC side. Again. It is the thing people skip.
* Torque the busbar hardware and re-check it after the first thermal cycles;
  a loose 20 A DC joint is a heater.
* No exposed mains anywhere inside the rack volume that hands reach during
  service. Keep the rectifier shelf's AC side enclosed and interlocked.
* Bare boards are ESD-sensitive and have sharp edges and hot surfaces at head
  height. Strap, gloves, and an aisle wide enough to work in.
* Smoke and heat detection, and a plan for a board that fails hard. Second-hand
  consumer silicon run continuously at its thermal limit will eventually
  produce a failure that is not merely a dead node.
