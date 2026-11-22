"""Hosted recommendation handoff: deterministic fake TomTom and actual app-only imports."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.simulation.scenario import make_scenario
from app.travel import hosted
from app.travel.tomtom import from_environment, http_transport
from tests.travel.helpers import client, no_route, route


def inputs():
    scenario = make_scenario()
    day = "2026-11-21"
    req = dict(service="dialysis", urgency="highest", as_of=day, max_travel_minutes=25)
    candidates = []
    for campus in scenario.campuses:
        if any(p.service == "dialysis" for p in campus.resources):
            services = {"dialysis": {"status": "yes", "source_date": day,
                                     "independent_families": ["synthetic"]}}
        else:
            services = {}
        candidates.append(dict(facility_id=campus.id, services=services, as_of=day))
    return req, dict(mode="synthetic", origin_id="central", as_of=day, candidates=candidates)


class HostedTests(unittest.TestCase):
    def test_all_shortlisted_results_precise_and_keyed_before_display(self):
        req, snap = inputs()
        points = {c.id: (c.latitude, c.longitude) for c in make_scenario().campuses}
        # F is physically farther than A. Road estimates reverse that order.
        answers = {points["A"]: route(610.5), points["F"]: route(123.25),
                   points["B"]: no_route(), points["C"]: {}, points["E"]: route(0)}
        def transport(origin, destination, config):
            self.assertEqual(origin, (26.936, 75.8))
            return answers[destination]
        service = client(transport)
        self.addCleanup(service.close)
        travel = hosted.demo_car_travel(req, snap, origin_id="central", provider=service)
        self.assertEqual(len(travel), 6)
        self.assertEqual(service.budget.used, 5)
        self.assertEqual(travel["F"]["minutes"], 123.25 / 60)
        self.assertLess(travel["F"]["minutes"], travel["A"]["minutes"])
        self.assertEqual(travel["E"]["minutes"], 0)
        self.assertEqual(travel["B"]["outcome"], "no_route")
        self.assertIsNone(travel["B"]["minutes"])
        self.assertEqual(travel["C"]["reason"], "invalid_provider_response")
        self.assertEqual(travel["D"]["reason"], "service_ineligible")
        self.assertTrue(all("simulated" in r["source"] for r in travel.values()))

    def test_only_canonical_points_reach_http(self):
        req, snap = inputs()
        snap["candidates"] = snap["candidates"][:1]
        c = client(http_transport)
        self.addCleanup(c.close)
        wire = Mock()
        wire.getresponse.return_value.status = 200
        wire.getresponse.return_value.read.return_value = json.dumps(route(125.25)).encode()
        with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=wire):
            travel = hosted.demo_car_travel(req, snap, origin_id="central", provider=c)
        self.assertEqual(travel["A"]["minutes"], 125.25 / 60)
        method, path = wire.request.call_args.args
        self.assertEqual(method, "GET")
        self.assertIn("26.936,75.8:26.949,75.791", path)
        self.assertIn("traffic=true", path)
        self.assertNotIn("dialysis", path)

    def test_reject_invalid_context_and_points_without_charging(self):
        req, snap = inputs()
        service = client()
        self.addCleanup(service.close)
        for change, origin, reason in (({"mode": "reviewed"}, "central", "unapproved_snapshot"),
                                       ({"as_of": "2026-11-20"}, "central", "snapshot_date_mismatch"),
                                       ({"origin_id": None}, "central", "unapproved_origin"),
                                       ({}, "east", "unapproved_origin"), ({}, "bogus", "unapproved_origin")):
            rows = hosted.demo_car_travel(req, {**snap, **change}, origin_id=origin, provider=service)
            self.assertEqual({r["reason"] for r in rows.values()}, {reason})
        rows = [dict(snap["candidates"][0], latitude=1, longitude=2),
                dict(snap["candidates"][1], facility_id="unknown")]
        bad = hosted.demo_car_travel(req, dict(snap, candidates=rows), origin_id="central", provider=service)
        self.assertEqual({r["reason"] for r in bad.values()}, {"unapproved_campus_point"})
        self.assertEqual(hosted.demo_car_travel(dict(req, emergency=True), snap, origin_id="central", provider=service), {})
        self.assertEqual(hosted.demo_car_travel(req, dict(snap, candidates=[]), origin_id="central", provider=service), {})
        for c in snap["candidates"]:
            c["services"] = {}
        empty = hosted.demo_car_travel(req, snap, origin_id="central", provider=service)
        self.assertTrue(all(row["reason"] == "service_ineligible" for row in empty.values()))
        self.assertEqual(service.budget.used, 0)

    def test_hosted_enable_cannot_use_local_ledger(self):
        for flag in ("DATABRICKS_APP_NAME", "DATABRICKS_APP_PORT", "DATABRICKS_APP_URL"):
            service = from_environment({flag: "example", "TOMTOM_ENABLED": "true",
                                        "TOMTOM_DEPLOYMENT_MODE": "single_host", "TOMTOM_BUDGET_DB": "/tmp/test"})
            self.addCleanup(service.close)
            self.assertEqual(service.disabled_reason(), "unsupported_budget_deployment")
            self.assertIsNone(service.budget)

    def test_actual_flat_packaging_in_isolated_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "deployment"
            shutil.copytree(Path(__file__).resolve().parents[2] / "app", root,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            code = """from travel.hosted import demo_car_travel, _process_client
from travel.tomtom import from_environment
assert _process_client() is _process_client()
request = dict(service='mri', as_of='2026-11-21', urgency='routine', max_travel_minutes=10)
candidate = dict(facility_id='A', services={}, as_of=request['as_of'])
snapshot = dict(mode='synthetic', origin_id='central', candidates=[candidate], as_of=request['as_of'])
assert demo_car_travel(request, snapshot, origin_id='central')['A']['reason'] == 'service_ineligible'
"""
            subprocess.run([sys.executable, "-B", "-c", code], cwd=root, check=True,
                           env={"PATH": os.defpath, "DATABRICKS_APP_NAME": "fake"})
