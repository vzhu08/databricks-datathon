import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.trauma.pipeline import LANES, ROOT, build, digest, publish


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        fixture = json.loads((ROOT / "contracts/fixtures/enrichment.json").read_text())
        self.batch = {k: v if k == "contract_version" else [] for k, v in fixture.items()}
        for lane in LANES:
            self.write(lane, "batch.json", self.batch)
        for table in ("source_snapshots", "external_facilities", "facility_evidence"):
            self.batch[table] = fixture[table][:1]
        claim = self.batch["facility_evidence"][0]
        raw = b"Synthetic source bytes"
        (self.root / "source.txt").write_bytes(raw)
        snapshot = self.batch["source_snapshots"][0]
        snapshot["sha256"] = hashlib.sha256(raw).hexdigest()
        (self.root / "raw_paths.json").write_text(json.dumps({snapshot["snapshot_id"]: "source.txt"}))
        claim.update(facility_id=None, match_id=None, snapshot_id=self.batch["source_snapshots"][0]["snapshot_id"])
        self.audit = dict(evidence_id=claim["evidence_id"], evidence_sha256=digest(claim), outcome="pass",
                          reviewer="fixture-reviewer", reviewed_at="2026-11-21T17:00:00Z", reason="Locator checked")
        self.write("B1", "batch.json", self.batch)
        self.write("B5", "audit.json", [self.audit])

    def write(self, lane, name, data):
        parent = self.root / lane
        parent.mkdir(exist_ok=True)
        (parent / name).write_text(json.dumps(data), encoding="utf-8")

    def test_idempotent_producers_and_release(self):
        self.write("B2", "batch.json", self.batch)
        output = self.root / "release"
        files = build(self.root)
        self.assertEqual(len(files["batch.json"]["source_snapshots"]), 1)
        self.assertEqual(files["coverage.json"]["verified_against_public_source"], [self.audit["evidence_id"]])
        publish(files, output)
        first = (output / "sha256.json").read_bytes()
        publish(build(self.root), output)
        self.assertEqual((output / "sha256.json").read_bytes(), first)
        (output / "coverage.json").write_text("different")
        with self.assertRaises(ValueError):
            publish(files, output)

    def test_conflicting_replay_fails(self):
        changed = copy.deepcopy(self.batch)
        changed["source_snapshots"][0]["attribution"] = "different"
        self.write("B2", "batch.json", changed)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            build(self.root)

    def test_bad_dates_and_missing_references_fail(self):
        source = self.batch["source_snapshots"][0]
        source["published_date"] = "2020-02-31"
        self.write("B1", "batch.json", self.batch)
        with self.assertRaisesRegex(ValueError, "Schema"):
            build(self.root)
        source["published_date"] = None
        self.batch["external_facilities"][0]["snapshot_id"] = "missing:source"
        self.write("B1", "batch.json", self.batch)
        with self.assertRaisesRegex(ValueError, "Missing snapshot"):
            build(self.root)

    def test_reject_base_links(self):
        self.batch["facility_evidence"][0].update(facility_id="base:example", match_id="match:example")
        self.write("B1", "batch.json", self.batch)
        with self.assertRaisesRegex(ValueError, "base link"):
            build(self.root)

    def test_changed_source_bytes_fail(self):
        (self.root / "source.txt").write_bytes(b"new bytes")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            build(self.root)

    def test_audit_binds_to_full_evidence_payload(self):
        self.batch["facility_evidence"][0]["assertion"] = "Updated statement"
        self.write("B1", "batch.json", self.batch)
        with self.assertRaisesRegex(ValueError, "changed"):
            build(self.root)

    def test_incomplete_audit_cannot_publish_final(self):
        self.write("B5", "audit.json", [])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            build(self.root)
        result = build(self.root, partial=True)
        self.assertEqual(result["coverage.json"]["review_outcomes"], {"unsampled": 1})
        self.assertEqual(result["coverage.json"]["stage"], "partial")

    def test_failed_and_uncertain_items_are_quarantined(self):
        for outcome in ("fail", "uncertain"):
            self.write("B5", "audit.json", [dict(self.audit, outcome=outcome)])
            result = build(self.root)
            self.assertEqual(result["batch.json"]["facility_evidence"], [])
            self.assertIsNone(result["batch.json"]["review_queue"][0]["evidence_id"])
            self.assertEqual(result["claim_ledger.json"][0]["decision"]["outcome"], outcome)
            self.assertEqual(result["coverage.json"]["verified_against_public_source"], [])

    def test_wrong_or_duplicate_reviewer_decisions_fail(self):
        for decisions in ([self.audit, self.audit], [dict(self.audit, reviewer="")],
                          [dict(self.audit, reviewed_at="yesterdayZ")]):
            self.write("B5", "audit.json", decisions)
            with self.assertRaises(ValueError):
                build(self.root)
