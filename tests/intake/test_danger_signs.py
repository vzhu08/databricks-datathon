"""Offline warning-policy checks using invented structured answers only."""

import itertools
import json
import unittest

from app.intake.danger_signs import (
    evaluate_danger_signs, message_catalogue, source_catalogue, warning_catalogue,
)


SIGNS = ("chest_pain", "stroke_like", "severe_breathing_difficulty", "unresponsive",
         "heavy_bleeding")
QUESTIONS = tuple("warning." + sign for sign in SIGNS)
NO = dict.fromkeys(QUESTIONS, "no")


class DangerSignsTests(unittest.TestCase):
    def test_all_finite_partial_visitor_screens(self):
        # 5^5 cases: including absent, unknown and contradictory answers.
        for values in itertools.product((None, "no", "yes", "unknown", "conflicting"), repeat=5):
            answers = {q: v for q, v in zip(QUESTIONS, values) if v is not None}
            result = evaluate_danger_signs(answers)
            positives = ["intake.warning." + sign + ".v1"
                         for sign, v in zip(SIGNS, values) if v == "yes"]
            expected = ("emergency_escalation" if positives else "no_reported_warning"
                        if all(v == "no" for v in values) else "more_information_needed")
            self.assertEqual((result["state"], result["rule_ids"]), (expected, positives), values)
            self.assertNotIn("request", result)

    def test_two_layers_cannot_erase_explicit_signs(self):
        for q in QUESTIONS:
            for first, second in itertools.product(("no", "yes", "unknown", "conflicting"), repeat=2):
                with self.subTest(q=q, first=first, second=second):
                    result = evaluate_danger_signs({q: first}, known_answers={**NO, q: second})
                    tokens = {first, second}
                    expected = ("emergency_escalation" if "yes" in tokens else
                                "no_reported_warning" if tokens == {"no"} else "more_information_needed")
                    self.assertEqual(result["state"], expected)
                    conflict = ("conflicting" in tokens or tokens in ({"yes", "no"}, {"no", "unknown"}))
                    self.assertEqual(q in result["conflicting_question_ids"], conflict)
                    self.assertEqual(q in result["unknown_question_ids"], "unknown" in tokens)

    def test_missing_negated_historical_and_malformed_observations(self):
        for q in QUESTIONS:
            others = {key: "no" for key in QUESTIONS if key != q}
            self.assertEqual(evaluate_danger_signs(others)["missing_question_ids"], [q])
            for value in (False, True, None, [], {}, 1, "no symptoms", "historical", "YES"):
                result = evaluate_danger_signs({q: value}, known_answers=others)
                self.assertEqual(result["state"], "more_information_needed")
                self.assertEqual(result["invalid_question_ids"], [q])
                self.assertEqual(result["rule_ids"], [])
        self.assertEqual(evaluate_danger_signs({"context.onset": "new"})["missing_question_ids"],
                         list(QUESTIONS))
        self.assertEqual(evaluate_danger_signs({**NO, "warning.unlisted": "yes"})["state"],
                         "more_information_needed")

    def test_escalation_survives_invalid_layer_and_other_missing_answers(self):
        for sign, q in zip(SIGNS, QUESTIONS):
            result = evaluate_danger_signs([], known_answers={q: "yes"})
            self.assertEqual(result["rule_ids"], [f"intake.warning.{sign}.v1"])
            self.assertEqual(result["state"], "emergency_escalation")
            self.assertEqual(result["missing_question_ids"], [key for key in QUESTIONS if key != q])
        self.assertEqual(evaluate_danger_signs(None, known_answers=NO)["state"],
                         "more_information_needed")

    def test_catalogues_resolve_and_are_independent_of_caller_mutation(self):
        all_yes = dict.fromkeys(QUESTIONS, "yes")
        result = evaluate_danger_signs(all_yes)
        rules, sources, messages = warning_catalogue(), source_catalogue(), message_catalogue()
        self.assertEqual([row["question_id"] for row in rules.values()], list(QUESTIONS))
        self.assertIn("mha_erss_112", result["source_ids"])
        self.assertIn("112", messages[result["message_ids"][0]])
        for rule in result["rule_ids"]:
            self.assertTrue(rules[rule]["rationale"])
            self.assertLessEqual(set(rules[rule]["source_ids"]), set(result["source_ids"]))
        for src in result["source_ids"]:
            self.assertTrue(sources[src]["url"].startswith("https://"))
        for answers in (all_yes, {}, NO):
            decision = evaluate_danger_signs(answers)
            self.assertLessEqual(set(decision["message_ids"] + decision["reason_codes"]), set(messages))
            self.assertEqual(json.loads(json.dumps(decision)), decision)
        rules[result["rule_ids"][0]]["source_ids"].clear()
        sources["mha_erss_112"].clear()
        messages.clear()
        self.assertTrue(warning_catalogue()[result["rule_ids"][0]]["source_ids"])
        self.assertTrue(source_catalogue()["mha_erss_112"]["title"])
        self.assertTrue(message_catalogue())
