# Burn-in and qualification checklist

Run this on every unit before it is allowed into a plan. It is written for
second-hand hardware of unknown history, which is what this fleet is made of:
the assumption throughout is that a unit is broken in some way nobody has
noticed yet, and the job is to find out how *before* it becomes a mysteriously
slow shelf at three in the morning.

Nothing below has been executed on physical hardware by the authors of this
repository. Treat it as a checklist to run, not a report.

## 0. Before you buy

- [ ] **PS5: firmware version.** Only the versions listed in
      `bringup/PS5_LINUX_NOTES.md` can boot Linux, and firmware cannot be rolled
      back. A console above that range is not a node. This is the single most
      common way to waste money on this project.
- [ ] **PS5: prefer an M.2-supported firmware.** Without it there is no internal
      SSD, and the NVMe coffer tier has nowhere to live.
- [ ] **Xbox: Developer Mode activation** is per-console and needs a developer
      account. Confirm you can activate before committing to a quantity.
- [ ] **BC-250: BIOS state.** Community-patched BIOS and the CU unlock change
      what the board is worth by ~1.3×. Ask what it ships with.

## 1. Intake

- [ ] Assign a `unit_id` and mark it on the board's tray, physically,
      permanently. Out of their cases these boards are indistinguishable.
- [ ] Add the row to the inventory CSV *before* powering it on, including
      `mac`, `shelf`, `rack`, `slot`, `pdu`, `pdu_outlet` (the last two name the
      12 V bus controller and channel — see `RACK_HARDWARE_SPEC.md`).
- [ ] Record the board revision / model number in `reasons`.
- [ ] Strip it, clean it, re-paste it. Everything here is years old and none of
      it was stored well, and after the transplant it will never be cheaper.
- [ ] `python3 deploy/check_fleet.py --inventory <csv> --gen9 <core>` — the row
      must parse and validate against the core's tables before you go further.

## 1a. Transplant and first power-on

Everything in this section happens on a **bench supply**, one board at a time,
before the board is anywhere near the rack's bus.

- [ ] Identify the board's 12 V input and confirm polarity. PS5: the spade
      terminals the ADP-400DR fed. BC-250: J1000 PCIe 8-pin. Xbox: **not
      characterised by us — measure the stock supply's rails under load before
      assuming anything**, and if a 12 V-only feed turns out to be impossible,
      leave that board in its stock enclosure.
- [ ] Bring it up on a current-limited bench supply and watch the standby draw
      before pressing anything. On a PS5 board, published repair figures put a
      healthy first stage around 321 mA and standby around 7–10 mA; a board
      drawing 0 mA, or tens of mA where it should be single digits, has a
      short and does not go in the rack.
- [ ] Confirm it POSTs and boots on the bench, on that supply, with the
      intended cooling attached.
- [ ] Only then fit it to a tray, route and strain-relieve the 12 V lugs, and
      land it on its **own fused, switchable** bus drop.
- [ ] Verify the fuse rating against this board's measured draw, not against
      its TDP and not against the planning table.
- [ ] BC-250: set AUTO_PWRON1 to pins 1-2 if the bus sequences power, and
      confirm the board comes up when its drop is energised.
- [ ] Confirm chassis fan control works and that airflow goes *through* the
      heatsink fins rather than around them.

## 2. Memory

The memory subsystem is what this workload saturates, and a marginal GDDR6
package is the failure that most looks like "the model is just bad".

- [ ] Run a memory test long enough to cover thermal drift — hours, not minutes.
- [ ] Record any capacity loss as `tier_losses` (bytes, not gigabytes) with a
      reason.
- [ ] Record a depopulated or degraded channel as `tier_bandwidth_scale`; it
      costs bandwidth without costing capacity, and the two are not the same
      thing to the planner.
- [ ] **BC-250 only:** raise the amdgpu GTT cap and `ttm.pages_limit` to cover
      the full 16 GiB, then *verify* with a large allocation. A board that looks
      too small is usually a board with a kernel limit in the way.

## 3. Backend qualification

- [ ] `vulkaninfo --summary` — RADV on GFX1013, or the unit is `cpu-avx2`.
- [ ] `rocminfo` only if you intend to declare ROCm; read
      `bringup/ROCM_GFX1013_NOTES.md` first.
- [ ] Set `backend` in the inventory to what you verified, not what you hoped.
- [ ] Never declare `d3d12`; no kernel exists behind it.

## 4. Thermal soak

This is the step people skip and regret.

- [ ] Run the expert kernel continuously for **at least 4 hours** in the
      chassis, in the rack, with the fan wall at its production setting and
      neighbouring U populated or blanked — not on a bench in open air. A board
      that passes on the bench and fails in the tray is the normal outcome.
- [ ] Log temperature and clock throughout. A unit that starts fast and ends
      slow is a unit that needs a declared clock cap, not a unit that is fine.
- [ ] Log per-drop current from the bus. Compare against the shelf's
      neighbours; an outlier in either direction is a story.
- [ ] Re-torque the bus and tray hardware after the first thermal cycles. A
      loose 20 A DC joint is a heater.
- [ ] If it throttles: set `cpu_ghz_cap` / `gpu_ghz_cap` in the inventory to a
      level it can actually hold, with a reason. A declared cap is planned
      around; a throttle is a surprise.

## 5. Measurement

- [ ] `python3 -m gen9_cluster probe --backend <backend> --write-fleet <fleet.json> --unit-id <id>`
- [ ] Run it **after** the thermal soak, not before. A cold measurement is a
      number the unit cannot sustain.
- [ ] If two backends are viable, measure both; keep the faster and record the
      other in `reasons`.
- [ ] Compare against the shelf's other units of the same SKU. A unit 20 % off
      its siblings has something wrong with it that the earlier steps missed.

## 6. Network and power

- [ ] DHCP reservation in place; the unit answers on its inventory address.
- [ ] `python3 deploy/check_fleet.py --inventory <csv> --connect` sees the node
      worker listening.
- [ ] Salvage boards: WoL enabled in BIOS and via `ethtool`, and
      `python3 power/wol.py --unit-id <id>` actually wakes it.
- [ ] Bus channel mapping verified *by switching it off and watching the right
      board go dark*. A channel map that has never been tested is wrong, and
      the mistake is only discovered while trying to recover something else.
- [ ] `python3 power/power_cycle.py --unit-id <id> --action cycle` reaches the
      right channel through whatever drives your bus.

## 7. Fleet integration

- [ ] Regenerate the fleet JSON and re-plan; confirm the unit appears where you
      expect and that the plan's warnings for it are ones you understand.
- [ ] `deploy/check_fleet.py --require-measured` passes for the production
      inventory.
- [ ] Restart the unit's worker (`deploy/start_shelf.sh --action restart`) and
      confirm it re-loads its shards and rejoins.
- [ ] Only then let it hold anything that matters. Prefer putting shelf *hosts*
      on salvage boards, which reboot unattended; consoles make better expert
      holders because losing one costs a re-load rather than a KV cache.

## Re-qualification

Re-run sections 2, 4 and 5 whenever a unit is repaired, re-pasted, moved to a
different shelf position, or has its firmware/BIOS changed — and update the
inventory. The plan is only as honest as its worst-maintained row.
