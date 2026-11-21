import json
import tempfile
import unittest
from pathlib import Path

from research.trauma.identity.crosswalk import Campus, build_crosswalk
from research.trauma.identity.producer import (
    build,
    empty_batch,
    facility,
    json_bytes,
    make_snapshot,
    read_b1,
    validate,
)
from research.trauma.identity.rghs import Table, normalize_words, parse_date, parse_tables


class PDFTableTests(unittest.TestCase):
    def test_repeated_headers_and_wrapped_address(self):
        header = ["S.No", "RGHS Hospital ID", "Name of Hospital", "Address",
                  "District", "City", "Empanelment\nValid Till"]
        rows, issues = parse_tables([
            Table(1, 1, [
                header,
                ["1", "0007", "A.B. Hospital", "Sector 8\nNear Lake", "Example", "Lake",
                 "31-12-2027"],
                [None, None, None, "North Gate", None, None, None],
            ]),
            Table(2, 1, [header, ["2", "0008", "नया अस्पताल", "Road 5", "Example", "Lake", None]]),
        ])
        self.assertEqual(issues, [])
        self.assertEqual([row.fields["identifier"] for row in rows], ["0007", "0008"])
        self.assertEqual(rows[0].fields["address"], "Sector 8\nNear Lake\nNorth Gate")
        self.assertEqual(rows[0].record_locator,
                         "PDF page 1, table 1, row 2; continuation at PDF page 1, table 1, row 3")
        self.assertEqual(rows[1].fields["name"], "नया अस्पताल")

    def test_header_layout_can_change_on_new_page(self):
        rows, issues = parse_tables([
            Table(1, 1, [["S.No", "Facility Name", "Address", "District"],
                         ["1", "Oak Centre", "Oak Rd", "Example"]]),
            Table(2, 1, [["District", "Facility ID", "Facility Name", "City"],
                         ["Other", "H-2", "Willow Centre", "Willow"]]),
        ])
        self.assertEqual(issues, [])
        self.assertEqual(rows[0].fields["serial"], "1")
        self.assertNotIn("identifier", rows[0].fields)
        self.assertEqual(rows[1].fields["identifier"], "H-2")
        self.assertEqual(rows[1].fields["district"], "Other")

    def test_unassigned_lines_are_visible_and_do_not_attach_to_prior_page(self):
        rows, issues = parse_tables([
            Table(1, 1, [["S.No", "Facility Name", "Address", "District"],
                         ["Test district", None, None, None],
                         ["1", "Oak Centre", "Old Rd", "Example"]]),
            Table(2, 1, [[None, None, "Unassigned Rd", None],
                         ["2", "Other Centre", "Other Rd", "Other"]]),
            Table(4, 1, [["3", "No header", "Unknown", "Other"]]),
        ])
        self.assertEqual([row.fields["address"] for row in rows], ["Old Rd", "Other Rd"])
        self.assertEqual([item["code"] for item in issues], [
            "section_or_non_numeric_serial", "unassigned_section_or_row", "unrecognized_layout"
        ])

    def test_missing_name_preserved_and_invalid_date_flagged(self):
        rows, _ = parse_tables([Table(1, 1, [
            ["Hospital ID", "Hospital Name", "City", "Valid Till"],
            ["H-1", None, "Sample", "31/02/2026"],
        ], "text")])
        self.assertEqual(set(rows[0].flags), {
            "missing_name", "missing_address", "missing_district", "invalid_expiry_date",
            "text_layout_review_required",
        })
        self.assertIsNone(parse_date("31/02/2026"))
        self.assertEqual(parse_date("29.02.2024"), "2024-02-29")
        self.assertEqual(parse_date("2027-10-05"), "2027-10-05")

    def test_duplicate_payload_deduped_and_repeated_id_variants_preserved(self):
        rows, issues = parse_tables([Table(1, 1, [
            ["S.No", "Hospital ID", "Hospital Name", "Address", "District"],
            ["1", "001", "Oak", "Oak street", "Example"],
            ["2", "001", "Oak", "Oak street", "Example"],
            ["3", "001", "Oak", "Willow street", "Example"],
        ])])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all("repeated_hospital_identifier" in row.flags for row in rows))
        self.assertEqual([issue["code"] for issue in issues].count("duplicate_identifier_payload"), 1)
        self.assertEqual([issue["code"] for issue in issues].count("conflicting_identifier_payload"), 2)

    def test_unicode_name_and_initials(self):
        self.assertEqual(normalize_words("A.B. अस्पताल"), ["ab", "अस्पताल"])
        self.assertEqual(normalize_words("A. B. Hospital"), ["ab", "hospital"])


