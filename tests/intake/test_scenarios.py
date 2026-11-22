import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

SCENARIOS = Path(__file__).with_name("scenarios")
JOURNEY_FILE = SCENARIOS / "journeys.json"


class ScenarioFixtureTests(unittest.TestCase):
    def test_digest_and_trusted_plan_bindings(self):
        data = JOURNEY_FILE.read_bytes()
        fixture = json.loads(data)
        self.assertEqual(json.loads((SCENARIOS / "digest.json").read_bytes()), {
            "schema_version": "intake.journeys.digest.v1",
            "file": JOURNEY_FILE.name,
            "sha256": hashlib.sha256(data).hexdigest(),
        })
        self.assertIs(fixture["synthetic"], True)
        for scenario_id, scenario in fixture["scenarios"].items():
            with self.subTest(scenario=scenario_id):
                self.assertEqual(scenario["schema_version"], "intake.scenario.v1")
                self.assertEqual(scenario["scenario_id"], scenario_id)
                self.assertIs(scenario["synthetic"], True)
                plan = scenario["clinician_plan"]
                if plan is None:
                    self.assertIsNone(scenario["service"])
                else:
                    self.assertIs(plan["synthetic"], True)
                    for key in ("scenario_id", "scenario_version", "service"):
                        self.assertEqual(plan[key], scenario[key])

    def test_assessments_follow_the_script_and_offer_only_current_requests(self):
        from app.intake.__main__ import load_journeys, replay_journey

        fixture, _ = load_journeys()
        for journey_id, steps in fixture["journeys"].items():
            actual = replay_journey(fixture, journey_id)["transitions"]
            self.assertEqual(len(steps), len(actual))
            for index, (step, transition) in enumerate(zip(steps, actual)):
                with self.subTest(journey=journey_id, step=index):
                    assessment = transition["assessment"]
                    finder = transition["finder"]
                    expected = step["expected"]
                    self.assertEqual(assessment["mode"], "synthetic")
                    for key in ("state", "next_question_ids", "request", "confirmation_status"):
                        if key in expected:
                            self.assertEqual(assessment[key], expected[key], key)
                    if "message_id" in expected:
                        self.assertEqual(assessment["message_ids"][0], expected["message_id"])
                    if "concern_category" in expected:
                        self.assertIn(expected["concern_category"], {
                            concern["category"] for concern in assessment["concerns"]
                        })
                    if expected["request"] is None:
                        self.assertIsNone(finder)
                    else:
                        self.assertEqual(finder["status"], "ok")
                        self.assertEqual(finder["service"], expected["request"]["service"])
                        self.assertEqual(finder["urgency"], expected["request"]["urgency"])
                        self.assertEqual(
                            [option["facility_id"] for option in finder["ranked"]],
                            expected["ranked_facility_ids"],
                        )
                        self.assertTrue(all(
                            option["availability"] == "unknown" for option in finder["ranked"]
                        ))


def measure_walk():
    """Measure reachable offline assessment records using the real engine."""
    from app.intake.assessment import SCHEMA_VERSION, assess_intake, confirm_intake
    from app.intake.questions import question_catalogue

    catalogue = {question["id"]: question["answers"] for question in question_catalogue()}
    fixture = json.loads(JOURNEY_FILE.read_bytes())
    metrics = {}
    for scenario_id, scenario in fixture["scenarios"].items():
        pending = [{}]
        visited = set()
        counts = Counter()
        longest = 0
        while pending:
            answers = pending.pop()
            key = tuple(sorted(answers.items()))
            if key in visited:
                continue
            visited.add(key)
            longest = max(longest, len(answers))
            payload = {
                "schema_version": SCHEMA_VERSION, "mode": "synthetic",
                "scenario_id": scenario_id, "input_revision": len(answers), "answers": answers,
            }
            assessment = assess_intake(payload, scenario=scenario)
            counts[assessment["state"]] += 1
            if assessment["state"] == "invalid_input" or assessment["request"] is not None:
                raise AssertionError(f"Unexpected preconfirmation assessment for {scenario_id}")
            if assessment["state"] == "confirmation_required":
                receipt = confirm_intake(payload, scenario=scenario)
                confirmed = assess_intake(payload, scenario=scenario, confirmation=receipt)
                if confirmed["state"] != "ready" or confirmed["request"] is None:
                    raise AssertionError(f"Confirmation did not reach ready for {scenario_id}")
                counts["ready"] += 1
            for question_id in assessment["next_question_ids"]:
                if question_id in answers or question_id in scenario["known_answers"]:
                    raise AssertionError(f"Repeated or preanswered question: {question_id}")
                pending.extend(
                    {**answers, question_id: answer["id"]}
                    for answer in catalogue[question_id]
                    if answer["id"] != "conflicting"
                )
        metrics[scenario_id] = {
            "longest_question_path": longest,
            "assessment_records": sum(counts.values()),
            "records_by_state": dict(counts),
        }
    return {
        "synthetic": True, "scenarios": metrics,
        "assessment_records": sum(row["assessment_records"] for row in metrics.values()),
        "longest_question_path": max(row["longest_question_path"] for row in metrics.values()),
    }


if __name__ == "__main__":
    print(json.dumps(measure_walk(), sort_keys=True))
