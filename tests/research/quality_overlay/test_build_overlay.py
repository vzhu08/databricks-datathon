import unittest

from research.quality_overlay.build_overlay import build


def repair(facility_id, confidence, method, lat="1.5", lon="2.5", precision="building", trigger="record_integrity:far_from_pin_100km"):
    return {"facility_id": facility_id, "confidence": confidence, "method": method, "new_lat": lat, "new_lon": lon,
            "point_precision": precision, "trigger": trigger}


class BuildOverlayTests(unittest.TestCase):
    def test_rules_on_synthetic_rows(self):
        integrity = [
            {"facility_id": "broken", "families": "structure", "reasons": "name_missing"},
            {"facility_id": "low", "families": "location", "reasons": "far_from_pin_100km|far_from_city_50km"},
        ]
        repairs = [
            repair("moved", "high", "name_match_osm"),
            repair("kept", "medium", "keep_point"),
            repair("low", "low", "pin_centroid", precision="pin_area"),
            repair("unres", "none", "unresolved", lat="", lon="", trigger="footprint:shared_coordinates"),
            repair("broken", "high", "name_match_osm"),
        ]
        duplicates = [{"vf_id": "d1", "cluster_id": "7", "cluster_confidence": "high"},
                      {"vf_id": "d2", "cluster_id": "7", "cluster_confidence": "high"},
                      {"vf_id": "d3", "cluster_id": "8", "cluster_confidence": "low"}]
        chains = [{"facility_id": "c2", "role": "duplicate_of_campus_record", "campus_record_id": "c1", "campus_id": "fortis-03"}]
        evidence = [{"facility_id": "moved", "dialysis_ladder": "Dated independent service evidence",
                     "mri_ladder": "Not claimed", "trauma_ladder": "Self-reported only"}]
        rows = {r["facility_id"]: r for r in build(integrity, repairs, duplicates, chains, evidence)}

        self.assertEqual(rows["broken"]["point_status"], "excluded")
        self.assertEqual((rows["moved"]["point_status"], rows["moved"]["latitude"], rows["moved"]["location_precision"]),
                         ("repaired", "1.5", "building"))
        self.assertEqual(rows["kept"]["point_status"], "")
        self.assertEqual((rows["low"]["point_status"], rows["low"]["location_checks"]),
                         ("unplaced", "far_from_pin_area|far_from_town"))
        self.assertEqual((rows["unres"]["point_status"], rows["unres"]["location_checks"]), ("unplaced", "shared_point"))
        self.assertEqual(rows["d1"]["duplicate_group"], rows["d2"]["duplicate_group"])
        self.assertNotIn("d3", rows)
        self.assertEqual(rows["c1"]["duplicate_group"], rows["c2"]["duplicate_group"])
        self.assertEqual((rows["moved"]["evidence_dialysis"], rows["moved"]["evidence_mri"], rows["moved"]["evidence_trauma_care"]),
                         ("dated_service", "", "self_reported"))


if __name__ == "__main__":
    unittest.main()
