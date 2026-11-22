import unittest

from app.patient_intake.interview import QuestionBinding, validate_answer


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


if __name__ == "__main__":
    unittest.main()