class CrosswalkTests(unittest.TestCase):
    def test_same_name_different_campuses_are_retained(self):
        state = Campus("b1:1", "state", "row 1", "Oak Hospital", "Example",
                       address="North Gate")
        north = Campus("b2:1", "rghs", "row 7", "Oak Hospital", "Example",
                       address="North Gate")
        south = Campus("b2:2", "rghs", "row 9", "Oak Hospital", "Example",
                       address="South Gate")
        other = Campus("b2:3", "rghs", "row 3", "Oak Hospital", "Different district")
        result, = build_crosswalk([state], [other, south, north])
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual([row["external_facility_id"] for row in result["alternatives"]],
                         ["b2:1", "b2:2", "b2:3"])
        self.assertIn("address_terms_agree", result["alternatives"][0]["signals"])
        self.assertIn("district_disagrees", result["alternatives"][2]["limitations"])

    def test_initialism_collision_remains_open(self):
        state = Campus("b1:1", "state", "row 1", "A.B. Hospital", "Example")
        a = Campus("b2:1", "rghs", "row 1", "Amber Banyan Hospital", "Example")
        b = Campus("b2:2", "rghs", "row 2", "Azure Brook Hospital", "Example")
        result, = build_crosswalk([state], [a, b])
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["review_status"], "pending")
        self.assertTrue(all("initialism_expansion" in item["signals"]
                            for item in result["alternatives"]))

    def test_medical_college_and_affiliated_hospital_stay_distinct(self):
        state = Campus("b1:1", "state", "row 1", "A.B. Hospital", "Example")
        hospital = Campus("b2:1", "rghs", "row 1", "AB Hospital", "Example")
        college = Campus("b2:2", "rghs", "row 2", "AB Medical College", "Example",
                         facility_type="medical_college")
        satellite = Campus("b2:3", "rghs", "row 3", "Satellite Hospital", "Example",
                           institution="AB Medical College")
        result, = build_crosswalk([state], [college, satellite, hospital])
        self.assertEqual(result["alternatives"][0]["external_facility_id"], "b2:1")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("associated_institution_name", result["alternatives"][2]["signals"])

    def test_no_weak_district_only_match(self):
        state = Campus("b1:1", "state", "row 1", "Oak Hospital", "Example")
        other = Campus("b2:1", "rghs", "row 2", "Willow Hospital", "Example")
        result, = build_crosswalk([state], [other])
        self.assertEqual(result["status"], "unmatched")
        self.assertEqual(result["alternatives"], [])

    def test_district_or_pin_conflict_retained_as_ambiguous(self):
        state = Campus("b1:1", "state", "row 1", "Oak Hospital", "Example", pin="111111")
        other = Campus("b2:1", "rghs", "row 2", "Oak Hospital", "Example", pin="222222")
        result, = build_crosswalk([state], [other])
        self.assertEqual(result["status"], "ambiguous")
        self.assertIn("pin_disagrees", result["alternatives"][0]["limitations"])


class ProducerTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name).resolve()
        self.raw = self.root / "source.html"
        self.raw.write_text("<table><tr><td id='name'>Oak Hospital</td></tr></table>",
                            encoding="utf-8")
        self.source = {
            "mode": "reviewed", "source_key": "official_example", "publisher": "Example",
            "source_family": "example", "url": "https://example.invalid/doc",
            "retrieved_at": "2026-11-21T00:00:00Z", "attribution": "Example",
            "published_date": "2025-03-04",
            "path": self.raw.name, "records": [{
                "name": "Oak Hospital", "district": "Example", "locator": "HTML row 1",
                "claims": [{"locator": "HTML row 1, name", "selector": "#name",
                            "excerpt": "Oak Hospital", "assertion": "The source names the hospital."}],
            }],
        }

    def test_replay_preserves_ids_bytes_and_reference_integrity(self):
        manifest = self.root / "manifest.json"
        manifest.write_bytes(json_bytes({"sources": [self.source]}))
        b1 = [Campus("b1:1", "state", "HTML row 1", "Oak Hospital", "Example")]
        result = build(manifest, b1)
        self.assertEqual(json_bytes(result), json_bytes(build(manifest, b1)))
        batch, ledger, _ = result
        validate(batch, {"b1:1"})
        self.assertEqual(ledger[0]["status"], "candidate")
        self.assertEqual(batch["facility_matches"], [])
        claim, = batch["facility_evidence"]
        self.assertIsNone(claim["facility_id"])
        self.assertIsNone(claim["match_id"])
        self.assertIsNone(claim["service"])
        self.assertIsNone(claim["effective_date"])
        self.assertEqual(claim["temporal_status"], "undated")
        self.assertEqual(batch["source_snapshots"][0]["published_date"], "2025-03-04")

    def test_reviewed_source_claim_must_be_at_cited_selector(self):
        manifest = self.root / "manifest.json"
        self.source["records"][0]["claims"][0]["selector"] = "#wrong"
        manifest.write_bytes(json_bytes({"sources": [self.source]}))
        with self.assertRaisesRegex(ValueError, "Excerpt missing"):
            build(manifest, [])

    def test_b1_ledger_join_detects_drift(self):
        base = empty_batch()
        source = {**self.source, "source_key": "rajasthan_trauma"}
        snapshot = make_snapshot(source, self.raw, None)
        external = facility(snapshot, {"name": "Oak Hospital", "locator": "HTML row 1"})
        base["source_snapshots"].append(snapshot)
        base["external_facilities"].append(external)
        batch_path = self.root / "batch.json"
        ledger_path = self.root / "campuses.json"
        batch_path.write_bytes(json_bytes(base))
        ledger_path.write_bytes(json_bytes([
            {"external_facility_id": external["external_facility_id"], "district_original": "Example"}
        ]))
        self.assertEqual(read_b1(batch_path, ledger_path)[0].district, "Example")
        ledger_path.write_text(json.dumps([]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "different facility IDs"):
            read_b1(batch_path, ledger_path)

    def test_invalid_or_conflicting_pin_null_with_quality_flag(self):
        snapshot = make_snapshot(self.source, self.raw, None)
        row = {"name": "Oak Hospital", "locator": "HTML row 1", "pin": "unknown",
               "address": "Sector 5, 305001"}
        invalid = facility(snapshot, row)
        self.assertIsNone(invalid["pin"])
        self.assertIn("invalid_pin", invalid["quality_flags"])
        conflict = facility(snapshot, {**row, "pin": "305002"})
        self.assertIsNone(conflict["pin"])
        self.assertIn("conflicting_pin", conflict["quality_flags"])


if __name__ == "__main__":
    unittest.main()
