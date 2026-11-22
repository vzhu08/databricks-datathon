import json
import unittest

from app.patient_intake import interview
from app.patient_intake.interview import (
    InterviewLimitReached,
    PatientInterview,
    QuestionBinding,
    UnsupportedInterview,
    _skip_requested,
    _validate_item_answers,
    _validate_quantity_answer,
    _validate_quantity_value,
    validate_answer,
)


class AnswerValidationTests(unittest.TestCase):
    def setUp(self):
        self.issued = QuestionBinding("invented-encounter", 2, "new-issued-question")

    def validate(self, answer, **overrides):
        kwargs = {
            "submitted": self.issued, "issued": self.issued, "kind": "single",
            "option_ids": ("recorded", "not-recorded", "unknown"),
        }
        return validate_answer(answer, **{**kwargs, **overrides})

    def test_rejects_old_revision_different_issuance_and_cross_encounter(self):
        for old in (
            QuestionBinding("invented-encounter", 1, "new-issued-question"),
            QuestionBinding("invented-encounter", 2, "old-issued-question"),
            QuestionBinding("another-encounter", 2, "new-issued-question"),
            None,
        ):
            with self.subTest(binding=old), self.assertRaisesRegex(ValueError, "question has changed"):
                self.validate("recorded", submitted=old)

    def test_accepts_unknown_without_treating_omission_as_a_negative(self):
        self.assertEqual(self.validate("unknown"), ("unknown",))
        for omitted in ("", None, False, [], ["unknown"]):
            with self.subTest(answer=omitted), self.assertRaises(ValueError):
                self.validate(omitted)

    def test_rejects_unissued_ids_without_echoing_them(self):
        canary = "invented-other-question-selection"
        with self.assertRaises(ValueError) as raised:
            self.validate(canary)
        self.assertNotIn(canary, str(raised.exception))

    def test_validates_multiple_choices_and_preserves_issued_order(self):
        kwargs = {
            "kind": "multiple", "option_ids": ("first", "second", "unknown"),
            "exclusive_option_ids": ("unknown",), "max_selections": 2,
        }
        self.assertEqual(self.validate(["second", "first"], **kwargs), ("first", "second"))
        self.assertEqual(self.validate(["unknown"], **kwargs), ("unknown",))
        for bad in ([], ["first", "first"], ["first", "unknown"], ["first", "other"], "first",
                    ["first", "second", "unknown"]):
            with self.subTest(answer=bad), self.assertRaises(ValueError):
                self.validate(bad, **kwargs)

    def test_clarification_text_remains_verbatim(self):
        clarification = "  Invented follow-up: not sure at all.\n"
        self.assertEqual(
            self.validate(clarification, kind="text", max_text_chars=len(clarification)),
            clarification,
        )
        with self.assertRaises(ValueError):
            self.validate(clarification, kind="text", max_text_chars=8)


