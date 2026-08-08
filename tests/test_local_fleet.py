"""End-to-end on loopback: generate a config, serve it, talk to it.

These are the tests that would catch a real break in the boundary — the ones
where this repository's output is handed to the core's node worker and the core's
coordinator, over real sockets. They skip without a core checkout.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deploy"))

from inventory import fleet_json, load_inventory  # noqa: E402

SIM = os.path.join(ROOT, "examples", "local_sim_inventory.csv")
CHECK_FLEET = os.path.join(ROOT, "deploy", "check_fleet.py")


def core_path():
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


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipIf(CORE is None, "no gen9-cluster checkout ($GEN9_CLUSTER)")
class TestSimulatedFleet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, CORE)
        cls.workdir = tempfile.mkdtemp()
        cls.units = load_inventory(SIM)
        # Bind to ports the OS says are free, not the ones the example file
        # suggests: a developer machine may already be using them.
        cls.ports = {u.unit_id: free_port() for u in cls.units}
        doc = fleet_json(cls.units)
        for entry in doc["fleet"]:
            entry["port"] = cls.ports[entry["unit_id"]]
        cls.fleet_path = os.path.join(cls.workdir, "fleet.json")
        with open(cls.fleet_path, "w") as handle:
            json.dump(doc, handle, indent=2)

    def plan(self):
        from pathlib import Path
        from gen9_cluster.inventory import deployment_config, load_fleet, units
        from gen9_cluster.model import profile_for
        from gen9_cluster.planner import plan_split
        fleet = load_fleet(Path(self.fleet_path))
        plan = plan_split(profile_for("deepseek-tiny"), units(fleet),
                          context_tokens=256, shelf_size=4)
        return plan, fleet, deployment_config(plan, fleet)

    def test_sim_inventory_plans(self):
        plan, _, config = self.plan()
        self.assertGreater(len(config["nodes"]), 0)
        self.assertEqual(config["model"], plan.model)

    def test_config_addresses_match_the_inventory(self):
        _, _, config = self.plan()
        for unit_id, node in config["nodes"].items():
            self.assertEqual(node["host"], "127.0.0.1")
            self.assertEqual(node["port"], self.ports[unit_id])

    def test_node_workers_serve_and_answer(self):
        """Start real workers on the generated config and ping them."""
        from gen9_cluster.protocol import Frame, MsgType
        from gen9_cluster.transport import NodeConnection

        _, _, config = self.plan()
        config_path = os.path.join(self.workdir, "deployment.json")
        with open(config_path, "w") as handle:
            json.dump(config, handle, indent=2)

        unit_ids = sorted(config["nodes"])[:2]
        processes = []
        try:
            for unit_id in unit_ids:
                processes.append(subprocess.Popen(
                    [sys.executable, "-m", "gen9_cluster", "serve",
                     config_path, unit_id, "--host", "127.0.0.1"],
                    cwd=CORE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True))

            deadline = time.time() + 20.0
            for unit_id in unit_ids:
                port = self.ports[unit_id]
                while time.time() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", port), 0.5):
                            break
                    except OSError:
                        time.sleep(0.2)
                else:
                    self.fail(f"{unit_id} never listened on {port}")

            for unit_id in unit_ids:
                with NodeConnection(unit_id, "127.0.0.1",
                                    self.ports[unit_id]) as conn:
                    pong = conn.request(Frame(MsgType.PING, 0), timeout=5.0)
                    self.assertIs(pong.msg_type, MsgType.PONG)
                    # STATUS is what `g9 health` reads, and it must name the
                    # unit the config placed here, not whatever the worker
                    # process happened to default to.
                    status = conn.request(Frame(MsgType.STATUS, 0), timeout=5.0)
                    text = status.payload.decode()
                    self.assertIn(unit_id, text)
                    self.assertIn("backend=", text)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    def test_check_fleet_connect_reports_a_dead_fleet(self):
        """Nothing is listening, and that must be an error, not a shrug."""
        result = subprocess.run(
            [sys.executable, CHECK_FLEET, "--inventory", SIM, "--connect",
             "--timeout", "0.5"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not listening", result.stderr)


if __name__ == "__main__":
    unittest.main()
