"""Replay a neutral four-class or general referral instance and audit both policies."""

import argparse
import json
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import storm_plan
from app.simulation import batch_planner
from tests.simulation.test_batch_audit import audit_policy


def replay(instance):
    if instance["geography"]["location_basis"] != "synthetic":
        raise ValueError("Use the neutral replay instance from the operator handoff")
    labels = instance["scenario"]["condition_categories"]
    services = tuple(dict.fromkeys((*batch_planner.SERVICES, *labels)))
    with patch.object(batch_planner, "SERVICES", services):
        plan = batch_planner.solve(instance)

    counts = {
        name: {row["patient"]: row["travel_seconds"] for row in result["assignments"]}
        for name, result in plan["policies"].items()
    }
    common = counts["nearest_first"].keys() & counts["exact_optimum"].keys()
    summary = {}
    for name, result in plan["policies"].items():
        objective = audit_policy(
            TestCase(), instance["patients"], instance["facilities"], instance["travel_seconds"],
            result, exact=name == "exact_optimum",
        )
        summary[name] = {
            "assigned": len(counts[name]),
            "unmet": len(result["unserved"]),
            "objective": objective,
            "same_served_travel_seconds": sum(counts[name][pid] for pid in common),
        }

    categories = {row["id"]: row["condition_category"] for row in instance["patients"]}
    plan["condition_breakdown"] = [
        {"category": category, "label": label, "requested": sum(x == category for x in categories.values())}
        for category, label in labels.items()
    ]
    return plan, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--plan-out", type=Path, help="Optional Streamlit plan for the routable synthetic fixture")
    args = parser.parse_args()
    plan, summary = replay(json.loads(args.instance.read_bytes()))
    if args.plan_out:
        storm_plan.checked(plan)
        with args.plan_out.open("x", encoding="utf-8") as output:
            json.dump(plan, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
