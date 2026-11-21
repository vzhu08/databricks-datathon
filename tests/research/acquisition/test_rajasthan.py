"""Synthetic regional selection and lossless handoff acceptance cases."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from research.acquisition.common import (AcquisitionError, ROOT, canonical, read_json,
                                         review, write_json)
from research.acquisition.parsers import make_batch
from research.acquisition.rajasthan import classify, extract, words, write_extract
from research.acquisition.run import acquire
from fixtures import feature, geojson, landing, snapshot


def batch_for(features):
    return make_batch(features, "health.geojson", snapshot(), "osm")[0]


def row(state="Rājasthān", address=None, xy=(75.5, 26.5), identifier="node/1", name="Example"):
    f = feature(identifier=identifier, name=name, adm1_name=state, addr_full=address)
    f["geometry"] = None if xy is None else {"type": "Point", "coordinates": list(xy)}
    return f


class SelectionTests(unittest.TestCase):
    def test_accented_and_hindi_state_and_missing_name_preserved(self):
        original = batch_for([row(name=None), row(state="राजस्थान", identifier="node/2")])
        outputs, _, report, _ = extract([original])
        self.assertEqual(2, report["totals"]["explicit"])
        self.assertEqual(original["external_facilities"], outputs["explicit"]["external_facilities"])
        self.assertEqual("rajasthan", words("Rājasthān"))
        self.assertEqual("राजस्थान", words("राजस्थान"))

    def test_missing_state_geography_and_address_are_separate(self):
        source = batch_for([row(state=None, identifier="node/1"),
                            row(state=None, address="1 Example Road, Rajasthan 302001, India", xy=None, identifier="node/2"),
                            row(state=None, xy=(80, 20), identifier="node/3")])
        outputs, decisions, report, _ = extract([source])
        self.assertEqual(1, report["totals"]["explicit"])
        self.assertEqual(1, report["totals"]["additional_review"])
        self.assertEqual(1, report["totals"]["excluded"])
        self.assertEqual("node/2", outputs["explicit"]["external_facilities"][0]["source_record_id"])
        self.assertEqual("node/1", outputs["additional_review"]["external_facilities"][0]["source_record_id"])
        self.assertTrue(any("missing_state_inside_geographic_screen" in d["reasons"] for d in decisions))

    def test_conflicting_state_address_and_coordinates_need_review(self):
        source = batch_for([row(state="Gujarat", address="1 Example Road, Rajasthan", identifier="node/1"),
                            row(state="Rajasthan", address="1 Example Road, Punjab", identifier="node/2"),
                            row(state="Rajasthan", xy=(-30, -20), identifier="node/3")])
        outputs, decisions, report, _ = extract([source])
        self.assertEqual(0, report["totals"]["explicit"])
        self.assertEqual(3, report["totals"]["additional_review"])
        reasons = {r for d in decisions for r in d["reasons"]}
        self.assertTrue({"state_address_disagreement", "address_state_disagreement",
                         "explicit_text_outside_geographic_screen"} <= reasons)
        self.assertEqual(source["external_facilities"], outputs["additional_review"]["external_facilities"])

    def test_name_or_street_token_is_not_state_proof(self):
        source = batch_for([row(state=None, name="Rajasthan Hospital", address="1 Rajasthan Road", xy=None),
                            row(state=None, address="1 Rajasthan Bhavan Road, Mumbai, Maharashtra", xy=None, identifier="node/2"),
                            row(state="Notrajasthan", xy=None, identifier="node/3")])
        _, _, report, _ = extract([source])
        self.assertEqual(3, report["totals"]["excluded"])

    def test_other_state_in_rectangle_is_only_recall_candidate(self):
        outputs, decisions, report, _ = extract([batch_for([row(state="Madhya Pradesh")])])
        self.assertEqual(0, report["totals"]["explicit"])
        self.assertEqual(["other_state_inside_geographic_screen"], decisions[0]["reasons"])
        self.assertEqual("Madhya Pradesh", outputs["additional_review"]["external_facilities"][0]["state"])
        self.assertEqual(1, len(outputs["additional_review"]["review_queue"]))

    def test_identical_duplicate_candidate_is_removed_and_counts_reconcile(self):
        source = batch_for([row()])
        outputs, decisions, report, _ = extract([source, copy.deepcopy(source)])
        self.assertEqual(2, report["totals"]["input_occurrences"])
        self.assertEqual(1, report["totals"]["identical_input_occurrences_removed"])
        self.assertEqual(1, len(outputs["explicit"]["external_facilities"]))
        self.assertEqual(1, len(decisions))
        self.assertTrue(all(s["partition_reconciles"] for s in report["snapshot_counts"].values()))

    def test_conflicting_payload_under_same_id_is_rejected(self):
        source = batch_for([row()]); changed = copy.deepcopy(source)
        changed["external_facilities"][0]["state"] = "Punjab"
        with self.assertRaisesRegex(AcquisitionError, "conflicting_input_payload"):
            extract([source, changed])

    def test_source_identifier_variants_and_distinct_campuses_survive(self):
        source = batch_for([row(address="1 Example Road"), row(address="2 Example Road"),
                            row(identifier="way/1", address="3 Example Road")])
        outputs, _, report, _ = extract([source])
        self.assertEqual(3, report["totals"]["explicit"])
        self.assertEqual(3, len(outputs["explicit"]["external_facilities"]))
        self.assertEqual(source["review_queue"], outputs["explicit"]["review_queue"])

    def test_reference_rows_and_selected_reviews_preserved_without_mutation(self):
        source = batch_for([row(state="Rajasthan", xy=(-30, -20)), row(state="Punjab", xy=(-31, -20), identifier="node/2")])
        before = canonical(source)
        outputs, _, _, _ = extract([source])
        self.assertEqual(before, canonical(source))
        for output in outputs.values():
            self.assertEqual(source["source_snapshots"], output["source_snapshots"])
        selected = outputs["additional_review"]["external_facilities"][0]
        inherited = [r for r in source["review_queue"] if r["external_facility_id"] == selected["external_facility_id"]]
        for review_row in inherited:
            self.assertIn(review_row, outputs["additional_review"]["review_queue"])
        self.assertEqual([], outputs["explicit"]["facility_matches"])
        self.assertEqual([], outputs["explicit"]["facility_evidence"])

    def test_stable_selection_ignores_input_order_and_retains_timestamps(self):
        a = batch_for([row(identifier="node/1")]); b = batch_for([row(state=None, identifier="node/2")])
        first = extract([a, b]); second = extract([b, a])
        self.assertEqual(canonical(first), canonical(second))
        self.assertEqual(snapshot()["retrieved_at"], first[0]["explicit"]["source_snapshots"][0]["retrieved_at"])

    def test_boundary_screen_is_inclusive_and_unknown_coordinates_are_unknown(self):
        source = batch_for([row(state=None, xy=(69.4, 23.0)), row(state=None, xy=(78.35, 30.25), identifier="node/2"),
                            row(state=None, xy=(69.399, 23.0), identifier="node/3"), row(state=None, xy=None, identifier="node/4")])
        _, _, report, _ = extract([source])
        self.assertEqual(2, report["totals"]["additional_review"])
        self.assertEqual(2, report["totals"]["excluded"])

    def test_address_suffix_country_pin_orders_and_hindi(self):
        forms = ["1 Example Road, Rajasthan, India 302001", "1 Example Road राजस्थान 302001 भारत",
                 "1 Example Road, Rajasthan PIN code 302001, India"]
        _, _, report, _ = extract([batch_for([row(state=None, address=a, xy=None, identifier="node/"+str(i)) for i,a in enumerate(forms)])])
        self.assertEqual(len(forms), report["totals"]["explicit"])


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        inputs = self.root / "inputs"; inputs.mkdir()
        national = inputs / "national.json"
        source_output = inputs / "acquired"; source_output.mkdir()
        raw = geojson([feature("nhp", identifier="1", State="Rajasthan"),
                       feature("nhp", identifier="2", State="0")])
        class SyntheticFetcher:
            def download(self, url, destination, kind, source):
                destination.write_bytes(landing() if kind == "html" else raw)
                return {"retrieved_at": "2020-01-01T00:00:00Z"}
        entry = next(s for s in read_json(ROOT / "contracts/enrichment/source_registry.json")["sources"] if s["source_key"] == "nhp_hospitals_mirror")
        batch, _, directory, _ = acquire("nhp", source_output, entry, SyntheticFetcher())
        write_json(national, batch)
        self.national, self.snapshot = national, Path(directory)
        self.output = self.root / "result"

    def test_real_file_pipeline_hashes_stable_replay_and_no_input_changes(self):
        original = {p: p.read_bytes() for p in self.snapshot.iterdir()}
        national = self.national.read_bytes()
        report = write_extract([self.snapshot], self.national, self.output)
        files = {p.name: p.read_bytes() for p in self.output.iterdir()}
        again = write_extract([self.snapshot], self.national, self.output)
        self.assertEqual(report, again)
        self.assertEqual(files, {p.name: p.read_bytes() for p in self.output.iterdir()})
        self.assertEqual(original, {p: p.read_bytes() for p in self.snapshot.iterdir()})
        self.assertEqual(national, self.national.read_bytes())
        from research.acquisition.common import file_digest
        manifest = read_json(self.output / "manifest.json")
        for name, sha in manifest["files"].items(): self.assertEqual(sha, file_digest(self.output / name))

    def test_wrong_national_union_and_corrupted_snapshot_refused(self):
        national = read_json(self.national)
        national["external_facilities"] = national["external_facilities"][:1]
        write_json(self.national, national)
        with self.assertRaisesRegex(AcquisitionError, "national_batch_does_not_match_snapshot_union"):
            write_extract([self.snapshot], self.national, self.output)
        self.assertFalse(self.output.exists())
        (self.snapshot / "raw.geojson").write_bytes(b"corrupted")
        with self.assertRaisesRegex(AcquisitionError, "persisted_artifact_hash_mismatch"):
            write_extract([self.snapshot], self.national, self.output)

    def test_existing_different_output_and_overlap_refused(self):
        write_extract([self.snapshot], self.national, self.output)
        artifact = self.output / "explicit.json"; artifact.write_bytes(b"preserve me")
        with self.assertRaisesRegex(AcquisitionError, "existing_output_not_identical"):
            write_extract([self.snapshot], self.national, self.output)
        self.assertEqual(b"preserve me", artifact.read_bytes())
        with self.assertRaisesRegex(AcquisitionError, "output_overlaps_input_storage"):
            write_extract([self.snapshot], self.national, self.snapshot)

    def test_d_validator_accepts_both_contract_outputs(self):
        write_extract([self.snapshot], self.national, self.output)
        base = self.root / "empty-base.json"; write_json(base, [])
        result = subprocess.run([sys.executable, str(ROOT / "databricks/enrichment/validate_batch.py"),
                                 "--batch", str(self.output / "explicit.json"), "--batch", str(self.output / "additional_review.json"),
                                 "--base", str(base), "--as-of", "2026-11-21"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("valid", report["status"])
        self.assertEqual(2, report["counts"]["external_facilities"])
        self.assertEqual(0, report["base_rows"])


if __name__ == "__main__": unittest.main()
