import copy
from pathlib import Path
import unittest

from research.matching.common import MatchingError, digest, load
from research.service_status.projection import lookup, patient_lookup, project


DAY = "2026-11-21"
FID = "synthetic:base:001"
TEXT = "Example Campus offers onsite MRI. All dialysis patients are referred elsewhere."
ROOT = Path(__file__).resolve().parents[3]


def original(service="mri", finding="onsite_service", phrase="Example Campus offers onsite MRI."):
    return {"facility_id": FID, "service": service, "review_id": "r1",
            "finding": finding, "assessed_for": DAY, "reviewer": "fixture-reviewer",
            "reviewed_at": DAY + "T18:00:00Z",
            "source": {"kind": "original", "field": "description", "start": TEXT.index(phrase),
                       "end": TEXT.index(phrase) + len(phrase), "excerpt": phrase,
                       "source_date": "2026-11-18", "source_family": "synthetic-publisher"}}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.base = [{"facility_id": FID, "source_row": {"unique_id": "shared", "description": TEXT}},
                     {"facility_id": "twin", "source_row": {"unique_id": "shared", "description": TEXT}},
                     {"facility_id": "sparse", "source_row": {"unique_id": "empty"}}]
        self.meta = {"mapping": {"id": "unique_id"}, "row_count": 3, "original_table": "synthetic.facilities",
                     "observed_delta_version": 0, "base_file_sha256": "e" * 64}

    def run_projection(self, reviews=(), batches=(), identity=None):
        return project(self.base, self.meta, list(reviews), list(batches), as_of=DAY,
                       base_file_sha256="e" * 64, checked_sources=["synthetic"],
                       identity_rows=identity, identity_report={"base_sha256": digest(self.base),
                       "scope": {"state": None}, "denominators": {"original_rows": 3}} if identity is not None else None)

    def test_empty_coverage_preserves_sparse_and_twin_occurrences(self):
        result = self.run_projection()
        self.assertEqual(result["decision_count"], 9)
        self.assertEqual(result["coverage"]["mri"], {"no": 0, "yes": 0, "unconfirmed": 3})
        self.assertEqual(result["coverage_by_state"]["unknown"]["dialysis"]["unconfirmed"], 3)
        self.assertEqual(lookup(result, "twin")["source_id"], "shared")
        self.assertEqual(lookup(result, "sparse")["services"]["mri"]["reviews"], [])

    def test_reviewed_original_affirmative_and_referral_only(self):
        yes = original()
        no = original("dialysis", "referral_only", "All dialysis patients are referred elsewhere.")
        no["review_id"] = "r2"
        result = self.run_projection([yes, no])
        services = lookup(result, FID)["services"]
        self.assertEqual(services["mri"]["status"], "yes")
        self.assertEqual(services["dialysis"]["status"], "no")
        self.assertEqual(services["trauma_care"]["status"], "unconfirmed")
        self.assertEqual(services["mri"]["reviews"][0]["provenance"]["url_scope"], "record")
        self.assertEqual(lookup(result, "twin")["services"]["mri"]["status"], "unconfirmed")
        public = patient_lookup(result, FID)
        self.assertEqual(public["services"]["mri"]["sources"],
                         [{"kind": "original", "field": "description", "date": "2026-11-18"}])
        self.assertNotIn("reviews", public["services"]["mri"])

    def test_narrow_historical_and_mixed_campus_findings(self):
        for finding in ("historical_only", "planned", "equipment_only", "other_campus", "date_unclear"):
            with self.subTest(finding=finding):
                result = self.run_projection([original(finding=finding)])
                self.assertEqual(lookup(result, FID)["services"]["mri"]["status"], "unconfirmed")

    def test_applicable_conflict_is_retained_and_blocks(self):
        yes, no = original(), original(finding="explicit_no_onsite")
        # Both assessed reviews on distinct exact statements in the synthetic source.
        no_text = "MRI is not offered onsite."
        no.update(review_id="r2")
        self.base[0]["source_row"]["description"] += " " + no_text
        no["source"].update(start=len(TEXT) + 1, end=len(TEXT) + 1 + len(no_text), excerpt=no_text)
        result = self.run_projection([yes, no])
        claim = lookup(result, FID)["services"]["mri"]
        self.assertEqual(claim["reason_code"], "conflicting_claims")
        self.assertEqual(len(claim["reviews"]), 2)

    def test_dates_confine_the_assessment(self):
        for dates in ({"source_date": None}, {"source_date": "2026-11-22"},
                      {"valid_until": "2026-11-20"}, {"valid_from": "2026-11-22"}):
            r = original()
            r["source"].update(dates)
            self.assertEqual(lookup(self.run_projection([r]), FID)["services"]["mri"]["status"], "unconfirmed")

    def test_service_at_other_named_campus_preserves_the_original_locator(self):
        other = original(finding="other_campus")
        other.update(facility_id="twin", review_id="r2")
        self.base[0]["source_row"]["name"] = "Example Campus"
        attributed = original()
        attributed["source"]["occurrence_key"] = "twin"
        with self.assertRaises(MatchingError):
            self.run_projection([other, attributed])
        batch = load(ROOT / "contracts" / "fixtures" / "enrichment.json")
        attributed["source"]["target_match_id"] = batch["facility_matches"][0]["match_id"]
        attributed["campus_resolution"] = "The source explicitly names Example Campus and the reviewed match resolves that site."
        result = self.run_projection([other, attributed], [batch])
        self.assertEqual(lookup(result, "twin")["services"]["mri"]["status"], "unconfirmed")
        entry = lookup(result, FID)["services"]["mri"]
        self.assertEqual(entry["status"], "yes")
        self.assertEqual(entry["reviews"][0]["provenance"]["occurrence_key"], "twin")
        self.base[0]["source_row"]["name"] = "Different Campus"
        with self.assertRaises(MatchingError):
            self.run_projection([other, attributed], [batch])

    def test_wrong_field_span_and_base_version_fail(self):
        r = original()
        r["source"]["start"] += 1
        with self.assertRaises(MatchingError):
            self.run_projection([r])
        self.meta["base_file_sha256"] = "0" * 64
        with self.assertRaises(MatchingError):
            self.run_projection()

    def test_older_conflicts_and_explicit_supersession(self):
        yes = original()
        conflict = original(finding="campus_conflict")
        conflict["review_id"] = "older"
        conflict["source"]["valid_until"] = "2026-10-01"
        result = self.run_projection([yes, conflict])
        self.assertEqual(lookup(result, FID)["services"]["mri"]["status"], "yes")
        del conflict["source"]["valid_until"]
        self.assertEqual(lookup(self.run_projection([yes, conflict]), FID)["services"]["mri"]["status"], "unconfirmed")
        conflict["superseded_by"] = "r1"
        result = self.run_projection([yes, conflict])
        self.assertEqual(lookup(result, FID)["services"]["mri"]["status"], "yes")
        self.assertEqual(len(lookup(result, FID)["services"]["mri"]["reviews"]), 2)
        conflict["superseded_by"] = "missing"
        with self.assertRaises(MatchingError):
            self.run_projection([yes, conflict])

    def test_patient_view_keeps_time_scope_and_checked_sources(self):
        no = original("dialysis", "referral_only", "All dialysis patients are referred elsewhere.")
        no["source"].update(valid_from="2026-11-20", valid_until="2026-11-22")
        public = patient_lookup(self.run_projection([no]), FID)
        self.assertEqual(public["checked_sources"], ["synthetic"])
        self.assertEqual(public["services"]["dialysis"]["sources"][0]["valid_until"], "2026-11-22")
        self.assertEqual(public["services"]["mri"]["sources"], [])

    def test_external_snapshot_date_and_campus_link(self):
        batch = load(ROOT / "contracts" / "fixtures" / "enrichment.json")
        item = batch["facility_evidence"][0]
        r = original("trauma_care")
        r["source"] = {"kind": "external", "evidence_id": item["evidence_id"]}
        self.assertEqual(lookup(self.run_projection([r], [batch]), FID)["services"]["trauma_care"]["status"],
                         "unconfirmed")
        item.update(temporal_status="dated", assertion="Synthetic campus performs onsite trauma care.",
                    excerpt="This campus performs onsite trauma care.", effective_date=DAY)
        result = self.run_projection([r], [batch, copy.deepcopy(batch)])
        claim = lookup(result, FID)["services"]["trauma_care"]
        self.assertEqual(claim["status"], "yes")
        self.assertEqual(claim["reviews"][0]["provenance"]["locator"], item["locator"])
        batch["facility_matches"][0]["status"] = "candidate"
        with self.assertRaises(MatchingError):
            self.run_projection([r], [batch])

    def test_identity_conflict_requires_explicit_campus_resolution(self):
        geo = [{"facility_id": b["facility_id"], "state": "synthetic", "outcome": "ambiguous",
                "conflicts": ["competing_campuses"]}
               for b in self.base]
        r = original()
        unresolved = lookup(self.run_projection([r], identity=geo), FID)["services"]["mri"]
        self.assertEqual(unresolved["reason_code"], "campus_conflict")
        r["campus_resolution"] = "The reviewed statement and address identify the same synthetic campus."
        self.assertEqual(lookup(self.run_projection([r], identity=geo), FID)["services"]["mri"]["status"], "yes")
        with self.assertRaises(MatchingError):
            self.run_projection(identity=geo[:-1])
        with self.assertRaises(MatchingError):
            self.run_projection(identity=self.base)

    def test_same_excerpt_dispute_with_an_independent_undisputed_statement(self):
        yes, other_campus = original(), original(finding="other_campus")
        other_campus["review_id"] = "r2"
        disputed = lookup(self.run_projection([yes, other_campus]), FID)["services"]["mri"]
        self.assertEqual(disputed["reason_code"], "disputed_claim")
        different = original()
        different["review_id"] = "r3"
        different["source"]["field"] = "procedure"
        self.base[0]["source_row"]["procedure"] = "MRI scans are performed here."
        different["source"].update(start=0, end=29, excerpt="MRI scans are performed here.")
        self.assertEqual(lookup(self.run_projection([yes, other_campus, different]), FID)["services"]["mri"]["status"], "yes")

    def test_overlapping_reviews_preserve_disputes_and_disjoint_support(self):
        first = "Example Campus offers onsite MRI."
        second = "This site also operates an MRI clinic."
        field = first + " " + second
        self.base[0]["source_row"]["description"] = field
        yes = original()
        for start, end in ((0, len(first) - 1), (0, len(field)), (8, len(first) + 3)):
            with self.subTest(span=(start, end)):
                other = original(finding="other_campus")
                other["review_id"] = "r2"
                other["source"].update(start=start, end=end, excerpt=field[start:end])
                result = self.run_projection([yes, other])
                self.assertEqual(lookup(result, FID)["services"]["mri"]["reason_code"], "disputed_claim")
                self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "unconfirmed")

        # Half-open spans can touch without disputing the neighbouring statement.
        other["source"].update(start=0, end=len(first) + 1, excerpt=field[:len(first) + 1])
        independent = copy.deepcopy(yes)
        independent["review_id"] = "r3"
        independent["source"].update(start=len(first) + 1, end=len(field), excerpt=second)
        result = self.run_projection([other, independent, yes])
        self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "yes")
        self.assertEqual(len(lookup(result, FID)["services"]["mri"]["reviews"]), 3)


if __name__ == "__main__":
    unittest.main()
