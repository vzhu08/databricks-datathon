import unittest
from unittest.mock import patch

from app.intake.referral_gate import evaluate_referral_gate, referral_catalogue
from app.ranking.evidence import MATCHERS
from app.ranking.urgency import WEIGHTS, rank_campuses


SCENARIO_ID = "fictional-intake"
SCENARIO_VERSION = "1"
AUTHORITY_BY_SERVICE = {
    "dialysis": "simulated_treatment_plan",
    "mri": "simulated_clinician_referral",
    "trauma_care": "simulated_clinician_assessment",
}


def plan_for(service="mri", **changes):
    plan = {
        "scenario_id": SCENARIO_ID,
        "scenario_version": SCENARIO_VERSION,
        "synthetic": True,
        "authority": AUTHORITY_BY_SERVICE[service],
        "service": service,
        "urgency": "routine",
        "required_capabilities": [],
        "preferred_capabilities": [],
    }
    plan.update(changes)
    return plan


def evaluate(plan, *, service="mri", scenario_id=SCENARIO_ID, scenario_version=SCENARIO_VERSION):
    return evaluate_referral_gate(service=service, clinician_plan=plan,
                                  scenario_id=scenario_id, scenario_version=scenario_version)


class ReferralGateTests(unittest.TestCase):
    def assert_blocked(self, result, state, reason, confirmation):
        self.assertEqual(result, {
            "state": state,
            "reason_codes": [reason],
            "clinician_confirmation": confirmation,
            "candidate_request": None,
        })
        self.assertIn(reason, referral_catalogue()["reasons"])

    def test_all_explicit_service_plans_produce_ranker_compatible_candidates(self):
        self.assertEqual(set(AUTHORITY_BY_SERVICE), set(MATCHERS))
        self.assertEqual(set(AUTHORITY_BY_SERVICE.values()), set(referral_catalogue()["authorities"]))
        for service, authority in AUTHORITY_BY_SERVICE.items():
            for urgency in WEIGHTS:
                with self.subTest(service=service, urgency=urgency):
                    result = evaluate(plan_for(service, authority=authority, urgency=urgency),
                                      service=service)
                    self.assertEqual(result, {
                        "state": "eligible",
                        "reason_codes": ["referral_plan_eligible"],
                        "clinician_confirmation": "present",
                        "candidate_request": {
                            "service": service,
                            "urgency": urgency,
                            "required_capabilities": [],
                            "preferred_capabilities": [],
                        },
                    })
                    candidate = result["candidate_request"]
                    ranking = rank_campuses(candidate["service"], candidate["urgency"], [],
                                           as_of="2026-11-21", travel_metric="travel_minutes",
                                           travel_budget=20, required=candidate["required_capabilities"],
                                           preferred=candidate["preferred_capabilities"])
                    self.assertEqual(ranking["status"], "no_match")
        self.assertIn("referral_plan_eligible", referral_catalogue()["reasons"])

    def test_symptoms_and_service_selection_do_not_supply_authority(self):
        self.assert_blocked(evaluate(None, service=None), "clinician_assessment_needed",
                            "referral_service_unspecified", "required")
        for service in AUTHORITY_BY_SERVICE:
            with self.subTest(service=service):
                self.assert_blocked(evaluate(None, service=service), "clinician_assessment_needed",
                                    "referral_plan_missing", "required")

    def test_unsupported_and_mixed_service_values_do_not_route(self):
        for service in ("trauma", "general_emergency", "stroke", "MRI"):
            with self.subTest(service=service):
                self.assert_blocked(evaluate(plan_for(), service=service), "unsupported_care_need",
                                    "referral_service_unsupported", "not_required")
        for service in (["mri", "dialysis"], {"service": "mri"}, True, " "):
            with self.subTest(service=service):
                self.assert_blocked(evaluate(plan_for(), service=service), "invalid_input",
                                    "referral_service_unsupported", "invalid")
        self.assert_blocked(evaluate(plan_for(), service=None), "invalid_input",
                            "referral_service_mismatch", "invalid")
        self.assert_blocked(evaluate([plan_for(), plan_for("dialysis")]), "invalid_input",
                            "referral_plan_invalid", "invalid")

    def test_plan_service_and_authority_must_both_match(self):
        self.assert_blocked(evaluate(plan_for("dialysis")), "invalid_input",
                            "referral_service_mismatch", "invalid")
        for authority in (None, True, "simulated_treatment_plan", "visitor_confirmed"):
            with self.subTest(authority=authority):
                self.assert_blocked(evaluate(plan_for(authority=authority)), "invalid_input",
                                    "referral_authority_mismatch", "invalid")

    def test_fictional_plan_is_bound_to_current_scenario_and_edition(self):
        for binding in ({"scenario_id": "another-scenario"}, {"scenario_version": "2"}):
            with self.subTest(binding=binding):
                self.assert_blocked(evaluate(plan_for(), **binding), "invalid_input",
                                    "referral_plan_stale", "invalid")
        for binding in ({"scenario_id": " "}, {"scenario_version": True}):
            with self.subTest(binding=binding):
                self.assert_blocked(evaluate(plan_for(), **binding), "invalid_input",
                                    "referral_plan_invalid", "invalid")

    def test_plan_requires_exact_fields_and_synthetic_marker(self):
        no_synthetic = plan_for()
        del no_synthetic["synthetic"]
        no_preferred = plan_for()
        del no_preferred["preferred_capabilities"]
        for plan in (no_synthetic, no_preferred, plan_for(synthetic=False), plan_for(synthetic=1),
                     plan_for(synthetic="true"), plan_for(scenario_version=1),
                     plan_for(confirmation=True), True):
            with self.subTest(plan=plan):
                self.assert_blocked(evaluate(plan), "invalid_input", "referral_plan_invalid", "invalid")

    def test_invalid_urgency_is_not_replaced_with_a_default(self):
        for urgency in (None, True, [], "", "unknown", "Routine", " routine "):
            with self.subTest(urgency=urgency):
                self.assert_blocked(evaluate(plan_for(urgency=urgency)), "invalid_input",
                                    "referral_urgency_invalid", "invalid")

    def test_explicit_capabilities_are_preserved_and_invalid_arrays_withheld(self):
        plan = plan_for(required_capabilities=["protocol-b", "protocol-a"],
                        preferred_capabilities=["feature-a"])
        candidate = evaluate(plan)["candidate_request"]
        self.assertEqual(candidate["required_capabilities"], ["protocol-b", "protocol-a"])
        self.assertEqual(candidate["preferred_capabilities"], ["feature-a"])
        for field in ("required_capabilities", "preferred_capabilities"):
            for values in (None, "scanner", ("scanner",), [True], [" "], ["a", "a"], ["a", " a "]):
                with self.subTest(field=field, values=values):
                    result = evaluate(plan_for(**{field: values}))
                    self.assert_blocked(result, "invalid_input", "referral_capabilities_invalid", "invalid")

    def test_replay_is_offline_and_returns_independent_results(self):
        plan = plan_for(required_capabilities=["protocol"], preferred_capabilities=["feature"])
        with patch("socket.socket", side_effect=AssertionError("network call")) as sockets:
            result = evaluate(plan)
            self.assertEqual(result, evaluate(plan))
            self.assertIsNone(evaluate(None)["candidate_request"])
            sockets.assert_not_called()
        result["candidate_request"]["required_capabilities"].append("another-protocol")
        result["candidate_request"]["preferred_capabilities"].clear()
        self.assertEqual(evaluate(plan)["candidate_request"]["required_capabilities"], ["protocol"])
        self.assertEqual(evaluate(plan)["candidate_request"]["preferred_capabilities"], ["feature"])

    def test_display_catalogue_is_independent(self):
        catalogue = referral_catalogue()
        self.assertEqual(set(catalogue), {"reasons", "authorities"})
        self.assertTrue(all(label.strip() for labels in catalogue.values() for label in labels.values()))
        catalogue["reasons"].clear()
        catalogue["authorities"].clear()
        self.assertEqual(len(referral_catalogue()["reasons"]), 10)
        self.assertEqual(len(referral_catalogue()["authorities"]), 3)
