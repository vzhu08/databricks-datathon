import json
import subprocess
import sys
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

from app.simulation.replay import POLICIES, replay, run_policy
from app.simulation.scenario import SCENARIOS, make_scenario


class StormReplayTests(unittest.TestCase):
    def setUp(self):
        self.storm = make_scenario("storm", 17)

    def result(self, name, policy, cap=10):
        return run_policy(make_scenario(name, 17), policy, cap)

    def test_checked_fixture_matches_cli_byte_for_byte(self):
        root = Path(__file__).resolve().parents[2]
        actual = subprocess.check_output([sys.executable, "-m", "app.simulation"], cwd=root)
        self.assertEqual(actual, (root / "contracts/fixtures/storm_replay.json").read_bytes())
        data = json.loads(actual)
        self.assertTrue(data["synthetic"])
        self.assertEqual(6, len(data["campuses"]))
        self.assertGreater(len({q["origin_id"] for q in data["requests"]}), 1)

    def test_routine_detour_preserves_one_shared_slot(self):
        near = self.result("storm", "nearest_first")["events"]
        aware = self.result("storm", "scarcity_aware")["events"]
        self.assertEqual([e["campus_id"] for e in near[:2]], ["A", None])
        self.assertEqual([e["campus_id"] for e in aware[:2]], ["B", "A"])
        self.assertEqual(aware[0]["preserved_profiles"], ["dialysis/monitored"])
        self.assertEqual(4, aware[0]["extra_travel_minutes"])
        self.assertEqual(0, aware[1]["extra_travel_minutes"])
        self.assertEqual(aware[1]["resource_before"], {"used": 0, "free": 1})

    def test_first_decision_cannot_see_future_arrivals_or_downtime(self):
        for policy in POLICIES:
            first = self.result("storm", policy)["events"][0]
            for name in ("no_surge", "overload", "resource_loss"):
                self.assertEqual(first, self.result(name, policy)["events"][0])
        ns = self.result("no_surge", "scarcity_aware")
        self.assertEqual(ns["metrics"]["assigned"], 1)
        self.assertEqual(ns["metrics"]["extra_travel_minutes"], 4)

    def test_no_diversion_for_highest_urgency_or_when_detour_too_long(self):
        if_urgent = replace(self.storm.requests[0], urgency="highest")
        s = replace(self.storm, requests=(if_urgent,))
        self.assertEqual("A", run_policy(s, "scarcity_aware", 10)["events"][0]["campus_id"])
        for cap, expected in ((0, "A"), (3, "A"), (4, "B"), (15, "B")):
            event = self.result("storm", "scarcity_aware", cap)["events"][0]
            self.assertEqual(expected, event["campus_id"])

    def test_same_tick_requests_use_identical_priority_queues(self):
        routine, urgent = self.storm.requests[:2]
        simultaneous = replace(self.storm, requests=(routine, replace(urgent, arrival_minute=0)))
        for policy in POLICIES:
            events = run_policy(simultaneous, policy, 0)["events"]
            self.assertEqual(["r02", "r01"], [e["request_id"] for e in events])
            self.assertEqual(["A", "B"], [e["campus_id"] for e in events])
        fifo = run_policy(simultaneous, "arrival_fifo", 0)["events"]
        self.assertEqual(["A", None], [e["campus_id"] for e in fifo])

    def test_no_spare_or_unknown_specialist_options(self):
        for policy in POLICIES:
            unknown = self.result("missing_capacity", policy)
            self.assertEqual("unknown_or_stale_capacity", unknown["events"][1]["reason"])
            self.assertIsNone(unknown["final_free_slots"]["A-dialysis"])
            for e in unknown["events"]:
                self.assertNotIn(e["resource_id"], ("E-dialysis", "E-trauma", "A-dialysis"))
        reverse = self.result("reversal", "scarcity_aware")["events"]
        self.assertEqual(["A", "B"], [e["campus_id"] for e in reverse[:2]])

    def test_capacity_shock_applies_at_announced_time(self):
        scarce = self.result("resource_loss", "scarcity_aware")
        self.assertEqual(1, scarce["capacity_events"][0]["lost_free_slots"])
        self.assertEqual({"used": 0, "free": 0}, scarce["capacity_events"][0]["resource_after"])
        self.assertEqual("unassigned", scarce["events"][1]["status"])
        # An offline unbooked slot cannot be removed twice or cancel a prior booking.
        near = self.result("resource_loss", "nearest_first")
        self.assertEqual(0, near["capacity_events"][0]["lost_free_slots"])
        self.assertEqual({"used": 1, "free": 0}, near["capacity_events"][0]["resource_after"])

    def test_multiple_seeds_and_modes_never_overbook_or_break_constraints(self):
        for mode in SCENARIOS:
            for seed in range(8):
                scenario = make_scenario(mode, seed)
                requests = {q.id: q for q in scenario.requests}
                pools = {p.id: p for c in scenario.campuses for p in c.resources}
                for policy in POLICIES:
                    result = run_policy(scenario, policy, 5)
                    events = result["events"]
                    self.assertCountEqual([e["request_id"] for e in events], requests.keys())
                    visits = Counter()
                    for e in events:
                        if e["status"] != "assigned":
                            self.assertTrue(e["reason"])
                            continue
                        q, p = requests[e["request_id"]], pools[e["resource_id"]]
                        self.assertEqual((p.service, p.capacity_status), (q.service, "known"))
                        self.assertTrue(set(q.required_tools) <= set(p.tools))
                        self.assertLessEqual(e["travel_minutes"], q.max_travel_minutes)
                        self.assertLessEqual(e["extra_travel_minutes"], 0 if q.urgency == "highest" else 5)
                        self.assertGreaterEqual(e["resource_after"]["free"], 0)
                        visits[p.id] += 1
                        self.assertLessEqual(visits[p.id], p.slots)
                    self.assertEqual(0, result["metrics"]["capacity_violations"])
                    self.assertEqual(sum(visits.values()), result["metrics"]["within_window"])

    def test_overload_exposes_unserved_requests(self):
        results = replay(make_scenario("overload", 17))["policies"]
        for result in results.values():
            self.assertGreater(result["metrics"]["unassigned"], 0)
            self.assertEqual(result["metrics"]["unassigned"],
                             sum(result["metrics"]["unassigned_reasons"].values()))

    def test_seed_controls_arrival_stream_and_invalid_inputs_fail(self):
        self.assertNotEqual(self.storm.requests, make_scenario("storm", 25).requests)
        self.assertEqual(self.storm, make_scenario("storm", 17))
        with self.assertRaises(ValueError):
            run_policy(self.storm, "nearest_first", -1)
        with self.assertRaises(ValueError):
            run_policy(self.storm, "unrecognized", 10)
        with self.assertRaises(ValueError):
            run_policy(replace(self.storm, requests=tuple(reversed(self.storm.requests))),
                       "nearest_first", 10)


if __name__ == "__main__":
    unittest.main()
