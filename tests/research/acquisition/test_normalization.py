import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from shapely.geometry import Point, shape

from research.acquisition.common import AcquisitionError, ROOT, canonical, read_json, validate
from research.acquisition.parsers import coordinates, load_features, make_batch, normalize, resolve_nhp_landing
from fixtures import feature, geojson, landing, osm_archive, snapshot


class NormalizationTests(unittest.TestCase):
    def test_exact_duplicates_conflicting_ids_and_same_name_campuses(self):
        one = feature(addr_full="1 Example Road")
        conflicting = feature(addr_full="2 Example Road")
        other_id = feature(identifier="way/1", addr_full="3 Example Road")
        batch, report = make_batch([one, copy.deepcopy(one), conflicting, other_id], "health.geojson", snapshot(), "osm")
        validate(batch)
        self.assertEqual(3, len(batch["external_facilities"]))
        self.assertEqual(1, report["exact_duplicates_removed"])
        self.assertEqual(1, report["conflicting_source_identifiers"])
        self.assertEqual(2, report["conflicting_variants"])
        self.assertEqual(2, len(batch["review_queue"]))
        self.assertEqual(2, report["repeated_identifier_rows"])
        self.assertEqual(3, len({r["address_original"] for r in batch["external_facilities"]}))
        self.assertTrue(all(r["record_locator"].startswith("zip:health.geojson#/features/") for r in batch["external_facilities"]))

    def test_retrieval_clock_is_not_record_identity(self):
        s = snapshot()
        first, _ = make_batch([feature()], None, s, "osm")
        s2 = dict(s, retrieved_at="2024-01-01T00:00:00Z")
        second, _ = make_batch([feature()], None, s2, "osm")
        self.assertEqual(first["external_facilities"], second["external_facilities"])

    def test_non_ascii_originals_and_absent_native_names(self):
        f = feature(name="  ÉXAMPLE अस्पताल  ", addr_full="住所  例")
        r = normalize(f, "s:1", "osm", "raw#/features/0")
        self.assertEqual("  ÉXAMPLE अस्पताल  ", r["name_original"])
        self.assertEqual("éxample अस्पताल", r["name_normalized"])
        self.assertEqual("住所  例", r["address_original"])
        for absent in (None, "", "   "):
            r = normalize(feature(name=absent, name_latin="Translation"), "s:1", "osm", "raw#/features/0")
            self.assertIsNone(r["name_original"])
            self.assertIsNone(r["name_normalized"])
            self.assertIn("name_missing", r["quality_flags"])

    def test_nhp_sentinels_pin_text_unknown_specialty(self):
        f = feature("nhp", identifier="1", Hospital_Name="0", Hospital_Care_Type="0", Town="0", District="District only")
        r = normalize(f, "s:1", "nhp", "raw#/features/0")
        self.assertEqual("001234", r["pin"])
        self.assertIsNone(r["name_original"])
        self.assertIsNone(r["city"])
        self.assertEqual("unknown", r["facility_type"])
        self.assertIn("specialty_unknown", r["quality_flags"])
        for bad in ("0", "12345", " 123456", "123456.0", "१२३४५६"):
            f["properties"]["Pincode"] = bad
            r = normalize(f, "s:1", "nhp", "raw#/features/0")
            self.assertIsNone(r["pin"])
            self.assertIn("pin_invalid", r["quality_flags"])

    def test_health_types_and_nhp_fields_survive(self):
        for kind in ("pharmacy", "dentist", "alternative"):
            r = normalize(feature(healthcare=kind, amenity=None), "s:1", "osm", "raw#/features/0")
            self.assertEqual(kind, r["facility_type"])
            self.assertIn("source_healthcare=" + kind, r["quality_flags"])
        r = normalize(feature("nhp", Hospital_Care_Type="Clinic", Discipline_Systems_of_Medicine="Ayurveda"), "s:1", "nhp", "raw#/features/0")
        self.assertEqual("Clinic", r["facility_type"])
        self.assertIn("source_Discipline_Systems_of_Medicine=Ayurveda", r["quality_flags"])

    def test_nodes_ways_relations_and_missing_ids(self):
        fs = [feature(identifier=x) for x in ("node/1", "way/1", "relation/1", None)]
        batch, coverage = make_batch(fs, "health.geojson", snapshot(), "osm")
        self.assertEqual(4, len(batch["external_facilities"]))
        self.assertEqual(3, coverage["output"]["distinct_source_identifiers"])
        self.assertTrue(any("source_identifier_missing" in r["quality_flags"] for r in batch["external_facilities"]))

    def test_coordinates_invalid_missing_swapped_outside(self):
        for xy in ([75, 91], [181, 26], ["75", 26], [75, float("nan")], [True, 26], [75]):
            self.assertEqual((None, None, None, ["coordinates_invalid"]), coordinates({"type": "Point", "coordinates": xy}))
        self.assertEqual(["coordinates_missing"], coordinates(None)[3])
        self.assertEqual(["coordinates_missing"], coordinates({"type": "Point", "coordinates": []})[3])
        lat, lon, _, flags = coordinates({"type": "Point", "coordinates": [26, 75]})
        self.assertEqual((75, 26), (lat, lon))
        self.assertIn("possibly_swapped_coordinates", flags)
        self.assertIn("outside_india_bbox", flags)
        self.assertIn("outside_india_bbox", coordinates({"type": "Point", "coordinates": [-40, -20]})[3])

    def test_polygon_multipolygon_representative_point_not_entrance(self):
        ring = [[75, 26], [76, 26], [76, 27], [75, 27], [75, 26]]
        for kind, points in (("Polygon", [ring]), ("MultiPolygon", [[ring]])):
            geometry = {"type": kind, "coordinates": points}
            lat, lon, method, flags = coordinates(geometry)
            self.assertTrue(shape(geometry).contains(Point(lon, lat)))
            self.assertEqual("polygon_representative_point", method)
            self.assertIn("representative_point_not_entrance", flags)
            self.assertIn("geometry_" + kind.lower(), flags)
        bowtie = {"type": "Polygon", "coordinates": [[[75, 26], [76, 27], [75, 27], [76, 26], [75, 26]]]}
        self.assertIn("coordinates_invalid", coordinates(bowtie)[3])
        self.assertIn("geometry_unsupported", coordinates({"type": "LineString", "coordinates": ring})[3])

    def test_coverage_uses_input_and_unique_denominators(self):
        f = feature(name=None, healthcare="pharmacy", healthcare_speciality="Example specialty")
        b, c = make_batch([f, f], None, snapshot(), "osm")
        self.assertEqual(2, c["input"]["rows"])
        self.assertEqual(1, c["output"]["rows"])
        self.assertEqual(0, c["output"]["name_populated"])
        self.assertEqual(1, c["by_facility_type"]["pharmacy"]["output"]["specialty_populated"])
        self.assertEqual([], b["facility_evidence"])
        self.assertEqual([], b["facility_matches"])

    def test_shared_fixture_schema_and_separate_base(self):
        schema = read_json(ROOT / "contracts/enrichment/schema.json")
        fixture = read_json(ROOT / "contracts/fixtures/enrichment.json")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(fixture)
        base = read_json(ROOT / "contracts/fixtures/enrichment_base.json")
        self.assertEqual(len(base), len({r["facility_id"] for r in base}))

    def test_references_and_required_fields(self):
        b, _ = make_batch([feature()], None, snapshot(), "osm")
        validate(b)
        b["external_facilities"][0]["snapshot_id"] = "missing:1"
        with self.assertRaises(AcquisitionError): validate(b)
        b["external_facilities"][0]["snapshot_id"] = snapshot()["snapshot_id"]
        del b["external_facilities"][0]["pin"]
        with self.assertRaises(Exception): validate(b)


