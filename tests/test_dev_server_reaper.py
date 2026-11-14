import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dev_server_reaper as r  # noqa: E402

HZ = 100
UPTIME = 1_000_000.0  # seconds
MAX = 4 * 3600


def started_ago(seconds):
    return int((UPTIME - seconds) * HZ)


class FindVictims(unittest.TestCase):
    def test_old_next_chain_is_killed_with_wrappers(self):
        procs = {
            258: (1, started_ago(900000), "hermes gateway"),
            10: (258, started_ago(90000), "npm exec next start --port 3199"),
            11: (10, started_ago(90000), "sh -c next start --port 3199"),
            12: (11, started_ago(90000), "next-server (v16.3.3)"),
        }
        self.assertEqual(r.find_victims(procs, UPTIME, HZ, MAX, 999), {10, 11, 12})

    def test_young_next_server_is_kept(self):
        procs = {12: (258, started_ago(600), "next-server (v16.3.3)"), 258: (1, 0, "hermes gateway")}
        self.assertEqual(r.find_victims(procs, UPTIME, HZ, MAX, 999), set())

    def test_never_touches_unrelated_or_parent(self):
        procs = {
            258: (1, started_ago(900000), "hermes gateway"),
            12: (258, started_ago(90000), "next-server (v16.3.3)"),
            20: (258, started_ago(900000), "node /tmp/wmm-credentials/scripts/wmm-local-mcp.mjs"),
        }
        self.assertEqual(r.find_victims(procs, UPTIME, HZ, MAX, 999), {12})

    def test_dev_server_with_port_matches(self):
        procs = {5: (258, started_ago(90000), "node node_modules/next/dist/bin/next dev --port 45983")}
        self.assertEqual(r.find_victims(procs, UPTIME, HZ, MAX, 999), {5})

    def test_self_is_never_a_victim(self):
        procs = {7: (1, started_ago(90000), "python dev_server_reaper.py next-server")}
        self.assertEqual(r.find_victims(procs, UPTIME, HZ, MAX, 7), set())


if __name__ == "__main__":
    unittest.main()
