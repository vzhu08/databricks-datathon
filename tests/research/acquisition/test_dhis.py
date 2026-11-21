"""Synthetic original pages and institutional tables for the DHIS parser."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.acquisition.common import AcquisitionError, canonical, digest, write_json
from research.acquisition.dhis import audit_sample, compile_reference, extract, read_table, district_check
from fixtures import snapshot


HEADER = ["S. No.", "District", "Name"]


def section(annexure="A", status="registration", page=1):
    return {"annexure": annexure, "status": status, "heading": "Synthetic registration list",
            "page": page, "heading_page": page, "table": 1, "reviewer": "fixture-reader"}


def blank_pdf():
    # One blank original page for a hash-bound synthetic visual transcript.
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << >> >>"]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(body)
    body.extend(b"xref\n0 4\n0000000000 65535 f \n")
    for offset in offsets:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return bytes(body)


class DhisTests(unittest.TestCase):
    def test_wrapping_and_repeated_headers_keep_first_and_last_row(self):
        rows = read_table([HEADER, ["1", "North", "Example\nRegional"], [None, None, "Campus"],
                           HEADER, ["2", "South", "Other campus"]], section())
        self.assertEqual(rows[0]["name_original"], "Example\nRegional\nCampus")
        self.assertEqual((2, 3), (rows[0]["first_table_row"], rows[0]["last_table_row"]))
        self.assertEqual(rows[1]["record_locator"], "annexure=A;page=1;table=1;row=5")

    def test_district_review_keeps_printed_label_and_whole_word_mentions(self):
        rows = read_table([HEADER, ["1", "South", "Clinic in North"], ["2", "North", "Northumberland"],
                           ["3", None, "Centre"]], section())
        self.assertEqual(district_check(rows[0], {"north", "south"}), ("name_mentions_another_district", ["north"]))
        self.assertEqual(rows[0]["district_original"], "South")
        self.assertEqual(district_check(rows[1], {"north", "south"})[0], "no_disagreement_detected")
        self.assertEqual(district_check(rows[2], {"north", "south"})[0], "printed_district_unrecognized")

    def test_annexure_status_and_duplicate_campus_entries_remain_distinct(self):
        rows = []
        states = ["registration", "onboarding", "eligibility", "incentive_claimed", "incentive_paid"]
        for page, state in enumerate(states, 1):
            metadata = section(str(page), state, page)
            metadata["heading"] = "Synthetic " + state + " list"
            rows += read_table([HEADER, ["1", "North", "Example Campus"]], metadata)
        result = compile_reference(rows, snapshot(), {"district_labels": ["North"]}, len(states))
        self.assertEqual(set(states), set(result["report.json"]["by_administrative_status"]))
        batch = result["batch.json"]
        self.assertEqual(len(states), len({f["external_facility_id"] for f in batch["external_facilities"]}))
        self.assertEqual([], batch["facility_matches"])
        self.assertEqual([], batch["facility_evidence"])

    def test_unexpected_noninstitutional_tables_or_orphan_rows_stop(self):
        cases = [[["S. No.", "Transaction threshold", "Incentive amount"], ["1", "5", "X"]],
                 [HEADER, ["", "", "Orphan"]], [HEADER, ["1", "North", "Name", "Extra"]]]
        for table in cases:
            with self.subTest(table=table), self.assertRaises(AcquisitionError):
                read_table(table, section())

    def test_sample_round_robins_annexures_and_pages(self):
        rows = []
        for annexure, page in (("A", 1), ("A", 2), ("B", 3)):
            rows += read_table([HEADER] + [[str(i), "North", "Clinic"] for i in range(1, 24)],
                               section(annexure, page=page))
        sample = audit_sample(rows)
        self.assertEqual(20, len(set(sample)))
        self.assertTrue(sample[0].startswith("annexure=A;page=1;"))
        self.assertTrue(sample[1].startswith("annexure=B;page=3;"))
        self.assertTrue(sample[2].startswith("annexure=A;page=2;"))

    def test_audit_wrong_digest_is_rejected(self):
        rows = read_table([HEADER, ["1", "North", "Example"]], section())
        layout = {"district_labels": ["North"], "audit": {rows[0]["record_locator"]: {
            "reviewer": "second reader", "reason": "Compared cells", "outcome": "pass", "fields_sha256": "bad"}}}
        with self.assertRaisesRegex(AcquisitionError, "invalid_audit"):
            compile_reference(rows, snapshot(), layout, 1)

    @unittest.skipUnless(importlib.util.find_spec("pdfplumber"), "install optional acquisition PDF requirements")
    def test_real_pdf_hash_binding_overlap_and_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            pdf = Path(temp) / "synthetic.pdf"
            pdf.write_bytes(blank_pdf())
            layout = {
                "sha256": digest(pdf.read_bytes()), "url": "https://example.invalid/letter.pdf",
                "retrieved_at": "2025-08-01T12:00:00Z", "document_date": "2025-06-09", "artifact_uri": pdf.as_uri(),
                "district_labels": ["North", "South"], "tables": [{**section(), "visual_transcript": [
                    HEADER, ["1", "North", "Example South Campus"]]}],
            }
            overlap = Path(temp) / "explicit.json"
            write_json(overlap, {"external_facilities": [{"external_facility_id": "example:1", "name_original": "Example South Campus"}]})
            results = extract(pdf, layout, overlap)
            self.assertEqual(results["report.json"]["rows"], 1)
            self.assertEqual(results["overlap.json"]["candidate_pairs"], 1)
            self.assertEqual(results["overlap.json"]["confirmed_campuses"], 0)
            self.assertEqual(results["overlap.json"]["unmatched_reference_rows"], 0)
            self.assertEqual(results["report.json"]["audit_reviewed"], 0)
            self.assertEqual(canonical(results), canonical(extract(pdf, copy.deepcopy(layout), overlap)))
            duplicate = copy.deepcopy(layout)
            duplicate["tables"] *= 2
            with self.assertRaisesRegex(AcquisitionError, "invalid_visual"):
                extract(pdf, duplicate)
            layout["sha256"] = "a" * 64
            with self.assertRaisesRegex(AcquisitionError, "wrong_source"):
                extract(pdf, layout)


if __name__ == "__main__":
    unittest.main()