class FormatTests(unittest.TestCase):
    def load(self, data, source="osm"):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "raw"
            p.write_bytes(data)
            return load_features(p, source)

    def test_safe_zip_and_truncated_archive(self):
        data, _ = osm_archive([feature()])
        self.assertEqual(1, len(self.load(data)[0]))
        with self.assertRaises(AcquisitionError): self.load(data[:-15])

    def test_unsafe_archive_paths(self):
        for name in ("../escape.txt", "/absolute.txt", "a/../../escape.txt", "a\\escape.txt", "C:escape"):
            with self.subTest(name=name):
                # Write the literal POSIX archive name even when running on Windows.
                with patch("zipfile.os.sep", "/"):
                    data, _ = osm_archive([feature()], {name: "malicious"})
                with self.assertRaises(AcquisitionError): self.load(data)

    def test_html_schema_drift_nan_and_empty_are_rejected(self):
        for data in (b"<html>Error</html>", b'{"type":"FeatureCollection","features":[]}',
                     geojson([{"type": "Feature", "properties": {}, "geometry": None}]),
                     geojson([feature("nhp", coordinates=[75, float("nan")])])):
            with self.assertRaises(AcquisitionError): self.load(data, "nhp")

    def test_resolves_only_observed_unambiguous_nhp_download(self):
        url, metadata = resolve_nhp_landing(landing(), "https://bharatlas.com/view/nhp_hospitals")
        self.assertEqual("https://example.invalid/nhp.geojson", url)
        self.assertNotIn("datePublished", metadata)
        for bad in (b"<html>Unavailable</html>", landing().replace(b'<a href=', b'<span data-link='),
                    landing("https://user:secret@example.invalid/data.geojson")):
            with self.assertRaises(AcquisitionError): resolve_nhp_landing(bad, "https://bharatlas.com/view/nhp_hospitals")


if __name__ == "__main__": unittest.main()
