import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from app.ranking.urgency import rank_campuses
from app.travel.finder import find_campuses
from app.travel.tomtom import TransportFailure
from tests.travel.helpers import campus, client, no_route, route, request


ROOT = Path(__file__).resolve().parents[2]


def by_id(result):
    return {row["facility_id"]: row for row in result["routing"]["results"]}


class LiveFinderTests(unittest.TestCase):
    def test_driving_time_reverses_straight_line_order_and_preserves_snapshot(self):
        inputs = request([campus("near", 75.801), campus("far", 75.85)])
        before = copy.deepcopy(inputs)
        result = find_campuses(inputs, provider=client(lambda origin, dest, config: route(600 if dest[1] == 75.85 else 1200)))
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["far", "near"])
        self.assertEqual(result["ranked"][0]["travel"], 10)
        self.assertEqual(result["travel_metric"], "travel_minutes")
        self.assertEqual(result["routing"]["state"], "ok")
        self.assertEqual(by_id(result)["far"]["requested_at"], "2026-11-21T20:00:00Z")
        self.assertEqual(by_id(result)["far"]["departure_time_source"], "request_time")
        self.assertEqual(inputs, before)

    def test_reviewed_service_capabilities_and_coordinates_gate_before_provider(self):
        rows = [campus("accepted"), campus("no"), campus("unknown"), campus("undated"),
                campus("future"), campus("stale"), campus("required-no"), campus("required-unknown"),
                campus("disputed", coordinate_status="disputed"), campus("invalid", latitude=91),
                campus("unreviewed", coordinate_status="unknown")]
        for row in rows:
            row["services"]["mri"]["capabilities"]["protocol"] = "yes"
        rows[1]["services"]["mri"]["status"] = "no"
        rows[2]["services"]["mri"]["status"] = "unconfirmed"
        rows[3]["services"]["mri"].pop("source_date")
        rows[4]["services"]["mri"]["source_date"] = "2027-01-01"
        rows[5]["as_of"] = "2026-11-20"
        rows[6]["services"]["mri"]["capabilities"]["protocol"] = "no"
        rows[7]["services"]["mri"]["capabilities"] = {}
        send = Mock(return_value=route())
        result = find_campuses(request(rows, required=["protocol"]), provider=client(send))
        self.assertEqual(send.call_count, 1)
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["accepted"])
        self.assertEqual(result["routing"]["counts"]["considered"], 11)
        self.assertEqual(result["routing"]["counts"]["excluded"], 10)
        self.assertEqual(result["routing"]["counts"]["evaluated"], 1)
        self.assertEqual(by_id(result)["disputed"]["reason"], "coordinates_disputed")
        self.assertEqual(by_id(result)["undated"]["exclusion_reasons"], ["missing_service_evidence_date"])
        self.assertEqual(by_id(result)["invalid"]["reason"], "invalid_coordinates")

    def test_no_eligible_destinations_never_call_provider(self):
        row = campus("no")
        row["services"]["mri"]["status"] = "no"
        send = Mock()
        result = find_campuses(request([row]), provider=client(send))
        send.assert_not_called()
        self.assertEqual(result["routing"]["state"], "not_requested")
        self.assertEqual(result["status"], "no_match")

    def test_national_empty_coordinate_coverage_spends_zero_even_with_fallback(self):
        rows = [campus("SYNTHETIC-%s" % i, coordinate_status="unreviewed") for i in range(10088)]
        data = request(rows)
        data["routing"]["fallback_distance_km"] = 50
        send = Mock()
        provider = client(send)
        self.addCleanup(provider.close)
        result = find_campuses(data, provider=provider)
        counts = result["routing"]["counts"]
        self.assertEqual(counts["considered"], 10088)
        self.assertEqual(counts["routing_eligible"], 0)
        self.assertEqual(counts["shortlisted"], 0)
        self.assertEqual(counts["provider_calls_attempted"], 0)
        self.assertEqual(result["routing"]["coverage_state"], "empty")
        self.assertEqual(result["routing"]["state"], "not_requested")
        self.assertEqual(result["ranked"], [])
        send.assert_not_called()

    def test_default_25_geographic_shortlist_is_before_final_top_three_scoring(self):
        rows = [campus(str(i), 75.8 + .001 * i) for i in range(30, 0, -1)]
        send = Mock(side_effect=lambda origin, dest, config: route(60 * (31 - round((dest[1] - 75.8) * 1000))))
        result = find_campuses(request(rows), provider=client(send))
        self.assertEqual(send.call_count, 25)
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["25", "24", "23"])
        self.assertEqual(result["routing"]["counts"]["scored"], 25)
        self.assertEqual(result["routing"]["counts"]["excluded"], 5)
        self.assertEqual(by_id(result)["30"]["reason"], "outside_geographic_shortlist")
        self.assertEqual(result, find_campuses(request(list(reversed(rows))), provider=client(send)))

    def test_partial_response_ranks_only_times_even_with_explicit_fallback(self):
        data = request([campus("near", 75.801), campus("far", 75.85), campus("no", 75.9)])
        data["routing"]["fallback_distance_km"] = 100
        result = find_campuses(data, provider=client(Mock(side_effect=[{}, route(1200), no_route()])))
        self.assertEqual(result["routing"]["state"], "partial")
        self.assertEqual(result["travel_metric"], "travel_minutes")
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["far"])
        self.assertEqual(by_id(result)["near"]["reason"], "invalid_provider_response")
        self.assertEqual(by_id(result)["no"]["outcome"], "no_route")

    def test_all_distance_fallback_is_explicit_and_uses_its_own_budget(self):
        data = request([campus("near", 75.801), campus("far", 76)], travel_budget=.001)
        data["routing"]["fallback_distance_km"] = 5
        send = Mock(side_effect=TransportFailure("provider_timeout"))
        result = find_campuses(data, provider=client(send, max_retries=0))
        self.assertEqual(result["routing"]["state"], "fallback")
        self.assertEqual(result["travel_metric"], "distance_km")
        self.assertEqual(result["routing"]["travel_budget"], 5)
        self.assertEqual([r["facility_id"] for r in result["ranked"]], ["near"])
        row = by_id(result)["near"]
        self.assertEqual(row["outcome"], "unavailable")
        self.assertIsNone(row["estimated_seconds"])
        self.assertEqual(row["metric"], "distance_km")
        self.assertEqual(by_id(result)["far"]["exclusion_reasons"], ["travel_budget_exceeded"])
        self.assertFalse(result["routing"]["attribution"]["required"])
        del data["routing"]["fallback_distance_km"]
        result = find_campuses(data, provider=client(send, max_retries=0))
        self.assertEqual(result["ranked"], [])
        self.assertEqual(result["routing"]["state"], "unavailable")

    def test_no_route_survives_other_campus_failure_in_either_order_and_never_falls_back(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                responses = [no_route(), TransportFailure("provider_timeout")]
                if reverse:
                    responses.reverse()
                data = request([campus("a", 75.801), campus("b", 75.802),
                                campus("disputed", coordinate_status="disputed")])
                data["routing"]["fallback_distance_km"] = 50
                result = find_campuses(data, provider=client(Mock(side_effect=responses), max_retries=0))
                missing, unroutable = ("a", "b") if reverse else ("b", "a")
                self.assertEqual([r["facility_id"] for r in result["ranked"]], [missing])
                self.assertEqual(result["travel_metric"], "distance_km")
                self.assertEqual(by_id(result)[unroutable]["outcome"], "no_route")
                self.assertEqual(by_id(result)["disputed"]["reason"], "coordinates_disputed")

    def test_timed_campus_and_failed_campus_never_mix_distance_and_minutes(self):
        for reverse in (False, True):
            responses = [route(120), TransportFailure("provider_timeout")]
            if reverse:
                responses.reverse()
            data = request([campus("a", 75.801), campus("b", 75.802)])
            data["routing"]["fallback_distance_km"] = 50
            result = find_campuses(data, provider=client(Mock(side_effect=responses), max_retries=0))
            self.assertEqual(result["travel_metric"], "travel_minutes")
            self.assertEqual(result["routing"]["state"], "partial")
            self.assertEqual([r["facility_id"] for r in result["ranked"]], ["b" if reverse else "a"])
            self.assertEqual(result["ranked"][0]["travel"], 2)

    def test_missing_or_invalid_summary_is_unknown_not_an_overall_transport_outage(self):
        for payload in ({}, {"routes": []}, {"routes": [{}]}, route(None)):
            with self.subTest(payload=payload):
                data = request([campus("a")])
                data["routing"]["fallback_distance_km"] = 50
                result = find_campuses(data, provider=client(lambda *_: payload))
                self.assertEqual(result["ranked"], [])
                self.assertEqual(result["routing"]["state"], "unavailable")
                self.assertEqual(result["travel_metric"], "travel_minutes")

    def test_all_no_routes_and_over_budget_times_do_not_trigger_fallback(self):
        for payload, state in [(no_route(), "no_route"), (route(99999), "ok")]:
            data = request([campus("a")])
            data["routing"]["fallback_distance_km"] = 50
            result = find_campuses(data, provider=client(lambda *_: payload))
            self.assertEqual(result["ranked"], [])
            self.assertEqual(result["routing"]["state"], state)
            self.assertEqual(result["travel_metric"], "travel_minutes")

    def test_city_pin_origin_remains_approximate_even_if_input_says_false(self):
        for kind, approximate in [("city", True), ("pin", True), ("coordinates", False)]:
            data = request([campus("a")])
            data["routing"]["origin"].update(kind=kind, approximate=False)
            result = find_campuses(data, provider=client())
            self.assertEqual(result["routing"]["approximate_origin"], approximate)
            self.assertNotIn("origin", result["routing"])

    def test_malformed_request_and_larger_shortlist_fail_before_network(self):
        send = Mock()
        base = request([campus("a")])
        variants = []
        for key, val in [("travel_budget", 0), ("travel_metric", "distance_km"), ("limit", None),
                         ("required", "scanner"), ("as_of", "wrong")]:
            variants.append({**base, key: val})
        for key, val in [("shortlist_limit", 26), ("shortlist_limit", True),
                         ("fallback_distance_km", float("nan")), ("fallback_distance_km", None),
                         ("api_key", "NEVER-FROM-REQUEST")]:
            variants.append({**base, "routing": {**base["routing"], key: val}})
        variants.append({**base, "candidates": [campus("duplicate"), campus("duplicate")]})
        variants.append({**base, "routing": {**base["routing"], "origin": {"latitude": 91, "longitude": 0}}})
        for data in variants:
            with self.subTest(data=data), self.assertRaises((ValueError, TypeError)):
                find_campuses(data, provider=client(send))
        send.assert_not_called()

    def test_live_path_never_reuses_caller_supplied_times(self):
        data = request([campus("a", travel_minutes=0, distance_km=0)])
        result = find_campuses(data, provider=client(lambda *_: []))
        self.assertEqual(result["ranked"], [])
        self.assertIsNone(by_id(result)["a"]["estimated_minutes"])


class NormalInvocationTests(unittest.TestCase):
    def test_no_routing_is_byte_identical_to_existing_ranker_and_never_reads_credentials(self):
        data = json.loads((ROOT / "contracts/fixtures/urgent_finder.json").read_text())
        with patch("app.travel.finder.from_environment", side_effect=AssertionError("must remain offline")):
            self.assertEqual(find_campuses(data), rank_campuses(**data))

    def test_normal_cli_opt_in_with_disabled_environment_and_no_key(self):
        data = json.loads((ROOT / "app/travel/example_request.json").read_text())
        env = {k: v for k, v in os.environ.items() if not k.startswith("TOMTOM_")}
        result = subprocess.run([sys.executable, "-m", "app.ranking", "-"], cwd=ROOT,
                                input=json.dumps(data), text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["routing"]["state"], "unavailable")
        self.assertEqual(response["routing"]["errors"], ["routing_disabled"])
        self.assertEqual(response["routing"]["counts"]["provider_calls_attempted"], 0)
        self.assertEqual(response["ranked"], [])

    def test_normal_entry_point_consumes_fake_provider_through_live_request(self):
        from app.ranking.__main__ import main
        from io import StringIO
        data = request([campus("a")])
        output = StringIO()
        with patch("app.travel.finder.from_environment", return_value=client()), \
                patch("sys.stdin", StringIO(json.dumps(data))), patch("sys.stdout", output):
            self.assertEqual(main(["-"]), 0)
        self.assertEqual(json.loads(output.getvalue())["ranked"][0]["travel"], 90.5 / 60)


if __name__ == "__main__":
    unittest.main()
