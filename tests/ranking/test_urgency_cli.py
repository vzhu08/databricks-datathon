import json
import subprocess
import sys
import unittest
from pathlib import Path

from app.ranking.urgency import rank_campuses


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "fixtures" / "urgent_finder.json"


def cli(*args, input_text=None):
    return subprocess.run(
        [sys.executable, "-m", "app.ranking", *args],
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=10,
    )


class FinderCliTests(unittest.TestCase):
    def test_fixture_and_urgency_override_match_the_direct_ranker(self):
        request = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for override, expected in [((), "SYNTHETIC-CAMPUS-UPGRADED"),
                                   (("--urgency", "highest"), "SYNTHETIC-CAMPUS-NEAR")]:
            with self.subTest(override=override):
                if override:
                    request["urgency"] = "highest"
                result = cli(str(FIXTURE), *override)
                self.assertEqual(result.returncode, 0, result.stderr)
                response = json.loads(result.stdout)
                self.assertEqual(response, rank_campuses(**request))
                self.assertEqual(response["ranked"][0]["facility_id"], expected)

    def test_unreviewed_service_returns_success_with_unscored_leads(self):
        result = cli("-", "--service", "trauma_care", input_text=FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response["status"], "needs_confirmation")
        self.assertEqual(response["ranked"], [])
        self.assertEqual(len(response["needs_confirmation"]), 2)
        for row in response["needs_confirmation"]:
            self.assertEqual(row["reasons"], ["service_unconfirmed"])
            self.assertNotIn("score", row)

    def test_no_candidates_is_a_valid_no_match(self):
        request = json.loads(FIXTURE.read_text(encoding="utf-8"))
        request["candidates"] = []
        result = cli(input_text=json.dumps(request))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "no_match")

    def test_malformed_request_does_not_write_a_partial_result(self):
        for text in ["{", "null", '{"candidates":[null]}', '{"candidates":[],"limit":null}',
                     '{"candidates":[],"travel_budget":Infinity}', '{"candidates":[]}']:
            with self.subTest(text=text):
                result = cli("-", input_text=text)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertEqual(json.loads(result.stderr)["status"], "invalid_input")


if __name__ == "__main__":
    unittest.main()
