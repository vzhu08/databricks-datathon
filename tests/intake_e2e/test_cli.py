import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/intake/scenarios/journeys.json"

# Install the guard before importing the demo. The audit hook catches attempted
# socket use even if code catches the resulting exception.
OFFLINE_CLI = """
import runpy
import sys

network_events = []
def reject_network(event, args):
    if event.startswith("socket."):
        network_events.append(event)
        raise AssertionError(event)

sys.addaudithook(reject_network)
try:
    runpy.run_module("app.intake", run_name="__main__", alter_sys=True)
finally:
    if network_events:
        raise AssertionError(network_events)
"""


def run_cli(*args):
    env = {**os.environ, "FIND_CARE_DATA": "warehouse",
           "DATABRICKS_HOST": "https://synthetic.invalid"}
    return subprocess.run(
        [sys.executable, "-c", OFFLINE_CLI, *args], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=15,
    )


class IntakeCliTests(unittest.TestCase):
    def test_cli_emits_a_reproducible_offline_receipt(self):
        first = run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = run_cli("all")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        data = json.loads(first.stdout)
        fixture = json.loads(FIXTURE.read_bytes())
        self.assertIs(data["synthetic"], True)
        self.assertEqual(data["mode"], "synthetic")
        self.assertEqual(data["fixture_sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(
            [journey["journey_id"] for journey in data["journeys"]], list(fixture["journeys"]),
        )
        for journey in data["journeys"]:
            for step in journey["transitions"]:
                self.assertEqual(step["input"]["mode"], "synthetic")
                self.assertEqual(step["assessment"]["state"] == "ready", step["finder"] is not None)

    def test_edit_withholds_the_previous_result_and_requires_a_new_receipt(self):
        result = run_cli("edit_after_confirmation")
        self.assertEqual(result.returncode, 0, result.stderr)
        journey, = json.loads(result.stdout)["journeys"]
        self.assertEqual(journey["journey_id"], "edit_after_confirmation")
        previous, edited, renewed = journey["transitions"][-3:]
        old_assessment = previous["assessment"]
        current = edited["assessment"]
        self.assertEqual(old_assessment["state"], "ready")
        self.assertTrue(previous["finder"]["ranked"])
        self.assertEqual(current["confirmation_status"], "stale")
        self.assertNotEqual(current["input_fingerprint"], old_assessment["input_fingerprint"])
        self.assertGreater(current["input_revision"], old_assessment["input_revision"])
        self.assertIsNone(current["request"])
        self.assertIsNone(edited["finder"])
        self.assertEqual(renewed["assessment"]["confirmation_status"], "current")
        self.assertEqual(renewed["assessment"]["input_fingerprint"], current["input_fingerprint"])
        self.assertTrue(renewed["finder"]["ranked"])

    def test_blocked_paths_never_reach_the_ranker(self):
        from app.intake import finder_bridge
        from app.intake.__main__ import load_journeys, replay_journey

        fixture, _ = load_journeys()
        ranker = finder_bridge.rank_campuses
        bridge = finder_bridge.find_care_for_intake
        with patch.object(finder_bridge, "rank_campuses", wraps=ranker) as rank:
            for journey_id, steps in fixture["journeys"].items():
                expected_calls = [int(step["expected"]["request"] is not None) for step in steps]
                calls_by_transition = []

                def observe(*args, **kwargs):
                    before = rank.call_count
                    response = bridge(*args, **kwargs)
                    calls_by_transition.append(rank.call_count - before)
                    return response

                with self.subTest(journey=journey_id), patch.object(
                    finder_bridge, "find_care_for_intake", side_effect=observe,
                ):
                    replay_journey(fixture, journey_id)
                    self.assertEqual(calls_by_transition, expected_calls)

    def test_cli_rejects_an_unlisted_journey(self):
        result = run_cli("not-a-checked-in-journey")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("invalid choice", result.stderr)
