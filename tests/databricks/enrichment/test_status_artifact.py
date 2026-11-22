import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest, empty, load
from occurrence_keys import POLICY, SOURCE, map_occurrences
from publication import current, publish
from simulation import SimulatedStore
from status_artifact import read_status_artifact

try:
    from research.service_status.projection import lookup, patient_lookup, project
except ModuleNotFoundError as error:
    if not error.name.startswith("research.service_status"):
        raise
    project = None  # PR #79 is separate; this test runs in the combined checkout.


class StatusBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SimulatedStore(str(Path(self.temp.name) / "store.sqlite"))
        twin = {"unique_id": "synthetic:twins", "description": "Synthetic unchanged text."}
        rows = [twin, copy.deepcopy(twin), {"unique_id": "synthetic:sparse", "description": None}]
        self.base, _ = map_occurrences(rows, "unique_id", SOURCE, 0, POLICY)
        self.metadata = {"original_table": SOURCE, "observed_delta_version": 0,
                         "row_count": 3, "mapping": {"id": "unique_id"}, "id_policy": POLICY,
                         "base_file_sha256": digest(self.base),
                         "source_rows_sha256": digest(sorted(rows, key=canonical))}
        counts = {s: {"yes": 0, "no": 0, "unconfirmed": 3} for s in ("dialysis", "mri", "trauma_care")}
        self.artifact = {"policy": "onsite-service-review-v1", "as_of": "2026-11-21",
                         "checked_sources": [], "reviews_sha256": digest([]),
                         "identity_rows_content_sha256": None, "identity_report_content_sha256": None,
                         "original_table": SOURCE, "delta_version": 0,
                         "base_file_sha256": self.metadata["base_file_sha256"],
                         "metadata_sha256": digest(self.metadata), "batch_sha256": digest(empty()),
                         "identity_rows_file_sha256": None, "occurrences": 3, "decision_count": 9,
                         "coverage": counts, "coverage_by_state": {"unknown": {s: {"unconfirmed": 3} for s in counts}},
                         "facilities": {r["facility_id"]: {"source_id": r["source_row"]["unique_id"],
                             "state": "unknown", "identity_conflicts": [],
                             "services": {s: {"status": "unconfirmed", "reviews": [],
                             "reason": "No reviewed claim establishes the status of this service.",
                             "reason_code": "no_reviewed_evidence"} for s in counts}} for r in self.base}}
        self.spec = {"path": "/Volumes/synthetic/private/status/artifact.json", "identity_rows_sha256": None,
                     "input_metadata": self.metadata}
        self.set_bytes()

    def set_bytes(self):
        self.raw = (canonical(self.artifact) + "\n").encode()
        self.spec["sha256"] = hashlib.sha256(self.raw).hexdigest()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def publish(self, run="synthetic-status", **kwargs):
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            return publish(self.store, [empty()], self.base, run, "2026-11-21",
                           source_metadata={**self.metadata, "producer_artifacts": []},
                           status_artifact=self.spec, **kwargs)

    def staged(self):
        return self.store.connection.execute("SELECT count(*) FROM stage").fetchone()[0]

    def test_binding_replay_and_captured_manifest_preserve_twins(self):
        before = copy.deepcopy(self.metadata)
        manifest = self.publish()
        self.assertEqual(self.metadata, before)
        self.assertEqual(manifest, self.publish())
        self.assertEqual(self.staged(), 5)
        self.assertEqual(manifest["source_metadata"]["service_status_artifact"]["input_metadata_sha256"], digest(before))
        self.publish("synthetic-next")
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            recovered = read_status_artifact(manifest, self.base, self.metadata)
        self.assertEqual(set(recovered["facilities"]), {r["facility_id"] for r in self.base})
        self.assertEqual(recovered["decision_count"], 9)
        self.assertEqual(current(self.store)[0]["run_id"], "synthetic-next")

    def test_pins_and_coverage_fail_before_writes(self):
        original = copy.deepcopy(self.artifact)
        edits = [
            lambda a: a.update(base_file_sha256="b" * 64),
            lambda a: a.update(metadata_sha256="b" * 64),
            lambda a: a.update(identity_rows_file_sha256="b" * 64),
            lambda a: a.update(batch_sha256="b" * 64),
            lambda a: a.update(as_of="2026-11-22"),
            lambda a: a.update(decision_count=8),
            lambda a: a["facilities"].pop(self.base[0]["facility_id"]),
            lambda a: a["facilities"][self.base[0]["facility_id"]].update(source_id="changed"),
            lambda a: a["facilities"][self.base[0]["facility_id"]]["services"].pop("mri"),
            lambda a: a["coverage"]["mri"].update(unconfirmed=2),
            lambda a: a["coverage_by_state"]["unknown"]["mri"].update(unconfirmed=2),
        ]
        for index, edit in enumerate(edits):
            with self.subTest(index=index):
                self.artifact = copy.deepcopy(original)
                edit(self.artifact)
                self.set_bytes()
                with self.assertRaises(Invalid):
                    self.publish()
                self.assertEqual(self.staged(), 0)
                self.assertEqual(self.store.read_state()[0], 0)

    def test_corrupt_file_rejected_on_replay_and_consumer_read(self):
        manifest = self.publish()
        self.raw += b" "
        with self.assertRaisesRegex(Invalid, "file hash mismatch"):
            self.publish()
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            with self.assertRaisesRegex(Invalid, "file hash mismatch"):
                read_status_artifact(manifest, self.base, self.metadata)
        self.assertEqual(current(self.store)[0], manifest)
        self.assertEqual(self.staged(), 5)

    def test_missing_or_malformed_lookup_fields_fail_before_staging(self):
        original = copy.deepcopy(self.artifact)
        fid = self.base[0]["facility_id"]
        edits = [lambda a: a.pop("checked_sources"), lambda a: a.update(checked_sources="source"),
                 lambda a: a.update(checked_sources=[None]),
                 lambda a: a["facilities"][fid]["services"]["mri"].pop("reason"),
                 lambda a: a["facilities"][fid]["services"]["mri"].update(reason=[]),
                 lambda a: a["facilities"][fid]["services"]["mri"].pop("reviews"),
                 lambda a: a["facilities"][fid]["services"]["mri"].update(reviews={}),
                 lambda a: a["facilities"][fid]["services"].update(mri=None)]
        for index, edit in enumerate(edits):
            with self.subTest(index=index):
                self.artifact = copy.deepcopy(original)
                edit(self.artifact)
                self.set_bytes()
                with self.assertRaises(Invalid):
                    self.publish()
                self.assertEqual(self.staged(), 0)
                self.assertEqual(self.store.read_state(), (0, {"current_run": None, "runs": {}}))

    def test_malformed_review_citations_fail_before_staging(self):
        original = copy.deepcopy(self.artifact)
        fid = self.base[0]["facility_id"]
        for kind, field in (("original", "field"), ("external", "publisher")):
            review = {"superseded_by": None, "provenance": {"kind": kind, "source_date": None,
                      field: "description" if kind == "original" else "Synthetic publisher"}}
            edits = [lambda r: r.pop("superseded_by"), lambda r: r.update(superseded_by=[]),
                     lambda r: r.pop("provenance"), lambda r: r.update(provenance=[]),
                     lambda r: r["provenance"].pop("kind"), lambda r: r["provenance"].update(kind="unknown"),
                     lambda r: r["provenance"].pop("source_date"),
                     lambda r: r["provenance"].update(source_date="not-a-date"),
                     lambda r: r["provenance"].update(valid_until=[]),
                     lambda r: r["provenance"].pop(field)]
            for index, edit in enumerate(edits):
                with self.subTest(kind=kind, index=index):
                    self.artifact = copy.deepcopy(original)
                    invalid_review = copy.deepcopy(review)
                    edit(invalid_review)
                    self.artifact["facilities"][fid]["services"]["mri"]["reviews"] = [invalid_review]
                    self.set_bytes()
                    with self.assertRaises(Invalid):
                        self.publish()
                    self.assertEqual(self.staged(), 0)
                    self.assertEqual(self.store.read_state()[0], 0)

    @unittest.skipIf(project is None, "requires PR #79 producer in the combined checkout")
    def test_real_producer_and_lookup_consumers_after_readback(self):
        # First verify the normal positive fixture, which originally exposed this bug.
        manifest = self.publish()
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            recovered = read_status_artifact(manifest, self.base, self.metadata)
        for row in self.base:
            fid = row["facility_id"]
            self.assertEqual(lookup(recovered, fid)["source_id"], row["source_row"]["unique_id"])
            self.assertEqual(set(patient_lookup(recovered, fid)["services"]), {"dialysis", "mri", "trauma_care"})

        # Then use an actual producer output with original-review provenance.
        fid = self.base[0]["facility_id"]
        text = self.base[0]["source_row"]["description"]
        reviews = [{"facility_id": fid, "service": "mri", "review_id": "synthetic:review",
                    "finding": "insufficient", "assessed_for": "2026-11-21", "reviewer": "synthetic-reviewer",
                    "reviewed_at": "2026-11-21T18:00:00Z", "source": {"kind": "original", "field": "description",
                    "start": 0, "end": len(text), "excerpt": text, "source_date": None}}]
        self.artifact = project(self.base, self.metadata, reviews, [], as_of="2026-11-21",
                                checked_sources=["synthetic-source"], base_file_sha256=self.metadata["base_file_sha256"])
        self.artifact["identity_rows_file_sha256"] = None  # Added by the producer CLI.
        self.spec["identity_rows_sha256"] = None
        self.set_bytes()
        manifest = self.publish("producer-output")
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            recovered = read_status_artifact(manifest, self.base, self.metadata)
        self.assertEqual(lookup(recovered, fid)["checked_sources"], ["synthetic-source"])
        self.assertEqual(patient_lookup(recovered, fid)["services"]["mri"]["sources"],
                         [{"kind": "original", "date": None, "field": "description"}])
        # Exercise the other citation branch without deriving any clinical finding.
        decision = recovered["facilities"][fid]["services"]["mri"]
        decision["reviews"][0]["provenance"] = {"kind": "external", "source_date": None, "publisher": "Synthetic publisher"}
        self.artifact = recovered
        self.set_bytes()
        manifest = self.publish("external-citation-shape")
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            recovered = read_status_artifact(manifest, self.base, self.metadata)
        self.assertEqual(patient_lookup(recovered, fid)["services"]["mri"]["sources"],
                         [{"kind": "external", "date": None, "publisher": "Synthetic publisher"}])

    def test_batch_pin_covers_previous_accepted_rows(self):
        accepted = empty()
        accepted["source_snapshots"] = load(ROOT / "contracts/fixtures/enrichment.json")["source_snapshots"]
        previous = publish(self.store, [accepted], self.base, "prior", "2026-11-21")
        with self.assertRaisesRegex(Invalid, "entire merged batch"):
            self.publish()
        self.assertEqual(current(self.store)[0], previous)
        self.assertEqual(self.staged(), 5)

    def test_original_metadata_not_replaced_by_operational_fields(self):
        self.spec["input_metadata"] = {**self.metadata, "producer_artifacts": []}
        with self.assertRaisesRegex(Invalid, "metadata_sha256"):
            self.publish()
        self.assertEqual(self.staged(), 0)

    def test_duplicate_json_occurrence_key_is_rejected(self):
        key = self.base[0]["facility_id"]
        encoded = json.dumps(key) + ":"
        self.raw = self.raw.replace(encoded.encode(), (encoded + "{}," + encoded).encode(), 1)
        self.spec["sha256"] = hashlib.sha256(self.raw).hexdigest()
        with self.assertRaisesRegex(Invalid, "duplicate object key"):
            self.publish()
        self.assertEqual(self.staged(), 0)

    def test_consumer_rejects_changed_completed_reference_or_base(self):
        manifest = self.publish()
        with patch("status_artifact.Path.read_bytes", return_value=self.raw):
            for key in ("batch_sha256", "base_sha256"):
                altered = copy.deepcopy(manifest)
                altered[key] = "b" * 64
                with self.assertRaises(Invalid):
                    read_status_artifact(altered, self.base, self.metadata)
            altered = copy.deepcopy(manifest)
            altered["coverage"]["as_of"] = "2026-11-22"
            with self.assertRaises(Invalid):
                read_status_artifact(altered, self.base, self.metadata)


if __name__ == "__main__":
    unittest.main()
