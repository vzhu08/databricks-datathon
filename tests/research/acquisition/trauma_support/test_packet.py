"""Synthetic boundary tests; no source or Marketplace rows in Git."""
from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from research.acquisition.trauma_support.parser import (
    GridRow, functionality, parse_grid, read_edition, state_key,
)
from research.acquisition.trauma_support.packet import (
    compare_editions, encoded, national_run, summarize, save,
)
from research.acquisition.trauma_support.verify_packet import verify


def observed(edition="functional2025", resource="trauma_care", status="reported_functional", name="Example Hospital"):
    return {"edition": edition, "resource": resource, "functionality": status,
            "name_printed": name, "state": "Rajasthan", "mention_id": edition + ":" + resource + ":" + name,
            "effective_date": None, "programme_stage": "sanctioned"}


def original(fid, uid="source-a", name="Example Hospital", state="Rajasthan"):
    return {"facility_id": fid, "source_row": {"unique_id": uid, "name": name,
                                               "address_stateOrRegion": state}}


class GridTests(unittest.TestCase):
    def test_carries_state_across_page_but_preserves_printed_cells(self):
        grid = [GridRow(7, ("1", "Andhra\nPrades\nh", "Example Alpha", "II", "11th", "Functional")),
                GridRow(8, ("2", "", "Example Beta", "III", "12th", "Non Functional"))]
        rows = parse_grid(grid, "trauma_care", 6, 2, True)
        self.assertEqual(rows[1]["state"], "Andhra Pradesh")
        self.assertEqual(rows[1]["state_page"], 7)
        self.assertEqual(rows[1]["raw_cells"][1], "")
        self.assertEqual(rows[1]["functionality"], "reported_nonfunctional")

    def test_all_observed_negative_forms_stay_negative(self):
        for value in ["Non-Functional", "Non functional", "Non - Functional", "Nonfunctional", "Non-functioanl"]:
            self.assertEqual(functionality(value), "reported_nonfunctional")
        self.assertEqual(functionality(None), "not_reported")
        with self.assertRaises(ValueError):
            functionality("Not yet functional but will start")

    def test_sanction_is_not_functionality(self):
        row = GridRow(2, ("1", "Rajasthan", "Example Alpha", "II"))
        result = parse_grid([row], "trauma_care", 4, 1, False)[0]
        self.assertEqual(result["functionality"], "not_reported")
        self.assertIsNone(result["status_printed"])

    def test_fails_on_lost_row_unknown_state_and_wrong_width(self):
        for row in [GridRow(2, ("2", "Rajasthan", "Example", "II")),
                    GridRow(2, ("1", "", "Example", "II")),
                    GridRow(2, ("1", "Unknownland", "Example", "II")),
                    GridRow(2, ("1", "Rajasthan", "Example"))]:
            with self.assertRaises(ValueError):
                parse_grid([row], "trauma_care", 4, 1, False)

    def test_historical_boundaries_not_silently_reassigned(self):
        self.assertEqual(state_key("J&K"), "Jammu and Kashmir")
        self.assertEqual(state_key("Ladakh"), "Ladakh")
        self.assertNotEqual(state_key("Dadar & Nagar Haveli"), state_key("Dadra and Nagar Haveli and Daman and Diu"))

    def test_changed_source_fails_before_pdf_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "functional-20250725.pdf").write_bytes(b"changed edition")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                read_edition(tmp, "functional2025")


class NationalTests(unittest.TestCase):
    def test_preserves_duplicate_occurrences_unknowns_and_three_decisions(self):
        base = [original("copy-1"), original("copy-2"), original("missing", "b", None, None)]
        before = deepcopy(base)
        report, links, decisions = national_run(base, [observed()], "2026-11-22")
        self.assertEqual(base, before)
        self.assertEqual(len(decisions), 9)
        self.assertEqual({d["status"] for d in decisions}, {"unconfirmed"})
        self.assertEqual(report["extra_identical_occurrences_preserved"], 1)
        self.assertEqual(report["ambiguous_label_candidate_occurrences"], 0)
        self.assertEqual(report["candidate_distinct_upstream_ids"], 1)
        self.assertEqual(report["geography"]["(no state label)"]["original_occurrences"], 1)
        self.assertEqual(len(links), 2)

    def test_negative_or_burn_does_not_promote_service(self):
        rows = [observed(status="reported_nonfunctional"), observed(resource="burn_treatment")]
        report, links, decisions = national_run([original("a")], rows, "2026-11-22")
        self.assertEqual(report["no_decisions"], 0)
        self.assertEqual(report["yes_decisions"], 0)
        trauma = next(d for d in decisions if d["service"] == "trauma_care")
        self.assertEqual(len(trauma["candidate_mentions"]), 1)
        self.assertFalse(any(l["campus_confirmed"] for l in links))

    def test_name_collisions_flagged_and_other_state_not_joined(self):
        base = [original("a"), original("b", "different-id"), original("c", "c", state="Gujarat")]
        report, _, _ = national_run(base, [observed()], "2026-11-22")
        self.assertEqual(report["ambiguous_label_candidate_occurrences"], 2)
        self.assertEqual(report["candidate_occurrences"], 2)

    def test_replay_is_deterministic_and_cannot_lose_keys(self):
        args = ([original("a")], [observed()], "2026-11-22")
        self.assertEqual(encoded(national_run(*args)), encoded(national_run(*args)))
        with self.assertRaises(ValueError):
            national_run([original("a"), original("a")], [], "2026-11-22")

    def test_editions_share_origin_but_keep_differing_assertions(self):
        rows = [observed("freeze65"), observed(status="reported_nonfunctional"), observed("sanction2026", status="not_reported")]
        report, pairs = compare_editions(rows)
        self.assertEqual(sum(r["different_functionality_assertions"] for r in report), 1)
        self.assertFalse(any(p["same_date_conflict"] for p in pairs))
        summary = summarize(rows)
        self.assertEqual(summary["raw_mentions"], 3)
        self.assertEqual(summary["unique_label_resource_keys_across_editions"], 1)
        self.assertEqual(summary["independent_upstream_origins"], 1)

    def test_ambiguous_edition_keys_are_not_paired(self):
        rows = [observed("freeze65"), observed("freeze65"), observed()]
        reports, pairs = compare_editions(rows)
        self.assertEqual(reports[0]["ambiguous_shared_label_keys"], 1)
        self.assertEqual(pairs, [])


class PacketBoundaryTests(unittest.TestCase):
    def test_changed_bytes_and_extra_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {"original_occurrences": 10088, "distinct_upstream_ids": 10077,
                      "occurrence_service_decisions": 30264,
                      "geography": {"synthetic": {"original_occurrences": 10088}}}
            files = {name: save(root / name, data) for name, data in [
                ("aggregate-report.json", report), ("edition-provenance.json", []), ("source-gaps.json", {})]}
            saved = save(root / "manifest.json", {"files": files})
            self.assertEqual(verify(root, saved["sha256"])["verified_files"], 4)
            (root / "raw-unexpected.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                verify(root, saved["sha256"])
            (root / "raw-unexpected.json").unlink()
            (root / "source-gaps.json").write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, "Size/hash"):
                verify(root, saved["sha256"])

    def test_path_traversal_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = save(root / "manifest.json", {"files": {"../outside.json": {}}})
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                verify(root, saved["sha256"])


if __name__ == "__main__":
    unittest.main()
