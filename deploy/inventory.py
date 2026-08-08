#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read and validate the fleet inventory CSV.

The inventory is the single source of truth: the gen9-cluster fleet JSON,
Wake-on-LAN lists and PDU power maps are all derived from it. Stdlib only, so it
runs on a stock PS5 Linux userland as well as on a deployment host.

One row is one *unit*. Consoles arrive from eBay in unknown condition, so the
columns that matter most are the ones describing how this particular unit
differs from a catalogue one: fused-off CUs, a dead memory package, a clock cap
after a fan swap, a dev-mode sandbox budget. Those become the ``downbin`` block
in the fleet JSON, and the planner reads only the effective numbers that result.

See ``examples/fleet_inventory.csv`` for the column contract.
"""
from __future__ import annotations

import csv
import dataclasses
from typing import Dict, Iterable, List, Optional, Tuple

REQUIRED = ("unit_id", "sku", "host")

#: Columns that go straight into the ``downbin`` block of the fleet JSON.
DOWNBIN_INT = ("cu_disabled", "cpu_cores_disabled")
DOWNBIN_FLOAT = ("cpu_ghz_cap", "gpu_ghz_cap")

#: SKUs gen9-cluster knows. Mirrored from ram-coffers ``hardware.SKUS``; a
#: mismatch is caught by ``check_fleet.py`` against the real table rather than
#: being silently accepted here.
KNOWN_SKUS = ("ps5", "ps5-slim", "ps5-pro", "xbox-series-x", "xbox-series-s",
              "amd-4700s", "amd-4800s", "bc-250", "host-sim")

KNOWN_RUNTIMES = ("ps5-linux", "ps5-hen", "xbox-devmode", "xbox-gdk",
                  "salvage-linux", "host-sim")

KNOWN_BACKENDS = ("cpu-avx2", "vulkan", "rocm", "d3d12")

DEFAULT_PORT = 9713

#: Default runtime per SKU, used when the row leaves ``runtime`` blank.
DEFAULT_RUNTIME = {"ps5": "ps5-linux", "ps5-slim": "ps5-linux",
                   "ps5-pro": "ps5-linux", "xbox-series-x": "xbox-devmode",
                   "xbox-series-s": "xbox-devmode",
                   "amd-4700s": "salvage-linux", "amd-4800s": "salvage-linux",
                   "bc-250": "salvage-linux", "host-sim": "host-sim"}


@dataclasses.dataclass(frozen=True)
class Unit:
    """One console, kit or blade, exactly as the operator described it."""

    unit_id: str
    sku: str
    host: str
    runtime: str
    port: int = DEFAULT_PORT
    backend: Optional[str] = None
    measured_gemv_gflops: Optional[float] = None
    devmode_app: bool = False
    cu_enabled_override: Optional[int] = None
    # Per-unit damage.
    cu_disabled: int = 0
    cpu_cores_disabled: int = 0
    cpu_ghz_cap: Optional[float] = None
    gpu_ghz_cap: Optional[float] = None
    memory_budget_bytes: Optional[int] = None
    tier_losses: Tuple[Tuple[str, int], ...] = ()
    tier_bandwidth_scale: Tuple[Tuple[str, float], ...] = ()
    reasons: Tuple[str, ...] = ()
    # Physical location, for power and hands-on work.
    mac: Optional[str] = None
    shelf: Optional[str] = None
    rack: Optional[str] = None
    slot: Optional[str] = None
    pdu: Optional[str] = None
    pdu_outlet: Optional[str] = None

    @property
    def is_pristine(self) -> bool:
        return not (self.cu_disabled or self.cpu_cores_disabled
                    or self.cpu_ghz_cap or self.gpu_ghz_cap
                    or self.memory_budget_bytes or self.tier_losses
                    or self.tier_bandwidth_scale)

    def to_fleet_entry(self) -> Dict:
        """Render one entry of a gen9-cluster inventory JSON ``fleet`` list."""
        entry: Dict[str, object] = {"unit_id": self.unit_id, "sku": self.sku,
                                    "runtime": self.runtime,
                                    "host": self.host, "port": self.port}
        if self.backend:
            entry["backend"] = self.backend
        if self.measured_gemv_gflops is not None:
            entry["measured_gemv_gflops"] = self.measured_gemv_gflops
        if self.devmode_app:
            entry["devmode_app"] = True
        if self.cu_enabled_override is not None:
            entry["cu_enabled_override"] = self.cu_enabled_override
        downbin: Dict[str, object] = {}
        if self.cu_disabled:
            downbin["cu_disabled"] = self.cu_disabled
        if self.cpu_cores_disabled:
            downbin["cpu_cores_disabled"] = self.cpu_cores_disabled
        if self.cpu_ghz_cap is not None:
            downbin["cpu_ghz_cap"] = self.cpu_ghz_cap
        if self.gpu_ghz_cap is not None:
            downbin["gpu_ghz_cap"] = self.gpu_ghz_cap
        if self.memory_budget_bytes is not None:
            downbin["memory_budget_bytes"] = self.memory_budget_bytes
        if self.tier_losses:
            downbin["tier_losses"] = dict(self.tier_losses)
        if self.tier_bandwidth_scale:
            downbin["tier_bandwidth_scale"] = dict(self.tier_bandwidth_scale)
        if self.reasons:
            downbin["reasons"] = list(self.reasons)
        if downbin:
            entry["downbin"] = downbin
        labels = {k: v for k, v in (("shelf", self.shelf), ("rack", self.rack),
                                    ("slot", self.slot)) if v}
        if labels:
            entry["labels"] = labels
        return entry


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(row: Dict[str, str], column: str, where: str) -> Optional[int]:
    raw = _clean(row.get(column))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{where}: {column} must be an integer "
                         f"({raw!r})") from exc


def _float(row: Dict[str, str], column: str, where: str) -> Optional[float]:
    raw = _clean(row.get(column))
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{where}: {column} must be a number "
                         f"({raw!r})") from exc


def _bool(row: Dict[str, str], column: str, where: str) -> bool:
    raw = _clean(row.get(column))
    if raw is None:
        return False
    lowered = raw.lower()
    if lowered in ("1", "true", "yes", "y"):
        return True
    if lowered in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"{where}: {column} must be a boolean ({raw!r})")


def _parse_pairs(raw: Optional[str], column: str, where: str) \
        -> List[Tuple[str, str]]:
    raw = _clean(raw)
    if raw is None:
        return []
    pairs = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"{where}: {column} entry {chunk!r} is not "
                             f"tier=value")
        tier, _, value = chunk.partition("=")
        pairs.append((tier.strip(), value.strip()))
    return pairs


def parse_tier_losses(raw: Optional[str], where: str) \
        -> Tuple[Tuple[str, int], ...]:
    """Parse ``"gddr6=2147483648;slow=1073741824"`` into pairs.

    Bytes rather than gigabytes because a half-populated memory package is not
    a round number of anything, and rounding a capacity *up* is how a plan
    becomes an out-of-memory kill three hours in.
    """
    losses = []
    for tier, value in _parse_pairs(raw, "tier_losses", where):
        try:
            losses.append((tier, int(value)))
        except ValueError as exc:
            raise ValueError(f"{where}: tier_losses {tier}={value!r} needs an "
                             f"integer byte count") from exc
    return tuple(losses)


def parse_tier_bandwidth_scale(raw: Optional[str], where: str) \
        -> Tuple[Tuple[str, float], ...]:
    """Parse ``"gddr6=0.75"`` — a tier running below its nominal bandwidth.

    A depopulated memory channel costs bandwidth without costing capacity, so
    it cannot be expressed as a ``tier_losses`` entry.
    """
    scales = []
    for tier, value in _parse_pairs(raw, "tier_bandwidth_scale", where):
        try:
            scale = float(value)
        except ValueError as exc:
            raise ValueError(f"{where}: tier_bandwidth_scale {tier}={value!r} "
                             f"needs a number") from exc
        if not 0.0 < scale <= 1.0:
            raise ValueError(f"{where}: tier_bandwidth_scale {tier}={scale} "
                             f"must be in (0, 1]; this field derates a tier, "
                             f"it does not overclock one")
        scales.append((tier, scale))
    return tuple(scales)


def parse_reasons(raw: Optional[str]) -> Tuple[str, ...]:
    """Split the ``|``-separated audit reasons for a unit's downbin."""
    raw = _clean(raw)
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split("|") if part.strip())


