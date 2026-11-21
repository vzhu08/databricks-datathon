import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, canonical, digest, empty, load
from occurrence_keys import POLICY, SOURCE, map_occurrences
from publication import current, publish
from simulation import SimulatedStore
from status_artifact import read_status_artifact


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
                         "original_table": SOURCE, "delta_version": 0,
                         "base_file_sha256": self.metadata["base_file_sha256"],
                         "metadata_sha256": digest(self.metadata), "batch_sha256": digest(empty()),
                         "identity_rows_file_sha256": "a" * 64, "occurrences": 3, "decision_count": 9,
                         "coverage": counts, "coverage_by_state": {"unknown": {s: {"unconfirmed": 3} for s in counts}},
                         "facilities": {r["facility_id"]: {"source_id": r["source_row"]["unique_id"],
                             "state": "unknown", "services": {s: {"status": "unconfirmed", "reviews": [],
                             "reason_code": "no_reviewed_evidence"} for s in counts}} for r in self.base}}
        self.spec = {"path": "/Volumes/synthetic/private/status/artifact.json", "identity_rows_sha256": "a" * 64,
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
