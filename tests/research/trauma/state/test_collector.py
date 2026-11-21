import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from research.trauma.state.collector import build_artifacts, parse_listing


ROOT = Path(__file__).resolve().parents[4]
METADATA = {
    "source_url": "https://example.invalid/roadsafety",
    "retrieved_at": "2026-11-21T18:00:00Z",
    "artifact_uri": "file:///synthetic.html",
}
HEADERS = [
    "S.No.", "District", "Truma center Location", "108 Ambulance Availabilty",
    "Vehicle No", "ALS Ambulance Availabilty", "Vehicle No",
]
EXAMPLE = ["1", "Jaipur", "परीक्षण चिकित्सालय &amp; Trauma Unit", "No", "&nbsp;", "YES", "TEST 01"]


def html_row(values, tag="td"):
    return "<tr>" + "".join(f"<{tag}>{value}</{tag}>" for value in values) + "</tr>"


def page(*rows, headers=HEADERS, annotations="", title="Trauma Centres", layout=True):
    body = "".join(rows)
    header = html_row(headers, "th")
    if layout:
        header = f"<thead>{header}</thead>"
        body = f"<tbody>{body}</tbody>"
    return (
        f"<html><body><h2>{title}</h2>{annotations}"
        f"<table>{header}{body}<tfoot><tr><td>Total</td></tr></tfoot></table>"
        '<footer class="copyright">Copyright © 2022</footer></body></html>'
    ).encode("utf-8")


