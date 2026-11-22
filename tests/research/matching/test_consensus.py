import unittest

from research.matching.consensus import Candidate, Reference, address_key, classify
from research.matching.normalize import tokens


def candidate(family, record, point=(13.01, 80.19), address=None, *, strength=3, conflict=False):
    name = "Lotus Memorial Hospital"
    pin = "600016"
    city = "chennai"
    reference = Reference(record, name, family, record, "example", "synthetic", point,
                          address, pin, city, "tamil nadu", tuple(tokens(name)),
                          address_key(address, pin, city))
    return Candidate(reference, strength, contradicts_base=conflict)


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


if __name__ == "__main__":
    unittest.main()