def _row_to_unit(row: Dict[str, str], where: str) -> Unit:
    unit_id = _clean(row.get("unit_id"))
    sku = _clean(row.get("sku"))
    host = _clean(row.get("host"))
    if not unit_id:
        raise ValueError(f"{where}: unit_id is required")
    if not sku:
        raise ValueError(f"{where}: sku is required")
    if not host:
        raise ValueError(f"{where}: host is required")
    if sku not in KNOWN_SKUS:
        raise ValueError(f"{where}: unknown sku {sku!r}; expected one of "
                         f"{', '.join(KNOWN_SKUS)}")
    runtime = _clean(row.get("runtime")) or DEFAULT_RUNTIME[sku]
    if runtime not in KNOWN_RUNTIMES:
        raise ValueError(f"{where}: unknown runtime {runtime!r}; expected one "
                         f"of {', '.join(KNOWN_RUNTIMES)}")
    backend = _clean(row.get("backend"))
    if backend is not None and backend not in KNOWN_BACKENDS:
        raise ValueError(f"{where}: unknown backend {backend!r}; expected one "
                         f"of {', '.join(KNOWN_BACKENDS)}")
    port = _int(row, "port", where)
    return Unit(
        unit_id=unit_id, sku=sku, host=host, runtime=runtime,
        port=DEFAULT_PORT if port is None else port,
        backend=backend,
        measured_gemv_gflops=_float(row, "measured_gemv_gflops", where),
        devmode_app=_bool(row, "devmode_app", where),
        cu_enabled_override=_int(row, "cu_enabled_override", where),
        cu_disabled=_int(row, "cu_disabled", where) or 0,
        cpu_cores_disabled=_int(row, "cpu_cores_disabled", where) or 0,
        cpu_ghz_cap=_float(row, "cpu_ghz_cap", where),
        gpu_ghz_cap=_float(row, "gpu_ghz_cap", where),
        memory_budget_bytes=_int(row, "memory_budget_bytes", where),
        tier_losses=parse_tier_losses(row.get("tier_losses"), where),
        tier_bandwidth_scale=parse_tier_bandwidth_scale(
            row.get("tier_bandwidth_scale"), where),
        reasons=parse_reasons(row.get("reasons")),
        mac=_clean(row.get("mac")), shelf=_clean(row.get("shelf")),
        rack=_clean(row.get("rack")), slot=_clean(row.get("slot")),
        pdu=_clean(row.get("pdu")), pdu_outlet=_clean(row.get("pdu_outlet")))


