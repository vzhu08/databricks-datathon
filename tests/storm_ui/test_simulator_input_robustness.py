"""Finite-input checks for the release simulator using only invented data."""

from collections import Counter
from importlib.util import find_spec
from itertools import product
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from app import find_capacity, find_decision, storm_page
from app.ranking.individual import select_individual

APP = Path(__file__).resolve().parents[2] / "app"
_CHOICES = tuple(
    (service, urgency, origin, tool)
    for service, urgency, origin in product(find_capacity.SERVICES, find_capacity.URGENCIES, find_capacity.ORIGINS)
    for tool in ((False, True) if service in find_capacity.TOOLS else (False,))
)


class DecisionMatrixTests(unittest.TestCase):
    def test_all_offered_person_choices_reference_an_eligible_staffed_pool(self):
        self.assertEqual(len(_CHOICES), 48)
        counts = Counter()
        for service, urgency, origin, equipment in _CHOICES:
            with self.subTest(service=service, urgency=urgency, origin=origin, equipment=equipment):
                check = find_capacity.run(service, urgency, origin, equipment, False)
                choice = check["result"]["chosen"]
                self.assertIsNotNone(choice)
                self.assertIn(choice["facility_id"], check["result"]["eligible_campus_ids"])
                self.assertLessEqual(choice["travel_minutes"], check["max_minutes"])
                self.assertGreater(choice["free_staffed_slots"], 0)
                campus = next(row for row in check["roster"] if row["facility_id"] == choice["facility_id"])
                self.assertEqual(campus["decision"]["status"], "yes")
                if equipment:
                    self.assertEqual(campus["decision"]["capabilities"]["monitored"], "yes")
                decision = select_individual(service, find_decision.campus_candidates(check),
                                             allocation=check["result"])
                self.assertEqual(decision["status"], "assigned")
                self.assertEqual(find_capacity.explain(check)["destination"], find_capacity.campus(choice["facility_id"]))
                if urgency == "highest":
                    self.assertEqual(choice, check["result"]["fastest"])
                counts[decision["reason"]] += 1
        self.assertEqual(counts, {"nearest_feasible": 46, "preserve_reachable_specialist_slot": 2})

    def test_unsupported_service_cannot_promote_an_existing_assignment(self):
        check = find_capacity.run("dialysis", "highest", "central", True, False)
        for service in ("fertility_care", "dialysis and mri", ""):
            with self.subTest(service=service):
                decision = select_individual(service, find_decision.campus_candidates(check),
                                             allocation=check["result"])
                self.assertEqual(decision["status"], "no_usable_evidence")
                self.assertEqual(decision["next_action"], "clarify_input")
                self.assertIsNone(decision["chosen"])
                self.assertIsNone(find_decision.explain(decision, service)["note_kind"])

    def test_each_storm_control_has_an_outcome_and_visible_disposition(self):
        bundle = storm_page.bundle()
        keys = set(product(bundle["scenarios"], bundle["detour_caps"]))
        self.assertEqual(len(keys), 24)
        for scenario, cap in sorted(keys):
            with self.subTest(scenario=scenario, cap=cap):
                key = f"{scenario}|{cap}"
                row = bundle["replays"][key]
                headline = storm_page.headline({**bundle, "default": key})
                sentence = storm_page.sentence(headline)
                self.assertIn(f"{cap}-minute limit", sentence)
                self.assertIn(scenario, sentence)
                for policy in headline["policies"]:
                    events = row["policies"][policy["policy"]]["events"]
                    ids = [event["request_id"] for event in events]
                    self.assertCountEqual(ids, [request["id"] for request in row["requests"]])
                    self.assertEqual(policy["requested"], policy["served"] + policy["not_served"])
                    self.assertTrue(all(event["reason"] for event in events))
                    self.assertIn(f"{policy['name']} served {policy['served']}", sentence)


