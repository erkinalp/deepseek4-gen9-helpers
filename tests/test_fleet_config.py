"""Config generation, including the round trip through the real core.

The contract this repository has to keep is narrow and testable: whatever
``gen_fleet_config.py`` writes must be loadable by ``gen9_cluster`` unchanged.
Those tests skip when no core checkout is reachable, so this suite still runs
standalone — but they are the ones that matter, so point ``$GEN9_CLUSTER`` at a
checkout when you can.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(ROOT, "deploy")
sys.path.insert(0, DEPLOY)

from inventory import fleet_json, load_inventory  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "fleet_inventory.csv")
GEN_FLEET = os.path.join(DEPLOY, "gen_fleet_config.py")
CHECK_FLEET = os.path.join(DEPLOY, "check_fleet.py")


def core_path():
    """A ram-coffers/gen9-cluster directory, or None."""
    explicit = os.environ.get("GEN9_CLUSTER")
    candidates = [explicit] if explicit else []
    candidates.append(os.path.join(os.path.dirname(ROOT), "ram-coffers",
                                   "gen9-cluster"))
    for candidate in candidates:
        if candidate and os.path.isdir(os.path.join(candidate,
                                                    "gen9_cluster")):
            return candidate
    return None


CORE = core_path()


class TestGenFleetConfig(unittest.TestCase):
    def run_gen(self, *args):
        out = os.path.join(tempfile.mkdtemp(), "fleet.json")
        result = subprocess.run(
            [sys.executable, GEN_FLEET, "--inventory", EXAMPLE, "-o", out,
             *args],
            capture_output=True, text=True)
        return result, out

    def read(self, path):
        with open(path) as handle:
            return json.load(handle)

    def test_writes_a_fleet_document(self):
        result, out = self.run_gen()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read(out)["fleet"]), 10)

    def test_shelf_filter(self):
        result, out = self.run_gen("--shelf", "s02")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([e["unit_id"] for e in self.read(out)["fleet"]],
                         ["xsx-001", "xss-001"])

    def test_sku_filter(self):
        result, out = self.run_gen("--sku", "bc-250")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.read(out)["fleet"]), 2)

    def test_empty_filter_fails_loudly(self):
        result, _ = self.run_gen("--shelf", "s99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no units on shelf", result.stderr)

    def test_unmeasured_nodes_are_warned_about(self):
        result, _ = self.run_gen()
        # Every downbinned unit without a measurement should be named, so the
        # operator knows which numbers in the plan are guesses.
        self.assertIn("ps5-002", result.stderr)
        self.assertIn("g9-probe", result.stderr)

    def test_measured_nodes_are_not_warned_about(self):
        result, _ = self.run_gen("--sku", "bc-250")
        self.assertNotIn("bc250-001", result.stderr)

    def test_plan_without_core_explains_itself(self):
        out = os.path.join(tempfile.mkdtemp(), "fleet.json")
        plan = os.path.join(tempfile.mkdtemp(), "deployment.json")
        env = dict(os.environ)
        env.pop("GEN9_CLUSTER", None)
        result = subprocess.run(
            [sys.executable, GEN_FLEET, "--inventory", EXAMPLE, "-o", out,
             "--plan", plan, "--gen9", "/nonexistent"],
            capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot import gen9_cluster", result.stderr)
        # The fleet JSON is this repo's own output and must still be there.
        self.assertTrue(os.path.exists(out))


@unittest.skipIf(CORE is None, "no gen9-cluster checkout ($GEN9_CLUSTER)")
class TestCoreAcceptsOurOutput(unittest.TestCase):
    """The whole point of the boundary: the core must take our JSON as-is."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, CORE)

    def write_fleet(self):
        path = os.path.join(tempfile.mkdtemp(), "fleet.json")
        with open(path, "w") as handle:
            json.dump(fleet_json(load_inventory(EXAMPLE)), handle, indent=2)
        return path

    def test_load_fleet_accepts_it_unchanged(self):
        from pathlib import Path
        from gen9_cluster.inventory import load_fleet
        fleet = load_fleet(Path(self.write_fleet()))
        self.assertEqual(len(fleet), 10)

    def test_every_field_survives(self):
        from pathlib import Path
        from gen9_cluster.inventory import load_fleet
        fleet = {e.unit.unit_id: e for e in load_fleet(Path(self.write_fleet()))}

        ps5_003 = fleet["ps5-003"].unit
        self.assertEqual(ps5_003.downbin.cu_disabled, 4)
        self.assertEqual(ps5_003.downbin.tier_losses["gddr6"], 2147483648)

        kit = fleet["kit-4800s-001"].unit
        self.assertEqual(kit.downbin.tier_bandwidth_scale["gddr6"], 0.75)
        self.assertEqual(kit.downbin.cpu_cores_disabled, 2)

        self.assertTrue(fleet["xss-001"].unit.devmode_app)
        self.assertEqual(fleet["bc250-001"].unit.cu_enabled_override, 40)
        self.assertEqual(fleet["bc250-001"].unit.measured_gemv_gflops, 940.0)
        self.assertEqual(fleet["ps5-002"].unit.downbin.gpu_ghz_cap, 1.8)
        self.assertEqual(fleet["ps5-001"].address.port, 9713)

    def test_downbins_actually_reduce_the_unit(self):
        from pathlib import Path
        from gen9_cluster.inventory import load_fleet
        fleet = {e.unit.unit_id: e for e in load_fleet(Path(self.write_fleet()))}
        healthy = fleet["ps5-001"].unit.effective()
        damaged = fleet["ps5-003"].unit.effective()
        self.assertLess(damaged.weight_bytes, healthy.weight_bytes)

    def test_devmode_app_is_the_smaller_budget(self):
        from pathlib import Path
        from gen9_cluster.inventory import load_fleet
        fleet = {e.unit.unit_id: e for e in load_fleet(Path(self.write_fleet()))}
        # A Series S on the app partition must end up smaller than a Series X
        # on the game partition, even though the S has less memory anyway.
        self.assertLess(fleet["xss-001"].unit.effective().weight_bytes,
                        fleet["xsx-001"].unit.effective().weight_bytes)

    def test_planner_places_the_example_fleet(self):
        from pathlib import Path
        from gen9_cluster.inventory import load_fleet, units
        from gen9_cluster.model import profile_for
        from gen9_cluster.planner import plan_split
        fleet = load_fleet(Path(self.write_fleet()))
        plan = plan_split(profile_for("deepseek-tiny"), units(fleet),
                          context_tokens=512, shelf_size=4)
        self.assertGreater(len(plan.units), 0)
        self.assertGreater(plan.tokens_per_second, 0.0)

    def write_ps5_inventory(self, count):
        """A CSV of ``count`` nominal PS5s — enough to hold V4.1-Flash."""
        path = os.path.join(tempfile.mkdtemp(), "ps5s.csv")
        with open(path, "w") as handle:
            handle.write("unit_id,sku,host,runtime\n")
            for i in range(count):
                handle.write(f"ps5-{i:03d},ps5,10.0.0.{10 + i},ps5-linux\n")
        return path

    def test_v41_plan_uses_the_no_ssd_flag(self):
        """V4.1's Engram tables are the first thing a deployment has a reason
        to forbid from NVMe: --no-ssd must reach plan_split, or the generated
        config quietly describes drives the operator said not to use."""
        inventory = self.write_ps5_inventory(60)
        with_ssd = os.path.join(tempfile.mkdtemp(), "deployment.json")
        without = os.path.join(tempfile.mkdtemp(), "deployment.json")
        fleet_out = os.path.join(tempfile.mkdtemp(), "fleet.json")

        for extra, expect in (([], "engram-1@ssd"),
                              (["--no-ssd"], "engram-1-rows")):
            target = without if extra else with_ssd
            result = subprocess.run(
                [sys.executable, GEN_FLEET, "--inventory", inventory,
                 "-o", fleet_out, "--plan", target, "--gen9", CORE,
                 "--model", "deepseek-v4.1-flash", *extra],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with open(target) as handle:
                nodes = json.load(handle)["nodes"]
            pieces = {piece for node in nodes.values()
                      for piece in node["io_pieces"]}
            self.assertIn(expect, pieces)
            if extra:
                self.assertFalse(any(p.endswith("@ssd") for p in pieces))
                held = sum(node.get("engram_ram_bytes", 0)
                           for node in nodes.values())
                self.assertGreater(held, 0)


@unittest.skipIf(CORE is None, "no gen9-cluster checkout ($GEN9_CLUSTER)")
class TestCheckFleet(unittest.TestCase):
    def run_check(self, *args, inventory=EXAMPLE):
        return subprocess.run(
            [sys.executable, CHECK_FLEET, "--inventory", inventory,
             "--gen9", CORE, *args],
            capture_output=True, text=True)

    def test_example_fleet_validates(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0,
                         result.stdout + "\n" + result.stderr)

    def test_require_measured_fails_on_guessed_nodes(self):
        result = self.run_check("--require-measured")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no measured_gemv_gflops", result.stderr)

    def test_summary_counts_the_fleet(self):
        result = self.run_check()
        self.assertIn("10 unit(s)", result.stdout)
        self.assertIn("bc-250", result.stdout)

    def test_bad_backend_for_the_runtime_is_reported(self):
        # A Dev Mode Xbox cannot reach Vulkan. The core's tables know that; the
        # point of --gen9 is that we do not have to duplicate the knowledge.
        path = os.path.join(tempfile.mkdtemp(), "bad.csv")
        with open(path, "w") as handle:
            handle.write("unit_id,sku,host,runtime,backend\n")
            handle.write("xsx-9,xbox-series-x,10.0.0.90,xbox-devmode,vulkan\n")
        result = self.run_check(inventory=path)
        self.assertIn("xsx-9", result.stderr)


if __name__ == "__main__":
    unittest.main()
