"""Exercises the judge workflow with synthetic inputs and loader results only."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.facility_evidence_demo import area, care_decision, loader

HERE = Path(__file__).resolve().parent


def load_fixture(module, name):
    path = HERE / name
    fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    return module.load({module.PATH_SETTING: str(path)}, expected_sha256=fingerprint)


class CareDecisionTests(unittest.TestCase):
    def setUp(self):
        self.display = load_fixture(loader, "synthetic_display.json")
        self.area = load_fixture(area, "synthetic_area.json")
        self.request = {"concern": "injury", "severity": "mild", "urgency": "routine", "danger": "no"}

    def decision(self, **changes):
        return care_decision.evaluate({**self.request, **changes}, self.display, self.area)

    def test_rule_priority_is_independent_of_the_reported_time_priority(self):
        routine = self.decision(severity="moderate")
        soon = self.decision(severity="moderate", urgency="soon")
        self.assertEqual((routine["assessment_priority"], routine["workflow_urgency"]), ("standard", "standard"))
        self.assertEqual((soon["assessment_priority"], soon["workflow_urgency"]), ("standard", "prompt_review"))
        self.assertEqual(soon["request"]["urgency"], "soon")
        self.assertIn("request for help soon raises", soon["reason"])
        self.assertEqual(routine["service"], soon["service"])

        higher_review = self.decision(severity="severe")
        self.assertEqual(higher_review["request"]["urgency"], "routine")
        self.assertEqual((higher_review["assessment_priority"], higher_review["workflow_urgency"]),
                         ("prompt_review", "prompt_review"))
        self.assertIn("routine", higher_review["reason"])
        self.assertIn("severe", higher_review["reason"])

        incomplete = self.decision(danger="unsure", urgency="soon")
        self.assertEqual((incomplete["assessment_priority"], incomplete["workflow_urgency"]),
                         ("clarify", "clarify"))
        self.assertEqual(incomplete["action"], "clarify")

    def test_warning_or_reported_emergency_interrupts_before_evidence(self):
        with patch.object(care_decision, "_loaded", side_effect=AssertionError("read evidence")):
            cases = [
                ({"danger": "yes", "urgency": "routine", "severity": "mild"}, "emergency"),
                ({"concern": "injury", "danger": "no", "urgency": "emergency", "severity": "mild"}, "standard"),
                ({"urgency": "emergency", "concern": "invalid"}, "clarify"),
            ]
            for request, assessment in cases:
                with self.subTest(request=request):
                    result = care_decision.evaluate(request, self.display, self.area)
                    self.assertEqual((result["status"], result["action"]), ("emergency", "interrupt"))
                    self.assertEqual(result["workflow_urgency"], "emergency")
                    self.assertEqual(result["assessment_priority"], assessment)
                    self.assertIsNone(result["service"])
                    self.assertIsNone(result["evidence"])
                    self.assertIsNone(result["area"])

    def test_unknown_answers_cannot_implicitly_clear_danger_or_select_a_service(self):
        for changes in ({"danger": "unsure"}, {"concern": "unsure"}, {"severity": "unsure"}):
            with self.subTest(changes=changes):
                result = self.decision(**changes)
                self.assertEqual(result["status"], "needs_clarification")
                self.assertIsNone(result["service"])
        self.assertEqual(self.decision(concern="other")["status"], "no_supported_service")
        self.assertEqual(self.decision(urgency="unsure")["request"]["urgency"], "unsure")
        self.assertEqual(self.decision(concern="cardiac")["status"], "invalid_request")

    def test_service_selection_does_not_infer_orders_or_leak_other_service_evidence(self):
        for concern, service in (("injury", "trauma_care"), ("mri", "mri"), ("dialysis", "dialysis")):
            with self.subTest(concern=concern):
                result = self.decision(concern=concern, severity="severe")
                evidence = result["evidence"]
                self.assertEqual((result["status"], result["service"]), ("no_reviewed_destination", service))
                self.assertEqual(result["eligible_destinations"], 0)
                trace = self.display["data"]["vf_trace_case"]
                self.assertEqual(evidence["trace"]["same_object_keys"], trace["same_osm_by_service"][service])
                self.assertEqual(evidence["trace"]["grain"], trace["grain"])
                self.assertEqual(evidence["trace"]["source"]["url"], trace["source"])
                self.assertEqual(evidence["synthetic"], True)
                if service == "dialysis":
                    self.assertIsNotNone(evidence["issuer_pilot"])
                    self.assertIsNotNone(evidence["historical_case"])
                else:
                    self.assertIsNone(evidence["issuer_pilot"])
                    self.assertIsNone(evidence["historical_case"])
                self.assertEqual(result["area"]["total"], self.area["data"]["originals"])
                self.assertIsNone(result.get("route"))

    def test_named_injury_kinds_keep_distinct_gaps_when_selection_changes(self):
        dialysis = self.decision(concern="dialysis", injury_kind="head", severity="severe")
        self.assertEqual(dialysis["request"]["injury_kind"], "unsure")
        self.assertIsNotNone(dialysis["evidence"]["historical_case"])
        head = self.decision(injury_kind="head", severity="severe")
        burn = self.decision(injury_kind="burn", severity="severe")
        self.assertEqual(head["workflow_urgency"], burn["workflow_urgency"])
        self.assertIn("head injuries", head["next_check"])
        self.assertIn("burn care", burn["next_check"])
        for result in (head, burn):
            self.assertEqual(result["status"], "no_supported_service")
            self.assertIsNone(result["service"])
            self.assertIsNone(result["evidence"])
            self.assertIsNone(result["eligible_destinations"])
        broad = self.decision(injury_kind="unsure", severity="severe")
        self.assertEqual(broad["service"], "trauma_care")
        self.assertIn("broad trauma", broad["reason"])
        self.assertIsNone(broad["evidence"]["historical_case"])

    def test_absent_wrong_hash_and_malformed_payloads_stay_unavailable(self):
        # The real pin must reject synthetic bytes under normal configuration.
        real_pin_rejects = loader.load({loader.PATH_SETTING: str(HERE / "synthetic_display.json")})
        with tempfile.TemporaryDirectory() as root:
            missing = loader.load({loader.PATH_SETTING: str(Path(root) / "missing.json")})
        for display in (None, {"status": "ok", "data": {}}, loader.load({}), missing, real_pin_rejects):
            with self.subTest(status=display and display.get("status")):
                result = care_decision.evaluate(self.request, display, self.area)
                self.assertEqual(result["status"], "data_unavailable")
                self.assertIsNone(result["eligible_destinations"])
                self.assertIsNone(result["evidence"])
                self.assertEqual(result["area"]["as_of"], self.area["data"]["as_of"])
        result = care_decision.evaluate(self.request, self.display, area.load({}))
        self.assertEqual(result["status"], "no_reviewed_destination")
        self.assertIsNone(result["area"])
