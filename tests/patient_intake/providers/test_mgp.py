import json
import unittest
from unittest.mock import Mock

from app.patient_intake.providers.mgp import MgpSurveyCandidate
from app.patient_intake.providers.transport import Budget, Transport

SURVEY = "01234567-0123-0123-0123-0123456789ab"
PREFIX = "/api/mgp/v1/surveys/" + SURVEY
QUESTION = {
    "id": "fictional_question", "answer_type": "choice",
    "question": {"text": "Fictional answer prompt"},
    "meta": {"answers": [{"id": "unknown", "label": "Unsure"}]},
}


def json_response(data):
    return 200, "application/json", json.dumps(data).encode(), {}


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Mock()
        self.transport = Transport(host="fictional.invalid", headers={}, attempts=12, exchange=self.exchange)
        self.survey_for = Mock(side_effect=lambda interview: SURVEY if interview.get("bound") else None)
        self.adapter = MgpSurveyCandidate(
            survey_for=self.survey_for, choices_for=lambda interview, _: interview.get("answer"),
            transport=self.transport, budget=Budget(8), enabled=True,
        )

    def provision_completed(self, level, conditions, serious=()):
        self.exchange.side_effect = [
            json_response(QUESTION), (204, "", b"", {}),
            json_response({"id": SURVEY, "type": "triage", "status": "completed"}),
            json_response({"triage": {"level": level, "description": "Fictional vendor guidance",
                                     "serious": list(serious)}, "conditions": conditions}),
        ]

    def run_interview(self):
        pending = self.adapter.assess({"bound": True})
        return self.adapter.assess({"bound": True, "answer": ["unknown"]},
                                   continuation=pending["continuation"])

    def test_default_disabled_and_unbound_send_nothing(self):
        disabled = MgpSurveyCandidate(transport=self.transport, budget=Budget(8),
                                      survey_for=self.survey_for, choices_for=lambda *_: [])
        self.assertEqual(disabled.assess({"bound": True})["state"], "provider_unavailable")
        self.survey_for.assert_not_called()
        self.assertEqual(self.adapter.assess({"source": "unmatched invented text"})["reason"],
                         "unsupported_correction")
        self.exchange.assert_not_called()

    def test_confirmed_vendor_choice_and_completed_result(self):
        self.provision_completed("consultation", [{"common_name": "Fictional label", "probability": .91}])
        result = self.run_interview()
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["possible_causes"], ["Fictional label"])
        self.assertNotIn("probability", repr(result))
        self.assertEqual(result["next_step"], {"kind": "consultation", "specialty_code": None})
        calls = self.exchange.call_args_list
        self.assertEqual([c.args[1:3] for c in calls], [
            ("GET", PREFIX + "/questions/current"), ("POST", PREFIX + "/questions/current"),
            ("GET", PREFIX), ("GET", PREFIX + "/evidence_assessment"),
        ])
        self.assertEqual(json.loads(calls[1].args[4]), {"answer": {"id": "unknown"}})
        self.assertEqual(self.adapter.assess({"bound": True})["state"], "unsupported")
        self.assertEqual(self.exchange.call_count, 4)

    def test_multiple_choice_submits_only_selected_vendor_ids(self):
        multi = {**QUESTION, "answer_type": "multiple_choice",
                 "meta": {"answers": [{"id": key, "label": key} for key in ("one", "two", "three")]}}
        self.exchange.side_effect = [json_response(multi), json_response(QUESTION)]
        pending = self.adapter.assess({"bound": True})
        self.assertEqual(pending["question"]["kind"], "multiple")
        next_step = self.adapter.assess({"bound": True, "answer": ["one", "three"]},
                                        continuation=pending["continuation"])
        self.assertEqual(next_step["state"], "awaiting_clarification")
        self.assertEqual(json.loads(self.exchange.call_args.args[4]),
                         {"answer": [{"id": "one"}, {"id": "three"}]})
        self.assertNotEqual(next_step["continuation"], pending["continuation"])

    def test_emergency_preserved_with_no_causes_without_navigation(self):
        self.provision_completed("emergency", [])
        result = self.run_interview()
        self.assertEqual(result["state"], "urgent")
        self.assertEqual(result["possible_causes"], [])
        self.assertIsNone(result["next_step"])

    def test_mismatched_continuation_and_invalid_choices_cannot_submit(self):
        self.exchange.return_value = json_response(QUESTION)
        pending = self.adapter.assess({"bound": True})
        incoming = {"bound": True, "answer": ["yes"]}
        self.assertEqual(self.adapter.assess(incoming, continuation="invented")["state"], "unsupported")
        pending["question"]["options"].append({"id": "yes", "label": "Tampered"})
        token = pending["continuation"]
        self.assertEqual(self.adapter.assess(incoming, continuation=token)["state"], "unsupported")
        incoming["answer"] = ["unknown"]
        self.assertEqual(self.adapter.assess(incoming, continuation=token)["state"], "unsupported")
        self.assertEqual(self.exchange.call_count, 1)

    def test_unrepresentable_question_and_empty_get_end_without_assessment(self):
        self.exchange.return_value = json_response({**QUESTION, "answer_type": "symptoms"})
        self.assertEqual(self.adapter.assess({"bound": True})["state"], "unsupported")
        self.assertEqual(self.exchange.call_count, 1)
        another = MgpSurveyCandidate(
            survey_for=self.survey_for, choices_for=lambda *_: [],
            transport=self.transport, budget=Budget(8), enabled=True,
        )
        self.exchange.return_value = (204, "", b"", {})
        self.assertEqual(another.assess({"bound": True})["state"], "unsupported")
        self.assertEqual(self.exchange.call_count, 2)

    def test_result_without_causes_and_without_urgency_is_unsupported(self):
        self.provision_completed("self_care", [])
        self.assertEqual(self.run_interview()["state"], "unsupported")

    def test_provider_level_conflict_is_unavailable(self):
        self.provision_completed("consultation", [], [{"seriousness": "emergency"}])
        self.assertEqual(self.run_interview()["reason"], "invalid_response")

    def test_incomplete_survey_cannot_reuse_early_assessment(self):
        self.exchange.side_effect = [
            json_response(QUESTION), (204, "", b"", {}),
            json_response({"id": SURVEY, "type": "triage", "status": "pending"}),
        ]
        self.assertEqual(self.run_interview()["reason"], "invalid_response")
        self.assertEqual(self.exchange.call_count, 3)
