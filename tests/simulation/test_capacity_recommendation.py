import copy
import unittest
from unittest.mock import patch

from app.capacity_recommendation import demo_capacity_inputs, recommend_capacity
from app.simulation.replay import replay
from app.simulation.scenario import make_scenario


class CapacityRecommendationTests(unittest.TestCase):
    def test_preview_matches_the_replay_and_does_not_reserve(self):
        request, snapshot = demo_capacity_inputs()
        original = copy.deepcopy(snapshot)
        result = recommend_capacity(request, snapshot)
        event = replay(make_scenario())["policies"]["scarcity_aware"]["events"][0]
        self.assertEqual(result["chosen"]["facility_id"], event["campus_id"])
        self.assertEqual(result["chosen"]["free_staffed_slots"], event["resource_before"]["free"])
        self.assertEqual(result["chosen"]["travel_minutes"], event["travel_minutes"])
        self.assertEqual(result["fastest"]["facility_id"], event["nearest_campus_id"])
        self.assertEqual(result["extra_travel_minutes"], event["extra_travel_minutes"])
        self.assertEqual(result["preserved_profiles"], ["dialysis/monitored"])
        self.assertEqual(result["mode"], "synthetic")
        self.assertIn("Synthetic", result["chosen"]["capacity_source"])
        self.assertIn("Synthetic", result["chosen"]["travel_source"])
        self.assertEqual(recommend_capacity(request, snapshot), result)
        self.assertEqual(snapshot, original)

    def test_highest_and_lower_scarcity_change_the_winner(self):
        for options, chosen, fastest in [
            ({}, "B", "A"),
            ({"urgency": "highest"}, "A", "A"),
            ({"variant": "spare_specialist"}, "A", "A"),
            ({"variant": "fastest_pool_exhausted"}, "B", "B"),
            ({"required_tools": ("monitored",)}, "A", "A"),
        ]:
            with self.subTest(options=options):
                result = recommend_capacity(*demo_capacity_inputs(**options))
                self.assertEqual((result["chosen"]["facility_id"], result["fastest"]["facility_id"]),
                                 (chosen, fastest))

    def test_exact_and_just_over_fractional_window_and_detour(self):
        request, snapshot = demo_capacity_inputs()
        request.update(detour_minutes=0.2, max_travel_minutes=8.3)
        snapshot["travel"]["A"]["minutes"] = 8.1
        snapshot["travel"]["B"]["minutes"] = 8.3
        result = recommend_capacity(request, snapshot)
        self.assertEqual(result["chosen"]["facility_id"], "B")
        self.assertEqual(result["extra_travel_minutes"], 0.2)
        snapshot["travel"]["B"]["minutes"] = 8.300000000000002
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["facility_id"], "A")
        request["max_travel_minutes"] = 9
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["facility_id"], "A")

    def test_capacity_unknown_stale_and_exhausted_cannot_produce_a_slot(self):
        request, snapshot = demo_capacity_inputs(service="mri")
        for status, free, reason in [
            ("known", 0, "no_staffed_slot_left"),
            ("unknown", None, "unknown_or_stale_capacity"),
            ("stale", 9, "unknown_or_stale_capacity"),
            ("unavailable", None, "unknown_or_stale_capacity"),
        ]:
            with self.subTest(status=status):
                for rows in snapshot["capacity"].values():
                    for row in rows:
                        row.update(status=status, free_slots=free)
                result = recommend_capacity(request, snapshot)
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["chosen"])

    def test_travel_unknown_stale_unavailable_and_distance_never_supply_minutes(self):
        request, snapshot = demo_capacity_inputs(service="mri")
        for row, reason in [
            ({"status": "unknown"}, "travel_unknown"),
            ({"status": "unavailable", "minutes": 8}, "travel_unavailable"),
            ({"status": "stale", "minutes": 8}, "travel_stale"),
            ({"status": "known", "distance_km": 1, "source": "distance fallback"}, "travel_invalid"),
        ]:
            with self.subTest(row=row):
                snapshot["travel"] = dict.fromkeys(("A", "D"), row)
                result = recommend_capacity(request, snapshot)
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["chosen"])
        snapshot["travel"]["D"] = {"status": "known", "minutes": 0, "source": "test zero-minute ETA"}
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["travel_minutes"], 0)

    def test_full_shortlist_uses_eta_with_stable_ties_and_campus_ids(self):
        request, snapshot = demo_capacity_inputs(urgency="highest")
        # Latitude/distance order is deliberately different from ETA order.
        for row in snapshot["candidates"]:
            row["distance_km"] = 99 if row["facility_id"] == "F" else 1
        snapshot["travel"]["F"]["minutes"] = 1
        result = recommend_capacity(request, snapshot)
        self.assertEqual(result["chosen"]["facility_id"], "F")
        self.assertEqual(result["chosen"]["resource_id"], "F-dialysis")
        self.assertEqual(result["eligible_campus_ids"], ["F", "A", "B", "C"])
        snapshot["travel"]["A"]["minutes"] = 1
        tied = recommend_capacity(request, snapshot)
        self.assertEqual(tied["chosen"]["facility_id"], "A")
        snapshot["candidates"].reverse()
        self.assertEqual(recommend_capacity(request, snapshot), tied)

    def test_scarcity_requires_a_reviewed_and_reachable_profile(self):
        request, snapshot = demo_capacity_inputs()
        snapshot["travel"]["F"]["minutes"] = 20
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["facility_id"], "A")
        f = next(r for r in snapshot["candidates"] if r["facility_id"] == "F")
        f["services"]["dialysis"]["capabilities"]["monitored"] = "unconfirmed"
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["facility_id"], "B")
        a = next(r for r in snapshot["candidates"] if r["facility_id"] == "A")
        a["services"]["dialysis"]["status"] = "unconfirmed"
        result = recommend_capacity(request, snapshot)
        self.assertEqual(result["fastest"]["facility_id"], "B")
        self.assertEqual(result["preserved_profiles"], [])

    def test_reachable_specialist_spare_can_be_ineligible_for_this_request(self):
        request, snapshot = demo_capacity_inputs(required_tools=("isolation",))
        for row in snapshot["candidates"]:
            campus = row["facility_id"]
            if campus in ("A", "B"):
                row["services"]["dialysis"]["capabilities"]["isolation"] = "yes"
                pool = next(p for p in snapshot["capacity"][campus] if p["service"] == "dialysis")
                pool["tools"].append("isolation")
        self.assertEqual(recommend_capacity(request, snapshot)["chosen"]["facility_id"], "B")
        snapshot["travel"]["F"]["minutes"] = 20
        result = recommend_capacity(request, snapshot)
        self.assertEqual(result["chosen"]["facility_id"], "A")
        self.assertEqual(result["eligible_campus_ids"], ["A", "B"])

    def test_emergency_and_missing_snapshot_are_explicit(self):
        request, snapshot = demo_capacity_inputs()
        with patch("app.capacity_recommendation._eligible_snapshot", side_effect=AssertionError("evidence lookup")):
            self.assertEqual(recommend_capacity({"emergency": True}, snapshot)["status"], "emergency")
            self.assertEqual(recommend_capacity(request)["reason"], "snapshot_unavailable")
            self.assertEqual(recommend_capacity(request, {**snapshot, "as_of": "2026-11-21"})["reason"],
                             "stale_snapshot")
