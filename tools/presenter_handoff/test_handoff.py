"""Verify the synthetic replay and the vendored Leaflet assets."""

import json
from pathlib import Path
import unittest

from replay import replay
from app import storm_plan
from street_map import LEAFLET, LEAFLET_FILES, source_file


FIXTURE = Path(__file__).with_name("synthetic-smoke.json")


class HandoffTests(unittest.TestCase):
    def test_synthetic_smoke_replays_both_policies(self):
        plan, result = replay(json.loads(FIXTURE.read_bytes()))
        self.assertIs(storm_plan.checked(plan), plan)
        self.assertEqual(len(plan["condition_breakdown"]), 4)
        self.assertEqual(result["nearest_first"]["objective"], (1, 0, 0, 115))
        self.assertEqual(result["exact_optimum"]["objective"], (0, 0, 0, 135))

    def test_general_replay_uses_the_supplied_vocabulary(self):
        fixture = FIXTURE.read_text(encoding="utf-8").replace("ophthalmic_treatment", "dental")
        plan, result = replay(json.loads(fixture))
        self.assertEqual(result["exact_optimum"]["assigned"], 5)
        self.assertIn("dental", {row["category"] for row in plan["condition_breakdown"]})

    def test_leaflet_files_match_the_pinned_bytes(self):
        for name, digest in LEAFLET_FILES.items():
            with self.subTest(name=name):
                self.assertTrue(source_file(LEAFLET / name, digest))


if __name__ == "__main__":
    unittest.main()