@unittest.skipUnless(find_spec("streamlit"), "Streamlit is required to exercise ordinary submits")
class AppEntryTests(unittest.TestCase):
    def setUp(self):
        clean = {k: v for k, v in os.environ.items()
                 if not k.startswith(("TOMTOM_", "DATABRICKS_", "FIND_CARE_", "PATIENT_", "STORM_"))}
        clean["FIND_CARE_DATA"] = "demo"
        patches = (
            patch.dict(os.environ, clean, clear=True),
            patch.object(sys, "path", [str(APP), *sys.path]),
            patch("socket.socket.connect", side_effect=AssertionError("network not expected")),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS not expected")),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def open_person_simulation(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        app.radio(key="view").set_value("Find care").run()
        app.radio(key="lookup_source").set_value("Simulated scenarios").run()
        self.assertFalse(app.exception)
        return app

    @staticmethod
    def text(app):
        return " ".join(element.value for kind in ("markdown", "caption", "error", "warning", "subheader")
                        for element in getattr(app, kind))

    def submit(self, app):
        app.button(key="find").click().run()
        self.assertFalse(app.exception)
        return self.text(app)

    def test_all_48_normal_submits_and_request_edits(self):
        app = self.open_person_simulation()
        previous = None
        for choice in _CHOICES:
            service, urgency, origin, equipment = choice
            with self.subTest(case=choice):
                service_changed = app.radio(key="service").value != service
                if service_changed:
                    app.radio(key="service").set_value(service).run()
                    self.assert_request_cleared(app)
                app.radio(key="urgency").set_value(urgency)
                app.radio(key="origin").set_value(origin)
                if service in find_capacity.TOOLS:
                    app.checkbox(key="needs_tool").set_value(equipment)
                app.run()
                self.assertFalse(app.exception)
                if previous is not None and not service_changed:
                    self.assert_request_cleared(app)
                result = self.submit(app)
                request = app.session_state["capacity"]["asked"]
                self.assertEqual(request, {"service": service, "urgency": urgency, "origin_id": origin,
                                           "needs_tool": equipment, "traffic": False})
                self.assertIn("Send the patient to Campus", result)
                self.assertIn("Referral note", result)
                previous = choice

    def assert_request_cleared(self, app):
        self.assertFalse(app.exception)
        self.assertNotIn("capacity", app.session_state)
        shown = self.text(app)
        self.assertTrue("You changed the request" in shown)
        self.assertNotIn("Send the patient to Campus", shown)

    def test_same_session_capacity_misses_and_recovery_have_safe_feedback(self):
        import find_capacity as presenter
        app = self.open_person_simulation()
        self.assertIn("Send the patient to Campus B", self.submit(app))
        real_snapshot = presenter.demo_capacity_inputs

        def changed(status):
            def build(**kwargs):
                request, snapshot = real_snapshot(**kwargs)
                for pools in snapshot["capacity"].values():
                    for row in pools:
                        row.update(status=status, free_slots=0 if status == "known" else None)
                return request, snapshot
            return build

        expected = {
            "known": "Every campus within reach that offers this is full.",
            "unknown": "No campus within reach has a known free staffed place.",
            "stale": "No campus within reach has a known free staffed place.",
        }
        for status, reason in expected.items():
            with self.subTest(stock=status), patch.object(presenter, "demo_capacity_inputs", changed(status)):
                shown = self.submit(app)
                self.assertIn("No campus is recommended.", shown)
                self.assertIn(reason, shown)
                self.assertNotIn("Send the patient to Campus", shown)
                self.assertNotIn("Referral note", shown)
                self.assertIn('data-fallback="campus"', shown)
                self.assertIn("confirm the service runs today", shown)
        self.assertIn("Send the patient to Campus B", self.submit(app))

    def test_road_lookup_failure_does_not_reuse_prior_travel(self):
        from travel import hosted
        settings = {"TOMTOM_ENABLED": "true", "TOMTOM_COPYRIGHT_CAPTION": "Test attribution",
                    "TOMTOM_COPYRIGHT_NOTICES": "Test notice"}
        with patch.dict(os.environ, settings):
            app = self.open_person_simulation()
            app.radio(key="traffic").set_value(False).run()
            self.assertIn("Send the patient to Campus B", self.submit(app))
            with patch.object(hosted, "demo_car_travel", side_effect=TimeoutError("injected only")) as fake:
                app.radio(key="traffic").set_value(True).run()
                fake.assert_not_called()
                shown = self.submit(app)
                fake.assert_called_once()
                self.assertIn("Road time could not be fetched.", shown)
                self.assertIn("Confirmation call script", shown)
                self.assertNotIn("Send the patient to Campus", shown)
                app.run()
                fake.assert_called_once()
            app.radio(key="traffic").set_value(False).run()
            self.assertIn("Send the patient to Campus B", self.submit(app))
