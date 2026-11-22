import json
import unittest

from app.intake.danger_signs import source_catalogue
from app.intake.questions import edit_answers, next_question, question_catalogue


WARNINGS = (
    "warning.chest_pain", "warning.stroke_like", "warning.severe_breathing_difficulty",
    "warning.unresponsive", "warning.heavy_bleeding",
)
CONTEXT = {
    "context.age_group": "adult",
    "context.pregnancy": "not_pregnant",
    "context.onset": "scheduled",
    "context.severity": "mild",
}
NO_WARNINGS = dict.fromkeys(WARNINGS, "no")


class QuestionTests(unittest.TestCase):
    def test_closed_display_catalogue_is_fresh_and_resolves_warning_sources(self):
        rows = question_catalogue()
        self.assertEqual(tuple(row["id"] for row in rows), (*WARNINGS, *CONTEXT))
        self.assertEqual(json.loads(json.dumps(rows)), rows)
        sources = source_catalogue()
        for row in rows:
            self.assertTrue(row["text"] and row["short"])
            self.assertTrue(all(choice["label"] for choice in row["answers"]))
            if row["id"] in WARNINGS:
                self.assertEqual([choice["id"] for choice in row["answers"]], ["yes", "no", "unknown"])
                self.assertTrue(row["sources"])
                self.assertTrue(set(row["sources"]) <= sources.keys())
        rows[0]["answers"][0]["label"] = "Changed"
        self.assertEqual(question_catalogue()[0]["answers"][0]["label"], "Yes")

    def test_missing_and_unknown_warnings_progress_to_a_stop(self):
        first = next_question({})
        self.assertEqual(first["next_question_ids"], [WARNINGS[0]])
        self.assertEqual(first["missing_question_ids"], list(WARNINGS))
        partial = next_question({WARNINGS[0]: "unknown"})
        self.assertEqual(partial["next_question_ids"], [WARNINGS[1]])
        self.assertEqual(partial["unknown_question_ids"], [WARNINGS[0]])
        stop = next_question({**NO_WARNINGS, WARNINGS[0]: "unknown"})
        self.assertEqual(stop["status"], "needs_review")
        self.assertEqual(stop["next_question_ids"], [])

    def test_a_known_warning_stops_before_every_question(self):
        result = next_question(
            {"context.age_group": False, WARNINGS[-1]: "no"},
            context_answers={WARNINGS[-1]: "yes"},
        )
        self.assertEqual(result["status"], "escalated")
        self.assertEqual(result["next_question_ids"], [])
        self.assertIn(WARNINGS[-1], result["conflicting_question_ids"])
        self.assertIn("context.age_group", result["invalid_question_ids"])
        self.assertEqual(next_question({WARNINGS[-1]: "yes"})["status"], "escalated")

    def test_bare_conflict_is_unresolved_and_does_not_erase_story_facts(self):
        visitor = {**NO_WARNINGS, WARNINGS[1]: "conflicting"}
        step = next_question(visitor, context_answers=CONTEXT)
        self.assertEqual(step["status"], "needs_review")
        self.assertEqual(step["conflicting_question_ids"], [WARNINGS[1]])
        self.assertEqual(step["next_question_ids"], [])
        known = {**CONTEXT, "context.severity": "severe"}
        self.assertEqual(next_question(NO_WARNINGS, context_answers=known)["status"], "complete")
        changed = next_question({**NO_WARNINGS, "context.severity": "mild"},
                                context_answers=known)
        self.assertEqual(changed["status"], "needs_review")
        self.assertEqual(changed["conflicting_question_ids"], ["context.severity"])

    def test_scope_stops_context_and_safety_comes_first(self):
        known = {"context.pregnancy": "pregnant"}
        self.assertEqual(next_question({}, context_answers=known)["status"], "question")
        result = next_question(NO_WARNINGS, context_answers=known)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["next_question_ids"], [])
        self.assertEqual(next_question(NO_WARNINGS, context_answers=CONTEXT)["status"], "complete")

    def test_invalid_answers_fail_closed_without_echoing_free_text(self):
        for answers in ({WARNINGS[0]: True}, {"context.severity": ["mild"]},
                        {"unrecognized free text": "no"}, None):
            with self.subTest(answers=answers):
                step = next_question(answers, context_answers=CONTEXT)
                self.assertEqual(step["status"], "invalid")
                self.assertEqual(step["next_question_ids"], [])
                self.assertTrue(step["invalid_question_ids"])
                self.assertNotIn("unrecognized free text", step["invalid_question_ids"])

    def test_edit_discards_stale_suffix_and_restarts_from_changed_answer(self):
        answers = {**NO_WARNINGS, **CONTEXT}
        edited = edit_answers(answers, WARNINGS[1], "unknown")
        self.assertEqual(edited["answers"], {WARNINGS[0]: "no", WARNINGS[1]: "unknown"})
        self.assertEqual(edited["invalidated_question_ids"], [*WARNINGS[2:], *CONTEXT])
        self.assertTrue(edited["invalidate_confirmation"] and edited["invalidate_finder"])
        self.assertEqual(next_question(edited["answers"])["next_question_ids"], [WARNINGS[2]])
        cleared = edit_answers(answers, "context.onset", None)
        self.assertEqual(cleared["invalidated_question_ids"], ["context.onset", "context.severity"])
        self.assertEqual(next_question(cleared["answers"])["next_question_ids"], ["context.onset"])
        self.assertEqual(answers, {**NO_WARNINGS, **CONTEXT})
        with self.assertRaises(ValueError):
            edit_answers(answers, WARNINGS[1], "conflicting")

    def test_exhaustive_catalogue_walk_has_no_loops_and_respects_the_bound(self):
        rows = {row["id"]: row for row in question_catalogue()}
        pending, seen = [{}], set()
        longest, complete_count = 0, 0
        while pending:
            answers = pending.pop()
            key = tuple(sorted(answers.items()))
            self.assertNotIn(key, seen)
            seen.add(key)
            longest = max(longest, len(answers))
            step = next_question(answers)
            self.assertEqual(step, next_question(dict(reversed(list(answers.items())))))
            if step["status"] == "question":
                question_id, = step["next_question_ids"]
                self.assertNotIn(question_id, answers)
                pending.extend({**answers, question_id: option["id"]} for option in rows[question_id]["answers"])
            else:
                self.assertEqual(step["next_question_ids"], [])
                self.assertIn(step["status"], {"escalated", "needs_review", "unsupported", "complete"})
                complete_count += step["status"] == "complete"
        self.assertEqual((len(seen), longest, complete_count), (116, 9, 9))


if __name__ == "__main__":
    unittest.main()