class StructuredInputValidationTests(unittest.TestCase):
    def test_only_explicit_permitted_skip_can_omit_an_answer(self):
        self.assertTrue(_skip_requested({"skip": True}, optional=True))
        for omitted in (None, [], {}):
            self.assertFalse(_skip_requested(omitted, optional=True))
        for malformed in ({"skip": False}, {"skip": 1}, {"skip": True, "value": 1}):
            with self.subTest(answer=malformed), self.assertRaises(ValueError):
                _skip_requested(malformed, optional=True)
        with self.assertRaises(ValueError):
            _skip_requested({"skip": True}, optional=False)

    def test_item_answers_preserve_explicit_unknown_and_absent_in_issued_order(self):
        answer = [{"id": "b", "presence": "absent"}, {"id": "a", "presence": "unknown"}]
        result = _validate_item_answers(answer, issued_ids=("a", "b", "optional"), required_ids=("a", "b"))
        self.assertEqual(result, [answer[1], answer[0]])
        self.assertEqual(len(answer), 2)

    def test_item_answers_reject_omission_duplicates_and_unissued_invented_ids(self):
        good = {"id": "a", "presence": "unknown"}
        for bad in (
            None, [], [good], [good, good], [good, {"id": "foreign", "presence": "absent"}],
            [good, {"id": "b", "presence": False}], [good, {"id": "b"}],
            [good, {"id": "b", "presence": "unknown", "authority": "fake"}],
        ):
            with self.subTest(answer=bad), self.assertRaises(ValueError):
                _validate_item_answers(bad, issued_ids=("a", "b"), required_ids=("a", "b"))

    def test_quantity_uses_inclusive_provider_bounds_and_preserves_exact_value(self):
        self.assertEqual(_validate_quantity_value(0, minimum=0, maximum=24, integer_only=True), 0)
        self.assertEqual(_validate_quantity_value(24, minimum=0, maximum=24, integer_only=True), 24)
        self.assertEqual(_validate_quantity_value(0.125, minimum=0.1, maximum=5, integer_only=False), 0.125)
        self.assertEqual(_validate_quantity_value(1.0, minimum=0, maximum=1, integer_only=False), 1.0)
        for bad in (None, False, "1", 1.0, -1, 25, float("nan"), float("inf"), 2**64):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                _validate_quantity_value(bad, minimum=0, maximum=24, integer_only=True)

    def test_quantity_rejects_missing_or_inconsistent_metadata(self):
        for minimum, maximum, integer_only in (
            (None, 1, False), (1, 0, False), (0, float("inf"), False),
            (False, 3, False), (0.1, 0.9, True), (0, 1, "true"),
        ):
            with self.subTest(bounds=(minimum, maximum, integer_only)), self.assertRaises(ValueError):
                _validate_quantity_value(0, minimum=minimum, maximum=maximum, integer_only=integer_only)

    def test_quantity_uses_selected_issued_unit_without_inference_or_conversion(self):
        units = {
            "months": {"minimum": 1, "maximum": 24, "integer_only": True},
            "years": {"minimum": 1, "maximum": 2, "integer_only": True},
        }
        answer = {"value": 24, "unit_id": "months"}
        self.assertEqual(_validate_quantity_answer(answer, issued_units=units), answer)
        for bad in ({"value": 24, "unit_id": "years"}, {"value": 2, "unit_id": "decades"},
                    {"value": 1}, {"value": 2, "unit_id": ["years"]}):
            with self.subTest(answer=bad), self.assertRaises(ValueError):
                _validate_quantity_answer(bad, issued_units=units)


