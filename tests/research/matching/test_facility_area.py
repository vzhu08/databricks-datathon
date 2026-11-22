from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import gzip
import json
import sqlite3
import unittest

from research.matching.consensus import Candidate, Reference
from research.matching.facility_area import RegistryIndex, area_counts, facility_area, listing, registry_listings


class FacilityAreaTests(unittest.TestCase):
    def setUp(self):
        self.row = {"name": "Rainbow Heron Hospital", "address_city": "Pune", "address_zipOrPostcode": "411001",
                    "address_line1": "Juniper Colony, Near Willow Gate", "source_types": "Overture"}
        self.original = {"branch_evidence": {}, "state_for_matching": "Maharashtra",
                         "original_point": {"latitude": 18.5, "longitude": 73.85}}

    def result(self, records=(), maps=(), signals=None):
        return facility_area(self.row, self.original, maps, signals or {}, {}, RegistryIndex(records))

    def authority(self, address="", pin=None, state="Maharashtra", name="Rainbow Heron Hospital"):
        return listing("operator", "operator.example/site", name, address, pin, state, "Pune")

    def map(self, key, point=(18.5, 73.85), family="osm"):
        return Candidate(Reference(key, self.row["name"], family, key, "row", "edition", point,
                                   "Juniper Colony", "411001", "pune", "maharashtra", (), None),
                         strength=2, plausible_branch=True)

    def test_operator_pin_locality_or_landmark_keeps_supported_value(self):
        for ref, basis in ((self.authority(pin="411001"), ("pin", "411001")),
                           (self.authority("Juniper Colony, Pune", "411009"), ("locality", "juniper colony")),
                           (self.authority("Opposite Willow Gate"), ("landmark", "willow gate"))):
            with self.subTest(basis=basis):
                decision = self.result([ref])
                witness, = decision["registry_or_operator"]
                self.assertEqual((witness["area_kind"], witness["area"]), basis)
                self.assertIsNone(decision["nearby_points"])

    def test_city_alone_wrong_branch_wrong_state_or_unrelated_entity(self):
        self.row["name"] += " - East"
        for ref in (self.authority("Pune"), self.authority(pin="411001", state="Kerala"),
                    self.authority(pin="411001", name="Rainbow Heron Hospital - West"),
                    self.authority(pin="411001", name="Rainbow Heron Dental Laboratory")):
            self.assertFalse(self.result([ref])["registry_or_operator"])

    def test_shared_map_and_identical_point_survive_coordinate_free_listing(self):
        r = self.result(maps=[self.map("overture-place:x", family="overture"), self.map("empty", None)])
        self.assertTrue(r["map_area"][0]["possible_shared_origin"])
        self.assertEqual(r["nearby_points"]["max_separation_m"], 0)
        self.assertEqual(len(r["nearby_points"]["alternatives"]), 1)
        self.assertTrue(r["nearby_points"]["exact_location_uncertain"])

    def test_farther_named_pin_allows_area_and_retains_uncertainty(self):
        r = self.result(maps=[self.map("near"), self.map("far", (18.51, 73.9))])
        self.assertEqual(len(r["map_area"]), 2)
        self.assertIsNone(r["nearby_points"])
        self.assertFalse(self.result(maps=[self.map("n")], signals={"n": {"non_hospital_type": True}})["map_area"])

    def test_city_marketing_suffix_with_distant_branch_and_tenant(self):
        self.row["name"] += ", Pune"
        base = self.map("overture-place:wetland", family="overture")
        local = replace(base, reference=replace(base.reference,
                        name="Rainbow Heron Hospital - Best Multispeciality Hospital in Pune"))
        other = replace(base, reference=replace(base.reference, id="other", name="Rainbow Heron Hospital",
                        city="nashik", address="Nashik", pin="422001", coordinates=(20.0, 73.8)))
        tenant = replace(base, reference=replace(base.reference, id="tenant", name="Rainbow Heron Dental"))
        result = self.result(maps=[other, tenant, local], signals={local.reference.id: {
            "premises": {"branch_qualifier_conflict": True}}})
        self.assertEqual([w["reference"] for w in result["nearby_points"]["alternatives"]], [local.reference.id])
        self.assertTrue(result["map_area"])

    def test_explicit_acronym_and_state_spelling(self):
        self.row["name"] = "Heron Institute of Medical Sciences (HIMS), Pune, Maharshtra"
        ref = self.authority(name="Heron Institute of Medical Sciences", pin="411001")
        self.assertTrue(self.result([ref])["registry_or_operator"])
        full = self.map("full")
        far = self.map("alias", (18.54, 73.85))
        far = replace(far, reference=replace(far.reference, name="HIMS Pune"))
        result = self.result(maps=[full, far])
        self.assertEqual(len(result["map_area"]), 2)
        self.assertIsNone(result["nearby_points"])

    def test_missing_vf_point_needs_different_external_families(self):
        self.original["original_point"] = {}
        first = self.map("a")
        second = self.map("b", (18.5, 73.851))
        self.assertIsNone(self.result(maps=[first, second])["nearby_points"])
        second = replace(second, reference=replace(second.reference, family="nhp"))
        self.assertTrue(self.result(maps=[first, second])["nearby_points"])
        self.original["original_point"] = {"latitude": 18.6, "longitude": 73.85}
        nearby = self.result(maps=[first, second])["nearby_points"]
        self.assertTrue(nearby["vf_point_disagrees"])
        self.assertIsNone(nearby["vf_point"])

    def test_adapters_and_national_overlap(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            official, nabh, operator = root / "nhp.gz", root / "nabh.sqlite", root / "operator.jsonl"
            with gzip.open(official, "wt") as stream:
                print(json.dumps(dict(official_locator="line:2", Hospital_Name=self.row["name"],
                                      Address_Original_First_Line="Juniper Colony", Pincode="411001",
                                      State="Maharashtra", Town="Pune")), file=stream)
            with closing(sqlite3.connect(nabh)) as db:
                db.execute("create table listings(listing_id, hco_name, address, pin_from_address)")
                db.execute("insert into listings values (1, ?, 'Juniper Colony, Pune, Maharashtra', '411001')",
                           (self.row["name"],))
                db.commit()
            operator.write_text(json.dumps({"operator_url": "https://operator.example/site", "name": self.row["name"],
                                            "state": "Maharashtra", "pin": "411001"}))
            area = self.result(registry_listings(official, nabh, [operator]), [self.map("x")])
            self.assertEqual({r["family"] for r in area["registry_or_operator"]}, {"nhp_official", "nabh", "operator"})
            decision = {"facility_area": area, "directory_location": {"status": "area_located"},
                        "address_search": {"status": "no_new_result"}}
            occurrence = {"state": "maharashtra", "retrieval_representative": "x"}
            counts = area_counts([occurrence, occurrence], {"x": decision})
            self.assertEqual(counts["mutually_exclusive"], {"registry_or_operator": 2})
            self.assertEqual(counts["overlapping"]["agreeing_points"], 2)
