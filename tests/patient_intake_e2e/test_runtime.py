from pathlib import Path
import unittest

from tests.patient_intake_e2e.app_copy import offline_probe, staged_app


class StagedPatientRuntimeTests(unittest.TestCase):
    def test_runtime_journeys_and_failures_from_app_only(self):
        cases = Path(__file__).with_name("runtime_cases.py").read_text(encoding="utf-8")
        with staged_app() as source:
            result = offline_probe(source, cases, settings={"FIND_CARE_DATA": "demo"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("test_fresh_input_review_follow_up_and_no_reviewed_destination", result.stderr)
