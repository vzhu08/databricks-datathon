import hashlib
import json
import unittest
from unittest.mock import patch

from research.matching import facility_area_display as display


class FacilityAreaDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tiers = dict(zip(display.TIERS, (3, 2, 1, 1, 3)))
        self.evidence = dict(zip(display.EVIDENCE, (4, 3, 5, 2)), covered=7)
        self.source = {"population": 10, "national": {"mutually_exclusive": self.tiers,
                        "overlapping": self.evidence, "by_state": {"private": 99}},
                       "private_source_path": "private"}

    def test_projects_only_national_counts(self):
        summary = display.project(self.source)
        self.assertEqual(summary["covered"], 7)
        self.assertEqual(summary["coverage_tiers"], self.tiers)
        raw = json.dumps(summary).encode()
        self.assertNotIn(b"private", raw)
        with patch.object(display, "DISPLAY_SHA256", hashlib.sha256(raw).hexdigest()):
            self.assertEqual(display.read_summary(raw), summary)
            with self.assertRaises(ValueError):
                display.read_summary(raw + b" ")

    def test_inconsistent_totals_and_noncounts_are_rejected(self):
        for field, value in (("registry_or_agreeing_points", 2), ("nearby_only_possible_shared_origins", 4),
                             ("agreeing_points", True), ("covered", 3)):
            with self.subTest(field=field), patch.dict(self.evidence, {field: value}), self.assertRaises(ValueError):
                display.project(self.source)
