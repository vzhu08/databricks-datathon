"""Synthetic checks: source semantics, source isolation, and nationwide denominator."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import pdfplumber
from unittest.mock import patch

from research.acquisition.railway_activity.compare import compare
from research.acquisition.railway_activity.extract import canonical, digest, extract_profile, logical_rows, metric, observation
from research.acquisition.railway_activity.run import verify_manifest


SOURCE = {"sha256": "a" * 64, "edition_id": "synthetic-2020", "url": "https://example.test/audit.pdf",
          "source_family": "synthetic_audit", "upstream_origin_family": "synthetic_health_records",
          "published_date": "2020-01-01", "report_period": "2018-19",
          "sharing_permission": "accurate_attributed_reproduction"}


class RailwayActivityTests(unittest.TestCase):
    def test_shortfall_is_not_inventory_or_service_absence(self):
        self.assertEqual(metric("NS", "equipment_shortfall")["value_semantics"], "no_shortfall")
        self.assertEqual(metric("0", "equipment_shortfall")["unit"], "equipment_shortfall_count")
        for raw in ["NA", "", "-1", "three", "12.5"]:
            with self.assertRaises(ValueError):
                metric(raw, "equipment_shortfall")
        with self.assertRaises(ValueError):
            metric("NS", "bed_inventory")

    def test_merge_placeholders_do_not_remove_empty_source_cells(self):
        self.assertEqual(logical_rows([["A", None, "", "0"]], 0, 3), [["A", "", "0"]])
        with self.assertRaises(ValueError):
            logical_rows([["A", None, ""]], 0, 3)

    def test_source_ids_separate_mirrors_editions_and_repeated_mentions(self):
        a = observation(SOURCE, "p1:r1", "Synthetic Hospital", "ZZ", "capacity", "3")
        b = observation(SOURCE, "p1:r2", "Synthetic Hospital", "ZZ", "capacity", "3")
        self.assertEqual(a["source_campus_key"], b["source_campus_key"])
        self.assertNotEqual(a["observation_id"], b["observation_id"])
        changed = dict(SOURCE, sha256="b" * 64)
        self.assertNotEqual(a["observation_id"], observation(changed, "p1:r1", "Synthetic Hospital", "ZZ", "capacity", "3")["observation_id"])
        self.assertFalse(a["current_service_eligible"])
        with self.assertRaises(ValueError):
            observation(SOURCE, "p1", "Synthetic Hospital", "ZZ", "capacity", "3", current_service_eligible=True)

    def test_full_frame_retains_duplicates_and_missing_geography(self):
        base = [{"facility_id": f"occ-{i}", "source_row": {"id": i % 10077, "name": None, "state": None}}
                for i in range(10088)]
        before = copy.deepcopy(base)
        frame, leads, report = compare(base, [], {"id": "id", "name": "name", "state": "state"},
                                       expected_rows=10088, expected_upstream_ids=10077)
        self.assertEqual((len(frame), len(leads)), (30264, 0))
        self.assertEqual(report["occurrences"], 10088)
        self.assertEqual(sum(report["state_ut_unknown_counts"].values()), 10088)
        self.assertEqual(base, before)
        self.assertEqual(len({r["facility_id"] for r in frame}), 10088)
        self.assertTrue(all(r["baseline_status"] is None and not r["current_service_upgrade"] for r in frame))
        with self.assertRaises(ValueError):
            compare(base[:-1], [], {"id": "id", "name": "name", "state": "state"}, expected_rows=10088, expected_upstream_ids=10077)

    def test_name_screen_is_not_accepted_link_and_does_not_expand_abbreviations(self):
        base = [{"facility_id": "one", "source_row": {"id": 1, "name": "Synthetic Hospital", "state": "Mystery"}}]
        obs = observation(SOURCE, "p1", "Synthetic Hospital", "ZZ", "mri_referral", "4", clinical_service="mri")
        frame, leads, summary = compare(base, [obs], {"id": "id", "name": "name", "state": "state"}, expected_rows=1, expected_upstream_ids=1)
        self.assertEqual(len(leads), 1)
        self.assertEqual(summary["accepted_campus_links"], 0)
        self.assertEqual(sum(bool(r["candidate_observation_ids"]) for r in frame), 1)
        obs["campus_raw"] = "SH/ZZ"
        self.assertFalse(compare(base, [obs], {"id": "id", "name": "name", "state": "state"}, expected_rows=1, expected_upstream_ids=1)[1])

    def test_hash_and_exact_span_replay(self):
        class Page:
            def extract_text(self):
                return "Synthetic Hospital referred 14 people in 2018."
        class PDF:
            pages = [Page()]
            def __enter__(self): return self
            def __exit__(self, *_): pass
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "source.pdf"
            path.write_bytes(b"synthetic test bytes")
            source = dict(SOURCE, sha256=digest(path.read_bytes()))
            excerpt = Page().extract_text()
            profile = {"source": source, "parser": {"name": "pdfplumber", "version": pdfplumber.__version__},
                "page_count": 1, "spans": [{"page": 1, "start": 0, "end": len(excerpt),
                "excerpt": excerpt, "observations": [{"campus": "Synthetic Hospital", "zone": "ZZ",
                    "measure": "referrals", "value": 14, "unit": "patients", "delivery_scope": "referral_to_external_hospital"}]}],
                "expected_measure_counts": {"referrals": 1}}
            with patch("pdfplumber.open", return_value=PDF()):
                self.assertEqual(extract_profile(path, profile)["counts"]["observations"], 1)
                profile["spans"][0]["observations"][0]["value"] = 4
                with self.assertRaises(ValueError): extract_profile(path, profile)
                profile["spans"][0]["observations"][0]["value"] = 14
                profile["spans"][0]["excerpt"] = "Different Hospital referred 14 people in 2018."
                with self.assertRaises(ValueError): extract_profile(path, profile)
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError): extract_profile(path, profile)

    def test_manifest_readback_detects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sample.json").write_bytes(b"[]")
            files = {"sample.json": {"bytes": 2, "sha256": digest(b"[]")}}
            manifest = {"packet_id": "railway-activity-" + digest(canonical(files)), "files": files}
            (root / "manifest.json").write_text(json.dumps(manifest))
            verify_manifest(root)
            (root / "sample.json").write_bytes(b"{}")
            with self.assertRaises(ValueError): verify_manifest(root)

    def test_deficiency_list_preserves_combined_scope_and_na_zero(self):
        class Page:
            def extract_text(self): return "Synthetic deficiency table; NA: Not Applicable"
            def extract_tables(self):
                return [[["ZZ", None, "H/A,\nH/B,"], ["YY", None, "NA"], ["XX", None, "0"]]]
        class PDF:
            pages = [Page()]
            def __enter__(self): return self
            def __exit__(self, *_): pass
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "source.pdf"
            path.write_bytes(b"synthetic table")
            source = dict(SOURCE, sha256=digest(path.read_bytes()))
            profile = {"source": source, "parser": {"name": "pdfplumber", "version": pdfplumber.__version__},
                "page_count": 1, "tables": [{"page": 1, "table": 0, "start_row": 0, "width": 2,
                "row_count": 3, "zone_column": 0, "anchors": ["Not Applicable"], "metrics": [
                    {"column": 1, "kind": "deficiency_list", "measure": "combined_deficiency",
                     "scope_wording": "Services with sufficient staff not available",
                     "delivery_scope": "combined_service_staffing_deficiency"}]}],
                "expected_measure_counts": {"combined_deficiency": 2}}
            with patch("pdfplumber.open", return_value=PDF()):
                result = extract_profile(path, profile)
                self.assertEqual(result["counts"]["source_cells"], 3)
                self.assertEqual(result["counts"]["observations"], 2)
                self.assertTrue(all(o["clinical_service"] is None for o in result["observations"]))
                self.assertEqual(result["observations"][0]["raw_value_or_excerpt"], "H/A,\nH/B,")


if __name__ == "__main__":
    unittest.main()
