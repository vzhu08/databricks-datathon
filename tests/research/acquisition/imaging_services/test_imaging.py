"""Synthetic source bytes only. Never copy real hospital or operator rows here."""
import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from research.acquisition.common import canonical, digest, envelope
from research.acquisition.imaging_services.collector import collect, publish, summarize
from research.acquisition.imaging_services.compare import compare, frozen_reach, reconcile_legacy
from research.mri.maharashtra.inventory import URL


ROOT = Path(__file__).resolve().parents[4]


class ImagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = b'<main><p id="notice">Example Campus MRI is planned; scans are reported offsite.</p></main>'
        (self.root / "source.html").write_bytes(self.html)
        self.source = dict(key="example", path="source.html", sha256=digest(self.html),
                           url="https://example.invalid/notice", publisher="Synthetic publisher",
                           source_family="synthetic_family", geography="Synthetic scope", status="ok",
                           retrieved_at="2026-11-22T00:00:00Z", published_date=None,
                           sharing_status="restricted", reuse_reason="Synthetic test only", pursue_or_stop="test")
        self.annotation = dict(key="one", source_key="example", locator={"selector": "#notice"},
                               excerpt="Example Campus MRI is planned; scans are reported offsite.",
                               subject="Example Campus", grain="campus", modality="mri", kind="planned",
                               reported_value=None, period="undated", series_key="example", state="Maharashtra",
                               effective_date=None, interpretation_reviewer="fixture-reviewer",
                               interpretation_note="Synthetic planned MRI with offsite reporting; review campus/time.")

    def run_collect(self, sources=None, annotations=None):
        return collect(self.root, {"sources": sources or [self.source]},
                       annotations if annotations is not None else [self.annotation])

    def test_locator_and_hash_binding(self):
        for mutation, message in [(lambda: (self.root / "source.html").write_bytes(b"changed"), "hash mismatch"),
                                  (lambda: self.annotation.update(excerpt="MRI is operational"), "excerpt not found"),
                                  (lambda: self.annotation.update(locator={"selector": ".missing"}), "exactly one")]:
            with self.subTest(message=message):
                (self.root / "source.html").write_bytes(self.html)
                self.annotation.update(excerpt="Example Campus MRI is planned; scans are reported offsite.", locator={"selector": "#notice"})
                mutation()
                with self.assertRaisesRegex(ValueError, message): self.run_collect()

    def test_path_escape_and_symlink(self):
        self.source["path"] = "../source.html"
        with self.assertRaisesRegex(ValueError, "escapes"): self.run_collect()
        (self.root / "linked").symlink_to("/etc/hosts")
        self.source["path"] = "linked"
        with self.assertRaisesRegex(ValueError, "outside"): self.run_collect()

    def test_unresolved_and_restricted_are_preserved(self):
        result = self.run_collect()
        batch, row = result["batch.json"], result["observations.json"][0]
        self.assertEqual(row["sharing_status"], "restricted")
        self.assertEqual(row["current_service_decision"], "unconfirmed")
        self.assertEqual(batch["facility_matches"], [])
        self.assertEqual(batch["facility_evidence"][0]["polarity"], "inconclusive")
        self.assertIsNone(batch["facility_evidence"][0]["facility_id"])
        schema = json.loads((ROOT / "contracts/enrichment/schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(batch)

    def test_ct_not_mri_or_trauma_and_aggregate_not_campus(self):
        self.annotation["modality"] = "ct"
        ev = self.run_collect()["batch.json"]["facility_evidence"][0]
        self.assertIsNone(ev["service"])
        self.assertEqual(ev["claim_type"], "identity")
        self.annotation["grain"] = "operator_network"
        result = self.run_collect()
        self.assertEqual(result["batch.json"]["external_facilities"], [])
        self.assertEqual(result["summary.json"]["raw_observations"], 1)

    def test_failed_sources_cannot_emit_and_duplicates_fail(self):
        self.source["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "failed source"): self.run_collect()
        self.source["status"] = "ok"
        with self.assertRaisesRegex(ValueError, "duplicate annotation"): self.run_collect(annotations=[self.annotation] * 2)

    def test_dmer_header_alignment_group_and_zero(self):
        html = b'''<table><tr><th>Hospital Name</th><th>MRI Scan</th><th>CT Scan Facility</th></tr>
        <tr><td>Example Group Hospitals</td><td>0</td><td>2</td></tr>
        <tr><td>Hospital Name</td><td>MRI Scan</td><td>CT Scan Facility</td></tr>
        <tr><td>Example Campus</td><td>3</td><td>not recorded</td></tr>
        <tr><td colspan="2">Shifted row</td><td>7</td></tr></table>'''
        (self.root / "source.html").write_bytes(html)
        self.source.update(sha256=digest(html), url=URL, parser="dmer")
        result = self.run_collect(annotations=[])
        rows = result["observations.json"]
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["reported_value"], 0)
        self.assertEqual(rows[0]["grain"], "campus_group")
        self.assertEqual(rows[0]["negation"], "equipment_zero_not_service_absence")
        self.assertEqual(rows[1]["reported_value"], 2)
        self.assertEqual(rows[2]["reported_value"], 3)
        self.assertIsNone(rows[3]["reported_value"])
        self.assertIsNone(rows[4]["reported_value"])
        self.assertIsNone(rows[5]["reported_value"])
        self.assertTrue(all(e["service"] == "mri" and e["polarity"] == "inconclusive" for e in result["batch.json"]["facility_evidence"]))

    def test_repeated_and_conflicting_editions_not_independent(self):
        row = self.run_collect()["observations.json"][0]
        a, b = copy.deepcopy(row), copy.deepcopy(row)
        a["reported_value"], b["reported_value"] = 2, 3
        summary = summarize([a, b], [self.source])
        self.assertEqual(summary["raw_observations"], 2)
        self.assertEqual(summary["campus_service_literal_keys"], 1)
        self.assertEqual(summary["conflicting_series_period_values"], 1)
        self.assertIsNone(summary["independent_origins"])

    def test_snapshot_identity_ignores_retrieval_clock(self):
        before = self.run_collect()["batch.json"]["source_snapshots"][0]
        self.source["retrieved_at"] = "2026-11-23T00:00:00Z"
        after = self.run_collect()["batch.json"]["source_snapshots"][0]
        self.assertEqual(before["snapshot_id"], after["snapshot_id"])
        # Never overwrite a persisted release with a new retrieval clock.
        publish(self.root / "release", {"batch.json": before})
        publish(self.root / "release", {"batch.json": before})
        with self.assertRaises(Exception): publish(self.root / "release", {"batch.json": after})

    def test_full_occurrences_and_three_decisions(self):
        row = dict(unique_id="one", name="Example Campus", state="Maharashtra")
        base = [{"facility_id": "a", "source_row": row}, {"facility_id": "b", "source_row": copy.deepcopy(row)},
                {"facility_id": "c", "source_row": {"unique_id": "two", "name": "Unknown Campus", "state": None}}]
        sha = digest(canonical(base))
        meta = dict(mapping={"id": "unique_id", "name": "name", "state": "state"}, row_count=3,
                    original_table="synthetic.facilities", observed_delta_version=0, base_file_sha256=sha)
        result = compare(base, meta, sha, [envelope()], [self.run_collect()["batch.json"]], "2026-11-22", 3, 2, 1)
        report = result["comparison.json"]
        self.assertEqual(report["service_decisions"], 9)
        self.assertEqual(report["service_coverage"]["mri"]["unconfirmed"], 3)
        self.assertIsNone(report["frozen_147_incremental_gain"])
        self.assertEqual(len(result["expanded_rows.json"]), 3)
        self.assertEqual(sum(v["original_rows"] for v in report["by_state"].values()), 3)
        with self.assertRaisesRegex(ValueError, "denominator"):
            compare(base[:-1], meta, sha, [envelope()], [], "2026-11-22", 3, 2, 1)

    def test_legacy_directory_and_documentary_grains_stay_separate(self):
        release = self.root / "release-final"
        release.mkdir()
        batch = envelope()
        batch["external_facilities"] = [{"external_facility_id": "node"}, {"external_facility_id": "document"}]
        ledger = [dict(kind="directory_identity", source="directory", unit_key=None),
                  dict(kind="named_mri_service", source="annual_report", unit_key="example")]
        (release / "batch.json").write_text(json.dumps(batch))
        (release / "claim_ledger.json").write_text(json.dumps(ledger))
        (self.root / "manifest.json").write_text(json.dumps({"sources": []}))
        report = reconcile_legacy(self.root)
        self.assertEqual(report["directory_nodes"], 1)
        self.assertEqual(report["documentary_observations"], 1)
        self.assertEqual(report["latest_report_named_mri_unit_keys"], 1)

    def test_frozen_reach_hash_payload_and_decision_product(self):
        base = [{"facility_id": "a", "source_row": {"id": "one"}}]
        occurrences = [{"original": base[0], "joint_identity": {"facility_id": "a", "state": "unknown",
                        "outcomes": {"joint": "unmatched"}}}]
        decisions = [dict(occurrence_key="a", service=s, status="unconfirmed", as_of="2026-11-21")
                     for s in ("mri", "dialysis", "trauma_care")]
        manifest = {"files": {}}
        for name, rows in [("occurrences.jsonl.gz", occurrences), ("decisions.jsonl.gz", decisions)]:
            data = gzip.compress(b"".join(canonical(r) + b"\n" for r in rows), mtime=0)
            (self.root / name).write_bytes(data)
            manifest["files"][name] = dict(bytes=len(data), sha256=digest(data), records=len(rows))
        raw = canonical(manifest)
        (self.root / "manifest.json").write_bytes(raw)
        imaging = [{"facility_id": "a", "candidate_count": 1, "outcome_by_source": {"example": "candidate_only"}}]
        result = frozen_reach(base, self.root, digest(raw), imaging)["frozen_reach.json"]
        self.assertEqual(result["newly_reached"], 1)
        self.assertEqual(result["newly_reached_by_imaging_source"], {"example": 1})
        self.assertEqual(result["unchanged_baseline_decisions"], 3)
        self.assertEqual(result["service_status_transitions"], 0)
        with self.assertRaisesRegex(ValueError, "manifest hash"):
            frozen_reach(base, self.root, "0" * 64, imaging)
        with self.assertRaisesRegex(ValueError, "payload/order"):
            frozen_reach([{"facility_id": "other"}], self.root, digest(raw), imaging)


if __name__ == "__main__":
    unittest.main()
