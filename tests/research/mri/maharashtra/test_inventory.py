import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.mri.maharashtra.inventory import URL, compile_inventory, run


def table(headings, rows, caption=""):
    header = "<tr>" + "".join(f"<th>{v}</th>" for v in headings) + "</tr>"
    return ("<table>" + (f"<caption>{caption}</caption>" if caption else "") + header +
            "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows) + "</table>")


def inputs(document):
    raw = document.encode()
    return raw, {"url": URL, "sha256": hashlib.sha256(raw).hexdigest(), "retrieved_at": "2026-01-10T00:00:00Z"}


class InventoryTests(unittest.TestCase):
    def test_swapped_columns_positive_zero_missing_and_group(self):
        decoy = table(["Hospital Name", "CT Scan Facility"], [["Unrelated", "98"]])
        page = decoy + table(["MRI Scan", "Hospital Name", "CT Scan Facility"],
                             [["3", "Example Group of Hospitals", "91"], ["0", "Example Campus East", "8"],
                              ["", "Example Campus West", "79"], ["N/A", "Example Campus South", "70"]])
        result = compile_inventory(*inputs(page))
        rows = result["rows.json"]
        self.assertEqual([r["count"] for r in rows], [3, 0, None, None])
        self.assertEqual([r["value_status"] for r in rows], ["positive", "zero", "missing", "malformed"])
        self.assertIn("group_institution", rows[0]["flags"])
        batch = result["batch.json"]
        self.assertEqual(len(batch["facility_evidence"]), 2)
        self.assertEqual([r["excerpt"] for r in batch["facility_evidence"]], ["3", "0"])
        self.assertEqual(batch["facility_matches"], [])
        for e in batch["facility_evidence"]:
            self.assertIsNone(e["facility_id"])
            self.assertIsNone(e["match_id"])
            self.assertIsNone(e["effective_date"])
            self.assertEqual((e["service"],e["polarity"]),("mri","inconclusive"))
            self.assertIn("HTML table 2",e["locator"])
            self.assertIn("cell 1, column MRI Scan", e["locator"])
        self.assertEqual(result["report.json"]["reported_units"], 3)
        self.assertEqual(result["report.json"]["rows_without_evidence"], 2)
        self.assertEqual(result["report.json"]["rejected_row_reasons"], {"missing_mri_value":1,"malformed_mri_value":1})

    def test_partial_rows_spans_and_missing_name_are_retained_for_review(self):
        page = table(["Hospital Name","CT Scan Facility","MRI Scan"], [
            ["Example Campus","17"], ["","1","6"], ["Example Campus","0","1"]])
        page = page.replace("</table>", '<tr><td colspan="2">Merged cells</td><td>7</td></tr></table>')
        result = compile_inventory(*inputs(page))
        self.assertEqual(result["report.json"]["input_rows"],4)
        self.assertEqual(result["report.json"]["rows_without_evidence"],3)
        self.assertEqual(len(result["batch.json"]["review_queue"]),3)
        self.assertEqual(result["rows.json"][0]["value_status"],"unreadable_layout")
        self.assertEqual(result["rows.json"][2]["locator"],"HTML table 1, physical tr 4 (1-based)")
        self.assertEqual(result["batch.json"]["facility_evidence"][0]["excerpt"],"1")

    def test_dates_are_distinct_and_frozen(self):
        page = '<meta property="article:published_time" content="2025-02-02T08:00:00Z">' + table(
            ["Hospital Name","MRI Scan"], [["Example","1"]], "Inventory as of: 2025-01-31")
        result = compile_inventory(*inputs(page))
        self.assertEqual(result["batch.json"]["source_snapshots"][0]["published_date"],"2025-02-02")
        self.assertEqual(result["batch.json"]["facility_evidence"][0]["effective_date"],"2025-01-31")
        undated = compile_inventory(*inputs(page.replace("Inventory as of: 2025-01-31","Other heading")))
        self.assertIsNone(undated["batch.json"]["facility_evidence"][0]["effective_date"])

    def test_ambiguous_headers_wrong_capture_and_repeat_headers(self):
        one = table(["Hospital Name","MRI Scan"], [["Example","0"]])
        for malformed in (one+one, one.replace("MRI Scan","CT Scan"), table(["Hospital Name","MRI","MRI Scan"],[])):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                compile_inventory(*inputs(malformed))
        raw, meta = inputs(one)
        with self.assertRaisesRegex(ValueError, "hash"):
            compile_inventory(raw+b" ",meta)
        repeated = one.replace("</table>", "<tr><th>Hospital Name</th><th>MRI Scan</th></tr></table>")
        self.assertEqual(compile_inventory(*inputs(repeated))["report.json"]["repeated_headers"],1)

    def test_repeat_build_and_changed_input_do_not_overwrite_a_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html, receipt, out = root/"snapshot.html", root/"capture.json", root/"out"
            raw, meta = inputs(table(["Hospital Name","MRI Scan"],[["Example", "0"]]))
            html.write_bytes(raw)
            receipt.write_text(json.dumps(meta))
            digests = run(html,receipt,out)
            self.assertEqual(run(html,receipt,out),digests)
            self.assertEqual(hashlib.sha256((out/"batch.json").read_bytes()).hexdigest(),digests["batch.json"])
            raw, meta = inputs(table(["Hospital Name","MRI Scan"],[["Example","1"]]))
            html.write_bytes(raw)
            receipt.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, "differs"):
                run(html,receipt,out)
