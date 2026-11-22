"""Offline #345 acceptance: run with the separately staged edition-one plan.

    STORM_AUDIT_PLAN=/path/to/plan.json python -m unittest tests.simulation.test_storm_traffic_audit

All transports are fakes. The public campus coordinates and real provider observations
are never stored in this test. The environment path is needed only for edition tests.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.simulation.test_batch_audit import audit_policy
from tests.travel.helpers import client, no_route, route

PLAN_SHA = "56c61b5519362e918b4f913e055eccba730d8d22d8de4d4842e3b3516aba6414"
PICKUP_PREFIX = "PUNE-SIM-PICKUP-"


def approved_pickups(facilities):
    ordered = sorted(facilities, key=lambda f: (f["longitude"], f["latitude"], f["id"]))
    result = []
    for side, sites in (("W", ordered[:6]), ("E", ordered[6:])):
        point = {"id": PICKUP_PREFIX + side}
        for axis in ("latitude", "longitude"):
            mean = sum(Decimal(str(site[axis])) for site in sites) / len(sites)
            point[axis] = float(mean.quantize(Decimal("0.000001")))
        result.append(point)
    return result


def point(row):
    return (row["latitude"], row["longitude"])


def chord_distance(left, right):
    # Unit-sphere chord is strictly increasing with surface distance.
    def unit(location):
        lat, lon = map(math.radians, point(location))
        return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))
    return math.dist(unit(left), unit(right))


def check_allocations(case, baseline, live, pickups, matrix):
    """Rebuild the 120x12 travel table and check both policies with the independent oracle."""
    case.assertEqual(baseline["facilities"], live["facilities"])
    expected_patients = {p["id"]: p for p in baseline["patients"]}
    case.assertCountEqual(expected_patients.keys(), [p["id"] for p in live["patients"]])
    groups = Counter()
    times = {}
    for p in live["patients"]:
        before = expected_patients[p["id"]]
        for key in ("priority", "service", "required_tools", "arrival_minute", "deadline_minute"):
            case.assertEqual(p[key], before[key], (p["id"], key))
        pickup = min(pickups, key=lambda q: (chord_distance(before, q), q["id"]))
        case.assertEqual(p["pickup_id"], pickup["id"])
        case.assertEqual(point(p), point(pickup))
        groups[pickup["id"]] += 1
        # The fake observations are in quarter seconds. Express both the original
        # windows and the observations in the same scaled units for the integer oracle.
        times[p["id"]] = {fid: int(seconds * 4) for fid, seconds in matrix[pickup["id"]].items()
                          if seconds is not None}
    case.assertEqual(groups, {PICKUP_PREFIX + "W": 55, PICKUP_PREFIX + "E": 65})
    patients, facilities = deepcopy(baseline["patients"]), deepcopy(baseline["facilities"])
    for p in patients:
        p["arrival_minute"] *= 4
        p["deadline_minute"] *= 4
    for f in facilities:
        for slot in f["resources"]:
            slot["start_minute"] *= 4
    for name in ("nearest_first", "exact_optimum"):
        policy = deepcopy(live["policies"][name])
        # The baseline oracle uses its own label for the same missing-edge condition.
        original_reasons = Counter(row["reason"] for row in policy["unserved"])
        case.assertNotIn("modelled_travel_unknown", original_reasons)
        case.assertEqual(policy["metrics"]["unserved_reasons"], original_reasons)
        for row in policy["unserved"]:
            if row["reason"] == "traffic_travel_unavailable":
                row["reason"] = "modelled_travel_unknown"
        policy["metrics"]["unserved_reasons"] = dict(Counter(row["reason"] for row in policy["unserved"]))
        for booking in policy["assignments"]:
            booking["travel_seconds"] *= 4
            booking["slot_start_minute"] *= 4
        policy["metrics"]["total_travel_seconds"] *= 4
        audit_policy(case, patients, facilities, times, policy, exact=name == "exact_optimum")


@unittest.skipUnless(os.environ.get("STORM_AUDIT_PLAN"), "set STORM_AUDIT_PLAN to the approved plan")
class EditionOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = Path(os.environ["STORM_AUDIT_PLAN"]).read_bytes()
        if sha256(raw).hexdigest() != PLAN_SHA:
            raise ValueError("Supply the unchanged edition-one plan")
        cls.plan = json.loads(raw)
        cls.pickups = approved_pickups(cls.plan["facilities"])
        cls.sites = [{k: f[k] for k in ("id", "latitude", "longitude")} for f in cls.plan["facilities"]]

    def setUp(self):
        for attr in ("socket.connect", "getaddrinfo"):
            guard = patch("socket." + attr, side_effect=AssertionError("Unexpected network access"))
            guard.start()
            self.addCleanup(guard.stop)

    def test_original_modeled_replay(self):
        from app.simulation.batch_planner import solve

        fields = ("geography", "patients", "facilities", "scenario")
        replay = solve({key: self.plan[key] for key in fields})
        self.assertEqual(replay, self.plan)
        self.assertEqual([replay["policies"][p]["metrics"]["assigned"] for p in ("nearest_first", "exact_optimum")],
                         [112, 117])

    def observe(self, *, pickups=None, destinations=None, fail_first=False, no_routes=False, **limits):
        from app.travel.storm import storm_car_matrix

        origins = {point(p): p["id"] for p in self.pickups}
        sites = {point(f): f["id"] for f in self.sites}
        sent = Counter()
        expected = {o: dict.fromkeys(sites.values()) for o in origins.values()}

        def fake(origin, dest, config):
            # Only approved coordinates can reach transport. No patient or
            # service data enters the route argument.
            key = (origins[tuple(origin)], sites[tuple(dest)])
            sent[key] += 1
            if fail_first and sent[key] == 1:
                raise TimeoutError()
            if no_routes:
                return no_route()
            seconds = 60 * int(key[1][1:]) + (0.25 if key[0].endswith("W") else 12.5)
            expected[key[0]][key[1]] = seconds
            return route(seconds)

        service = client(fake, **limits)
        self.addCleanup(service.close)
        got = storm_car_matrix(pickups=self.pickups if pickups is None else pickups,
                               destinations=self.sites if destinations is None else destinations, provider=service)
        self.assertEqual(got["eligible_pairs"], 24)
        self.assertEqual(got["attempted_pairs"], len(sent))
        self.assertEqual(got["actual_attempts"], sum(sent.values()))
        self.assertEqual(service.budget.used, sum(sent.values()))
        self.assertEqual(got["usable_pairs"], sum(v is not None for row in expected.values() for v in row.values()))
        self.assertEqual(got["unavailable_pairs"], 24 - got["usable_pairs"])
        self.assertEqual(got["travel_seconds"], expected)
        self.assertLessEqual(max(sent.values(), default=0), 2)
        self.assertEqual(bool(got["observed_at"]), bool(sent))
        return got

    def test_route_deduplication_retries_and_one_action_limit(self):
        self.assertEqual(self.observe()["actual_attempts"], 24)
        self.assertEqual(self.observe(fail_first=True)["actual_attempts"], 48)
        self.assertEqual(self.observe(fail_first=True, query_calls=7)["actual_attempts"], 7)
        self.assertEqual(self.observe(daily_calls=0)["actual_attempts"], 0)

    def test_altered_points_do_not_reach_provider(self):
        from app.travel.storm import storm_car_matrix, storm_pickups

        self.assertEqual({p["id"]: point(p) for p in storm_pickups()},
                         {p["id"]: point(p) for p in self.pickups})
        altered = deepcopy(self.sites)
        altered[0]["longitude"] += 0.0001
        service = client(lambda *_: self.fail("An altered endpoint reached transport"))
        self.addCleanup(service.close)
        with self.assertRaises(ValueError):
            storm_car_matrix(pickups=self.pickups, destinations=altered, provider=service)
        self.assertEqual(service.budget.used, 0)

    def run_planner(self, matrix, observer):
        from app.simulation.traffic_plan import run_traffic_plan

        requests = []

        def observed(*, pickups, destinations):
            requests.append((deepcopy(pickups), deepcopy(destinations)))
            return observer(pickups=pickups, destinations=destinations)

        baseline = deepcopy(self.plan)
        live = run_traffic_plan(baseline, pickups=deepcopy(self.pickups), observe=observed)
        self.assertEqual(len(requests), 1)
        picks, sites = requests[0]
        self.assertCountEqual(list(picks), self.pickups)
        self.assertCountEqual(list(sites), self.sites)
        self.assertEqual(baseline, self.plan)
        self.assertNotIn("travel_seconds", live["traffic"])
        self.assertNotIn("travel_seconds", live)
        check_allocations(self, self.plan, live, self.pickups, matrix)
        return live

    def test_planner_sparse_matrix_and_observer_failure(self):
        matrix = {q["id"]: {} for q in self.pickups}
        for index, site in enumerate(self.sites):
            # Each origin has a different usable subset. An omitted cell and a null
            # cell must both preclude assignment, even at the nearest physical site.
            if index % 3 == 0:
                matrix[self.pickups[0]["id"]][site["id"]] = 45.25 + index
            elif index % 3 == 1:
                matrix[self.pickups[1]["id"]][site["id"]] = 901.5 + index
            else:
                matrix[self.pickups[0]["id"]][site["id"]] = None
        successful = sum(v is not None for row in matrix.values() for v in row.values())
        receipt = {"travel_seconds": matrix, "eligible_pairs": 24, "attempted_pairs": 24,
                   "actual_attempts": 26, "attempts": 26, "usable_pairs": successful,
                   "unavailable_pairs": 24 - successful, "pickup_count": 2, "site_count": 12,
                   "requested_at": "2026-11-22T12:00:00Z", "observed_at": "2026-11-22T12:00:00Z",
                   "completed_at": "2026-11-22T12:01:00Z", "source": "Fake ordinary-car transport",
                   "errors": [], "attribution": "Synthetic test credit"}
        live = self.run_planner(matrix, lambda **_: receipt)
        self.assertGreater(live["policies"]["nearest_first"]["metrics"]["assigned"], 0)
        self.assertEqual(live["traffic"]["usable_pairs"], successful)

        def fail(**kwargs):
            raise TimeoutError("Fake request interrupted")

        empty = {p["id"]: {} for p in self.pickups}
        unavailable = self.run_planner(empty, fail)
        self.assertIsNone(unavailable["traffic"]["actual_attempts"])
        self.assertIsNone(unavailable["traffic"]["attempted_pairs"])
        for policy in unavailable["policies"].values():
            self.assertEqual(policy["metrics"]["assigned"], 0)
            self.assertEqual(policy["metrics"]["unmet"], 120)

    def test_adapter_and_planner_together(self):
        for opts in ({}, {"daily_calls": 4}, {"no_routes": True}):
            with self.subTest(opts=opts):
                receipt = {}
                matrix = {}

                def observe(**points):
                    receipt.update(self.observe(**points, **opts))
                    matrix.update(receipt["travel_seconds"])
                    return receipt

                live = self.run_planner(matrix, observe)
                for name in ("eligible_pairs", "attempted_pairs", "usable_pairs", "unavailable_pairs", "actual_attempts"):
                    self.assertEqual(live["traffic"][name], receipt[name])
