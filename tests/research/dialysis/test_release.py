import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.dialysis.audit import verify
from research.dialysis.release import compile_batch, digest, encode, publish


class DialysisReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "original.html"
        self.source.write_bytes(b"<html><body><h1>Example Campus</h1><p>Proposed dialysis service.</p></body></html>")
        self.manifest = self.root / "manifest.json"
        self.spec = dict(key="synthetic", url="https://example.invalid/source", publisher="Synthetic publisher",
                         family="synthetic", independence_status="unassessed", path=self.source.name,
                         sha256=digest(self.source.read_bytes()), retrieved_at="2026-10-21T12:00:00Z")
        self.claim = dict(source="synthetic", campus=dict(name="Example Campus", city="Example City",
                          district="Example District", ownership="public"), format="html", segment=1,
                          excerpt="Proposed dialysis service.", locator="paragraph 1", identity_locator="page heading",
                          assertion="The source describes a proposal.", kind="procurement_only",
                          time_specific=False, temporal_status="undated", next_action="Check operational evidence.")

    def build(self, claims=None):
        self.manifest.write_bytes(encode(dict(sources=[self.spec], claims=[self.claim] if claims is None else claims)))
        return compile_batch(self.manifest)

    def decision(self, batch):
        row = batch["facility_evidence"][0]
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return dict(evidence_id=row["evidence_id"], evidence_sha256=hashlib.sha256(signature).hexdigest(),
                    source_snapshot_sha256=self.spec["sha256"], outcome="pass", exact_excerpt_at_locator=True,
                    reviewer="Synthetic reviewer", reviewed_at="2026-11-21T16:00:00Z")

    def test_proposals_referrals_and_unknowns_stay_unlinked(self):
        for kind, text in [("procurement_only", "Proposed dialysis service."),
                           ("referral_only", "Dialysis referrals go to another hospital."),
                           ("unknown_service", "Kidney clinic.")]:
            with self.subTest(kind=kind):
                self.source.write_text("<h1>Example Campus</h1><p>" + text + "</p>", encoding="utf-8")
                self.spec["sha256"] = digest(self.source.read_bytes())
                self.claim.update(kind=kind, excerpt=text)
                batch, ledger = self.build()
                row = batch["facility_evidence"][0]
                self.assertEqual((row["polarity"], row["match_id"], row["facility_id"]), ("inconclusive", None, None))
                self.assertEqual(ledger[0]["kind"], kind)
                self.assertEqual(batch["facility_matches"], [])

    def test_timestamps_and_identity_survive_replay(self):
        self.spec["published_date"] = "2023-01-19"
        batch, _ = self.build()
        self.assertEqual(batch["source_snapshots"][0]["published_date"], "2023-01-19")
        self.assertIsNone(batch["facility_evidence"][0]["effective_date"])
        output = self.root / "release"
        publish(self.manifest, output)
        original = (output / "batch.json").read_bytes()
        publish(self.manifest, output)
        self.assertEqual(original, (output / "batch.json").read_bytes())

    def test_frozen_output_refuses_different_payload(self):
        self.build()
        output = self.root / "release"
        publish(self.manifest, output)
        self.claim["assertion"] = "Separate interpretation."
        self.build()
        with self.assertRaises(ValueError):
            publish(self.manifest, output)

    def test_changed_original_rejected(self):
        self.spec["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.build()

    def test_quote_at_wrong_locator_rejected(self):
        self.claim["segment"] = 0
        with self.assertRaisesRegex(ValueError, "locator"):
            self.build()

    def test_duplicate_claim_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate evidence"):
            self.build([self.claim, self.claim])

    def test_sources_cannot_escape_the_inventory_root(self):
        self.spec["path"] = "../unrelated.html"
        with self.assertRaisesRegex(ValueError, "archive path"):
            self.build()

    def test_two_campuses_with_the_same_name_stay_separate(self):
        other = dict(self.claim, campus=dict(self.claim["campus"], address="Other synthetic road"))
        batch, _ = self.build([self.claim, other])
        self.assertEqual(len(batch["external_facilities"]), 2)
        self.assertEqual(len({c["external_facility_id"] for c in batch["facility_evidence"]}), 2)

    def test_audit_is_bound_to_evidence_source_and_full_coverage(self):
        batch, _ = self.build()
        decision = self.decision(batch)
        self.assertEqual(verify(batch, [decision]), 1)
        for invalid in ([], [decision, decision], [dict(decision, outcome="uncertain")],
                        [dict(decision, exact_excerpt_at_locator=False)], [dict(decision, evidence_sha256="bad")],
                        [dict(decision, source_snapshot_sha256="bad")]):
            with self.subTest(decisions=invalid), self.assertRaises(ValueError):
                verify(batch, invalid)
