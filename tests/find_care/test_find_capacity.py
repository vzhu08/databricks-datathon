"""#304: the capacity-aware choice on Find care, with simulated minutes and a stubbed traffic source."""
import unittest
from datetime import datetime, timezone

from app import find_capacity as capacity
from app.simulation.scenario import make_scenario
from app.travel import hosted
from tests.travel.helpers import client, no_route, route

NOW = datetime(2026, 11, 22, 15, 40, tzinfo=timezone.utc)
CATALOGUE_IDS = {"demo-near", "demo-north", "demo-south", "demo-excluded", "demo-east", "demo-trauma"}


class Recorder:
    """A traffic source that records every call, so a test can count them."""
    def __init__(self, rows=None):
        self.calls, self.rows = [], rows

    def demo_car_travel(self, request, snapshot, *, origin_id, provider=None):
        self.calls.append(origin_id)
        ids = [row["facility_id"] for row in snapshot["candidates"]]
        return self.rows if self.rows is not None else {
            fid: {"status": "unavailable", "minutes": None, "source": "stub", "reason": "provider_disabled",
                  "outcome": "unavailable"} for fid in ids}


class CapacityChoiceTests(unittest.TestCase):
    def test_a_routine_case_diverts_to_keep_the_scarce_station_and_says_by_how_much(self):
        check = capacity.run("dialysis", "routine", "central", False, False)
        lines = capacity.explain(check)
        self.assertEqual("Suggested by free places: Campus B.", lines["headline"])
        self.assertIn("Campus B: 12 min (simulated), 2 free staffed places", lines["chosen"])
        self.assertEqual("Fastest with a free place: Campus A, 8 min (simulated).", lines["fastest"])
        self.assertIn("Campus B adds 4 min.", lines["why"])
        self.assertIn("last free place with a monitored dialysis station", lines["why"])
        self.assertEqual(capacity.SIMULATED_LABEL, lines["time_label"])
        self.assertIn("not a judgement of quality", lines["status"][0])
        self.assertIn("Nothing is booked", lines["status"][0])

    def test_the_highest_urgency_takes_the_fastest_feasible_campus(self):
        lines = capacity.explain(capacity.run("dialysis", "highest", "central", False, False))
        self.assertEqual("Suggested by free places: Campus A.", lines["headline"])
        self.assertIsNone(lines["fastest"])
        self.assertIn("Highest urgency", lines["why"])

    def test_unknown_capacity_is_named_and_the_closest_campus_is_not_slipped_in(self):
        check = capacity.run("dialysis", "routine", "south", False, False)
        lines = capacity.explain(check)
        # E is 8 minutes from the south start but its free places are unknown.
        self.assertNotEqual("E", check["result"]["chosen"]["facility_id"])
        self.assertIn("1 campus left out: free staffed places unknown or out of date.", lines["excluded"])
        self.assertIn("1 campus left out: no reviewed, dated evidence that the service runs there.", lines["excluded"])

    def test_no_eligible_campus_says_so_and_suggests_nothing(self):
        check = capacity.run("dialysis", "routine", "central", False, True, travel=Recorder(), now=NOW)
        lines = capacity.explain(check)
        self.assertEqual("No campus is suggested.", lines["headline"])
        self.assertIn("Road times", lines["why"])
        self.assertIsNone(lines["chosen"])
        self.assertTrue(all("road time unavailable (provider disabled)" in line
                            for line in lines["unavailable_minutes"]))
        self.assertEqual(6, len(lines["unavailable_minutes"]))

    def test_road_time_is_labelled_with_provider_vehicle_and_time_and_never_called_unless_asked(self):
        quiet = Recorder()
        capacity.run("dialysis", "routine", "central", False, False, travel=quiet)
        self.assertEqual([], quiet.calls)
        points = {c.id: (c.latitude, c.longitude) for c in make_scenario().campuses}
        answers = {points["A"]: route(30 * 60), points["B"]: route(10 * 60), points["C"]: no_route(),
                   points["F"]: route(40 * 60)}
        service = client(lambda origin, destination, config: answers.get(destination, no_route()))
        self.addCleanup(service.close)
        check = capacity.run("dialysis", "routine", "central", False, True, travel=hosted, provider=service, now=NOW)
        lines = capacity.explain(check)
        self.assertIn("ordinary car with traffic, from TomTom, as of 15:40 UTC, 22 Nov 2026", lines["time_label"])
        self.assertIn("simulated Jaipur places", lines["time_label"])
        # With traffic, A is 30 minutes away and outside the limit, so B is now fastest.
        self.assertEqual("B", check["result"]["chosen"]["facility_id"])
        self.assertIn("(road)", lines["chosen"])
        self.assertTrue(any(line.startswith("Campus C: road time unavailable") for line in lines["unavailable_minutes"]))

    def test_an_emergency_never_gets_a_capacity_suggestion(self):
        check = capacity.run("dialysis", "routine", "central", False, False)
        check["result"] = {**check["result"], "status": "emergency", "reason": "emergency_stop"}
        self.assertIn("Call 112 now", capacity.explain(check)["headline"])

    def test_scenario_campuses_never_share_ids_with_the_catalogue_hospitals(self):
        ids = {campus.id for campus in make_scenario().campuses}
        self.assertFalse(ids & CATALOGUE_IDS)
        for service in ("dialysis", "mri", "trauma_care"):
            for urgency in capacity.URGENCIES:
                for origin in capacity.ORIGINS:
                    lines = capacity.explain(capacity.run(service, urgency, origin, False, False))
                    self.assertTrue(lines["headline"])
                    words = " ".join(str(value) for value in lines.values())
                    self.assertNotIn("Example", words)
                    self.assertNotIn("demo-", words)


if __name__ == "__main__":
    unittest.main()
