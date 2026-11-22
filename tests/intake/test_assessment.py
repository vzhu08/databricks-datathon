"""Contract checks at the same entry points used by the finder and offline builder."""
import json
import pickle
import socket
import unittest
from tempfile import TemporaryDirectory
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app.intake import (
    POLICY_VERSION, SCHEMA_VERSION,
    assess_intake, assessment_catalogue, confirm_intake,
)

from app.intake import finder_bridge

WARNINGS = ("chest_pain", "stroke_like", "severe_breathing_difficulty", "unresponsive", "heavy_bleeding")


def fictional_case(service="mri"):
    scenario_id = {"mri": "scheduled_mri", "dialysis": "scheduled_dialysis",
                   "trauma_care": "injury_assessed"}[service]
    fixture = Path(__file__).parent / "scenarios" / "journeys.json"
    scenario = json.loads(fixture.read_text())["scenarios"][scenario_id]
    answers = {"warning." + key: "no" for key in WARNINGS}
    answers["context.severity"] = scenario["known_answers"].get("context.severity", "mild")
    payload = {"schema_version": SCHEMA_VERSION, "mode": "synthetic",
               "scenario_id": scenario["scenario_id"], "input_revision": len(answers), "answers": answers}
    return payload, scenario


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.payload, self.scenario = fictional_case()
        # Any provider, warehouse or network dependency would invalidate offline intake.
        guard = patch.object(socket, "socket", side_effect=AssertionError("unexpected network use"))
        guard.start()
        self.addCleanup(guard.stop)

    def assess(self, receipt=None):
        return assess_intake(self.payload, scenario=self.scenario, confirmation=receipt)

    def confirm(self):
        return confirm_intake(self.payload, scenario=self.scenario)

    def test_envelope_rejects_mode_version_id_revision_types_and_extra_fields(self):
        for key, value in [("mode", "warehouse"), ("schema_version", "intake.v9"),
                           ("scenario_id", "other"), ("input_revision", True), ("input_revision", -1),
                           ("answers", []), ("request", {"service": "mri"}), ("ready", True)]:
            with self.subTest(key=key, value=value):
                payload = {**self.payload, key: value}
                out = assess_intake(payload, scenario=self.scenario)
                self.assertEqual(out["state"], "invalid_input")
                self.assertIsNone(out["request"])
                with self.assertRaises(ValueError):
                    confirm_intake(payload, scenario=self.scenario)
        for key, value in [("synthetic", 1), ("schema_version", "warehouse.v1"), ("known_answers", [])]:
            out = assess_intake(self.payload, scenario={**self.scenario, key: value})
            self.assertEqual(out["state"], "invalid_input")

    def test_all_eligible_paths_require_two_distinct_actions(self):
        for service in ("dialysis", "mri", "trauma_care"):
            with self.subTest(service=service):
                self.payload, self.scenario = fictional_case(service)
                initial = self.assess()
                self.assertEqual(initial["state"], "confirmation_required")
                self.assertEqual(initial["clinician_confirmation"], "present")
                self.assertIsNone(initial["request"])
                out = self.assess(self.confirm())
                self.assertEqual(out["state"], "ready")
                self.assertEqual(out["confirmation_status"], "current")
                self.assertEqual(out["request"], {
                    "service": service, "urgency": "time_sensitive" if service == "trauma_care" else "routine",
                    "required_capabilities": [], "preferred_capabilities": [],
                })
                for key in ("scenario_id", "scenario_version", "input_revision", "input_fingerprint",
                            "policy_version", "schema_version", "care_summary"):
                    self.assertEqual(initial[key], out[key])
                out["request"]["required_capabilities"].append("mutated-result")
                self.assertEqual(initial["care_summary"], out["care_summary"])
                self.assertEqual(self.scenario["clinician_plan"]["required_capabilities"], [])

    def test_canonical_order_and_json_round_trip_replay(self):
        receipt = self.confirm()
        original = self.assess(receipt)
        self.payload["answers"] = dict(reversed(self.payload["answers"].items()))
        self.scenario = json.loads(json.dumps(self.scenario, sort_keys=True))
        self.assertEqual(original, self.assess(receipt))
        self.assertEqual(json.loads(json.dumps(original)), original)

    def test_edits_revoke_confirmation_even_when_answer_count_stays_constant(self):
        receipt = self.confirm()
        for change in ("answer", "revision", "edition", "plan", "narrative", "policy"):
            self.payload, self.scenario = fictional_case()
            if change == "answer":
                self.payload["answers"]["context.severity"] = "moderate"
            elif change == "revision":
                self.payload["input_revision"] += 1
            elif change == "edition":
                self.scenario["scenario_version"] = self.scenario["clinician_plan"]["scenario_version"] = "2"
            elif change == "plan":
                self.scenario["clinician_plan"]["required_capabilities"] = ["new capability"]
            elif change == "narrative":
                self.scenario["presenting_problem"] += " Another fictional detail."
            with self.subTest(change=change), patch("app.intake.assessment.POLICY_VERSION",
                    "intake-policy.changed" if change == "policy" else POLICY_VERSION):
                out = self.assess(receipt)
                self.assertEqual(out["confirmation_status"], "stale")
                expected = "invalid_input" if change in ("edition", "plan", "narrative") else "confirmation_required"
                self.assertEqual(out["state"], expected)
                self.assertIsNone(out["request"])

    def test_only_reviewed_story_and_facts_can_reach_ranking(self):
        p, s = self.payload, self.scenario
        self.assertEqual(s["known_answers"]["warning.chest_pain"], "no")
        receipt = self.confirm()
        with patch.object(finder_bridge, "rank_campuses", wraps=finder_bridge.rank_campuses) as rank:
            good = finder_bridge.find_care_for_intake(p, scenario=s, confirmation=receipt, origin_id="central")
            self.assertTrue(good["finder"]["ranked"])
            self.assertEqual(good["assessment"]["request"]["service"], "mri")
            rank.assert_called_once()
            rank.reset_mock()

            for changed in (dict(s, presenting_problem="Current chest pain"),
                            dict(s, known_answers={**s["known_answers"], "context.onset": "recent"}),
                            dict(s, clinician_plan={**s["clinician_plan"], "urgency": "highest"}),
                            dict(s, presenting_problem=s["presenting_problem"] + " Another sentence.")):
                with self.subTest(story=changed["presenting_problem"]):
                    for previous in (None, receipt):
                        result = finder_bridge.find_care_for_intake(
                            p, scenario=changed, confirmation=previous, origin_id="central")
                        assessment = result["assessment"]
                        self.assertEqual(assessment["state"], "invalid_input")
                        self.assertEqual(assessment["reason_codes"], ["intake_scenario_unreviewed"])
                        self.assertIsNone(assessment["request"])
                        self.assertIsNone(assessment["care_summary"])
                        self.assertIsNone(result["finder"])
                    with self.assertRaises(ValueError):
                        confirm_intake(p, scenario=changed)
            rank.assert_not_called()

    def test_packaged_manifest_covers_each_shipped_edition(self):
        from app.intake.assessment import _edition_is_reviewed
        scripts = json.loads((Path(__file__).parent / "scenarios/journeys.json").read_text())["scenarios"]
        for scenario in scripts.values():
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertTrue(_edition_is_reviewed(scenario))
                changed = {**scenario, "presenting_problem": scenario["presenting_problem"] + " (edited)"}
                self.assertFalse(_edition_is_reviewed(changed))

    def test_unavailable_or_ambiguous_manifest_withholds_search_and_preserves_warnings(self):
        from app.intake.assessment import _load_reviewed_editions
        row = {"scenario_id": "example", "scenario_version": "1", "sha256": "a" * 64}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pins.json"
            for content in (None, "{", "null", json.dumps({"schema_version": "bad", "editions": [row]}),
                            json.dumps({"schema_version": "intake.editions.v1", "editions": [row, row]})):
                if content is not None:
                    path.write_text(content)
                pins = _load_reviewed_editions(path)
                self.assertFalse(pins)
            with patch("app.intake.assessment._REVIEWED_EDITIONS", pins):
                self.assertEqual(self.assess()["reason_codes"], ["intake_scenario_unreviewed"])
                self.payload["answers"]["warning.chest_pain"] = "yes"
                self.assertEqual(self.assess()["state"], "emergency_escalation")

    def test_serialized_results_and_unissued_receipts_cannot_confirm(self):
        receipt = self.confirm()
        ready = self.assess(receipt)
        for fake in (True, ready, ready["care_summary"], ready["input_fingerprint"], type(receipt)()):
            out = self.assess(fake)
            self.assertEqual(out["confirmation_status"], "invalid")
            self.assertIsNone(out["request"])
        with self.assertRaises(TypeError):
            pickle.dumps(receipt)
        with self.assertRaises(TypeError):
            json.dumps(receipt)

    def test_known_warning_wins_over_previous_ready_missing_answers_and_conflicts(self):
        receipt = self.confirm()
        for sign in WARNINGS:
            with self.subTest(sign=sign):
                self.payload, self.scenario = fictional_case()
                self.scenario["known_answers"] = {"warning." + sign: "yes"}
                self.payload["answers"] = {"warning." + sign: "no", "context.age_group": "unknown"}
                out = self.assess(receipt)
                self.assertEqual(out["state"], "emergency_escalation")
                self.assertEqual(out["message_ids"][0], "intake.warning.emergency.v1")
                self.assertTrue(out["rule_ids"] and out["source_ids"])
                self.assertEqual(out["next_question_ids"], [])
                self.assertIsNone(out["care_summary"])
                self.assertIsNone(out["request"])
                with self.assertRaises(ValueError):
                    self.confirm()

    def test_missing_unknown_conflicting_and_malformed_answers(self):
        key = "warning.heavy_bleeding"
        self.scenario["known_answers"].pop(key)
        self.payload["answers"].pop(key)
        pending = self.assess()
        self.assertEqual(pending["next_question_ids"], [key])
        for value in ("unknown", "conflicting", "not today", False, [], {}):
            with self.subTest(value=value):
                self.payload["answers"][key] = value
                out = self.assess()
                self.assertIn(out["state"], ("more_information_needed", "invalid_input"))
                self.assertIn(key, out["unknowns"])
                self.assertIsNone(out["request"])
        self.payload, self.scenario = fictional_case()
        self.payload["answers"]["invented.key"] = "no"
        self.assertEqual(self.assess()["state"], "invalid_input")

    def test_symptom_only_or_unsupported_concerns_withhold_search(self):
        self.scenario.update(clinician_plan=None, service=None)
        for concern in ("injury", "kidney_symptom", "cardiac", "stroke", "general_medical", "other"):
            with self.subTest(concern=concern):
                self.scenario["concern_category"] = concern
                out = self.assess()
                self.assertEqual(out["state"], "clinician_assessment_needed" if concern in
                                 ("injury", "kidney_symptom") else "unsupported_care_need")
                self.assertEqual(out["concerns"][0]["category"], concern)
                self.assertTrue(out["concerns"][0]["source_ids"])
                self.assertIsNone(out["request"])
                with self.assertRaises(ValueError):
                    self.confirm()
        self.payload, self.scenario = fictional_case()
        self.scenario["concern_category"] = "injury"
        self.assertEqual(self.assess()["state"], "invalid_input")

    def test_unsupported_need_stops_before_nonessential_context(self):
        self.scenario.update(concern_category="general_medical", clinician_plan=None, service=None,
                             known_answers={})
        self.payload["answers"].pop("context.severity")
        out = self.assess()
        self.assertEqual(out["state"], "unsupported_care_need")
        self.assertEqual(out["next_question_ids"], [])
        self.assertIsNone(out["request"])

    def test_referral_and_scope_failures_never_return_cached_success(self):
        receipt = self.confirm()
        self.scenario["clinician_plan"]["scenario_version"] = "obsolete"
        self.assertIsNone(self.assess(receipt)["request"])
        for field, value in (("context.age_group", "child"), ("context.pregnancy", "pregnant")):
            self.payload, self.scenario = fictional_case()
            self.scenario["known_answers"][field] = value
            self.assertEqual(self.assess(receipt)["state"], "unsupported_care_need")
            self.assertIsNone(self.assess(receipt)["request"])
        self.scenario["known_answers"]["warning.chest_pain"] = "yes"
        self.assertEqual(self.assess(receipt)["state"], "emergency_escalation")

    def test_catalogue_entries_and_input_independence(self):
        before = deepcopy([self.payload, self.scenario])
        catalogue = assessment_catalogue()
        for out in [self.assess(), self.assess(self.confirm())]:
            self.assertIn(out["message_ids"][0], catalogue["messages"])
            self.assertIn(out["concerns"][0]["category"], catalogue["concerns"])
        self.assertEqual(before, [self.payload, self.scenario])
        catalogue["reasons"].clear()
        self.assertTrue(assessment_catalogue()["reasons"])
