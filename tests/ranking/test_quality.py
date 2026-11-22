import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.ranking import search_facilities
from app.ranking.quality import (
    QUALITY_SETTING, apply_overlay, load_overlay, overlay_from_env, search_with_quality,
)

FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "search.json"
FIELDS = ["facility_id", "point_status", "latitude", "longitude", "location_method", "location_precision",
          "location_checks", "duplicate_group", "evidence_dialysis", "evidence_mri", "evidence_trauma_care"]


def campus(facility_id, latitude, longitude, **fields):
    return dict({
        "facility_id": facility_id,
        "name": "Synthetic Hospital " + facility_id,
        "city": "Sample City",
        "state": "Sample State",
        "pin": "001234",
        "latitude": latitude,
        "longitude": longitude,
        "procedures": "The clinic performs dialysis.",
    }, **fields)


def write_overlay(rows):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return handle.name


ORIGIN = {"latitude": 0.0, "longitude": 0.0}


class OffByDefaultTests(unittest.TestCase):
    def test_no_overlay_matches_search_facilities_on_the_shared_fixture(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(
                    search_with_quality(**case["query"], facilities=fixture["facilities"], overlay=None),
                    search_facilities(**case["query"], facilities=fixture["facilities"]),
                )

    def test_setting_unset_means_no_overlay(self):
        self.assertIsNone(overlay_from_env({}))
        self.assertIsNone(overlay_from_env({QUALITY_SETTING: "  "}))

    def test_setting_names_an_overlay_file(self):
        path = write_overlay([{"facility_id": "a", "point_status": "unplaced", "location_checks": "far_from_pin_area"}])
        self.assertEqual(overlay_from_env({QUALITY_SETTING: path})["a"]["point_status"], "unplaced")


class OverlayTests(unittest.TestCase):
    def test_repaired_point_is_used_and_labelled_as_estimated(self):
        rows = [campus("far", 5.0, 5.0), campus("mid", 0.0, 0.2)]
        overlay = load_overlay(write_overlay([{
            "facility_id": "far", "point_status": "repaired", "latitude": "0.0", "longitude": "0.05",
            "location_method": "name_match_osm", "location_precision": "building"}]))
        response = search_with_quality("dialysis", ORIGIN, facilities=rows, overlay=overlay)
        first = response["direct_results"][0]
        self.assertEqual(first["facility_id"], "far")
        self.assertAlmostEqual(first["distance_km"], 5.56, places=1)
        self.assertEqual(first["location_estimate"], {"precision": "building", "method": "name_match_osm"})
        self.assertNotIn("location_estimate", response["direct_results"][1])

    def test_unplaced_row_is_not_ranked_but_named_for_its_pin(self):
        rows = [campus("bad", 0.0, 0.01), campus("good", 0.0, 0.3)]
        overlay = load_overlay(write_overlay([{
            "facility_id": "bad", "point_status": "unplaced", "location_checks": "far_from_pin_area|far_from_town"}]))
        by_point = search_with_quality("dialysis", ORIGIN, facilities=rows, overlay=overlay)
        self.assertEqual([card["facility_id"] for card in by_point["direct_results"]], ["good"])
        self.assertEqual(by_point["unplaced_matches"], [])
        by_pin = search_with_quality("dialysis", {"pin": "001234"}, facilities=rows, overlay=overlay)
        self.assertEqual([card["facility_id"] for card in by_pin["direct_results"]], ["good"])
        lead = by_pin["unplaced_matches"][0]
        self.assertEqual(lead["facility_id"], "bad")
        self.assertIsNone(lead["distance_km"])
        self.assertIsNone(lead["location"]["latitude"])
        self.assertEqual(lead["location_warning"], ["far_from_pin_area", "far_from_town"])

    def test_unplaced_rows_do_not_move_the_pin_origin(self):
        rows = [campus("bad", 9.0, 9.0), campus("good", 0.0, 0.0)]
        overlay = load_overlay(write_overlay([{"facility_id": "bad", "point_status": "unplaced"}]))
        response = search_with_quality("dialysis", {"pin": "001234"}, facilities=rows, overlay=overlay)
        self.assertEqual(response["direct_results"][0]["distance_km"], 0.0)

    def test_excluded_row_is_left_out(self):
        rows = [campus("broken", 0.0, 0.0), campus("ok", 0.0, 0.1)]
        overlay = load_overlay(write_overlay([{"facility_id": "broken", "point_status": "excluded"}]))
        response = search_with_quality("dialysis", ORIGIN, facilities=rows, overlay=overlay)
        self.assertEqual([card["facility_id"] for card in response["direct_results"]], ["ok"])

    def test_duplicates_collapse_to_one_card_with_also_listed_as(self):
        rows = [campus("x1", 0.0, 0.10, name="Sri Clinic"), campus("x2", 0.0, 0.11, name="Shree Clinic"),
                campus("y", 0.0, 0.2)]
        overlay = load_overlay(write_overlay([
            {"facility_id": "x1", "duplicate_group": "g1"}, {"facility_id": "x2", "duplicate_group": "g1"}]))
        response = search_with_quality("dialysis", ORIGIN, facilities=rows, overlay=overlay)
        ids = [card["facility_id"] for card in response["direct_results"]]
        self.assertEqual(ids, ["x1", "y"])
        self.assertEqual(response["direct_results"][0]["also_listed_as"], ["Shree Clinic"])
        self.assertNotIn("also_listed_as", response["direct_results"][1])

    def test_evidence_badge_never_filters_or_reorders(self):
        rows = [campus("near", 0.0, 0.1), campus("far", 0.0, 0.2)]
        overlay = load_overlay(write_overlay([{"facility_id": "far", "evidence_dialysis": "dated_service"}]))
        response = search_with_quality("dialysis", ORIGIN, facilities=rows, overlay=overlay)
        self.assertEqual([card["facility_id"] for card in response["direct_results"]], ["near", "far"])
        self.assertIsNone(response["direct_results"][0]["evidence_level"])
        self.assertEqual(response["direct_results"][1]["evidence_level"]["level"], "dated_service")

    def test_overlay_does_not_change_the_input_rows(self):
        rows = [campus("a", 5.0, 5.0)]
        overlay = {"a": {"point_status": "repaired", "point": (0.0, 0.0), "precision": "city", "method": "m"}}
        apply_overlay(rows, overlay)
        self.assertEqual(rows[0]["latitude"], 5.0)

    def test_malformed_overlay_is_rejected(self):
        for bad in ({"facility_id": "", "point_status": ""},
                    {"facility_id": "a", "point_status": "moved"},
                    {"facility_id": "a", "point_status": "repaired", "latitude": "x", "longitude": "1",
                     "location_precision": "building"},
                    {"facility_id": "a", "point_status": "repaired", "latitude": "1", "longitude": "1",
                     "location_precision": "street"}):
            with self.subTest(row=bad), self.assertRaises(ValueError):
                load_overlay(write_overlay([bad]))

    def test_unknown_codes_and_levels_are_ignored(self):
        overlay = load_overlay(write_overlay([{"facility_id": "a", "location_checks": "planted|shared_point",
                                               "evidence_mri": "confirmed"}]))
        self.assertEqual(overlay["a"], {"point_status": None, "location_checks": ["shared_point"]})


if __name__ == "__main__":
    unittest.main()
