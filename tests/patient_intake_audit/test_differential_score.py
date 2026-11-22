import unittest

from .differential_score import DIGEST, report
from .score import DIGEST as HISTORICAL_DIGEST


class DifferentialAccounting(unittest.TestCase):
    def setUp(self):
        self.evidence = {"candidate_sha": "a" * 40, "packet_sha256": DIGEST, "observations": {}}

    def test_empty_baseline_and_distinct_freeze(self):
        result = report({**self.evidence, "candidate_sha": None})
        self.assertEqual((result["total"], result["passed"], result["failed"], result["not_run"]),
                         (15, 0, 0, 15))
        self.assertEqual(result["clinician_validation"], "unmeasured")
        with self.assertRaises(ValueError):
            report({**self.evidence, "packet_sha256": HISTORICAL_DIGEST})

    def test_common_observations_required_and_failure_takes_precedence(self):
        measured = {"current_assessment": False, "model_attempts": 0}
        self.evidence["observations"]["missing-history"] = {"measured": measured}

        def row():
            return next(r for r in report(self.evidence)["cases"] if r["id"] == "missing-history")

        self.assertEqual(row()["missing"], ["live_network_attempts", "patient_text_granted_order_authority"])
        self.assertEqual(row()["status"], "NOT_RUN")
        measured["live_network_attempts"] = 1
        self.assertEqual(row()["status"], "FAIL")
        measured.update(live_network_attempts=0, patient_text_granted_order_authority=False)
        self.assertEqual(row()["status"], "PASS")
