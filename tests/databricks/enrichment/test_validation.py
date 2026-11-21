import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "databricks/enrichment"))
from common import Invalid, digest, empty, load
from merge import plan_merge
from validation import semantic_check


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.batch = load(ROOT / "contracts/fixtures/enrichment.json")
        self.base = load(ROOT / "contracts/fixtures/enrichment_base.json")

    def validate(self):
        return plan_merge([self.batch], self.base)

    def test_shared_fixture_and_base_preservation(self):
        original = copy.deepcopy(self.base)
        plan = self.validate()
        self.assertEqual(plan["base"], original)
        self.assertEqual(self.base, original)
        self.assertEqual(plan["base_sha256"], digest(original))
        plan["base"][0]["original_evidence"] = "mutated output"
        self.assertEqual(self.base, original)

    def test_unknown_version(self):
        self.batch["contract_version"] = "2.0.0"
        with self.assertRaisesRegex(Invalid, "contract_version"):
            self.validate()

    def test_schema_unknown_field_and_missing_array(self):
        for mutation in (lambda b: b.update(extra=True), lambda b: b.pop("review_queue")):
            batch = copy.deepcopy(self.batch)
            mutation(batch)
            with self.assertRaisesRegex(Invalid, "schema"):
                plan_merge([batch], self.base)

    def test_formats(self):
        for field, value in (("retrieved_at", "2026-02-30T12:00:00Z"),
                             ("retrieved_at", "2026-01-01T12:00:00+01:00"),
                             ("published_date", "2026-02-30"), ("url", "not a URI")):
            with self.subTest(field=field, value=value):
                batch = copy.deepcopy(self.batch)
                batch["source_snapshots"][0][field] = value
                with self.assertRaisesRegex(Invalid, field):
                    plan_merge([batch], self.base)

    def test_nonfinite_and_bounds(self):
        for value in (float("nan"), float("inf"), float("-inf"), 91):
            with self.subTest(value=value):
                self.batch["external_facilities"][0]["latitude"] = value
                with self.assertRaisesRegex(Invalid, "latitude"):
                    self.validate()

    def test_unknown_base(self):
        self.batch["facility_matches"][0]["facility_id"] = "missing"
        with self.assertRaisesRegex(Invalid, "facility_id.*not found"):
            self.validate()

    def test_cross_batch_references(self):
        accepted = copy.deepcopy(self.batch)
        accepted["facility_evidence"] = []
        accepted["review_queue"] = []
        batch = empty()
        batch["facility_evidence"] = self.batch["facility_evidence"]
        batch["review_queue"] = self.batch["review_queue"]
        self.assertEqual(plan_merge([batch], self.base, accepted)["batch"]["facility_evidence"], self.batch["facility_evidence"])
        with self.assertRaisesRegex(Invalid, "external_facility_id.*not found"):
            plan_merge([batch], self.base)

    def test_dangling_snapshot_and_queue_reference(self):
        for table, key in (("external_facilities", "snapshot_id"), ("facility_evidence", "snapshot_id"),
                           ("review_queue", "evidence_id")):
            with self.subTest(table=table):
                batch = copy.deepcopy(self.batch)
                batch[table][0][key] = "missing:id"
                with self.assertRaisesRegex(Invalid, key + ".*not found"):
                    plan_merge([batch], self.base)

    def test_wrong_or_rejected_match(self):
        for match_id in ("synthetic:match:002", "synthetic:match:003"):
            self.batch["facility_evidence"][0]["match_id"] = match_id
            with self.assertRaisesRegex(Invalid, "confirmed match"):
                self.validate()

    def test_confirmed_match_wrong_external(self):
        self.batch["facility_evidence"][0]["external_facility_id"] = "synthetic:external:002"
        with self.assertRaisesRegex(Invalid, "identical base/external"):
            self.validate()

    def test_manual_confirmation_requires_review(self):
        self.batch["facility_matches"][0].update(reviewer=None, reviewed_at=None)
        with self.assertRaisesRegex(Invalid, "reviewer and UTC"):
            self.validate()

    def test_candidate_method_cannot_confirm(self):
        self.batch["facility_matches"][0]["method"] = "candidate_generation"
        with self.assertRaisesRegex(Invalid, "candidate generation cannot confirm"):
            self.validate()

    def test_partial_links_and_partial_review(self):
        for key, value in (("match_id", None), ("reviewer", None)):
            batch = copy.deepcopy(self.batch)
            batch["facility_evidence"][0][key] = value
            with self.assertRaises(Invalid):
                plan_merge([batch], self.base)

    def test_cross_source_evidence_permitted_but_reviewed(self):
        plan = self.validate()
        self.assertNotEqual(plan["batch"]["external_facilities"][0]["snapshot_id"],
                            plan["batch"]["facility_evidence"][0]["snapshot_id"])
        self.batch["facility_evidence"][2].update(reviewer=None, reviewed_at=None)
        with self.assertRaisesRegex(Invalid, "reviewer and UTC"):
            self.validate()

    def test_spatial_service_upgrade_fails(self):
        self.batch["facility_evidence"][2].update(claim_type="service", service="trauma_care")
        with self.assertRaisesRegex(Invalid, "schema"):
            self.validate()

    def test_spatial_units_and_limitations(self):
        for key, value in (("units", "km"), ("limitations", []), ("distance_m", float("nan"))):
            batch = copy.deepcopy(self.batch)
            batch["facility_evidence"][2]["observation"][key] = value
            with self.assertRaises(Invalid):
                plan_merge([batch], self.base)

    def test_unlinked_inconclusive_is_permitted(self):
        plan = self.validate()
        self.assertIsNone(plan["batch"]["facility_evidence"][1]["facility_id"])

    def test_clinical_review_and_known_bad_upgrades(self):
        for excerpt in ("General emergency services.", "A planned trauma centre.",
                        "Trauma referral-only services.", "Trauma services unavailable."):
            with self.subTest(excerpt=excerpt):
                batch = copy.deepcopy(self.batch)
                batch["facility_evidence"][0]["excerpt"] = excerpt
                with self.assertRaises(Invalid):
                    plan_merge([batch], self.base)
        self.batch["facility_evidence"][0].update(snapshot_id=self.batch["external_facilities"][0]["snapshot_id"],
                                                reviewer=None, reviewed_at=None)
        with self.assertRaisesRegex(Invalid, "reviewer and UTC"):
            self.validate()

    def test_claim_service_mismatch(self):
        self.batch["facility_evidence"][0]["claim_type"] = "accreditation"
        with self.assertRaisesRegex(Invalid, "service is required only"):
            self.validate()

    def test_temporal_consistency(self):
        for changes in ({"temporal_status": "undated"},
                        {"valid_until": "2017-01-01"},
                        {"temporal_status": "dated", "effective_date": None},
                        {"temporal_status": "expired"}):
            batch = copy.deepcopy(self.batch)
            batch["facility_evidence"][0].update(changes)
            with self.assertRaises(Invalid):
                plan_merge([batch], self.base)

    def test_base_duplicates_and_blank_id(self):
        for base in (self.base + [self.base[0]], [{"facility_id": " "}]):
            with self.assertRaisesRegex(Invalid, "base"):
                plan_merge([self.batch], base)

    def test_missing_name_not_fabricated(self):
        self.batch["external_facilities"][0]["name_original"] = None
        with self.assertRaisesRegex(Invalid, "missing original name"):
            self.validate()
        self.batch["external_facilities"][0]["name_normalized"] = None
        self.validate()

    def shared_setup(self):
        self.base[0]["source_row"] = {"registry_id": "EX-001"}
        self.batch["facility_matches"][0].update(method="shared_identifier", reviewer=None, reviewed_at=None,
            shared_identifier={"namespace": "synthetic_registry", "value": "EX-001",
                               "base_field": "source_row.registry_id", "external_field": "source_record_id"})
        return {"synthetic_registry": {"base_field": "source_row.registry_id", "external_field": "source_record_id",
                                       "source_keys": ["synthetic_directory"]}}

    def test_shared_identifier_needs_verified_policy_and_exact_values(self):
        policy = self.shared_setup()
        with self.assertRaisesRegex(Invalid, "unverified namespace"):
            self.validate()
        plan_merge([self.batch], self.base, identity_policy=policy)
        self.base[0]["source_row"]["registry_id"] = "EX-002"
        with self.assertRaisesRegex(Invalid, "not verifiable exactly"):
            plan_merge([self.batch], self.base, identity_policy=policy)

    def test_shared_identifier_ambiguity_and_branch_conflict(self):
        policy = self.shared_setup()
        self.base[1]["source_row"] = {"registry_id": "EX-001"}
        with self.assertRaisesRegex(Invalid, "ambiguous"):
            plan_merge([self.batch], self.base, identity_policy=policy)
        self.base[1].pop("source_row")
        competitor = copy.deepcopy(self.batch["facility_matches"][1])
        competitor.update(match_id="synthetic:competitor", external_facility_id="synthetic:external:001")
        self.batch["facility_matches"].append(competitor)
        with self.assertRaisesRegex(Invalid, "competing"):
            plan_merge([self.batch], self.base, identity_policy=policy)

    def test_review_queue_coherence_and_resolution(self):
        self.batch["review_queue"][0]["status"] = "resolved"
        with self.assertRaisesRegex(Invalid, "resolution"):
            self.validate()
        self.batch["review_queue"][0].update(status="open", facility_id=None, external_facility_id=None,
                                             match_id="synthetic:match:001")
        with self.assertRaisesRegex(Invalid, "different facilities"):
            self.validate()

    def test_cli_valid_and_invalid_no_output_artifact(self):
        command = [sys.executable, str(ROOT / "databricks/enrichment/validate_batch.py"),
                   "--base", str(ROOT / "contracts/fixtures/enrichment_base.json")]
        result = subprocess.run(command + ["--batch", str(ROOT / "contracts/fixtures/enrichment.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["base_rows"], 2)
        with tempfile.TemporaryDirectory() as tmp:
            invalid = Path(tmp) / "invalid.json"
            output = Path(tmp) / "plan.json"
            self.batch["facility_matches"][0]["facility_id"] = "missing"
            invalid.write_text(json.dumps(self.batch))
            result = subprocess.run(command + ["--batch", str(invalid), "--plan-out", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("facility_id", result.stderr)
            self.assertFalse(output.exists())

    def test_json_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.json"
            path.write_text('{"contract_version":"1.0.0","contract_version":"1.0.0"}')
            with self.assertRaisesRegex(Invalid, "duplicate object key"):
                load(path)


if __name__ == "__main__":
    unittest.main()