def load_inventory(path: str) -> List[Unit]:
    """Parse ``path`` into ``Unit`` rows, skipping ``#`` comment lines.

    Raises ``ValueError`` on a missing required column, an unparsable field, an
    unknown sku/runtime/backend, or a duplicate ``unit_id`` or ``host:port``.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        rows = [line for line in fh if not line.lstrip().startswith("#")]
    reader = csv.DictReader(rows)
    if reader.fieldnames is None:
        raise ValueError(f"{path}: no header row")
    missing = [c for c in REQUIRED if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"{path}: missing required column(s): "
                         f"{', '.join(missing)}")
    units: List[Unit] = []
    seen_ids: Dict[str, int] = {}
    seen_addrs: Dict[Tuple[str, int], int] = {}
    for lineno, row in enumerate(reader, start=2):
        where = f"{path}:{lineno}"
        unit = _row_to_unit(row, where)
        if unit.unit_id in seen_ids:
            raise ValueError(f"{where}: duplicate unit_id {unit.unit_id!r} "
                             f"(also line {seen_ids[unit.unit_id]})")
        seen_ids[unit.unit_id] = lineno
        addr = (unit.host, unit.port)
        if addr in seen_addrs:
            raise ValueError(f"{where}: {unit.host}:{unit.port} is already "
                             f"used on line {seen_addrs[addr]}")
        seen_addrs[addr] = lineno
        units.append(unit)
    if not units:
        raise ValueError(f"{path}: no unit rows")
    return units


def fleet_json(units: Iterable[Unit]) -> Dict:
    """Render the inventory as a gen9-cluster fleet document."""
    return {"fleet": [unit.to_fleet_entry() for unit in units]}


def by_shelf(units: Iterable[Unit]) -> Dict[str, List[Unit]]:
    """Group units by their ``shelf`` label, with ``""`` for unassigned ones."""
    shelves: Dict[str, List[Unit]] = {}
    for unit in units:
        shelves.setdefault(unit.shelf or "", []).append(unit)
    return shelves


def unmeasured(units: Iterable[Unit]) -> List[Unit]:
    """Units the planner will have to guess at.

    Every ROCm node belongs here until someone runs ``g9-probe`` on it: gfx1013
    library coverage is uneven enough that a datasheet figure means very little.
    """
    return [u for u in units
            if u.measured_gemv_gflops is None
            and (u.backend == "rocm" or not u.is_pristine)]
