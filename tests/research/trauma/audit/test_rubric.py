import copy
import hashlib
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from research.trauma.audit.__main__ import adjudicate, main
from research.trauma.audit.rubric import (
    CHECKS,
    assess,
    digest,
    finding,
    index_batches,
    queue_batch,
    review_context,
    select_claims,
    source_dependence,
)


FIXTURE = Path(__file__).resolve().parents[4] / "contracts/fixtures/enrichment.json"


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.batch = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.tables = index_batches([self.batch])
        self.evidence = self.batch["facility_evidence"][0]
        self.evidence_id = self.evidence["evidence_id"]
        self.context = review_context(self.evidence, self.tables)
        self.observation = {
            "reviewer": "synthetic-reviewer",
            "reviewed_at": "2026-11-21T18:00:00Z",
            "reviewed_payload_sha256": digest(self.context),
            "located_passage": "Example Health Centre, 1 Example Road:\ntrauma centre, 2018.",
            "source_temporal_status": "historical",
            "checks": {check: finding("pass", "Inspected synthetic original.") for check in CHECKS},
            "original": {"url": "https://example.invalid/program", "locator": "synthetic page 1, row 1"},
            "reason": "Historical programme listing with campus-specific synthetic address.",
            "correction_requested": None,
        }

    def test_exact_quote_allows_pdf_wrap_but_not_altered_punctuation(self):
        self.assertEqual(assess(self.context, self.observation)["outcome"], "pass")
        self.observation["located_passage"] = self.observation["located_passage"].replace(":", ";")
        self.assertEqual(assess(self.context, self.observation)["checks"]["quote"]["outcome"], "fail")

    def test_quote_from_wrong_row_does_not_pass(self):
        self.observation["checks"]["locator"] = finding("fail", "Excerpt is from row 2, not row 1.")
        decision = assess(self.context, self.observation)
        self.assertEqual(decision["checks"]["quote"]["outcome"], "pass")
        self.assertEqual(decision["outcome"], "fail")

    def test_historical_to_current_upgrade_fails(self):
        self.evidence["temporal_status"] = "dated"
        self.evidence["assertion"] = "Trauma services currently operate at this campus."
        self.observation["reviewed_payload_sha256"] = digest(self.context)
        self.assertEqual(assess(self.context, self.observation)["checks"]["dates"]["outcome"], "fail")

    def test_same_name_wrong_campus_fails_despite_valid_quote(self):
        self.observation["checks"]["campus"] = finding("fail", "Address identifies the other campus.")
        self.observation["correction_requested"] = "Preserve the source campus as a separate identity."
        decision = assess(self.context, self.observation)
        self.assertEqual(decision["outcome"], "fail")
        self.assertEqual(decision["evidence_sha256"], digest(self.evidence))
        queue = queue_batch(self.tables, [decision])["review_queue"][0]
        self.assertEqual(queue["evidence_id"], self.evidence_id)
        self.assertEqual(queue["next_action"], self.observation["correction_requested"])

    def test_unavailable_original_stays_uncertain(self):
        self.observation["located_passage"] = None
        self.observation["checks"]["locator"] = finding("uncertain", "Original unavailable.")
        self.assertEqual(assess(self.context, self.observation)["outcome"], "uncertain")

    def test_insufficient_specificity_fails_affirmative_claim(self):
        self.observation["checks"]["specificity"] = finding(
            "fail", "General emergency, outbound referral, or planned service does not establish trauma level."
        )
        self.assertEqual(assess(self.context, self.observation)["outcome"], "fail")

    def test_copied_sources_collapse_despite_different_urls_and_families(self):
        snapshots = self.tables["source_snapshots"]
        primary = self.context["snapshot"]
        alias = dict(primary, snapshot_id="synthetic:pdf-copy", source_family="other_family",
                     url="https://example.invalid/older.pdf")
        reencoded = dict(alias, snapshot_id="synthetic:pdf-reencoded", sha256="a" * 64)
        same_origin = dict(reencoded, snapshot_id="synthetic:pdf-third", source_family="third_family",
                           sha256="b" * 64)
        snapshots.update({row["snapshot_id"]: row for row in [alias, reencoded, same_origin]})
        annotations = {
            row["snapshot_id"]: {"upstream_origin": "synthetic_programme"}
            for row in [primary, same_origin]
        }
        group = next(group for group in source_dependence(snapshots, annotations)
                     if primary["snapshot_id"] in {member["snapshot_id"] for member in group["members"]})
        self.assertEqual(len(group["members"]), 4)
        self.assertEqual(group["candidate_origin_count"], 1)

    def test_selection_caps_at_thirty_and_preserves_risk_and_source_diversity(self):
        for i in range(40):
            identifier = f"synthetic:new:{i:02}"
            self.tables["facility_evidence"][identifier] = dict(
                self.evidence, evidence_id=identifier, temporal_status="undated",
            )
        labels = {"synthetic:new:39": {"campus": "conflict"}, self.evidence_id: {"lane": "secondary"}}
        selected, population, lanes = select_claims(self.tables, labels)
        self.assertEqual((len(selected), population, sum(lanes.values())), (30, 42, 42))
        self.assertIn(self.evidence_id, selected[:3])
        self.assertIn("synthetic:new:39", selected[:3])

    def test_selection_uses_every_available_service_claim_if_below_cap(self):
        selected, population, _ = select_claims(self.tables)
        self.assertEqual(population, 2)
        self.assertEqual(set(selected), {row["evidence_id"] for row in self.batch["facility_evidence"][:2]})

    def test_stale_review_cannot_pass_corrected_payload_and_history_is_retained(self):
        observations = {self.evidence_id: self.observation}
        self.observation["checks"]["campus"] = finding("fail", "Synthetic crosswalk was misapplied.")
        _, history = adjudicate([self.evidence_id], self.tables, observations, [])
        self.evidence["assertion"] = "The dated programme named the original campus."
        self.assertEqual(adjudicate([self.evidence_id], self.tables, {}, history)[0], [])
        with self.assertRaisesRegex(ValueError, "different payload"):
            adjudicate([self.evidence_id], self.tables, observations, history)
        corrected = copy.deepcopy(self.observation)
        corrected["checks"]["campus"] = finding("pass", "Corrected assertion names original campus.")
        corrected["reviewed_payload_sha256"] = digest(self.context)
        corrected["reviewed_at"] = "2026-11-21T18:10:00Z"
        reviews, history = adjudicate([self.evidence_id], self.tables, {self.evidence_id: corrected}, history)
        self.assertEqual(reviews[0]["outcome"], "pass")
        self.assertEqual([row["outcome"] for row in history], ["fail", "pass"])
        self.assertEqual(queue_batch(self.tables, reviews)["review_queue"], [])

    def test_duplicate_replay_and_conflict(self):
        self.assertEqual(index_batches([self.batch, self.batch]), self.tables)
        conflicting = copy.deepcopy(self.batch)
        conflicting["facility_evidence"][0]["excerpt"] = "Conflicting excerpt"
        with self.assertRaisesRegex(ValueError, "Conflicting facility_evidence"):
            index_batches([self.batch, conflicting])

    def test_cli_writes_audit_history_queue_and_checked_inventory(self):
        second = self.batch["facility_evidence"][1]
        observation = dict(
            self.observation,
            reviewed_payload_sha256=digest(review_context(second, self.tables)),
            source_temporal_status="undated",
            located_passage=None,
            reason="Synthetic original unavailable.",
        )
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "observations.json"
            output = folder / "review"
            source.write_text(json.dumps({
                self.evidence_id: self.observation,
                second["evidence_id"]: observation,
            }), encoding="utf-8")
            argv = [
                "b5", "--batch", str(FIXTURE), "--observations", str(source), "--out", str(output),
            ]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                main()
            decisions = json.loads((output / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {row["evidence_id"]: row["outcome"] for row in decisions},
                {self.evidence_id: "pass", second["evidence_id"]: "uncertain"},
            )
            inventory = json.loads((output / "artifact_inventory.json").read_text(encoding="utf-8"))
            outputs = {Path(row["path"]).name: row["sha256"] for row in inventory["outputs"]}
            self.assertEqual(outputs["audit.json"], hashlib.sha256((output / "audit.json").read_bytes()).hexdigest())
            batch = json.loads((output / "batch.json").read_text(encoding="utf-8"))
            self.assertEqual(batch["review_queue"][0]["evidence_id"], second["evidence_id"])


if __name__ == "__main__":
    unittest.main()
