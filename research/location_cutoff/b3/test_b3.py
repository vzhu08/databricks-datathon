"""Synthetic regression checks for coarse precision and D's frozen selection."""

import unittest

from . import audit, core, feeds


def original(**kwargs):
    e = {"pins": [], "postal_pins": [], "localities": [], "cities": [], "districts": [],
         "postal_state_disagreement": False}
    e.update(kwargs)
    return {"branch_evidence": e, "input_problems": []}


class Areas(unittest.TestCase):
    def test_conflicting_pin_and_state_withholds_area(self):
        value = original(pins=["123456"], postal_pins=["123456"], cities=["sample city"])
        value["input_problems"].append("state_disagrees_with_pin")
        self.assertIsNone(core.fallback_area(value))

    def test_postal_area_stays_postal(self):
        value = original(pins=["123456"], postal_pins=["123456"], cities=["sample city"])
        projected = core.area_projection({"status": "area_located", "basis": "pin", "area": "123456"}, value)
        self.assertEqual(projected["precision"], "postal_area")
        self.assertEqual(projected["evidence"]["families"], ["VF original", "India Post v0"])

    def test_city_only_without_locality(self):
        p = core.area_projection({"status": "area_located", "basis": "city", "area": "sample city"},
                                 original(cities=["sample city"]))
        self.assertEqual(p["precision"], "city")
        self.assertNotIn("coordinates", p)

    def test_frozen_area_mismatch_requires_review(self):
        with self.assertRaisesRegex(ValueError, "area witness did not reproduce"):
            core.area_projection({"status": "area_located", "basis": "district", "area": "sample district"},
                                 original(cities=["sample city"]))

    def test_unknown_stays_unknown(self):
        p = core.area_projection({"status": "unresolved", "basis": "insufficient"}, original())
        self.assertEqual((p["precision"], p["label"], p["evidence"]), ("unknown", None, None))

    def test_campus_classification_has_separate_coarse_projection(self):
        p = core.area_projection({"status": "campus_located", "basis": "named_map_listing"},
                                 original(localities=["sample locality"], cities=["sample city"]))
        self.assertEqual(p["precision"], "locality")
        self.assertNotIn("coordinates", p)


class BlindSampling(unittest.TestCase):
    def test_hmac_domains_are_distinct(self):
        secret = b"fictional-token"
        self.assertEqual(audit.token(secret, "original_occurrence", "test"), audit.token(secret, "original_occurrence", "test"))
        self.assertNotEqual(audit.token(secret, "original_occurrence", "test"), audit.token(secret, "payload_group", "test"))

    def test_identical_payloads_and_shortage(self):
        rows = [{"stratum": "chain", "occurrence_token": k, "payload_group_token": p} for k, p in
                (("first", "same"), ("second", "same"), ("third", "distinct"))]
        rows.append({"stratum": "unknown", "occurrence_token": "unknown", "payload_group_token": "unknown"})
        chosen, summary = audit.selection(rows)
        self.assertEqual(len(chosen["chain"]), 2)
        self.assertEqual(summary["chain"], {"original_occurrences": 3, "distinct_payload_groups": 2,
                                            "selected": 2, "shortage": 18})
        self.assertEqual(summary["rural_or_unnamed"]["shortage"], 20)
        self.assertEqual(summary["unknown"]["selected"], 0)
        self.assertEqual(audit.selection(list(reversed(rows)))[0], chosen)


class LeadOverlap(unittest.TestCase):
    def test_geometric_origin_and_rural_union_only_counts_keys_once(self):
        frame = {"both": {"baseline_directory_status": "area_located"},
                 "rural": {"baseline_directory_status": "area_located"},
                 "outside_cohort": {"baseline_directory_status": "campus_located"}}
        geo = {"both": {"interior": True, "any_building_interior": True},
               "rural": {"interior": False, "any_building_interior": False}}
        value, keys = feeds.overlap(frame, geo, {"both", "rural"})
        self.assertEqual(keys, {"both", "rural"})
        self.assertEqual(value["unique_originals_with_at_least_one_of_these_flags"], 2)
        self.assertEqual(sum(value["candidate_flags_by_exact_combination"].values()), 2)
        self.assertIsNone(value["outside_joined_feeds_overlap"])


if __name__ == "__main__":
    unittest.main()
