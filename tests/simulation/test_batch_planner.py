from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.ranking.location import coordinates, haversine_km
from app.simulation.batch_planner import load_pinned_roster, load_roster_csv, make_instance, neutral_instance, solve


def _site(site, tools=(), start=10):
    return {
        "id": site, "label": site, "precision": "point",
        "resources": [{"slot_id": site + "-1", "resource_id": site + "-dialysis",
                       "start_minute": start, "slots": 1, "service": "dialysis", "tools": list(tools)}],
    }


def _patient(pid, priority="routine", tools=(), arrival=0, deadline=20):
    return {"id": pid, "priority": priority, "service": "dialysis", "required_tools": list(tools),
            "arrival_minute": arrival, "deadline_minute": deadline}


def _instance(patients, times):
    return {"geography": {"location_basis": "synthetic"}, "scenario": {"horizon_minutes": 20},
            "facilities": [_site("A", ["monitored"]), _site("B")], "patients": patients,
            "travel_seconds": times}


class BatchPlannerTests(unittest.TestCase):
    def test_sharing_one_monitored_slot_can_make_greedy_lose_an_assignment(self):
        instance = _instance(
            [_patient("first"), _patient("urgent", "highest", ["monitored"], arrival=1)],
            {"first": {"A": 60, "B": 120}, "urgent": {"A": 120, "B": 60}},
        )
        policies = solve(instance)["policies"]
        greedy, exact = policies["nearest_first"], policies["exact_optimum"]
        self.assertEqual([(r["patient"], r["facility"]) for r in greedy["assignments"]], [("first", "A")])
        self.assertEqual([(r["patient"], r["facility"]) for r in exact["assignments"]],
                         [("first", "B"), ("urgent", "A")])
        self.assertEqual(exact["metrics"]["assigned"], 2)

    def test_exact_tradeoff_uses_priority_before_travel_and_nearest_comparator_is_unchanged(self):
        instance = _instance([_patient("first"), _patient("urgent", "highest", arrival=1)],
                             {"first": {"A": 0}, "urgent": {"A": 300}})
        policies = solve(instance)["policies"]
        self.assertEqual(policies["nearest_first"]["assignments"][0]["patient"], "first")
        self.assertEqual(policies["exact_optimum"]["assignments"][0]["patient"], "urgent")
        self.assertEqual(policies["exact_optimum"]["metrics"]["total_travel_seconds"], 300)

    def test_exact_minimizes_travel_when_served_priorities_tie(self):
        instance = _instance([_patient("first"), _patient("second")],
                             {"first": {"A": 1, "B": 4}, "second": {"A": 2, "B": 60}})
        policies = solve(instance)["policies"]
        self.assertEqual(policies["nearest_first"]["metrics"]["total_travel_seconds"], 61)
        self.assertEqual(policies["exact_optimum"]["metrics"]["total_travel_seconds"], 6)

    def test_exact_appointment_boundaries_and_missing_route(self):
        patient = _patient("p", arrival=8, deadline=10)
        for travel, reason in [(120, None), (121, "outside_appointment_window"),
                               (None, "modelled_travel_unknown")]:
            with self.subTest(travel=travel):
                plan = solve(_instance([patient], {"p": {"A": travel}}))
                for output in plan["policies"].values():
                    if reason is None:
                        self.assertEqual(output["assignments"][0]["slot_start_minute"], 10)
                        self.assertEqual(output["assignments"][0]["travel_seconds"], 120)
                    else:
                        self.assertEqual(output["unserved"], [{"patient": "p", "reason": reason}])

    def test_area_context_never_gets_a_route_or_slot(self):
        instance = _instance([_patient("p")], {"p": {"C": 0}})
        instance["facilities"].append({"id": "C", "label": "Test area", "precision": "area", "resources": []})
        output = solve(instance)
        self.assertFalse(output["policies"]["exact_optimum"]["assignments"])
        instance["facilities"][-1]["resources"] = [_site("C")["resources"][0]]
        with self.assertRaises(ValueError):
            solve(instance)

    def test_duplicate_physical_resource_start_cannot_inflate_capacity(self):
        instance = _instance([_patient("p")], {"p": {"A": 0}})
        instance["facilities"][0]["resources"].append(
            {**instance["facilities"][0]["resources"][0], "slot_id": "A-same-bucket"}
        )
        with self.assertRaises(ValueError):
            solve(instance)

    def test_csv_import_pins_input_bytes_and_preserves_point_scope(self):
        raw = b"facility_id,facility_name,latitude,longitude\ntest,Invented point,1,2\n"
        geo = {
            "location_basis": "public_source", "name": "Test-only public-shape roster",
            "selection": "Test control", "source": "Test source", "verification": "Fixture point",
            "attribution": [{"text": "Test", "url": "https://example.org/test"}],
            "roster_sha256": sha256(raw).hexdigest(),
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "roster.csv"
            path.write_bytes(raw)
            roster = load_roster_csv(path, geo)
            self.assertEqual(roster["facilities"][0]["label"], "Invented point")
            self.assertIn("entrance unknown", roster["facilities"][0]["point_scope"])
            self.assertEqual(make_instance(roster)["geography"]["roster_sha256"], geo["roster_sha256"])
            path.write_bytes(raw + b"tampered\n")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_roster_csv(path, geo)

    def test_pinned_twelve_site_roster_keeps_precision_and_rotates_staffing(self):
        rows = [
            {"planning_id": f"C{i+1:02}", "label": f"Invented site {i+1}",
             "location": {"precision": "mapped_point" if i < 8 else "campus_anchor",
                          "latitude": i * 0.01, "longitude": i * 0.01}}
            for i in range(12)
        ]
        raw = json.dumps({"schema_version": "storm-roster-v1", "facilities": rows}).encode()
        geo = {"location_basis": "public_source", "name": "Fixture for point parsing",
               "selection": "Test control", "source": "Test source", "verification": "Fixture only",
               "attribution": [{"text": "Test", "url": "https://example.org/test"}],
               "roster_sha256": sha256(raw).hexdigest()}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "pinned.json"
            path.write_bytes(raw)
            roster = load_pinned_roster(path, geo)
        instance = make_instance(roster)
        self.assertEqual(instance["geography"]["planning_point_sites"], 12)
        self.assertEqual(Counter(f["precision"] for f in instance["facilities"]),
                         {"mapped_point": 8, "campus_anchor": 4})
        self.assertEqual(sum(len(f["resources"]) for f in instance["facilities"]), 144)
        self.assertTrue(all(f["resources"] for f in instance["facilities"]))

    def test_neutral_export_replays_objective_without_source_points_or_labels(self):
        instance = make_instance()
        neutral = neutral_instance(instance)
        self.assertTrue(all("latitude" not in row and "longitude" not in row
                            for row in neutral["facilities"] + neutral["patients"]))
        self.assertTrue(all(row["label"].startswith("Neutral site ") for row in neutral["facilities"]))
        original, exported = (solve(d)["policies"] for d in (instance, neutral))
        for policy in original:
            for key in ("assigned", "unmet", "by_priority", "total_travel_seconds"):
                self.assertEqual(original[policy]["metrics"][key], exported[policy]["metrics"][key])

    def test_120_shift_deterministic_conserves_stock_and_time(self):
        instance = make_instance()
        original = deepcopy(instance)
        plan = solve(instance)
        self.assertEqual(instance, original)
        instance["facilities"].reverse()
        instance["patients"].reverse()
        for row in instance["facilities"]:
            row["resources"].reverse()
        self.assertEqual(solve(instance), plan)

        self.assertEqual(plan["geography"]["location_basis"], "synthetic")
        self.assertEqual(len(plan["patients"]), 120)
        self.assertGreaterEqual(plan["policies"]["exact_optimum"]["metrics"]["assigned"], 100)
        self.assertGreater(plan["policies"]["exact_optimum"]["metrics"]["assigned"],
                           plan["policies"]["nearest_first"]["metrics"]["assigned"])
        patients = {p["id"]: p for p in plan["patients"]}
        facilities = {f["id"]: f for f in plan["facilities"]}
        slots = {s["slot_id"]: (f["id"], s) for f in plan["facilities"] for s in f["resources"]}
        for output in plan["policies"].values():
            used = Counter(row["slot_id"] for row in output["assignments"])
            all_ids = [row["patient"] for row in output["assignments"] + output["unserved"]]
            self.assertCountEqual(all_ids, patients.keys())
            for row in output["assignments"]:
                facility, slot = slots[row["slot_id"]]
                p = patients[row["patient"]]
                self.assertEqual(facility, row["facility"])
                self.assertEqual(p["service"], slot["service"])
                self.assertTrue(set(p["required_tools"]).issubset(slot["tools"]))
                self.assertLessEqual(used[row["slot_id"]], slot["slots"])
                seconds = ceil(haversine_km(coordinates(p), coordinates(facilities[facility])) * 120)
                self.assertEqual(row["travel_seconds"], seconds)
                self.assertLessEqual(p["arrival_minute"] * 60 + seconds, slot["start_minute"] * 60)
                self.assertLessEqual(slot["start_minute"], p["deadline_minute"])
