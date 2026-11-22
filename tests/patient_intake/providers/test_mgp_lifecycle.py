import json
import unittest
from unittest.mock import Mock

from app.patient_intake.providers.mgp_lifecycle import AnonymousSurvey, SandboxSession
from app.patient_intake.providers.transport import Budget


def record(code, **data):
    return code, "application/json", json.dumps(data).encode(), {}


USER, PATIENT, SURVEY = (f"00000000-0000-0000-0000-{n:012d}" for n in (1, 2, 3))
TOKEN = record(200, access_token="fictional", token_type="Bearer", expires_in=30)
CREATES = [record(201, id=USER), record(201, id=PATIENT, user_id=USER),
           record(201, id=SURVEY, patient_id=PATIENT, type="triage")]
EMPTY = (204, "", b"", {})


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Mock()
        self.now = 0
        self.budget = Budget(10)
        self.session = SandboxSession(exchange=self.exchange, attempts=10, enabled=True, clock=lambda: self.now)
        self.survey = AnonymousSurvey(self.session, budget=self.budget)

    def login(self):
        return self.session.authenticate("fixture-mgp", "fictional-id", "fictional-key", encounter=self.budget)

    def test_full_anonymous_lifecycle(self):
        self.exchange.side_effect = [TOKEN, *CREATES, EMPTY, EMPTY, EMPTY]
        self.assertEqual(self.login().status, "authenticated")
        self.assertEqual(self.survey.create(), "created")
        self.assertEqual(self.survey.survey_id, SURVEY)
        self.assertEqual(self.survey.create(), "already_started")
        self.assertEqual(self.survey.dispose(), "disposed")
        self.assertIsNone(self.survey.survey_id)
        self.assertEqual(self.survey.dispose(), "disposed")
        calls = [call.args for call in self.exchange.call_args_list]
        self.assertTrue(all(c[0] == "api.dev.infermedica.com" for c in calls))
        self.assertEqual([c[1] for c in calls], ["POST"] * 4 + ["DELETE"] * 3)
        self.assertEqual(calls[0][2], "/api/auth/token")
        self.assertTrue(calls[0][3]["Authorization"].startswith("Basic "))
        self.assertEqual([json.loads(c[4]) for c in calls[1:4]],
                         [{}, {"user_id": USER}, {"type": "triage", "patient_id": PATIENT}])
        self.assertTrue(all(c[3]["Authorization"] == "Bearer fictional" and "Instance-Id" not in c[3]
                            for c in calls[1:]))
        self.assertEqual([c[2].split("/")[-2:] for c in calls[4:]],
                         [["surveys", SURVEY], ["patients", PATIENT], ["users", USER]])

    def test_unknown_creation_never_claims_disposal(self):
        self.exchange.side_effect = [TOKEN, CREATES[0], TimeoutError(), EMPTY]
        self.login()
        self.assertEqual(self.survey.create(), "timeout")
        self.assertEqual(self.survey.dispose(), "creation_unresolved")
        self.assertEqual(self.survey.dispose(), "creation_unresolved")
        self.assertEqual(self.exchange.call_count, 4)

    def test_disposal_can_resume_only_remaining_deletes(self):
        self.exchange.side_effect = [TOKEN, *CREATES, EMPTY, TimeoutError(), record(404), EMPTY]
        self.login()
        self.assertEqual(self.survey.create(), "created")
        self.assertEqual(self.survey.dispose(), "disposal_pending")
        self.assertIsNone(self.survey.survey_id)
        self.assertEqual(self.survey.dispose(), "disposed")
        calls = [c.args[2].split("/")[-1] for c in self.exchange.call_args_list[4:]]
        self.assertEqual(calls, [SURVEY, PATIENT, PATIENT, USER])

    def test_mismatched_patient_binding_never_deleted(self):
        self.exchange.side_effect = [TOKEN, CREATES[0], record(201, id=PATIENT, user_id=SURVEY), EMPTY]
        self.login()
        self.assertEqual(self.survey.create(), "invalid_response")
        self.assertIsNone(self.survey.survey_id)
        self.assertEqual(self.survey.dispose(), "creation_unresolved")
        self.assertTrue(self.exchange.call_args.args[2].endswith("/users/" + USER))

    def test_disabled_and_expired_token_cannot_start_api_calls(self):
        disabled = SandboxSession(exchange=self.exchange, attempts=12)
        self.assertEqual(disabled.authenticate("a", "b", "c", encounter=self.budget).status, "unavailable")
        self.exchange.assert_not_called()
        self.exchange.side_effect = [TOKEN]
        self.login()
        self.now = 30
        self.assertEqual(self.survey.create(), "access_denied")
        self.assertEqual(self.exchange.call_count, 1)

    def test_prefill_requires_confirmed_current_present_from_same_edition(self):
        review = {"origin": "patient_review", "decision": "confirm", "patient_presence": "present",
                  "candidate": {"temporality": "current", "presence": "present", "concept_id": "s_1"}}
        self.assertEqual(self.survey.create(confirmed_initial=[review]), "unsupported_correction")
        self.assertEqual(self.survey.create(confirmed_initial=[dict(review, decision="uncertain")],
                                            prefill_enabled=True), "unsupported_correction")
        self.exchange.assert_not_called()
        self.assertEqual(self.survey.create(confirmed_initial=[review], prefill_enabled=True), "unsupported_correction")
        demographics = {"age_years": 30, "sex": "female"}
        patient = record(201, user_id=USER, id=PATIENT, sex="female", age={"value": 30, "unit": "year"})
        self.exchange.side_effect = [TOKEN, CREATES[0], patient, CREATES[2]]
        self.login()
        self.assertEqual(self.survey.create(confirmed_initial=[review], prefill_enabled=True,
                                            demographics=demographics), "created")
        self.assertEqual(json.loads(self.exchange.call_args.args[4])["evidence"],
                         [{"id": "s_1", "choice_id": "present", "source": "initial"}])
