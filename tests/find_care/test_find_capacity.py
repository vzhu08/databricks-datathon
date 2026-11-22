"""#304: the capacity-aware recommendation on Find care, with simulated minutes and a stubbed traffic source."""
import unittest

from app import find_capacity as capacity
from app.simulation.scenario import make_scenario
from app.travel import hosted
from tests.travel.helpers import client, no_route, route

CATALOGUE_IDS = {"demo-near", "demo-north", "demo-south", "demo-excluded", "demo-east", "demo-trauma"}
SENT = "2026-11-22T15:40:00Z"


def row(minutes=None, reason=None, sent=SENT, outcome=None):
    known = minutes is not None
    return {"status": "known" if known else "unavailable", "minutes": minutes, "source": "stub",
            "reason": reason, "outcome": outcome or ("ok" if known else "unavailable"), "requested_at": sent}


class Recorder:
    """A traffic source that records every call, so a test can count them."""
    def __init__(self, rows=None):
        self.calls, self.rows = [], rows or {}

    def demo_car_travel(self, request, snapshot, *, origin_id, provider=None):
        self.calls.append(origin_id)
        return {c["facility_id"]: self.rows.get(c["facility_id"], row(reason="provider_disabled", sent=None))
                for c in snapshot["candidates"]}


class RecommendationTests(unittest.TestCase):
    def test_a_routine_case_names_b_in_the_result_and_the_note_and_says_what_it_protects(self):
        check = capacity.run("dialysis", "routine", "central", False, False)
        lines, note = capacity.explain(check), capacity.referral_note(check)
        self.assertEqual("Campus B", lines["destination"])
        self.assertEqual("Send the patient to Campus B.", lines["headline"])
        self.assertEqual("12 min (simulated). 2 free staffed places for this service when checked.", lines["trip"])
        self.assertEqual("Fastest with a free place: Campus A, 8 min. Not recommended for this patient.", lines["fastest"])
        self.assertIn("Campus B is 4 min further.", lines["why"])
        self.assertIn("last free place with a monitored dialysis station", lines["why"])
        self.assertEqual(capacity.SIMULATED_LABEL, lines["time_label"])
        # The protected campus is not offered as the fallback destination.
        self.assertEqual(["Campus C (14 min)"], lines["alternatives"])
        self.assertIn("Send to: Campus B", note)
        self.assertIn("If it cannot take the patient: Campus C (14 min)", note)
        self.assertNotIn("Send to: Campus A", note)
        self.assertIn("not quality", note)
        self.assertIn("call 112", note)

    def test_the_highest_urgency_names_a_in_the_result_and_the_note(self):
        check = capacity.run("dialysis", "highest", "central", False, False)
        lines, note = capacity.explain(check), capacity.referral_note(check)
        self.assertEqual("Send the patient to Campus A.", lines["headline"])
        self.assertIsNone(lines["fastest"])
        self.assertIn("Highest urgency", lines["why"])
        self.assertIn("Send to: Campus A", note)
        self.assertNotIn("Campus B is", note)

    def test_unknown_capacity_is_named_and_the_closest_campus_is_not_slipped_in(self):
        check = capacity.run("dialysis", "routine", "south", False, False)
        lines = capacity.explain(check)
        # E is 8 minutes from the south start but its free places are unknown.
        self.assertEqual("Campus C", lines["destination"])
        self.assertNotIn("Campus E", " ".join(lines["alternatives"]) + capacity.referral_note(check))
        self.assertIn("1 campus left out: free staffed places unknown or out of date.", lines["excluded"])
        self.assertIn("1 campus left out: no reviewed, dated evidence that the service runs there.", lines["excluded"])

    def test_the_selected_starting_area_is_bound_and_an_unknown_one_is_refused(self):
        for origin, expected in (("central", "B"), ("east", "B"), ("south", "C"), ("west", "F")):
            check = capacity.run("dialysis", "routine", origin, False, False)
            self.assertEqual(origin, check["asked"]["origin_id"])
            self.assertEqual(expected, check["result"]["chosen"]["facility_id"], origin)
            self.assertIn(f"from {origin} Jaipur (simulated)", capacity.request_line(check))
        for origin in (None, "", "Jaipur, Rajasthan", "302001"):
            with self.assertRaises(ValueError):
                capacity.run("dialysis", "routine", origin, False, False)

    def test_a_failed_road_time_gives_no_destination_no_note_and_no_simulated_minutes(self):
        check = capacity.run("dialysis", "routine", "central", False, True, travel=Recorder())
        lines = capacity.explain(check)
        self.assertEqual("No campus is recommended.", lines["headline"])
        self.assertIsNone(lines["destination"])
        self.assertIsNone(lines["trip"])
        self.assertIsNone(capacity.referral_note(check))
        self.assertIn("No simulated time is used in their place.", lines["why"])
        self.assertEqual(6, len(lines["travel_failures"]))
        self.assertTrue(all(line.endswith("road time unavailable (provider disabled), no request was sent.")
                            for line in lines["travel_failures"]))
        self.assertTrue(all(value["minutes"] is None for value in check["travel_rows"].values()))
        self.assertNotIn("simulated)", " ".join(str(value) for value in lines.values()))

    def test_road_time_carries_the_providers_own_request_time_and_is_never_called_unless_asked(self):
        quiet = Recorder()
        capacity.run("dialysis", "routine", "central", False, False, travel=quiet)
        self.assertEqual([], quiet.calls)
        source = Recorder({"A": row(30.0), "B": row(10.5), "C": row(reason="no_route_found", outcome="no_route"),
                           "F": row(40.0)})
        check = capacity.run("dialysis", "routine", "central", False, True, travel=source)
        lines = capacity.explain(check)
        self.assertEqual(["central"], source.calls)
        # With traffic, A is 30 minutes away and outside the limit, so B is the fastest.
        self.assertEqual("Send the patient to Campus B.", lines["headline"])
        self.assertIn("10.5 min (by road, ordinary car with traffic).", lines["trip"])
        self.assertIn("ordinary car with traffic, from TomTom", lines["time_label"])
        self.assertIn("simulated Jaipur places", lines["time_label"])
        self.assertIn("This time was requested at 15:40:00 UTC on 22 Nov 2026.", lines["time_label"])
        self.assertIn("Campus C: road time unavailable (no route found), requested at 15:40:00 UTC on 22 Nov 2026.",
                      lines["travel_failures"])
        self.assertIn("requested at 15:40:00 UTC", capacity.referral_note(check))

    def test_the_real_hosted_adapter_with_a_stubbed_provider_feeds_the_same_result(self):
        points = {c.id: (c.latitude, c.longitude) for c in make_scenario().campuses}
        answers = {points["A"]: route(30 * 60), points["B"]: route(10 * 60), points["C"]: no_route(),
                   points["F"]: route(40 * 60)}
        service = client(lambda origin, destination, config: answers.get(destination, no_route()))
        self.addCleanup(service.close)
        check = capacity.run("dialysis", "routine", "central", False, True, travel=hosted, provider=service)
        lines = capacity.explain(check)
        self.assertEqual("B", check["result"]["chosen"]["facility_id"])
        sent = check["travel_rows"]["B"]["requested_at"]
        self.assertTrue(sent)
        self.assertIn(capacity._when(sent), lines["time_label"])
        self.assertTrue(any(line.startswith("Campus C: road time unavailable") for line in lines["travel_failures"]))

    def test_an_indeterminate_scarcity_fallback_says_it_is_not_certain(self):
        # A's road time is known but the other monitored station (F) could not be timed, so "last one" is unproven.
        source = Recorder({"A": row(8.0), "B": row(12.0), "C": row(14.0), "E": row(20.0),
                           "F": row(reason="provider_unavailable")})
        check = capacity.run("dialysis", "routine", "central", False, True, travel=source)
        self.assertEqual("scarcity_indeterminate", check["result"]["reason"])
        lines = capacity.explain(check)
        self.assertEqual("Send the patient to Campus A.", lines["headline"])
        self.assertIn("Not certain: this may use the last free place with a monitored dialysis station", lines["uncertain"])
        self.assertIn("no detour was made on a guess", lines["uncertain"])
        self.assertIn("Not certain", capacity.referral_note(check))

    def test_an_emergency_never_gets_a_destination(self):
        check = capacity.run("dialysis", "routine", "central", False, False)
        check["result"] = {**check["result"], "status": "emergency", "reason": "emergency_stop"}
        self.assertIn("call 112 now", capacity.explain(check)["headline"])
        self.assertIsNone(capacity.referral_note(check))

    def test_scenario_campuses_never_share_ids_or_names_with_the_catalogue_hospitals(self):
        ids = {campus.id for campus in make_scenario().campuses}
        self.assertFalse(ids & CATALOGUE_IDS)
        for service in capacity.SERVICES:
            for urgency in capacity.URGENCIES:
                for origin in capacity.ORIGINS:
                    check = capacity.run(service, urgency, origin, False, False)
                    words = " ".join(str(value) for value in capacity.explain(check).values())
                    words += capacity.referral_note(check) or ""
                    self.assertNotIn("Example", words)
                    self.assertNotIn("demo-", words)
                    self.assertIn("Not a reviewed real facility", words)


if __name__ == "__main__":
    unittest.main()
