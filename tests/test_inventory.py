"""Inventory parsing: the file everything else is derived from."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deploy"))

from inventory import (Unit, by_shelf, fleet_json,  # noqa: E402
                       load_inventory, parse_reasons, parse_tier_losses,
                       parse_tier_bandwidth_scale, unmeasured)

HEADER = ("unit_id,sku,host,runtime,port,backend,measured_gemv_gflops,"
          "devmode_app,cu_enabled_override,cu_disabled,cpu_cores_disabled,"
          "cpu_ghz_cap,gpu_ghz_cap,memory_budget_bytes,tier_losses,"
          "tier_bandwidth_scale,reasons,mac,shelf,rack,slot,pdu,pdu_outlet")

EXAMPLE = os.path.join(ROOT, "examples", "fleet_inventory.csv")


def write_csv(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                         newline="")
    handle.write(HEADER + "\n")
    for row in rows:
        handle.write(row + "\n")
    handle.close()
    return handle.name


class TestExampleInventory(unittest.TestCase):
    def setUp(self):
        self.units = load_inventory(EXAMPLE)

    def test_example_parses(self):
        self.assertEqual(len(self.units), 10)
        self.assertEqual(self.units[0].unit_id, "ps5-001")

    def test_example_covers_every_hardware_class(self):
        skus = {unit.sku for unit in self.units}
        for expected in ("ps5", "ps5-pro", "xbox-series-x", "xbox-series-s",
                         "bc-250", "amd-4700s", "amd-4800s"):
            self.assertIn(expected, skus)

    def test_comment_lines_are_skipped(self):
        # The example file is mostly a comment block documenting the schema.
        self.assertTrue(all(u.unit_id for u in self.units))

    def test_downbins_survive_the_round_trip(self):
        by_id = {u.unit_id: u for u in self.units}
        entry = by_id["ps5-003"].to_fleet_entry()
        self.assertEqual(entry["downbin"]["cu_disabled"], 4)
        self.assertEqual(entry["downbin"]["tier_losses"], {"gddr6": 2147483648})
        self.assertEqual(len(entry["downbin"]["reasons"]), 2)

    def test_devmode_app_is_carried(self):
        by_id = {u.unit_id: u for u in self.units}
        self.assertTrue(by_id["xss-001"].to_fleet_entry()["devmode_app"])
        self.assertNotIn("devmode_app", by_id["xsx-001"].to_fleet_entry())

    def test_bandwidth_scale_is_carried(self):
        by_id = {u.unit_id: u for u in self.units}
        entry = by_id["kit-4800s-001"].to_fleet_entry()
        self.assertEqual(entry["downbin"]["tier_bandwidth_scale"],
                         {"gddr6": 0.75})
        self.assertEqual(entry["downbin"]["cpu_cores_disabled"], 2)

    def test_cu_override_distinguishes_patched_bc250s(self):
        by_id = {u.unit_id: u for u in self.units}
        self.assertEqual(by_id["bc250-001"].cu_enabled_override, 40)
        self.assertEqual(by_id["bc250-002"].cu_enabled_override, 24)

    def test_shelves_group(self):
        shelves = by_shelf(self.units)
        self.assertEqual(sorted(shelves), ["s01", "s02", "s03"])
        self.assertEqual(len(shelves["s02"]), 2)

    def test_fleet_json_shape(self):
        doc = fleet_json(self.units)
        self.assertEqual(len(doc["fleet"]), 10)
        for entry in doc["fleet"]:
            self.assertIn("unit_id", entry)
            self.assertIn("sku", entry)
            self.assertIn("host", entry)
            self.assertIn("runtime", entry)

    def test_labels_carry_physical_location(self):
        entry = self.units[0].to_fleet_entry()
        self.assertEqual(entry["labels"]["shelf"], "s01")
        self.assertEqual(entry["labels"]["rack"], "r01")


class TestValidation(unittest.TestCase):
    def test_missing_required_column(self):
        path = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
        path.write("unit_id,sku\nps5-001,ps5\n")
        path.close()
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path.name)
        self.assertIn("host", str(ctx.exception))

    def test_unknown_sku_is_rejected(self):
        path = write_csv(["x,playstation-6,10.0.0.1,,,,,,,,,,,,,,,,,,,"])
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path)
        self.assertIn("unknown sku", str(ctx.exception))

    def test_unknown_backend_is_rejected(self):
        path = write_csv(["x,ps5,10.0.0.1,ps5-linux,,cuda,,,,,,,,,,,,,,,,"])
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path)
        self.assertIn("unknown backend", str(ctx.exception))

    def test_duplicate_unit_id_is_rejected(self):
        path = write_csv(["x,ps5,10.0.0.1,,9713,,,,,,,,,,,,,,,,,",
                          "x,ps5,10.0.0.2,,9713,,,,,,,,,,,,,,,,,"])
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path)
        self.assertIn("duplicate unit_id", str(ctx.exception))

    def test_duplicate_address_is_rejected(self):
        # Two units on one address means one of them silently never serves.
        path = write_csv(["a,ps5,10.0.0.1,,9713,,,,,,,,,,,,,,,,,",
                          "b,ps5,10.0.0.1,,9713,,,,,,,,,,,,,,,,,"])
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path)
        self.assertIn("already used", str(ctx.exception))

    def test_same_host_different_ports_is_allowed(self):
        path = write_csv(["a,host-sim,127.0.0.1,host-sim,9713,,,,,,,,,,,,,,,,,",
                          "b,host-sim,127.0.0.1,host-sim,9714,,,,,,,,,,,,,,,,,"])
        self.assertEqual(len(load_inventory(path)), 2)

    def test_non_numeric_field_names_the_line(self):
        path = write_csv(["x,ps5,10.0.0.1,,not-a-port,,,,,,,,,,,,,,,,,"])
        with self.assertRaises(ValueError) as ctx:
            load_inventory(path)
        self.assertIn("port must be an integer", str(ctx.exception))
        self.assertIn(":2", str(ctx.exception))

    def test_empty_inventory_is_rejected(self):
        path = write_csv([])
        with self.assertRaises(ValueError):
            load_inventory(path)

    def test_runtime_defaults_per_sku(self):
        path = write_csv(["a,ps5,10.0.0.1,,,,,,,,,,,,,,,,,,,",
                          "b,xbox-series-s,10.0.0.2,,,,,,,,,,,,,,,,,,,",
                          "c,bc-250,10.0.0.3,,,,,,,,,,,,,,,,,,,"])
        runtimes = [u.runtime for u in load_inventory(path)]
        self.assertEqual(runtimes,
                         ["ps5-linux", "xbox-devmode", "salvage-linux"])


class TestFieldParsers(unittest.TestCase):
    def test_tier_losses(self):
        self.assertEqual(parse_tier_losses("gddr6=2147483648;slow=1024", "x"),
                         (("gddr6", 2147483648), ("slow", 1024)))
        self.assertEqual(parse_tier_losses("", "x"), ())
        self.assertEqual(parse_tier_losses(None, "x"), ())

    def test_tier_losses_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_tier_losses("gddr6", "x")
        with self.assertRaises(ValueError):
            parse_tier_losses("gddr6=lots", "x")

    def test_bandwidth_scale_must_derate(self):
        self.assertEqual(parse_tier_bandwidth_scale("gddr6=0.5", "x"),
                         (("gddr6", 0.5),))
        # 1.0 is a no-op but harmless; above 1.0 would be an overclock, which
        # this field must never express.
        self.assertEqual(parse_tier_bandwidth_scale("gddr6=1.0", "x"),
                         (("gddr6", 1.0),))
        with self.assertRaises(ValueError):
            parse_tier_bandwidth_scale("gddr6=1.4", "x")
        with self.assertRaises(ValueError):
            parse_tier_bandwidth_scale("gddr6=0", "x")

    def test_reasons_split_on_pipe(self):
        self.assertEqual(parse_reasons("dead package|fan replaced"),
                         ("dead package", "fan replaced"))
        self.assertEqual(parse_reasons(None), ())


class TestUnmeasured(unittest.TestCase):
    def make(self, **kwargs):
        base = dict(unit_id="u", sku="ps5", host="h", runtime="ps5-linux")
        base.update(kwargs)
        return Unit(**base)

    def test_pristine_catalogue_unit_needs_no_measurement(self):
        self.assertEqual(unmeasured([self.make()]), [])

    def test_rocm_node_always_needs_one(self):
        unit = self.make(backend="rocm")
        self.assertEqual(unmeasured([unit]), [unit])

    def test_downbinned_node_needs_one(self):
        unit = self.make(cu_disabled=4)
        self.assertEqual(unmeasured([unit]), [unit])

    def test_a_measured_node_is_never_flagged(self):
        unit = self.make(backend="rocm", cu_disabled=4,
                         measured_gemv_gflops=900.0)
        self.assertEqual(unmeasured([unit]), [])


if __name__ == "__main__":
    unittest.main()
