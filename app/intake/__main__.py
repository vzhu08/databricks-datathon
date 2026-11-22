"""Replay the checked-in fictional intake journeys through the offline finder."""

import argparse
import hashlib
import json
from pathlib import Path

JOURNEY_FILE = (
    Path(__file__).resolve().parents[2] / "tests" / "intake" / "scenarios" / "journeys.json"
)


def load_journeys():
    data = JOURNEY_FILE.read_bytes()
    fixture = json.loads(data)
    if fixture["schema_version"] != "intake.journeys.v1" or fixture["synthetic"] is not True:
        raise ValueError("Expected the versioned synthetic journey fixture")
    return fixture, hashlib.sha256(data).hexdigest()


def replay_journey(fixture, journey_id):
    from .assessment import SCHEMA_VERSION, confirm_intake
    from .finder_bridge import find_care_for_intake

    scenario = None
    confirmation = None
    answers = {}
    revision = 0
    transitions = []
    for step in fixture["journeys"][journey_id]:
        action = step["action"]
        if action == "select":
            if scenario is not None:
                revision += 1
            scenario = fixture["scenarios"][step["scenario_id"]]
            answers = {}
            confirmation = None
        elif action in ("answer", "edit"):
            answers = {**answers, step["question_id"]: step["answer_id"]}
            revision += 1
        elif action != "confirm":
            raise ValueError(f"Unsupported scripted action: {action}")

        payload = {
            "schema_version": SCHEMA_VERSION,
            "mode": "synthetic",
            "scenario_id": scenario["scenario_id"],
            "input_revision": revision,
            "answers": answers,
        }
        if action == "confirm":
            confirmation = confirm_intake(payload, scenario=scenario)

        # An edit deliberately presents the previous receipt to the bridge so
        # the trace records the rejection rather than assuming invalidation.
        result = find_care_for_intake(
            payload, scenario=scenario, confirmation=confirmation, origin_id=fixture["origin_id"],
        )
        transitions.append({
            "action": action,
            "input": payload,
            "assessment": result["assessment"],
            "finder": result["finder"],
        })
        if action == "edit":
            confirmation = None

    return {"journey_id": journey_id, "transitions": transitions}


def main(argv=None):
    fixture, digest = load_journeys()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "journey", nargs="?", default="all", choices=["all", *fixture["journeys"]],
        help="Fictional journey to replay (default: all)",
    )
    args = parser.parse_args(argv)
    journey_ids = fixture["journeys"] if args.journey == "all" else [args.journey]
    receipt = {
        "schema_version": "intake.journey-run.v1",
        "synthetic": True,
        "mode": "synthetic",
        "fixture_sha256": digest,
        "origin_id": fixture["origin_id"],
        "journeys": [replay_journey(fixture, journey_id) for journey_id in journey_ids],
    }
    print(json.dumps(receipt, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