class InterviewTests(unittest.TestCase):
    def setUp(self):
        self.description = "  Invented report: I noticed a strange thumping yesterday.  "
        self.context = {"age_years": 29, "language": "en-IN"}
        self.initial = interview.start(self.description, self.context)

    def issue(self, current, kind, *, issuance="issued-1", presence="present", source_ref="description"):
        options = [{"id": "reported", "label": "Reported"}, {"id": "unknown", "label": "Unsure"}]
        proposal = {"id": "reused-vendor-question", "kind": kind, "prompt": "Invented follow-up", "options": options}
        if kind == "text":
            proposal["options"] = []
        elif kind == "evidence_review":
            proposal["options"] = [{"id": option, "label": "untrusted copy"}
                                   for option in ("confirm", "uncertain", "disagree")]
            proposal["evidence"] = {
                "concept_id": "invented-concept", "label": "Invented observation",
                "presence": presence, "temporality": "current", "source_ref": source_ref,
            }
        return {**interview.prepare_question(proposal, current), "issuance_id": issuance}

    def test_novel_text_survives_json_storage_and_follow_up(self):
        self.assertEqual(self.initial["source"]["description"], self.description)
        self.assertEqual(self.initial["patient_evidence"], [])
        text = self.issue(self.initial, "text")
        clarification = "  Invented follow-up: I am uncertain about the timing.\n"
        updated = interview.answer(self.initial, text, text["issuance_id"], clarification)
        self.assertEqual(json.loads(json.dumps(updated)), updated)
        self.assertEqual(updated["answers"][0]["answer"], clarification)
        self.assertEqual(updated["patient_evidence"], [])
        self.assertEqual(self.initial["answers"], [])
        review = self.issue(updated, "evidence_review", source_ref=text["issuance_id"], issuance="issued-2")
        confirmed = interview.answer(updated, review, review["issuance_id"], "confirm")
        evidence = confirmed["patient_evidence"][0]
        self.assertEqual(evidence["candidate"]["source_ref"], text["issuance_id"])
        self.assertEqual(evidence["patient_presence"], "present")
        self.assertEqual(evidence["origin"], "patient_review")
        self.assertFalse(interview.has_unresolved_evidence(confirmed))
        self.assertEqual(updated["patient_evidence"], [])

    def test_view_uses_server_issuance_and_discards_provider_review_labels(self):
        review = self.issue(self.initial, "evidence_review")
        view = interview.question_view(review)
        self.assertEqual(view["issuance_id"], "issued-1")
        self.assertEqual(set(view["evidence"]), {"label", "presence", "temporality"})
        self.assertEqual(view["prompt"], "Does this observation match your statement?")
        self.assertNotIn(review["id"], json.dumps(view))
        self.assertNotIn(review["interview_id"], json.dumps(view))
        self.assertNotIn("untrusted copy", json.dumps(view))
        view["options"].clear()
        self.assertEqual(len(review["options"]), 3)

    def test_disagreement_unknown_and_contradictions_are_preserved(self):
        first = self.issue(self.initial, "evidence_review", presence="present")
        for decision in ("uncertain", "disagree"):
            with self.subTest(decision=decision):
                unresolved = interview.answer(self.initial, first, first["issuance_id"], decision)
                row = unresolved["patient_evidence"][0]
                self.assertEqual((row["patient_presence"], row["decision"]), ("unknown", decision))
                self.assertEqual(row["candidate"]["presence"], "present")
                self.assertTrue(interview.has_unresolved_evidence(unresolved))
        present = interview.answer(self.initial, first, first["issuance_id"], "confirm")
        opposite = self.issue(present, "evidence_review", issuance="issued-2", presence="absent")
        conflict = interview.answer(present, opposite, opposite["issuance_id"], "confirm")
        self.assertTrue(interview.has_unresolved_evidence(conflict))
        self.assertEqual([row["patient_presence"] for row in conflict["patient_evidence"]],
                         ["present", "absent"])

    def test_new_description_or_context_rejects_same_count_stale_submission(self):
        question = self.issue(self.initial, "single")
        for restarted in (interview.start(self.description + " Changed.", self.context),
                          interview.start(self.description, {**self.context, "age_years": 30})):
            with self.subTest(restarted=restarted["interview_id"]):
                self.assertEqual(restarted["answers"], [])
                self.assertEqual(restarted["patient_evidence"], [])
                with self.assertRaisesRegex(ValueError, "question has changed"):
                    interview.answer(restarted, question, question["issuance_id"], "reported")
        new_question = self.issue(self.initial, "single", issuance="new-issue")
        self.assertEqual(new_question["id"], question["id"])
        for stale_id in (question["issuance_id"], question["id"]):
            with self.assertRaisesRegex(ValueError, "question has changed"):
                interview.answer(self.initial, new_question, stale_id, "reported")

    def test_multiselect_output_and_replay_guard(self):
        question = self.issue(self.initial, "multiple")
        next_state = interview.answer(self.initial, question, question["issuance_id"], ["unknown", "reported"])
        self.assertEqual(next_state["answers"][0]["answer"], ["reported", "unknown"])
        with self.assertRaisesRegex(ValueError, "question has changed"):
            interview.answer(next_state, question, question["issuance_id"], ["reported"])

    def test_malformed_provider_question_or_foreign_evidence_cannot_issue(self):
        with self.assertRaisesRegex(ValueError, "current statement"):
            self.issue(self.initial, "evidence_review", source_ref="foreign-answer")
        for question in (
            {"id": "test", "kind": "text", "prompt": "Text", "options": [], "authority": "clinician"},
            {"id": "test", "kind": "single", "prompt": "Choose", "options": []},
            {"id": "test", "kind": "unknown", "prompt": "What?", "options": []},
        ):
            with self.subTest(kind=question["kind"]), self.assertRaises(ValueError):
                interview.prepare_question(question, self.initial)
        self.assertEqual(self.initial["answers"], [])

    def test_configured_limits_and_unsupported_context_are_explicit(self):
        limited = PatientInterview(max_turns=1, supported_age_range=(18, 90), supported_languages=("en-IN",))
        for context in ({}, {**self.context, "age_years": 8}, {**self.context, "language": "sv"}):
            with self.subTest(context=context), self.assertRaises(UnsupportedInterview) as raised:
                limited.start(self.description, context)
            self.assertEqual(raised.exception.code, "unsupported_context")
        self.assertEqual(interview.start(self.description, {})["context"], {"age_years": None, "language": None})
        first = limited.start(self.description, self.context)
        question = self.issue(first, "single")
        current = limited.answer(first, question, question["issuance_id"], "reported")
        with self.assertRaises(InterviewLimitReached) as raised:
            limited.prepare_question({}, current)
        self.assertEqual(raised.exception.code, "interview_limit")
        with self.assertRaises(InterviewLimitReached):
            limited.answer(current, question, question["issuance_id"], "reported")


if __name__ == "__main__":
    unittest.main()
