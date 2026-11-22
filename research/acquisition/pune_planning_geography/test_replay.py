"""Synthetic coverage for the two-stage public geography recipe."""

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from . import match, rank_hospitals as rank


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def feature(geometry, **properties):
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def point(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def rectangle(left, bottom, right, top):
    return {
        "type": "Polygon",
        "coordinates": [[[left, bottom], [right, bottom], [right, top], [left, top], [left, bottom]]],
    }


class PlanningGeographyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.boundaries = self.root / "districts.geojson"
        self.boundaries.write_text(json.dumps(collection([
            feature(rectangle(0, 0, 1, 1), shapeID=rank.PUNE_ID, shapeName="Fixture district"),
            feature(rectangle(0.9, 0.9, 1.1, 1.1), shapeID="fixture-other", shapeName="Other fixture district"),
        ])), encoding="utf-8")
        self.osm = self.root / "health.zip"
        nightingale = {"amenity": "hospital", "name": "Nightingale Hospital"}
        with zipfile.ZipFile(self.osm, "w") as archive:
            archive.writestr("health_facilities.geojson", json.dumps(collection([
                feature(point(0.1, 0.1), id="node/1", **nightingale),
                feature(rectangle(0.0999, 0.0999, 0.1001, 0.1001), id="way/2", **nightingale),
                feature(point(0.1, 0.1), id="node/1", **nightingale),
                feature(point(0.12, 0.1), id="node/3", amenity="hospital", name="Iris Hospital"),
                feature(point(0.12, 0.12), id="node/4", healthcare="hospital", name="Juniper Hospital"),
                feature(point(0.95, 0.95), id="node/5", amenity="hospital", name="Overlapping Hospital"),
                feature(point(0.1, 0.2), id="node/6", amenity="hospital", name="Unnamed"),
                feature(point(0.2, 0.2), id="node/7", amenity="hospital", name="Birch Hospital"),
                feature(point(0.3, 0.4), id="node/8", amenity="hospital", name="Cypress Hospital"),
            ])))
        self.nhp = self.root / "directory.csv"
        with self.nhp.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Sr_No", "Hospital_Name", "Location_Coordinates", "State", "District"])
            writer.writerows([
                (1, "Nightingale Hospital", "0.1,0.1", "Maharashtra", "Pune"),
                (2, "Iris Hospital", "0.1,0.12", "Maharashtra", "Pune"),
                (3, "Juniper Hospital", "0.12,0.12", "Maharashtra", "Pune"),
                (4, "Willow Hospital", "0.12,0.12", "Maharashtra", "Pune"),
                (5, "Overlapping Hospital", "0.95,0.95", "Maharashtra", "Pune"),
                (6, "Other Region Hospital", "0.3,0.2", "Maharashtra", "Other district"),
                (7, "Birch Hospital", "0.2,0.2", "Maharashtra", "Pune"),
                (8, "Birch North Hospital", "0.2,0.201", "Maharashtra", "Pune"),
                (9, "Cypress Hospital", "0.4,0.301", "Maharashtra", "Pune"),
            ])

    def extract(self, output):
        with patch.multiple(rank, OSM_SHA256=rank.sha256(self.osm), DISTRICT_SHA256=rank.sha256(self.boundaries)):
            return rank.run(self.osm, self.boundaries, output)

    def test_extract_and_screen(self):
        intermediate = self.root / "osm"
        report = self.extract(intermediate)
        self.assertEqual(report["counts"]["repeated_osm_object_ids"], 1)
        self.assertEqual(report["counts"]["same_name_geometry_duplicates_collapsed"], 1)
        self.assertEqual(report["counts"]["mapped_sites_without_unique_district"], 1)
        roster = intermediate / "pune-full.storm-roster-v1.json"
        self.assertIn(b"\r\n", roster.read_bytes())
        replay_dir = self.root / "osm-replay"
        self.assertEqual(self.extract(replay_dir)["pune_roster_sha256"], report["pune_roster_sha256"])
        data = json.loads(roster.read_bytes())
        self.assertEqual(
            {row["source_id"] for row in data["facilities"]},
            {"way/2", "node/3", "node/4", "node/7", "node/8"},
        )

        destination = self.root / "agreement"
        with patch.multiple(match, ROSTER_SHA=rank.sha256(roster), NHP_SHA=rank.sha256(self.nhp),
                            DISTRICT_SHA256=rank.sha256(self.boundaries)):
            result = match.run(roster, self.boundaries, self.nhp, destination)
        self.assertEqual(result["counts"]["matched"], 2)
        self.assertEqual(result["counts"]["shared_source_coordinate"], 1)
        self.assertEqual(result["counts"]["nearby_variant_name_rival"], 1)
        self.assertEqual(result["counts"]["point_difference_exceeds_threshold"], 1)
        self.assertEqual(result["counts"]["ambiguous_pune_district_boundary"], 1)
        self.assertEqual(result["counts"]["pune_nhp_name_point_groups_with_publisher_geography_conflict"], 1)
        self.assertEqual(result["selected_sites"], 2)
        final = destination / "pune-planning-agreement-roster.storm-roster-v1.json"
        self.assertNotIn(b"\r\n", final.read_bytes())
        selected = json.loads(final.read_bytes())["facilities"]
        self.assertEqual([(row["planning_id"], row["source_id"]) for row in selected],
                         [("C01", "node/3"), ("C02", "way/2")])

    def test_rank_rejects_changed_input_before_writing(self):
        destination = self.root / "osm"
        with self.assertRaisesRegex(ValueError, "expected SHA-256"):
            rank.run(self.osm, self.boundaries, destination)
        self.assertFalse(destination.exists())

    def test_match_rejects_changed_intermediate_before_writing(self):
        destination = self.root / "agreement"
        roster = self.root / "roster.json"
        roster.write_text("{}", encoding="utf-8")
        with patch.multiple(match, NHP_SHA=rank.sha256(self.nhp), DISTRICT_SHA256=rank.sha256(self.boundaries)):
            with self.assertRaisesRegex(ValueError, "roster.json: expected SHA-256"):
                match.run(roster, self.boundaries, self.nhp, destination)
        self.assertFalse(destination.exists())
