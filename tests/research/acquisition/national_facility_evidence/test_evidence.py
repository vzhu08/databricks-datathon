"""Synthetic controls for the national evidence research pipeline."""

import unittest

from research.acquisition.national_facility_evidence.model import (
    EvidenceBatch, claim_conflicts, dated_onsite, link_outcomes, source_counts,
)
from research.acquisition.national_facility_evidence.run import combined_status


def record(key="record", family="issuer", origin="registry-row"):
    return {"record_id": key, "edition": "test", "family": family, "origin_record": origin, "locator": "test row"}


def site(key="site", source="record", comparable=True, witnesses=(), reviewed=False):
    return {"premises_id": key, "record_id": source, "comparable": comparable,
            "identity_reviewed": reviewed, "witnesses": list(witnesses)}


def edge(occ="original-a", premise="site", exact=True, conflicts=()):
    return {"occurrence_key": occ, "premises_id": premise, "exact_candidate": exact,
            "basis": "documented basis", "conflicts": list(conflicts)}


def claim(key, scope, observation=None, start=None, end=None, premise="site", source="record"):
    return {"claim_id": key, "scope": scope, "premises_id": premise, "service": "dialysis",
            "record_id": source, "locator": "test statement", "publication_date": "2026-11-22",
            "observation_date": observation, "effective_from": start, "effective_to": end,
            "availability": None, "capacity": None}


class LinkControls(unittest.TestCase):
    def setUp(self):
        self.originals = {"original-a": {"payload_sha256": "same"}, "original-b": {"payload_sha256": "same"},
                          "other-branch": {"payload_sha256": "different"}, "missing": {"payload_sha256": "missing"}}

    def run_links(self, links, premises=None):
        batch = EvidenceBatch("control", {}, [record()], premises or [site()], links=links)
        return link_outcomes(batch, self.originals)

    def test_identical_copies_survive_reverse_uniqueness(self):
        forward, reverse = self.run_links([edge(), edge("original-b")])
        self.assertEqual(len(forward), 4)
        self.assertEqual([forward[k]["status"] for k in ("original-a", "original-b")], ["exact", "exact"])
        self.assertEqual(reverse["site"]["status"], "exact")
        self.assertEqual(len(reverse["site"]["candidates"]), 2)

    def test_distinct_branch_with_same_label_can_block_exact(self):
        forward, reverse = self.run_links([edge(), edge("other-branch", exact=False)])
        self.assertEqual(forward["original-a"]["status"], "ambiguous")
        self.assertEqual(forward["other-branch"]["status"], "ambiguous")
        self.assertEqual(reverse["site"]["status"], "ambiguous")

    def test_shared_pin_or_name_retrieval_cannot_confirm_branch(self):
        forward, reverse = self.run_links([edge(exact=False)])
        self.assertEqual(forward["original-a"]["status"], "ambiguous")
        self.assertEqual(reverse["site"]["status"], "ambiguous")

    def test_explicit_street_conflict_stays_visible(self):
        forward, _ = self.run_links([edge(conflicts=("street_conflict",))])
        self.assertEqual(forward["original-a"]["status"], "ambiguous")
        self.assertEqual(forward["original-a"]["candidates"][0]["conflicts"], ["street_conflict"])

    def test_alternate_buildings_across_methods_are_not_coalesced(self):
        first, _ = self.run_links([edge()])
        alt, _ = self.run_links([edge(premise="alternative", exact=False)], [site("alternative")])
        self.assertEqual(combined_status([first, alt], "original-a"), "ambiguous")
        self.assertEqual(combined_status([first, alt], "missing"), "unmatched")

    def test_missing_source_context_and_source_only_are_retained(self):
        forward, reverse = self.run_links([], [site(), site("missing-address", comparable=False)])
        self.assertTrue(all(r["status"] == "unmatched" for r in forward.values()))
        self.assertEqual(reverse["site"]["status"], "unmatched")
        self.assertEqual(reverse["missing-address"]["status"], "unresolved_before_comparison")

    def test_bad_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "orphan or duplicate"):
            self.run_links([edge("not-in-base")])


class ServiceControls(unittest.TestCase):
    def test_publication_date_programme_equipment_and_referral_are_not_onsite_dates(self):
        for scope in ("programme", "equipment_inventory", "referral", "planned", "pooled_report"):
            with self.subTest(scope=scope):
                self.assertFalse(dated_onsite(claim("a", scope, observation="2026-11-01")))
        self.assertFalse(dated_onsite(claim("a", "onsite_delivery")))
        self.assertFalse(dated_onsite(claim("b", "onsite_delivery", observation="2026-11-01", premise=None)))

    def test_relocation_and_renewal_do_not_create_false_conflict(self):
        yes = claim("a", "onsite_delivery", start="2026-01-01", end="2026-06-30")
        renewed = claim("b", "onsite_exclusion", start="2026-07-01")
        other_building = claim("c", "onsite_exclusion", observation="2026-02-01", premise="other-branch")
        self.assertTrue(dated_onsite(yes))
        self.assertEqual(claim_conflicts([yes, renewed, other_building]), set())

    def test_dated_overlapping_opposite_claims_are_conflicts(self):
        yes = claim("a", "onsite_delivery", start="2026-01-01", end="2026-09-30")
        no = claim("b", "onsite_exclusion", observation="2026-08-03")
        undated = claim("c", "onsite_exclusion")
        self.assertEqual(claim_conflicts([yes, no, undated]), {("site", "dialysis")})

    def test_map_display_roles_do_not_establish_second_physical_source(self):
        witnesses = [{"family": "issuer", "locator": "printed address", "role": "civic_address"},
                     {"family": "map", "locator": "map link", "role": "display_point"}]
        batch = EvidenceBatch("control", {}, [record()], [site(witnesses=witnesses, reviewed=True)])
        with self.assertRaisesRegex(ValueError, "independent premises review"):
            batch.validate({})

    def test_same_origin_and_cross_method_reuse_are_counted_separately(self):
        first = EvidenceBatch("first", {}, [record("r1")], [site(source="r1")],
                              [claim("a", "programme", source="r1")])
        same_origin = EvidenceBatch("repeat", {}, [record("r2")], [],
                                    [claim("b", "programme", premise="site", source="r2")])
        reused = EvidenceBatch("reused", {}, first.records, first.premises, first.claims)
        totals = source_counts([first, same_origin, reused])
        self.assertEqual(totals["source_records"], 2)
        self.assertEqual(totals["premises_hypotheses"], 1)
        self.assertEqual(totals["claims"], 2)
        self.assertEqual(totals["additional_claims_in_same_origin_record_scope"], 1)
        self.assertEqual(totals["independently_supported_physical_sites"], 0)


if __name__ == "__main__":
    unittest.main()
