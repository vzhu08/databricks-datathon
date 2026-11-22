"""Signed-in Storm UI tests. All observations, names and points here are invented."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import storm_page, storm_plan
from app.simulation.batch_planner import make_instance, solve
from app.simulation.traffic_plan import PUNE_ROSTER_SHA256, derive_pickups, run_traffic_plan

_READY = {
    "TOMTOM_ENABLED": "true",
    "TOMTOM_COPYRIGHT_CAPTION": "Test caption",
    "TOMTOM_COPYRIGHT_NOTICES": "Test notices",
}


def baseline_fixture():
    return solve(make_instance({
        "geography": {
            "name": "Invented Storm test", "source": "Fictional test source", "selection": "Test selection",
            "verification": "No real site used", "location_basis": "public_source", "roster_sha256": PUNE_ROSTER_SHA256,
            "attribution": [{"text": "Test only", "url": "https://example.invalid/"}],
        },
        "facilities": [{
            "id": f"C{i+1:02}", "label": f"Invented site {i+1}",
            "latitude": (i % 4) * 0.01, "longitude": i * 0.01,
            "precision": "mapped_point" if i < 8 else "campus_anchor",
            "source": {"publisher": "Test publisher", "license": "Test license"},
        } for i in range(12)],
    }))


def observation(pickups, sites, usable):
    return {
        "source": "Test ordinary-car provider", "observed_at": "2026-11-22T16:00:00Z" if usable else None,
        "attempted_pairs": 24 if usable else 0, "actual_attempts": 25 if usable else 0,
        "travel_seconds": {p["id"]: {f["id"]: 210.25 for f in sites[:10]} for p in pickups} if usable else {},
        "attribution": {"caption": "Test <copyright>", "notices": "Supplier notices & restrictions"},
    }


class TrafficViewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = baseline_fixture()
        cls.pickups = derive_pickups(cls.baseline["facilities"])

    def with_roads(self, usable=True):
        return run_traffic_plan(self.baseline, pickups=self.pickups, observe=lambda pickups, destinations:
                                observation(pickups, destinations, usable))

    def test_only_enabled_first_edition_offers_the_action(self):
        self.assertTrue(storm_page._traffic_available(self.baseline, _READY))
        for setting in _READY:
            self.assertFalse(storm_page._traffic_available(self.baseline, {**_READY, setting: ""}))
        other = deepcopy(self.baseline)
        other["patients"][0]["service"] = "eye_treatment"
        self.assertFalse(storm_page._traffic_available(other, _READY))

    def test_live_view_draws_shared_pickups_and_escapes_attribution(self):
        plan = storm_plan.checked(self.with_roads())
        page = storm_plan.markup(plan)
        self.assertIn("Road times were asked for 24 of the 24 pickup-to-site routes (2 pickups × 12 sites). "
                      "20 came back usable and 4 are unavailable. 25 requests were sent in all, counting retries.",
                      page)
        self.assertIn('<time datetime="2026-11-22T16:00:00Z">22 November 2026, 16:00 UTC</time>', page)
        self.assertIn("West shared pickup: ", page)
        self.assertIn("East shared pickup: ", page)
        self.assertNotIn("PUNE-SIM-PICKUP", page)  # the planner's own ids are not reader-facing words
        self.assertIn("shared simulated pickup (2)", page)
        self.assertIn("MRI", page)
        self.assertNotIn("Mri", page)
        self.assertIn("Test &lt;copyright&gt;", page)
        self.assertIn("Supplier notices &amp; restrictions", page)
        self.assertEqual(page.count('data-pickup="shared"'), 2)
        self.assertNotIn('fill="#8a9aa7"', page)
        self.assertNotIn("minutes of modelled travel", page)
        self.assertAlmostEqual(storm_plan.travel({"travel_seconds": 59.999}), 59.999 / 60)

    def test_zero_road_pairs_show_no_travel_estimate_and_keep_the_modeled_baseline(self):
        page = storm_plan.markup(storm_plan.checked(self.with_roads(False)))
        self.assertIn("No road estimates available for this run.", page)
        self.assertIn("The modeled baseline remains available", page)
        self.assertNotIn("0 on average", page)
        self.assertEqual(page.count("0 of 120 placed"), 2)
        self.assertIn("Nothing is wrong with the planner or the modeled result", page)
        self.assertIn("neither policy could place a simulated patient in this run", page)
        self.assertNotIn("both policies placed the same number", page)
        self.assertIn("No observation time, because no route was observed.", page)
        self.assertNotIn("No road estimates", storm_plan.markup(self.baseline))

    def test_usable_results_require_attribution_and_a_valid_shared_group(self):
        plan = self.with_roads()
        for change in (
            lambda p: p["traffic"]["attribution"].update(caption=""),
            lambda p: p["traffic"]["pickups"][0].update(patient_count=99),
            lambda p: p["traffic"].update(actual_attempts=49),
            lambda p: p["policies"]["exact_optimum"]["assignments"][0].update(travel_seconds=None),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                copy = deepcopy(plan)
                change(copy)
                storm_plan.checked(copy)

    def test_file_loader_refuses_a_saved_traffic_observation(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "plan.json"
            path.write_text(json.dumps(self.with_roads()), encoding="utf-8")
            with self.assertRaisesRegex(storm_plan.Unavailable, "modeled travel"):
                storm_plan.load(path)


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "streamlit is not installed")
class TrafficActionsTests(unittest.TestCase):
    def test_render_and_rerender_never_observe_without_explicit_press(self):
        from streamlit.testing.v1 import AppTest

        baseline = baseline_fixture()
        pickups = derive_pickups(baseline["facilities"])
        app = AppTest.from_string("import streamlit as st\nfrom app import storm_page\nstorm_page.render(st)")
        with patch.dict(os.environ, _READY), patch.object(storm_plan, "load", return_value=baseline), \
                patch.object(storm_page.storm_routes, "storm_pickups", return_value=pickups), \
                patch.object(storm_page.storm_routes, "storm_car_matrix", side_effect=lambda **kw:
                             observation(kw["pickups"], kw["destinations"], True)) as observe:
            app.run()
            self.assertFalse(app.exception)
            app.radio(key="storm_view").set_value(storm_plan.choice(baseline)).run()
            self.assertFalse(app.exception)
            observe.assert_not_called()

            app.button(key="storm_run_road_times").click().run()
            self.assertFalse(app.exception)
            observe.assert_called_once()
            self.assertIn("Signed-in road-time comparison", " ".join(m.value for m in app.markdown))
            self.assertTrue(any(e.label == "Modeled baseline" for e in app.expander))
            stored = app.session_state[storm_page._TRAFFIC_RESULT]
            self.assertIsInstance(stored[1], str)
            self.assertNotIn("210.25", stored[1])

            app.run()
            observe.assert_called_once()
            observe.side_effect = TimeoutError("injected private detail")
            app.button(key="storm_run_road_times").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(observe.call_count, 2)
            report = " ".join(m.value for m in app.markdown)
            self.assertIn("No road estimates available for this run.", report)
            self.assertNotIn("20 usable", report)

            app.radio(key="storm_view").set_value(storm_page.REPLAY).run()
            self.assertEqual(observe.call_count, 2)
            self.assertNotIn(storm_page._TRAFFIC_RESULT, app.session_state)
