import json
import unittest

from .score import DIGEST, case_result, load_cases, score, unique_object


class AuditAccounting(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "counter-check", "expect": {"mock_attempts_min": 1, "route_attempts": 0}}
        self.bundle = {"candidate_sha": "1" * 40, "packet_sha256": DIGEST, "observations": {}}

    def test_empty_replay_retains_all_frozen_cases(self):
        cases = load_cases()
        self.assertEqual(len({case["id"] for case in cases}), 35)
        self.assertEqual(len({case["group"] for case in cases}), 11)
        self.assertEqual(sum(c["group"] == "positive" for c in cases), 4)
        self.assertEqual(score(cases, self.bundle)["not_run"], 35)

    def test_missing_measurement_is_not_implicit_zero(self):
        row = case_result(self.case, {"measured": {"mock_attempts_min": 2}})
        self.assertEqual((row["status"], row["missing"]), ("NOT_RUN", ["route_attempts"]))

    def test_measured_failure_survives_missing_surface(self):
        row = case_result(self.case, {"measured": {"route_attempts": 1}, "blocker": "observer_missing"})
        self.assertEqual((row["status"], row["failed"]), ("FAIL", ["route_attempts"]))

    def test_unexpected_exception_fails_even_without_measurements(self):
        self.assertEqual(case_result(self.case, {"error": True})["status"], "FAIL")

    def test_boolean_cannot_masquerade_as_counter(self):
        for value in (False, 0.0, "0"):
            row = case_result(self.case, {"measured": {"mock_attempts_min": 1, "route_attempts": value}})
            self.assertEqual(row["status"], "FAIL")

    def test_lower_bound_requires_real_progress(self):
        for count, status in ((0, "FAIL"), (1, "PASS"), (2, "PASS")):
            self.assertEqual(case_result(self.case, {"measured": {
                "mock_attempts_min": count, "route_attempts": 0}})["status"], status)

    def test_invalid_provenance_rejected(self):
        original = {"counter-check": {"measured": {"route_attempts": 0}}}
        for change in ({"candidate_sha": None}, {"packet_sha256": "other"}, {"candidate_sha": "main"},
                       {"observations": {"wrong-case": {}}}):
            with self.assertRaises(ValueError):
                score([self.case], {**self.bundle, "observations": original, **change})

    def test_duplicate_keys_and_sensitive_extras_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"sample":1,"sample":2}', object_pairs_hook=unique_object)
        with self.assertRaises(ValueError):
            case_result(self.case, {"raw_text": "SYNTHETIC-CANARY"})
        row = case_result({"id": "text", "expect": {"tag": "correct"}},
                          {"measured": {"tag": "SYNTHETIC-CANARY"}})
        self.assertNotIn("SYNTHETIC-CANARY", json.dumps(row))
