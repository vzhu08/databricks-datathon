import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from app.routing_evaluation.comparison import evaluate
from app.routing_evaluation.smoke import synthetic_bundle


class RoutingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.bundle = synthetic_bundle()

    def test_smoke_never_promotes_and_methods_share_the_pool(self):
        result = evaluate(self.bundle)
        self.assertEqual("synthetic_smoke_only", result["status"])
        self.assertEqual("fixed", result["selected"])
        self.assertEqual(0, result["eligibility_violations"])
        self.assertEqual(6, result["test_scenarios"])
        for selection in result["held_out_choices"]:
            pools = [set(ids) for ids in selection["top3"].values()]
            self.assertEqual(pools[0], pools[1])
            self.assertEqual(pools[1], pools[2])

    def test_no_data_and_inadequate_data(self):
        self.assertEqual("pending_human_labels", evaluate(None)["status"])
        self.bundle["label_basis"] = "human_blinded"
        self.assertEqual("insufficient_evidence", evaluate(self.bundle)["status"])
        for case in self.bundle["scenarios"]:
            case["reviews"] = []
        self.assertEqual("pending_human_labels", evaluate(self.bundle)["status"])

    def test_holdout_judgments_never_change_training_or_selection(self):
        original = evaluate(self.bundle)
        for case in self.bundle["scenarios"][6:]:
            for review in case["reviews"]:
                review["acceptable_ids"] = []
                review["preferences"][0]["choice"] = "abstain"
        changed = evaluate(self.bundle)
        self.assertEqual(original["model_coefficients"], changed["model_coefficients"])
        self.assertEqual(original["held_out_choices"], changed["held_out_choices"])
        self.assertEqual(0, changed["test"]["top1_acceptable"]["learned"])

    def test_clustered_interval_is_paired_and_deterministic(self):
        first = evaluate(self.bundle)
        self.assertEqual(first, evaluate(self.bundle))
        for model in ("fixed", "nearest"):
            intervals = first["intervals_learned_minus_baseline"][model]
            self.assertEqual(6, intervals["clusters"])
            self.assertAlmostEqual(intervals["delta"], first["test"]["top1_acceptable"]["learned"]
                             - first["test"]["top1_acceptable"][model])
        self.assertEqual([0, 0], first["intervals_learned_minus_baseline"]["fixed"]["ci95"])
        for c in self.bundle["scenarios"][6:]:
            c["cluster_id"] = "test-set-as-one-related-cluster"
        self.assertIsNone(evaluate(self.bundle)["intervals_learned_minus_baseline"]["fixed"]["ci95"])

    def test_cross_split_leakage_including_excluded_campuses(self):
        for group in ["cluster_id", "scenario_group", "facility_id", "campus_group", "source_groups"]:
            with self.subTest(group=group):
                b = copy.deepcopy(self.bundle)
                left, right = b["scenarios"][0], b["scenarios"][-1]
                if group in ("cluster_id", "scenario_group"):
                    right[group] = left[group]
                else:
                    right["candidates"][0][group] = left["candidates"][0][group]
                    right["candidates"][0]["as_of"] = "2000-01-01"
                with self.assertRaisesRegex(ValueError, "Leakage"):
                    evaluate(b)

    def test_reviewer_abstentions_ties_and_partial_coverage(self):
        for case in self.bundle["scenarios"][:6]:
            for r in case["reviews"]:
                r["preferences"][0]["choice"] = "tie"
        c = self.bundle["scenarios"][-1]
        c["reviews"][0]["acceptable_ids"] = None
        result = evaluate(self.bundle)
        self.assertEqual({}, result["directional_train_scenarios_by_urgency"])
        self.assertEqual(5, result["test"]["scored_scenarios"])
        self.assertEqual(1, result["test_exclusions"]["fewer_than_two_acceptability_judgments"])

    def test_reviewer_identity_and_repeat_pair_checks(self):
        left = self.bundle["scenarios"][0]["reviews"]
        left[1]["reviewer_id"] = left[0]["reviewer_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate reviewer"):
            evaluate(self.bundle)
        left[1]["reviewer_id"] = "second"
        pair = left[0]["preferences"][0]
        left[0]["preferences"].append(dict(left=pair["right"], right=pair["left"], choice="tie"))
        with self.assertRaisesRegex(ValueError, "repeated reviewer pair"):
            evaluate(self.bundle)

    def test_review_cannot_override_ineligible_campus(self):
        c = self.bundle["scenarios"][-1]
        c["request"]["required"] = ["absent"]
        with self.assertRaisesRegex(ValueError, "outside the eligible pool"):
            evaluate(self.bundle)
        for r in c["reviews"]:
            r["acceptable_ids"] = None
            r["preferences"] = []
        result = evaluate(self.bundle)
        self.assertEqual(1, result["test_exclusions"]["no_eligible_destination"])
        self.assertTrue(all(v is None for v in result["held_out_choices"][-1]["choices"].values()))

    def test_geography_and_travel_units(self):
        c = self.bundle["scenarios"][-1]
        c["request"]["travel_metric"] = "distance_km"
        c["geography"] = "second-fictional-region"
        for candidate in c["candidates"]:
            candidate["distance_km"] = candidate.pop("travel_minutes")
        result = evaluate(self.bundle)
        self.assertEqual(1, result["test_by_geography"][c["geography"]]["scored_scenarios"])
        self.assertEqual({"distance_km", "travel_minutes"}, {x["unit"] for x in result["mean_top1_travel"]})

    def test_directional_judgments_can_change_the_learned_order(self):
        for case in self.bundle["scenarios"]:
            first, second = case["candidates"]
            case["request"]["preferred"] = []
            first["services"][case["request"]["service"]]["source_date"] = "2026-07-01"
            second["travel_minutes"] = 12
            for review in case["reviews"]:
                review["preferences"][0]["choice"] = "right"
                review["acceptable_ids"] = [second["facility_id"]]
        result = evaluate(self.bundle)
        for baseline in ("fixed", "nearest"):
            self.assertGreater(result["intervals_learned_minus_baseline"][baseline]["delta"], 0)
        self.assertEqual("synthetic_smoke_only", result["status"])

    def test_declared_geography_holdout_is_enforced_on_all_train_cases(self):
        self.bundle["geography_holdout"] = True
        for case in self.bundle["scenarios"][:6]:
            case["reviews"] = []
        with self.assertRaisesRegex(ValueError, "geographic holdout"):
            evaluate(self.bundle)
        for case in self.bundle["scenarios"][:6]:
            case["geography"] = "training-only-region"
        self.assertEqual([], evaluate(self.bundle)["training_test_geography_overlap"])

    def test_cli_pending_and_example_smoke(self):
        root = Path(__file__).resolve().parents[2]
        command = [sys.executable, "-m", "app.routing_evaluation"]
        pending = json.loads(subprocess.check_output(command, cwd=root))
        self.assertEqual("pending_human_labels", pending["status"])
        example = json.loads(subprocess.check_output(command + ["--example-bundle"], cwd=root))
        result = json.loads(subprocess.check_output(command + ["--synthetic-smoke"], cwd=root))
        self.assertEqual(evaluate(example), result)


if __name__ == "__main__":
    unittest.main()
