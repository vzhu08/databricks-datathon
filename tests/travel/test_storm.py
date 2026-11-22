import hashlib
import json
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from app.travel import storm
from tests.travel.helpers import client, no_route, route


class StormActionTests(unittest.TestCase):
    def setUp(self):
        self.pickups = storm.storm_pickups()
        self.sites = [dict(id=f"S{i}", latitude=12.0, longitude=70.0 + i / 10) for i in range(12)]

    def bind_fixture(self, sites):
        triples = sorted((s["id"], s["latitude"], s["longitude"]) for s in sites)
        digest = hashlib.sha256(json.dumps(triples, separators=(",", ":")).encode("ascii")).hexdigest()
        # Start the synthetic edition for this test and restore the production pin on exit.
        pin = patch.object(storm, "_DESTINATION_DIGEST", digest)
        pin.start()
        self.addCleanup(pin.stop)

    def provider(self, transport, **options):
        provider = client(transport, **options)
        self.addCleanup(provider.close)
        return provider

    def run_matrix(self, provider):
        return storm.storm_car_matrix(pickups=self.pickups, destinations=self.sites, provider=provider)

    def test_coordinate_only_dispatch_dedup_maps_back_to_ids_and_keeps_seconds(self):
        self.sites[1]["longitude"] = self.sites[0]["longitude"]
        self.bind_fixture(self.sites)
        calls = []
        def send(origin, destination, config):
            calls.append((origin, destination))
            return route(seconds=0 if origin == (18.519745, 73.821909) else 18.5)
        provider = self.provider(send)
        out = self.run_matrix(provider)
        self.assertEqual(out["eligible_pairs"], 22)
        self.assertEqual((out["usable_pairs"], out["attempted_pairs"], out["actual_attempts"]), (22, 22, 22))
        self.assertEqual(len(set(calls)), 22)
        for pickup in self.pickups:
            for site in self.sites:
                self.assertIn(((pickup["latitude"], pickup["longitude"]), (site["latitude"], site["longitude"])), calls)
        rows = out["travel_seconds"]
        self.assertEqual(rows["PUNE-SIM-PICKUP-W"]["S1"], 0)
        self.assertEqual(rows["PUNE-SIM-PICKUP-E"]["S0"], 18.5)
        self.assertEqual(out["requested_at"], out["observed_at"])
        self.assertEqual(out["completed_at"], out["observed_at"])
        # Two separate explicit actions must obtain new observations.
        self.sites.reverse()
        self.run_matrix(provider)
        self.assertEqual(len(calls), 44)

    def test_invalid_point_sets_never_initialize_or_call_the_provider(self):
        self.bind_fixture(self.sites)
        cases = [(self.pickups, []), (self.pickups + self.pickups[:1], self.sites)]
        for idx, change in [(0, {"latitude": True}), (0, {"latitude": float("nan")}),
                            (0, {"latitude": -90}), (1, {"id": "S0"}),
                            (1, {"patient": "fixture"}), (0, {"longitude": "70.0"})]:
            sites = deepcopy(self.sites)
            sites[idx].update(change)
            cases.append((self.pickups, sites))
        for change in ({"latitude": 18.0}, {"id": "OTHER"}, {"id": self.pickups[1]["id"]}):
            pickups = deepcopy(self.pickups)
            pickups[0].update(change)
            cases.append((pickups, self.sites))
        with patch.object(storm, "_process_client") as get:
            for pickups, sites in cases:
                with self.subTest(pickups=pickups, first=sites[:1]), self.assertRaises(ValueError):
                    storm.storm_car_matrix(pickups=pickups, destinations=sites)
            get.assert_not_called()

    def test_partial_failure_after_retry_and_no_route(self):
        self.bind_fixture(self.sites)
        calls = []
        def send(origin, destination, config):
            calls.append((origin, destination))
            if destination[1] == 70:
                raise TimeoutError
            if destination[1] == 70.1:
                return no_route()
            return route(seconds=79)
        out = self.run_matrix(self.provider(send))
        self.assertEqual((len(calls), out["attempted_pairs"], out["actual_attempts"]), (26, 24, 26))
        self.assertEqual((out["usable_pairs"], out["unavailable_pairs"]), (20, 4))
        for row in out["travel_seconds"].values():
            self.assertIsNone(row["S0"])
            self.assertIsNone(row["S1"])
        for row in out["reasons"].values():
            self.assertEqual(row["S0"], "provider_timeout")
            self.assertEqual(row["S1"], "no_route_found")

    def test_retries_and_one_ceiling_across_both_origins(self):
        self.bind_fixture(self.sites)
        for limit, sends, evaluated in [(50, 48, 24), (17, 17, 9)]:
            with self.subTest(limit=limit):
                calls = []
                def timeout(origin, destination, config):
                    calls.append((origin, destination))
                    raise TimeoutError
                provider = self.provider(timeout, query_calls=limit)
                out = self.run_matrix(provider)
                self.assertEqual(provider.budget.used, sends)
                self.assertEqual((len(calls), out["actual_attempts"], out["attempted_pairs"]), (sends, sends, evaluated))
                self.assertEqual((out["unavailable_pairs"], out["usable_pairs"]), (24, 0))
                self.assertTrue(all(s is None for row in out["travel_seconds"].values() for s in row.values()))

    def test_exhausted_shared_allowance_and_restricted_operator_shortlist(self):
        self.bind_fixture(self.sites)
        def forbidden(*args):
            self.fail("Transport must not run when the ledger denies admission")
        provider = self.provider(forbidden)
        provider.budget.used = provider.config.daily_calls
        out = self.run_matrix(provider)
        self.assertEqual((out["attempted_pairs"], out["attempts"], out["unavailable_pairs"]), (0, 0, 24))
        self.assertIsNone(out["observed_at"])
        self.assertIn("daily_call_budget_exceeded", out["errors"])
        out = self.run_matrix(self.provider(lambda *_: route(), shortlist_limit=4))
        self.assertEqual((out["attempted_pairs"], out["usable_pairs"], out["unavailable_pairs"]), (4, 4, 20))
        self.assertIn("shortlist_limit", out["errors"])

    def test_hosted_requires_display_settings_and_shared_ledger(self):
        self.bind_fixture(self.sites)
        with patch.dict(os.environ, {"TOMTOM_COPYRIGHT_CAPTION": ""}), patch.object(storm, "_process_client") as get:
            out = self.run_matrix(None)
            get.assert_not_called()
            self.assertEqual(out["errors"], ["missing_provider_attribution"])
            self.assertEqual(out["unavailable_pairs"], 24)
        provider = self.provider(lambda *_: self.fail("Hosted requires the shared ledger"))
        with patch.dict(os.environ, {"TOMTOM_COPYRIGHT_CAPTION": "Fixture", "TOMTOM_COPYRIGHT_NOTICES": "Fixture"}), \
                patch.object(storm, "_process_client", return_value=provider):
            out = self.run_matrix(None)
            self.assertEqual(out["errors"], ["unsupported_budget_deployment"])
            self.assertIsNone(out["requested_at"])
            self.assertEqual(out["actual_attempts"], 0)