class StateCollectorTests(unittest.TestCase):
    def test_unicode_html_rendering_and_evidence_context(self):
        batch, rows, report = build_artifacts(page(html_row(EXAMPLE)), METADATA, expected_count=3)
        row = rows[0]
        self.assertEqual(row["name_original"], "परीक्षण चिकित्सालय & Trauma Unit")
        self.assertTrue(batch["external_facilities"][0]["name_normalized"].startswith("परीक्षण"))
        self.assertEqual(row["district_original"], "Jaipur")
        self.assertEqual(row["ambulance_als_vehicle_values"], ["TEST 01"])
        self.assertIsNone(row["ambulance_108_vehicle_original"])
        self.assertIsNone(batch["external_facilities"][0]["city"])
        self.assertIsNone(batch["external_facilities"][0]["address_original"])
        claim = batch["facility_evidence"][0]
        self.assertEqual(claim["excerpt"], row["name_original"])
        self.assertIn("table 1, tr[2]", claim["locator"])
        self.assertIn("cell[3]", claim["locator"])
        self.assertEqual(row["designation_context"]["text"], "Trauma Centres")
        self.assertEqual(claim["temporal_status"], "undated")
        self.assertEqual(claim["polarity"], "inconclusive")
        self.assertIn("lists this facility under trauma centres", claim["assertion"])
        self.assertIn("Current trauma service capability is unknown", claim["assertion"])
        self.assertTrue(claim["evidence_id"].endswith(":trauma-listing-v2"))
        self.assertIsNone(claim["reviewer"])
        self.assertIsNone(claim["reviewed_at"])
        self.assertIsNone(claim["facility_id"])
        self.assertIsNone(claim["match_id"])
        self.assertEqual(report["row_count_delta"], -2)
        self.assertIsNone(batch["source_snapshots"][0]["published_date"])
        self.assertEqual(report["date_observations"]["copyright"][0]["original"], "2022")

    def test_layout_change_reordered_columns_decoy_and_repeated_header(self):
        order = [2, 1, 5, 6, 0, 3, 4]
        headers = [HEADERS[index] for index in order]
        record = [EXAMPLE[index] for index in order]
        raw = page(html_row(headers), html_row(record), headers=headers, layout=False)
        raw = raw.replace(b"<body>", b"<body><table><tr><th>District</th></tr></table>")
        _, rows, report = build_artifacts(raw, METADATA)
        self.assertEqual(report["table_number"], 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["table_row"], 3)
        self.assertEqual(rows[0]["ambulance_108_status_original"], "No")
        self.assertEqual(rows[0]["ambulance_als_status_original"], "YES")
        self.assertEqual(rows[0]["ambulance_als_vehicle_original"], "TEST 01")

    def test_missing_physical_cell_held_for_layout_review(self):
        omitted_district = html_row([EXAMPLE[0], *EXAMPLE[2:]])
        batch, rows, report = build_artifacts(page(omitted_district), METADATA)
        self.assertEqual(len(rows[0]["cells_original"]), 6)
        self.assertIsNone(rows[0]["name_original"])
        self.assertIsNone(batch["external_facilities"][0]["name_original"])
        self.assertEqual(report["observed_rows"], 1)
        self.assertEqual(report["quality_flag_counts"], {"row_layout_mismatch": 1})
        self.assertEqual(batch["review_queue"][0]["reason_code"], "row_layout_mismatch")
        self.assertFalse(batch["facility_evidence"])

    def test_explicit_empty_cell_preserves_column_alignment(self):
        values = ["1", "", "Fictional Clinic", "NO", "", "", ""]
        batch, rows, report = build_artifacts(page(html_row(values)), METADATA)
        self.assertEqual(rows[0]["name_original"], "Fictional Clinic")
        self.assertIsNone(rows[0]["district_original"])
        self.assertEqual(report["blank_fields"]["district_original"], 1)
        self.assertEqual(report["blank_fields"]["ambulance_als_status_original"], 1)
        self.assertEqual(len(batch["facility_evidence"]), 1)
        self.assertEqual({item["reason_code"] for item in batch["review_queue"]},
                         {"missing_district", "ambulance_als_missing_status"})

    def test_duplicate_names_serials_and_malformed_district_stay_separate(self):
        one = html_row(["1", "Jaipur", "Fictional Hospital", "No", "", "No", ""])
        two = html_row(["1", "Bhurr district?", "Fictional—Hospital", "No", "", "No", ""])
        three = html_row(["4", "Ajmer", "Other Fictional Clinic", "No", "", "No", ""])
        batch, rows, report = build_artifacts(page(one, two, three), METADATA)
        self.assertEqual(report["duplicate_name_groups"], 1)
        self.assertEqual(report["duplicate_serial_groups"], 1)
        self.assertEqual(report["serial_gap_ranges"], [[2, 3]])
        self.assertEqual(rows[1]["district_original"], "Bhurr district?")
        self.assertIn("unexpected_district", rows[1]["quality_flags"])
        self.assertEqual(len({row["external_facility_id"] for row in rows}), 3)
        self.assertTrue(all(row["source_record_id"] is None for row in batch["external_facilities"]))

    def test_vehicle_values_and_status_are_source_data_only(self):
        values = ["1", "Ajmer", "Sample Hospital", "YES", "ZZ01, ZZ02<br/>ZZ 03", "No", "ZZ04"]
        batch, rows, _ = build_artifacts(page(html_row(values)), METADATA)
        self.assertEqual(rows[0]["ambulance_108_vehicle_original"], "ZZ01, ZZ02\nZZ 03")
        self.assertEqual(rows[0]["ambulance_108_vehicle_values"], ["ZZ01", "ZZ02", "ZZ 03"])
        self.assertIn("ambulance_108_multiple_vehicle_values", rows[0]["quality_flags"])
        self.assertIn("ambulance_als_vehicle_with_no", rows[0]["quality_flags"])
        self.assertEqual(len(batch["facility_evidence"]), 1)
        self.assertNotIn("ambulance", batch["facility_evidence"][0]["assertion"])

    def test_dates_distinguish_publication_as_of_expiry_and_copyright(self):
        raw = page(html_row(EXAMPLE), annotations=(
            "<p>Published 14 January 2020. Data as of 2020-02-04. Valid until 2021-03-31.</p>"
        ))
        batch, _, report = build_artifacts(raw, METADATA)
        self.assertEqual(batch["source_snapshots"][0]["published_date"], "2020-01-14")
        claim = batch["facility_evidence"][0]
        self.assertEqual(claim["effective_date"], "2020-02-04")
        self.assertEqual(claim["valid_until"], "2021-03-31")
        self.assertEqual(claim["temporal_status"], "expired")
        self.assertEqual(report["date_observations"]["copyright"][0]["original"], "2022")

    def test_date_conflicts_and_ambiguous_numeric_date_remain_unresolved(self):
        raw = page(html_row(EXAMPLE), annotations=(
            "<p>Published 2022-01-01. Published 2022-02-02. Last updated 10/11/2023.</p>"
        ))
        batch, _, report = build_artifacts(raw, METADATA)
        self.assertIsNone(batch["source_snapshots"][0]["published_date"])
        self.assertEqual(len(report["date_observations"]["published_date"]), 2)
        self.assertIsNone(report["dates"]["last_updated"])
        self.assertEqual(report["date_observations"]["last_updated"][0]["original"], "10/11/2023")

    def test_publication_and_future_cutoff_do_not_supply_an_effective_date(self):
        raw = page(html_row(EXAMPLE), annotations=(
            "<p>Published 2020-01-14. Valid until 2030-03-31.</p>"
        ))
        batch, _, report = build_artifacts(raw, METADATA)
        self.assertEqual(batch["source_snapshots"][0]["published_date"], "2020-01-14")
        claim = batch["facility_evidence"][0]
        self.assertEqual(claim["temporal_status"], "undated")
        self.assertIsNone(claim["effective_date"])
        self.assertIsNone(claim["valid_until"])
        self.assertEqual(report["dates"]["valid_until"], "2030-03-31")

    def test_explicit_planned_designation_does_not_support_trauma_capability(self):
        raw = page(html_row([*EXAMPLE, "Planned"]), headers=[*HEADERS, "Trauma designation"])
        batch, rows, _ = build_artifacts(raw, METADATA)
        evidence = batch["facility_evidence"][0]
        self.assertEqual(rows[0]["designation_original"], "Planned")
        self.assertEqual(evidence["excerpt"], "Planned")
        self.assertIn("cell[8]", evidence["locator"])
        self.assertEqual(evidence["polarity"], "inconclusive")
        self.assertEqual(batch["review_queue"][0]["reason_code"], "explicit_designation_requires_review")

    def test_source_layout_without_unambiguous_columns_rejected(self):
        with self.assertRaisesRegex(ValueError, "Expected one trauma directory table"):
            parse_listing(page(html_row(EXAMPLE), headers=HEADERS[:-1]))
        with self.assertRaisesRegex(ValueError, "Ambiguous column headers"):
            parse_listing(page(html_row(EXAMPLE), headers=[*HEADERS, "District name"]))

    def test_snapshot_replay_and_contract_references(self):
        raw = page(html_row(EXAMPLE))
        first, _, _ = build_artifacts(raw, METADATA)
        self.assertEqual(first, build_artifacts(raw, METADATA)[0])
        newer = build_artifacts(raw.replace(b"TEST 01", b"TEST 02"), METADATA)[0]
        self.assertNotEqual(first["source_snapshots"][0]["snapshot_id"], newer["source_snapshots"][0]["snapshot_id"])
        self.assertNotEqual(first["external_facilities"][0]["external_facility_id"],
                            newer["external_facilities"][0]["external_facility_id"])
        schema = json.loads((ROOT / "contracts/enrichment/schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)
        claim = first["facility_evidence"][0]
        facility = first["external_facilities"][0]
        self.assertEqual(claim["external_facility_id"], facility["external_facility_id"])
        self.assertEqual(claim["snapshot_id"], facility["snapshot_id"])
        self.assertEqual(facility["snapshot_id"], first["source_snapshots"][0]["snapshot_id"])

    def test_cli_writes_validated_artifacts_and_absolute_checksums(self):
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            snapshot = tmp / "snapshot.html"
            snapshot.write_bytes(page(html_row(EXAMPLE)))
            metadata = tmp / "metadata.json"
            metadata.write_text(json.dumps(METADATA), encoding="utf-8")
            output = tmp / "output"
            result = subprocess.run(
                [sys.executable, "-m", "research.trauma.state.collector", "--html", str(snapshot),
                 "--metadata", str(metadata), "--output-dir", str(output), "--expected-count", "1"],
                cwd=ROOT, check=True, capture_output=True, text=True,
            )
            self.assertEqual(json.loads(result.stdout)["observed_rows"], 1)
            inventory = json.loads((output / "artifact_inventory.json").read_text(encoding="utf-8"))
            self.assertEqual(len(inventory["artifacts"]), 5)
            for item in inventory["artifacts"]:
                path = Path(item["absolute_path"])
                self.assertTrue(path.is_absolute())
                raw = path.read_bytes()
                self.assertEqual(item["bytes"], len(raw))
                self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
