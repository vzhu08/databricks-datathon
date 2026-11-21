"""Synthetic institutional-only PDF layout and audit gates."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.acquisition.adip import exact_name_overlap, institutions, make_reference, publish_overlap
from research.acquisition.common import AcquisitionError, canonical, digest, publish_json_directory
from fixtures import snapshot

HEADER = ["Sr. No.", "State", "Name of Hospital", "Name of Doctor", "Contact Details", "Email Id"]


class AdipTests(unittest.TestCase):
    def test_reference_failure_leaves_output_available_for_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "reference"
            payloads = {"a.json": [1], "b.json": [2]}
            with patch("research.acquisition.common.write_json", side_effect=[None, OSError("disk full")]):
                with self.assertRaises(OSError):
                    publish_json_directory(output, payloads, "conflict")
            self.assertFalse(output.exists())
            publish_json_directory(output, payloads, "conflict")
            publish_json_directory(output, payloads, "conflict")
            with self.assertRaises(AcquisitionError):
                publish_json_directory(output, {"a.json": [3], "b.json": [2]}, "conflict")

    def test_overlap_replay_and_preservation_of_existing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "prior.json"
            publish_overlap(path, {"accepted": True})
            publish_overlap(path, {"accepted": True})
            before = path.read_bytes()
            with self.assertRaisesRegex(AcquisitionError, "existing_overlap"):
                publish_overlap(path, {"different": True})
            self.assertEqual(path.read_bytes(), before)

    def table(self):
        return [HEADER.copy(), ["1", "Rajasthan", "Example Very Long\nHospital and College\n1 Road, Example City", "PRIVATE_DOCTOR", "PRIVATE_PHONE", "PRIVATE_EMAIL"],
                ["", "", "", "PRIVATE_CONTINUATION", "PRIVATE_PHONE", "PRIVATE_EMAIL"], HEADER.copy(),
                ["2", "Other State", "Other hospital", None, None, None]]

    def inputs(self):
        rows = institutions([(2, 1, self.table())])
        audit = {"raw_sha256": snapshot()["sha256"], "rows": [{
            "record_locator": rows[0]["record_locator"], "institution_sha256": digest(rows[0]["institution_original"].encode()),
            "name_end": len("Example Very Long\nHospital and College"), "visually_checked": True, "campus_ambiguity": True}]}
        return rows, audit

    def test_repeated_headers_blank_contact_rows_and_long_names(self):
        rows, audit = self.inputs(); batch, sidecar = make_reference(rows, snapshot(), audit)
        self.assertEqual(1, len(rows)); self.assertEqual(2, rows[0]["extracted_table_row"])
        self.assertEqual("Example Very Long\nHospital and College", batch["external_facilities"][0]["name_original"])
        self.assertNotIn(b"PRIVATE", canonical([batch, sidecar]))
        self.assertIsNone(batch["external_facilities"][0]["city"])
        self.assertEqual([], batch["facility_matches"]); self.assertEqual([], batch["facility_evidence"])
        self.assertIn("multiple_institution_or_group_wording", batch["external_facilities"][0]["quality_flags"])

    def test_missing_state_does_not_inherit_previous_row(self):
        table = self.table(); table[1][1] = None
        with self.assertRaisesRegex(AcquisitionError, "missing_state"): institutions([(2, 1, table)])

    def test_table_schema_drift_rejected(self):
        table = self.table(); table[0][2] = "Changed column"
        with self.assertRaisesRegex(AcquisitionError, "header_changed"): institutions([(2, 1, table)])
        table = self.table(); table[1] = table[1][:3]
        with self.assertRaisesRegex(AcquisitionError, "width_changed"): institutions([(2, 1, table)])

    def test_missing_audit_stale_hash_and_unchecked_rows_rejected(self):
        rows, audit = self.inputs()
        for mutate in (lambda a:a.update(raw_sha256="1"*64), lambda a:a.update(rows=[]),
                       lambda a:a["rows"][0].update(visually_checked=False), lambda a:a["rows"][0].update(name_end=999)):
            changed = copy.deepcopy(audit); mutate(changed)
            with self.assertRaises(AcquisitionError): make_reference(rows, snapshot(), changed)

    def test_changed_institution_and_deterministic_replay(self):
        rows, audit = self.inputs()
        self.assertEqual(canonical(make_reference(rows, snapshot(), audit)), canonical(make_reference(rows, snapshot(), audit)))
        rows[0]["institution_original"] += " changed"
        with self.assertRaisesRegex(AcquisitionError, "unaudited_or_changed"): make_reference(rows, snapshot(), audit)

    def test_name_overlap_keeps_both_candidates_and_confirms_no_campus(self):
        rows, audit = self.inputs(); batch, _ = make_reference(rows, snapshot(), audit)
        regional = copy.deepcopy(batch)
        other = copy.deepcopy(regional["external_facilities"][0]); other["external_facility_id"] = "other"
        regional["external_facilities"].append(other)
        before = canonical([batch, regional])
        result = exact_name_overlap(batch, regional)
        self.assertEqual(2, result["candidate_pairs"])
        self.assertEqual(0, result["confirmed_campuses"])
        self.assertEqual(before, canonical([batch, regional]))


if __name__ == "__main__": unittest.main()
