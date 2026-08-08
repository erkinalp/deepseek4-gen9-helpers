"""Power helpers: magic packets on a real socket, and refusal to do harm."""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deploy"))
sys.path.insert(0, os.path.join(ROOT, "power"))

from inventory import Unit  # noqa: E402
from power_cycle import apply_action  # noqa: E402
from wol import magic_packet, select, wake  # noqa: E402

EXAMPLE = os.path.join(ROOT, "examples", "fleet_inventory.csv")
WOL = os.path.join(ROOT, "power", "wol.py")
POWER_CYCLE = os.path.join(ROOT, "power", "power_cycle.py")


def unit(**kwargs):
    base = dict(unit_id="u", sku="bc-250", host="127.0.0.1",
                runtime="salvage-linux")
    base.update(kwargs)
    return Unit(**base)


class TestMagicPacket(unittest.TestCase):
    def test_structure(self):
        packet = magic_packet("00:1f:a7:00:01:01")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("001fa7000101"))
        # The MAC repeats exactly sixteen times after the sync stream.
        self.assertEqual(packet[6:], bytes.fromhex("001fa7000101") * 16)

    def test_separator_variants_agree(self):
        canonical = magic_packet("00:1f:a7:00:01:01")
        for form in ("00-1f-a7-00-01-01", "001fa7000101", "001f.a700.0101"):
            self.assertEqual(magic_packet(form), canonical)

    def test_rejects_bad_macs(self):
        for bad in ("", "00:1f:a7", "00:1f:a7:00:01:01:02", "zz:zz:zz:zz:zz:zz"):
            with self.assertRaises(ValueError):
                magic_packet(bad)


class TestWakeOverASocket(unittest.TestCase):
    """Send a real packet to a real UDP socket rather than mocking sendto."""

    def test_packet_arrives_intact(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        server.settimeout(5.0)
        port = server.getsockname()[1]
        received = []

        def receive():
            received.append(server.recvfrom(1024)[0])

        thread = threading.Thread(target=receive)
        thread.start()
        wake("00:1f:a7:00:01:01", broadcast="127.0.0.1", port=port)
        thread.join(timeout=5.0)
        server.close()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], magic_packet("00:1f:a7:00:01:01"))


class TestSelection(unittest.TestCase):
    def test_filters_compose(self):
        units = [unit(unit_id="a", shelf="s01", rack="r01"),
                 unit(unit_id="b", shelf="s01", rack="r02"),
                 unit(unit_id="c", shelf="s02", rack="r01")]
        self.assertEqual([u.unit_id for u in select(units, shelf="s01")],
                         ["a", "b"])
        self.assertEqual(
            [u.unit_id for u in select(units, shelf="s01", rack="r01")], ["a"])
        self.assertEqual([u.unit_id for u in select(units, unit_id="c")], ["c"])


class TestWolCli(unittest.TestCase):
    def run_wol(self, *args):
        return subprocess.run(
            [sys.executable, WOL, "--inventory", EXAMPLE, "--dry-run", *args],
            capture_output=True, text=True)

    def test_salvage_boards_are_wakeable(self):
        result = self.run_wol("--sku", "bc-250")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would wake bc250-001", result.stdout)

    def test_consoles_are_skipped_with_a_reason(self):
        # A PS5 boots Linux through an exploit chain and an Xbox wakes with its
        # own protocol; pretending a magic packet does either would be a lie
        # that costs someone a trip to the rack.
        result = self.run_wol("--shelf", "s01")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not boot from a magic packet", result.stderr)
        self.assertIn("nothing sent", result.stderr)

    def test_force_overrides_the_skip(self):
        result = self.run_wol("--shelf", "s01", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("would wake ps5-001", result.stdout)

    def test_unmatched_filter_is_an_error(self):
        result = self.run_wol("--shelf", "s99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no units matched", result.stderr)


class TestPowerCycle(unittest.TestCase):
    def test_dry_run_touches_nothing(self):
        apply_action(unit(pdu="pdu-a", pdu_outlet="3"), "cycle", "dry-run", "",
                     settle=0.0)

    def test_command_backend_expands_the_template(self):
        workdir = tempfile.mkdtemp()
        marker = os.path.join(workdir, "actions")
        script = os.path.join(workdir, "fake-pdu")
        with open(script, "w") as handle:
            handle.write('#!/bin/sh\necho "$@" >> "%s"\n' % marker)
        os.chmod(script, 0o755)
        target = unit(unit_id="bc250-001", pdu="pdu-a", pdu_outlet="3",
                      host="10.0.0.31")
        template = f"{script} {{unit}} {{pdu}} {{outlet}} {{action}}"
        apply_action(target, "cycle", "command", template, settle=0.0)
        with open(marker) as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines, ["bc250-001 pdu-a 3 off",
                                 "bc250-001 pdu-a 3 on"])

    def test_cycle_is_off_then_on(self):
        seen = []
        target = unit(pdu="pdu-a", pdu_outlet="1")
        # dry-run prints the steps in order; capture them through stdout.
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            apply_action(target, "cycle", "dry-run", "", settle=0.0)
        seen = [line.split(": ")[1] for line in
                buffer.getvalue().splitlines()]
        self.assertEqual(seen, ["off (pdu=pdu-a outlet=1)",
                                "on (pdu=pdu-a outlet=1)"])

    def test_missing_outlet_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(ValueError):
            apply_action(unit(), "off", "command", "true {pdu}", settle=0.0)

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_action(unit(pdu="p", pdu_outlet="1"), "off", "telepathy", "",
                         settle=0.0)

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, POWER_CYCLE, "--inventory", EXAMPLE, *args],
            capture_output=True, text=True)

    def test_refuses_to_kill_the_whole_fleet(self):
        result = self.run_cli("--action", "off", "--backend", "command",
                              "--cmd", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to power off the entire inventory",
                      result.stderr)

    def test_whole_fleet_dry_run_is_allowed(self):
        result = self.run_cli("--action", "off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run] ps5-001: off", result.stdout)

    def test_narrowed_command_backend_is_allowed(self):
        result = self.run_cli("--shelf", "s03", "--action", "off",
                              "--backend", "command", "--cmd", "true {pdu}")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_command_backend_requires_a_template(self):
        result = self.run_cli("--shelf", "s01", "--action", "off",
                              "--backend", "command")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--cmd", result.stderr)


if __name__ == "__main__":
    unittest.main()
