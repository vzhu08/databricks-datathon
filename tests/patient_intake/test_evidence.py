import unittest

from app.patient_intake.evidence import (
    Observation,
    conflicting_observation_indices,
    validate_verbatim_text,
)


class EvidenceTests(unittest.TestCase):
    def test_preserves_verbatim_invented_statement(self):
        statement = "  Invented report: I felt a faint flutter yesterday.\nToday I am unsure.  "
        self.assertEqual(validate_verbatim_text(statement, max_chars=len(statement)), statement)

    def test_rejects_missing_or_oversized_text_without_echoing_it(self):
        canary = "INVENTED-SENSITIVE-REFERENCE"
        for text in (None, True, "", " \n ", canary, "\ud800"):
            with self.subTest(kind=type(text)), self.assertRaises(ValueError) as raised:
                validate_verbatim_text(text, max_chars=5)
            self.assertNotIn(canary, str(raised.exception))

    def test_reports_only_explicit_conflicts_at_the_same_time(self):
        observations = [
            Observation("test-concept", "present", "historical"),
            Observation("test-concept", "absent", "current"),
            Observation("test-concept", "unknown", "current"),
            Observation("test-concept", "present", "current"),
            Observation("test-concept", "present", "unknown"),
            Observation("another-test-concept", "absent", "historical"),
        ]
        self.assertEqual(conflicting_observation_indices(observations), (1, 3))
        self.assertEqual(conflicting_observation_indices(observations[:3]), ())
        self.assertEqual(observations[2].presence, "unknown")

    def test_invalid_enums_fail_closed_and_repr_hides_the_concept(self):
        canary = "test-sensitive-concept"
        row = Observation(canary, "unknown", "unknown")
        self.assertNotIn(canary, repr(row))
        with self.assertRaises(ValueError):
            Observation(canary, False, "current")
        with self.assertRaises(ValueError):
            Observation(canary, "present", {"invented": "time"})


if __name__ == "__main__":
    unittest.main()
