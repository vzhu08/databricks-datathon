import unittest
from unittest.mock import patch

from research.matching.address_search import search_result
from research.matching.consensus import Candidate, Reference
from research.matching.normalize import tokens


class AddressSearchTests(unittest.TestCase):
    def setUp(self):
        self.row = {"name": "Rainbird Hospital", "address_city": "Pune", "address_zipOrPostcode": "411001",
                    "address_line1": "Asterleaf Complex", "source_urls": ""}
        self.original = {"branch_evidence": {}, "state_for_matching": "Maharashtra",
                         "original_point": {"latitude": 18.5, "longitude": 73.85}}

    def candidate(self, key, addr=None, longitude=73.85, family="osm", votes=True):
        point = (18.5, longitude) if longitude is not None else None
        ref = Reference(key, self.row["name"], family, key, key, family, point, addr, "411001", "pune",
                        "maharashtra", tuple(tokens(self.row["name"])), None)
        return Candidate(ref, strength=2, plausible_branch=True, votes=votes)

    def decide(self, *candidates, registry=False, providers=None):
        return search_result(self.row, self.original, candidates, {}, registry, providers or {})

    def test_named_complex_agrees_despite_far_apart_pins(self):
        result = self.decide(self.candidate("a", "Asterleaf Complex, Pune"),
                             self.candidate("b", "Asterleaf Complex, Pune", 73.90))
        self.assertEqual(result["status"], "corroborated_address")
        self.assertEqual(len(result["witnesses"]), 2)
        self.assertNotIn("coordinates", result)

    def test_plot_street_and_directed_landmark(self):
        for original, ref in [("Plot No. 31, Merlin Road", "31, Merlin Rd, Pune"),
                              ("Opp. Wildflower Mandir", "Opposite Wildflower Mandir, Pune")]:
            with self.subTest(original=original):
                self.row["address_line1"] = original
                self.assertEqual(self.decide(self.candidate("a", ref, None))["status"], "corroborated_address")
        self.assertEqual(self.decide(self.candidate("a", "Behind Wildflower Mandir", None))["status"],
                         "no_new_result")

    def test_equally_fitting_different_plot_numbers_only_support_area(self):
        result = self.decide(self.candidate("a", "Plot 1, Asterleaf Complex"),
                             self.candidate("b", "Plot 2, Asterleaf Complex", 73.854))
        self.assertEqual(result["status"], "nearby_name_search")
        self.assertEqual(len(result["alternatives"]), 2)
        self.assertTrue(result["exact_location_uncertain"])

    def test_locality_prefix_and_street_number_conflict(self):
        self.row["address_line1"] = "Plot 31, Umrer Road, Reshim Baug"
        self.assertEqual(self.decide(self.candidate("a", "31, Reshimbag Umrer Road"))["status"],
                         "corroborated_address")
        self.row["address_line1"] = "Plot 31, 1st Merlin Road, Rainwood Plaza"
        result = self.decide(self.candidate("a", "31, 2nd Merlin Road, Rainwood Plaza", None))
        self.assertEqual(result["status"], "no_new_result")

    def test_generic_building_or_area_only_cannot_verify_address(self):
        for generic in ("Commercial Complex", "411001, Pune", "Near Bus Stand", "Rainbird Hospital"):
            with self.subTest(generic=generic):
                self.row["address_line1"] = generic
                self.assertEqual(self.decide(self.candidate("a", generic, None))["status"], "no_new_result")

    def test_overture_and_facebook_reuse_cannot_supply_witness(self):
        item = self.candidate("overture-place:alpha", "Asterleaf Complex", 73.853, "overture")
        for types, urls in [('["overture"]', ''), ('[]', 'https://www.facebook.com/example')]:
            with self.subTest(types=types):
                self.row.update(source_types=types, source_urls=urls)
                result = self.decide(item, providers={item.reference.id: {"meta"}})
                self.assertEqual(result["status"], "no_new_result")

    def test_diameter_is_strict_pairwise_and_keeps_all_alternatives(self):
        left, right = self.candidate("a", longitude=73.845), self.candidate("b", longitude=73.855)
        self.assertEqual(self.decide(left, right)["status"], "no_new_result")
        with patch("research.matching.address_search.haversine_m", return_value=1000.0):
            self.assertEqual(self.decide(left)["status"], "no_new_result")
        with patch("research.matching.address_search.haversine_m", return_value=999.99):
            result = self.decide(left)
            self.assertEqual(result["status"], "nearby_name_search")
            self.assertEqual(result["external_point_count"], 1)
        self.assertEqual(self.decide(left, self.candidate("unknown", longitude=None))["status"], "no_new_result")
        self.assertEqual(self.decide(left, registry=True)["status"], "no_new_result")

    def test_named_far_rival_and_missing_or_duplicate_points(self):
        a = self.candidate("a", longitude=73.854)
        self.assertEqual(self.decide(a, self.candidate("b", longitude=74.0))["status"], "no_new_result")
        self.assertEqual(self.decide(self.candidate("a"), self.candidate("b"))["status"], "no_new_result")
        self.assertEqual(self.decide(self.candidate("a", longitude=None))["status"], "no_new_result")

    def test_both_external_points_are_retained_and_copied_rival_is_still_bounded(self):
        a, b = self.candidate("a", longitude=73.852), self.candidate("b", longitude=73.854)
        result = self.decide(a, b)
        self.assertEqual(result["external_point_count"], 2)
        self.assertEqual({x["reference"] for x in result["alternatives"]}, {"a", "b"})
        self.assertEqual(self.decide(a, b, self.candidate("duplicate", longitude=74.0, votes=False))["status"],
                         "no_new_result")
