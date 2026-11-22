"""Planner regressions use invented coordinates and an injected observer."""

from copy import deepcopy
import unittest
from unittest.mock import Mock

from app.simulation.batch_planner import make_instance, solve
from app.simulation.traffic_plan import PUNE_ROSTER_SHA256, derive_pickups, run_traffic_plan


def _shape_fixture():
    """Test-only stand-in for the 12-site publication shape, with no real rows."""
    return solve(make_instance({
        "geography": {
            "name": "Invented fixture only", "source": "Synthetic test control",
            "selection": "Synthetic test", "verification": "Fixture points",
            "location_basis": "public_source", "roster_sha256": PUNE_ROSTER_SHA256,
            "attribution": [{"text": "Fixture", "url": "https://example.org/test"}],
        },
        "facilities": [{
            "id": f"C{i+1:02}", "label": f"Invented {i+1}",
            "latitude": (i % 4) * 0.01, "longitude": i * 0.01,
            "precision": "mapped_point" if i < 8 else "campus_anchor",
        } for i in range(12)],
    }))


class TrafficPlannerTests(unittest.TestCase):
    def setUp(self):
        self.baseline = _shape_fixture()
        self.pickups = derive_pickups(self.baseline["facilities"])

    def observation(self, matrix, attempted=24, actual=24):
        return {
            "travel_seconds": matrix, "attempted_pairs": attempted, "actual_attempts": actual,
            "observed_at": "2026-11-22T16:00:00Z", "completed_at": "2026-11-22T16:01:00Z",
            "source": "Fake ordinary-car provider", "attribution": "Test attribution",
        }

    def run_fake(self, observer):
        return run_traffic_plan(self.baseline, pickups=self.pickups, observe=observer)

    def test_single_callback_receives_only_points_and_preserves_simulated_inputs(self):
        original = deepcopy(self.baseline)
        rd = self.baseline["facilities"]
        matrix = {point["id"]: {site["id"]: 300.25 for site in rd} for point in self.pickups}
        observer = Mock(return_value=self.observation(matrix, actual=30))
        plan = self.run_fake(observer)
        observer.assert_called_once()
        self.assertEqual(set(observer.call_args.kwargs), {"pickups", "destinations"})
        for points in observer.call_args.kwargs.values():
            self.assertTrue(all(set(row) == {"id", "latitude", "longitude"} for row in points))
        self.assertEqual(self.baseline, original)
        self.assertEqual(plan["facilities"], original["facilities"])
        self.assertEqual(sum(p["patient_count"] for p in plan["traffic"]["pickups"]), 120)
        self.assertEqual((plan["traffic"]["eligible_pairs"], plan["traffic"]["usable_pairs"],
                          plan["traffic"]["actual_attempts"]), (24, 24, 30))
        self.assertEqual(plan["traffic"]["observed_at"], "2026-11-22T16:00:00Z")
        self.assertNotIn("travel_seconds", plan["traffic"])
        self.assertNotIn("travel_seconds", plan)
        for old, new in zip(original["patients"], plan["patients"]):
            self.assertEqual({k: v for k, v in old.items() if k not in ("longitude", "latitude")},
                             {k: v for k, v in new.items() if k not in ("longitude", "latitude", "pickup_id")})
            point = next(row for row in self.pickups if row["id"] == new["pickup_id"])
            self.assertEqual((new["latitude"], new["longitude"]), (point["latitude"], point["longitude"]))
        for policy in plan["policies"].values():
            self.assertTrue(policy["assignments"])
            self.assertTrue(all(row["travel_seconds"] == 300.25 for row in policy["assignments"]))
            self.assertEqual(policy["metrics"]["total_travel_seconds"], len(policy["assignments"]) * 300.25)

    def test_partial_routes_are_shared_and_missing_cells_stay_unavailable(self):
        a, b = (p["id"] for p in self.pickups)
        matrix = {a: {"C01": 0, "C02": None, "C03": True}, b: {"C01": 250.5, "C04": -1}}
        plan = self.run_fake(Mock(return_value=self.observation(matrix, attempted=4, actual=5)))
        self.assertEqual((plan["traffic"]["usable_pairs"], plan["traffic"]["unavailable_pairs"]), (2, 22))
        patients = {p["id"]: p for p in plan["patients"]}
        for policy in plan["policies"].values():
            self.assertTrue(policy["assignments"])
            for row in policy["assignments"]:
                group = patients[row["patient"]]["pickup_id"]
                self.assertEqual(row["facility"], "C01")
                self.assertEqual(row["travel_seconds"], matrix[group]["C01"])

    def test_empty_and_failed_callback_never_backfill_synthetic_edges(self):
        for observer, attempts in [(Mock(return_value=self.observation({}, attempted=0, actual=0)), 0),
                                   (Mock(side_effect=TimeoutError("private provider detail")), None)]:
            with self.subTest(attempts=attempts):
                output = self.run_fake(observer)
                self.assertEqual(output["traffic"]["actual_attempts"], attempts)
                self.assertEqual(output["traffic"]["unavailable_pairs"], 24)
                for policy in output["policies"].values():
                    self.assertEqual(policy["metrics"]["assigned"], 0)
                    self.assertEqual(policy["metrics"]["unserved_reasons"], {"traffic_travel_unavailable": 120})

    def test_unpinned_plan_or_changed_pickup_stops_before_observation(self):
        observer = Mock()
        self.baseline["geography"]["roster_sha256"] = "not-cleared"
        with self.assertRaises(ValueError):
            self.run_fake(observer)
        self.baseline["geography"]["roster_sha256"] = PUNE_ROSTER_SHA256
        changed = ({**self.pickups[0], "longitude": 12}, self.pickups[1])
        with self.assertRaises(ValueError):
            run_traffic_plan(self.baseline, pickups=changed, observe=observer)
        observer.assert_not_called()

    def test_exact_fractional_second_appointment_boundary(self):
        case = make_instance()
        facility = case["facilities"][0]
        slot = next(row for row in facility["resources"] if row["service"] == "mri")
        patient = {**case["patients"][0], "service": "mri", "required_tools": [],
                   "arrival_minute": slot["start_minute"] - 1, "deadline_minute": slot["start_minute"]}
        case.update(facilities=[{**facility, "resources": [slot]}], patients=[patient])
        for ticks, expected in ((59999, 1), (60000, 1), (60001, 0)):
            with self.subTest(ticks=ticks):
                out = solve(case, travel_ticks={patient["id"]: {facility["id"]: ticks}}, ticks_per_second=1000)
                for policy in out["policies"].values():
                    self.assertEqual(policy["metrics"]["assigned"], expected)
                    if expected:
                        self.assertEqual(policy["assignments"][0]["travel_seconds"], ticks / 1000)
