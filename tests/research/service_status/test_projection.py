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
                "conflicts": ["base_geography_disagreement", "competing_campuses"]}
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

    def test_candidate_flags_apply_to_links_but_do_not_dispute_same_campus_text(self):
        geo = [{"facility_id": row["facility_id"], "state": "synthetic", "outcome": "ambiguous",
                "conflicts": ["competing_campuses", "candidate_geography_conflict"]} for row in self.base]
        batch = load(ROOT / "contracts" / "fixtures" / "enrichment.json")
        item = batch["facility_evidence"][0]
        item.update(temporal_status="dated", effective_date=DAY, excerpt="Trauma care onsite.")
        external = original("trauma_care")
        external.update(review_id="ext", source={"kind": "external", "evidence_id": item["evidence_id"]})
        result = self.run_projection([original(), external], [batch], identity=geo)
        services = lookup(result, FID)["services"]
        self.assertEqual(services["mri"]["status"], "yes")
        self.assertEqual(services["trauma_care"]["reason_code"], "campus_conflict")
        self.assertEqual(result["facilities"][FID]["identity_conflicts"], geo[0]["conflicts"])

        # An explicit dispute about the original itself always survives candidate retrieval.
        disputed = original(finding="campus_conflict")
        disputed["review_id"] = "dispute"
        result = self.run_projection([original(), disputed], identity=geo)
        self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "unconfirmed")

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

    def campus_reviews(self, text, host_excerpt, partner_excerpt):
        self.base[0]["source_row"].update(name="Partner Campus", description=text)
        self.base[1]["source_row"].update(name="Host Campus", description=text)
        batch = load(ROOT / "contracts" / "fixtures" / "enrichment.json")
        host, partner = original(), original()
        for review, target, excerpt in ((host, "twin", host_excerpt), (partner, FID, partner_excerpt)):
            review.update(review_id=target, facility_id=target)
            start = text.index(excerpt)
            review["source"].update(occurrence_key="twin", start=start, end=start + len(excerpt), excerpt=excerpt)
        partner["source"]["target_match_id"] = batch["facility_matches"][0]["match_id"]
        partner["campus_resolution"] = "The service statement explicitly identifies Partner Campus."
        return host, partner, batch

    def test_competing_onsite_targets_share_one_passage(self):
        phrase = "Only Partner Campus operates the onsite MRI service."
        text = "Host Campus is on Example Road. " + phrase
        for host_excerpt in (phrase, phrase[:-1], text):
            with self.subTest(host_excerpt=host_excerpt):
                host, partner, batch = self.campus_reviews(text, host_excerpt, phrase)
                contested = self.run_projection([host, partner], [batch])
                self.assertEqual(contested, self.run_projection([partner, host], [batch]))
                for target, rival in (("twin", FID), (FID, "twin")):
                    claim = lookup(contested, target)["services"]["mri"]
                    self.assertEqual(claim["reason_code"], "disputed_claim")
                    self.assertEqual(patient_lookup(contested, target)["services"]["mri"]["status"], "unconfirmed")
                    self.assertEqual(claim["reviews"][0]["finding"], "onsite_service")
                    self.assertEqual(claim["reviews"][0]["attribution_conflicts_with"], [rival])
                    self.assertEqual(claim["reviews"][0]["provenance"]["occurrence_key"], "twin")

        other = copy.deepcopy(host)
        other.update(review_id="other", finding="other_campus")
        for reviews in ([partner], [other, partner]):
            result = self.run_projection(reviews, [batch])
            self.assertEqual(patient_lookup(result, "twin")["services"]["mri"]["status"], "unconfirmed")
            self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "yes")

        # A third interpretation does not withdraw the host's active onsite attribution.
        contested = self.run_projection([host, partner, other], [batch])
        self.assertEqual(contested["coverage"]["mri"]["unconfirmed"], 3)
        partner_support = copy.deepcopy(partner)
        partner_support["review_id"] = "independent-partner"
        separate_text = "The MRI clinic at Partner Campus performs scans onsite."
        partner_support["source"] = dict(partner["source"], occurrence_key=FID, field="procedure",
                                         start=0, end=len(separate_text), excerpt=separate_text)
        self.base[0]["source_row"]["procedure"] = separate_text
        del partner_support["source"]["target_match_id"]
        supported = self.run_projection([host, partner, other, partner_support], [batch])
        self.assertEqual(patient_lookup(supported, FID)["services"]["mri"]["status"], "yes")

    def test_geography_held_onsite_review_still_competes_for_the_same_passage(self):
        phrase = "Only Partner Campus operates onsite MRI."
        host, partner, batch = self.campus_reviews(phrase, phrase, phrase)
        geo = [{"facility_id": r["facility_id"], "state": "synthetic", "outcome": "ambiguous",
                "conflicts": ["base_geography_disagreement"] if r["facility_id"] == "twin" else []}
               for r in self.base]
        result = self.run_projection([host, partner], [batch], identity=geo)
        self.assertEqual(result, self.run_projection([partner, host], [batch], identity=geo))
        for target, rival, reason in (("twin", FID, "campus_conflict"), (FID, "twin", "disputed_claim")):
            service = lookup(result, target)["services"]["mri"]
            self.assertEqual(service["reason_code"], reason)
            self.assertEqual(patient_lookup(result, target)["services"]["mri"]["status"], "unconfirmed")
            self.assertEqual(service["reviews"][0]["attribution_conflicts_with"], [rival])
        self.assertEqual(lookup(result, "twin")["services"]["mri"]["reviews"][0]["reviewed_finding"], "onsite_service")

        undated_host = copy.deepcopy(host)
        undated_host["source"]["source_date"] = None
        undated = self.run_projection([undated_host, partner], [batch], identity=geo)
        self.assertEqual(undated["coverage"]["mri"]["unconfirmed"], 3)

        for boundary in ({"valid_until": "2026-11-20"}, {"valid_from": "2026-11-22"}, {"source_date": "2026-11-22"}):
            with self.subTest(boundary=boundary):
                dated_host = copy.deepcopy(host)
                dated_host["source"].update(boundary)
                resolved = self.run_projection([dated_host, partner], [batch], identity=geo)
                self.assertEqual(patient_lookup(resolved, FID)["services"]["mri"]["status"], "yes")

    def test_explicit_joint_onsite_review_for_each_named_target(self):
        text = "Host Campus and Partner Campus each perform MRI onsite."
        host, partner, batch = self.campus_reviews(text, text, text)
        host["campus_resolution"] = "Host Campus is one of the two sites explicitly providing MRI onsite."
        self.assertEqual(self.run_projection([host, partner], [batch])["coverage"]["mri"]["unconfirmed"], 3)
        host["joint_onsite_targets"] = [FID, "twin"]
        self.assertEqual(self.run_projection([host, partner], [batch])["coverage"]["mri"]["unconfirmed"], 3)
        partner["joint_onsite_targets"] = ["twin", FID]
        result = self.run_projection([host, partner], [batch])
        for target in ("twin", FID):
            self.assertEqual(patient_lookup(result, target)["services"]["mri"]["status"], "yes")
            claim = lookup(result, target)["services"]["mri"]["reviews"][0]
            self.assertEqual(claim["joint_onsite_targets"], sorted([FID, "twin"]))
            self.assertNotIn("attribution_conflicts_with", claim)

        for targets, rationale in ((["twin", FID], "It is at the second campus."),
                                   (["twin", FID], "Host Campus and Partner Campus."),
                                   (["twin", "twin"], host["campus_resolution"]),
                                   (["twin", "absent"], host["campus_resolution"])):
            with self.subTest(targets=targets, rationale=rationale), self.assertRaises(MatchingError):
                self.run_projection([dict(host, joint_onsite_targets=targets, campus_resolution=rationale)], [batch])
        self.base[1]["source_row"]["name"] = "Campus"
        host["source"].update(start=16, end=len(text), excerpt=text[16:])
        with self.assertRaisesRegex(MatchingError, "identify each target separately"):
            self.run_projection([host], [batch])

    def test_separate_statements_and_twin_origins_can_support_two_campuses(self):
        first, second = "Host Campus performs onsite MRI.", "Partner Campus performs onsite MRI."
        host, partner, batch = self.campus_reviews(first + " " + second, first, second)
        self.assertEqual(self.run_projection([host, partner], [batch])["coverage"]["mri"]["yes"], 2)
        # Distinct original occurrences can have identical IDs, raw fields and character coordinates.
        both = "Host Campus and Partner Campus each perform onsite MRI."
        host, partner, batch = self.campus_reviews(both, both, both)
        partner["source"]["occurrence_key"] = FID
        del partner["source"]["target_match_id"]
        self.assertEqual(self.run_projection([host, partner], [batch])["coverage"]["mri"]["yes"], 2)

    def test_different_services_or_fields_do_not_compete_for_a_passage(self):
        text = "Host Campus offers dialysis and Partner Campus provides onsite MRI."
        host, partner, batch = self.campus_reviews(text, text, text)
        host["service"] = "dialysis"
        result = self.run_projection([host, partner], [batch])
        self.assertEqual(patient_lookup(result, "twin")["services"]["dialysis"]["status"], "yes")
        self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "yes")

        text = "Host Campus and Partner Campus each offer onsite MRI."
        host, partner, batch = self.campus_reviews(text, text, text)
        self.base[1]["source_row"]["capability"] = text
        host["source"]["field"] = "capability"
        self.assertEqual(self.run_projection([host, partner], [batch])["coverage"]["mri"]["yes"], 2)

    def test_competing_targets_keep_independent_support_and_historical_reviews(self):
        phrase = "Only Partner Campus operates onsite MRI."
        separate = "Host Campus refers all MRI cases elsewhere."
        host, partner, batch = self.campus_reviews(phrase + " " + separate, phrase, phrase)
        no = copy.deepcopy(host)
        no.update(review_id="host-referral", finding="referral_only")
        no["source"].update(start=len(phrase) + 1, end=len(phrase) + 1 + len(separate), excerpt=separate)
        result = self.run_projection([host, partner, no], [batch])
        self.assertEqual(patient_lookup(result, "twin")["services"]["mri"]["status"], "no")
        self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "unconfirmed")

        host["superseded_by"] = no["review_id"]
        result = self.run_projection([host, partner, no], [batch])
        self.assertEqual(patient_lookup(result, FID)["services"]["mri"]["status"], "yes")
        public_host = patient_lookup(result, "twin")["services"]["mri"]
        self.assertEqual(public_host["status"], "no")
        self.assertTrue(any(c.get("historical") for c in public_host["sources"]))
        self.assertEqual(len(lookup(result, "twin")["services"]["mri"]["reviews"]), 2)


if __name__ == "__main__":
    unittest.main()
