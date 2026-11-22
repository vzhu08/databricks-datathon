import unittest

from research.matching.consensus import Candidate, Reference, RegistryBranches, address_key, classify, map_candidate
from research.matching.normalize import tokens


def candidate(family, record, point=(13.01, 80.19), address=None, *, strength=3, conflict=False,
              basis=None, plausible=False):
    name = "Lotus Memorial Hospital"
    pin = "600016"
    city = "chennai"
    reference = Reference(record, name, family, record, "example", "synthetic", point,
                          address, pin, city, "tamil nadu", tuple(tokens(name)),
                          address_key(address, pin, city))
    return Candidate(reference, strength, contradicts_base=conflict, location_basis=basis,
                     plausible_branch=plausible)


class CampusConsensusTests(unittest.TestCase):
    def test_five_families_outvote_one_and_keep_dissent(self):
        agreeing = [candidate(f"family-{i}", f"record-{i}") for i in range(5)]
        dissent = candidate("other", "different-site", point=(13.02, 80.19), strength=2)
        result = classify(agreeing + [dissent])
        self.assertEqual(result["category"], "high")
        self.assertEqual(len(result["supporting_families"]), 5)
        self.assertEqual(result["dissenting_families"], ["other"])

    def test_missing_house_number_and_duplicate_feed(self):
        records = [candidate("map", "original", address="No 5/105, Defence Colony Road"),
                   candidate("map", "duplicate"), candidate("directory", "independent")]
        result = classify(records)
        self.assertEqual(result["category"], "high")
        self.assertEqual(result["supporting_families"], ["directory", "map"])
        self.assertEqual(classify(records[:2])["category"], "single_source")

    def test_text_address_can_link_a_record_without_coordinates(self):
        records = [candidate("map", "original", address="No 5/105, Defence Colony Road"),
                   candidate("directory", "licence", point=None, address="5/105 Defence Colony Road")]
        self.assertEqual(classify(records)["category"], "high")

    def test_separate_sites_and_split_sources_are_not_votes(self):
        records = [candidate("map", "first"),
                   candidate("map", "other", point=(13.02, 80.19)),
                   candidate("directory", "independent")]
        result = classify(records)
        self.assertEqual(result["category"], "contested")
        self.assertEqual(result["split_families"], ["map"])
        self.assertEqual(result["supporting_families"], ["directory"])
        self.assertEqual(classify([records[0], candidate("directory", "different",
                                                        point=(13.02, 80.19))])["category"], "contested")

    def test_agreement_on_an_incompatible_site_stays_contested(self):
        records = [candidate("map", "first", strength=1, conflict=True),
                   candidate("directory", "second", strength=1, conflict=True)]
        self.assertEqual(classify(records)["category"], "contested")
        self.assertEqual(classify([], original_conflict=True)["category"], "unmatched")

    def test_one_map_listing_can_locate_the_campus(self):
        map_record = candidate("osm", "mapped").reference
        signals = {"name_level": "strong", "non_hospital_type": False, "pin": "agree",
                   "place": "unknown", "state": "agree", "address": "unknown",
                   "distance_band": "unknown", "external_source_key": "hot_osm_health"}
        pair = {"signals": signals, "flags": [], "pre_cut_rank": 1}
        result = classify([map_candidate(pair, map_record)])["directory_location"]
        self.assertEqual(result["status"], "campus_located")
        self.assertEqual(result["basis"], "named_map_listing")
        signals["pin"] = "unknown"
        self.assertEqual(classify([map_candidate(pair, map_record)])["directory_location"]["status"],
                         "unresolved")

    def test_branch_address_agreement_accepts_a_campus_without_a_pinpoint(self):
        records = [candidate("directory", "one", point=None, address="5 Defence Colony Road", plausible=True),
                   candidate("registry", "two", point=None, address="5 Defence Colony Rd.", plausible=True)]
        result = classify(records)["directory_location"]
        self.assertEqual(result["status"], "campus_located")
        self.assertEqual(result["basis"], "matching_branch_address")
        self.assertIsNone(result["coordinates"])

    def test_only_one_competing_family_can_be_outvoted(self):
        first = candidate("osm", "map", basis="named_map_listing", plausible=True)
        corroborating = candidate("registry", "registry", plausible=True)
        rival = candidate("overture", "rival", point=(13.02, 80.19), plausible=True)
        result = classify([first, corroborating, rival])["directory_location"]
        self.assertEqual(result["status"], "campus_located")
        self.assertEqual(result["competing_families"], ["overture"])

        copy = candidate("osm", "second-map-export", plausible=True)
        split = candidate("osm", "alternate-map-branch", point=(13.02, 80.19), plausible=True)
        second_rival = candidate("insurer", "another-rival", point=(13.02, 80.19), plausible=True)
        for records in ([first, copy, rival], [first, corroborating, split],
                        [first, corroborating, rival, second_rival]):
            self.assertEqual(classify(records)["directory_location"]["status"], "area_located")

    def test_distinct_civic_addresses_can_compete_within_150_metres(self):
        records = [candidate("osm", "map", address="5 Defence Colony Road",
                             basis="named_map_listing", plausible=True),
                   candidate("registry", "rival", point=(13.0101, 80.19), plausible=True,
                             address="5 Gandhi Nagar Road")]
        self.assertEqual(classify(records)["directory_location"]["status"], "area_located")

    def test_supplemental_registry_rival_counts_with_its_existing_family(self):
        first = candidate("osm", "map", basis="named_map_listing", plausible=True)
        corroborating = candidate("overture", "other-map", plausible=True)
        supplement = RegistryBranches(set(), {"map"})
        result = classify([first], supplement=supplement)["directory_location"]
        self.assertEqual(result["status"], "area_located")
        result = classify([first, corroborating], supplement=supplement)["directory_location"]
        self.assertEqual(result["status"], "campus_located")
        self.assertEqual(result["competing_families"], ["nhp"])
        registry = candidate("nhp", "same-registry", plausible=True)
        result = classify([first, registry], supplement=supplement)["directory_location"]
        self.assertEqual(result["status"], "area_located")

    def test_original_area_is_preserved_without_a_candidate(self):
        original = {"input_problems": [], "branch_evidence": {
            "postal_state_disagreement": False, "pins": ["600016"], "postal_pins": ["600016"],
            "localities": [], "cities": [], "districts": [],
        }}
        self.assertEqual(classify([], original=original)["directory_location"],
                         {"status": "area_located", "basis": "pin", "area": "600016"})
        original["input_problems"].append("state_disagrees_with_pin")
        self.assertEqual(classify([], original=original, original_conflict=True)["directory_location"]["status"],
                         "unresolved")


if __name__ == "__main__":
    unittest.main()
