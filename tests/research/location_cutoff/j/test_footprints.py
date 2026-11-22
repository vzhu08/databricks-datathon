import gzip
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

if any(importlib.util.find_spec(package) is None for package in ("osmium", "shapely")):
    raise unittest.SkipTest("Install the pinned #234 optional geometry dependencies")

from shapely import STRtree
from shapely.geometry import Point, Polygon, box

from research.acquisition.osm_services.pbf import file_digest
from research.location_cutoff.j import address_shortlist, areas, buildings, rollup
from research.location_cutoff.j.compare import evaluate


def mapped(label, geometry, **tags):
    return {"id": label, "version": 1, "tags": tags, "geometry": geometry}


def check(features, point=Point(0, 0), name="Example Hospital"):
    source = {"name": name, "address_line1": "27 Fiction Street", "address_zipOrPostcode": "123456"}
    return evaluate(source, point, features, STRtree([f["geometry"] for f in features]))


class FootprintTests(unittest.TestCase):
    def test_nested_campus_and_adjacent_named_rival(self):
        campus = mapped("relation/1", box(-.002, -.002, .002, .002), amenity="hospital")
        building = mapped("way/2", box(-.0002, -.0002, .0002, .0002), building="hospital", name="Other")
        rival = mapped("way/3", box(.0004, -.0002, .0006, .0002), building="hospital", name="Example Hospital")
        flags, candidates = check([campus, building, rival])
        self.assertTrue(flags["building_nested_in_site"])
        self.assertTrue(flags["inside_one_outline_with_disjoint_exact_name_nearby"])
        self.assertTrue(flags["inside_named_nonmatching_without_exact_name"])
        self.assertFalse(flags["inside_exact_name_building"])
        self.assertEqual(3, len(candidates))

    def test_postal_conflict_blocks_structured_civic_address_agreement(self):
        obj = mapped("way/1", box(-.001, -.001, .001, .001), name="Example Hospital", building="hospital",
                     **{"addr:postcode": "123455", "addr:housenumber": "27", "addr:street": "Fiction Street"})
        flags, _ = check([obj])
        self.assertTrue(flags["inside_conflicting_postcode"])
        self.assertFalse(flags["inside_exact_name_and_address"])
        obj["tags"]["addr:postcode"] = "123456"
        self.assertTrue(check([obj])[0]["inside_building_exact_name_and_address"])

    def test_exterior_boundary_and_hole_do_not_count_as_interior(self):
        outer = list(box(-.001, -.001, .001, .001).exterior.coords)
        inner = list(box(-.0001, -.0001, .0001, .0001).exterior.coords)
        site = mapped("way/1", Polygon(outer, [inner]), amenity="clinic")
        self.assertFalse(check([site])[0]["interior"])
        flags, _ = check([site], point=Point(.001, 0))
        self.assertTrue(flags["boundary"])
        self.assertFalse(flags["interior"])

    def test_pbf_assembly_and_all_buildings_keep_repeated_original_points(self):
        with TemporaryDirectory() as name:
            path = Path(name)
            fixture = path / "example.osm"
            fixture.write_text("""<osm version="0.6">
<node id="1" lat="1" lon="1"/><node id="2" lat="1" lon="2"/>
<node id="3" lat="2" lon="2"/><node id="4" lat="2" lon="1"/>
<way id="5" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
<tag k="building" v="yes"/><tag k="name" v="Example Hospital"/></way>
<relation id="6" version="1"><member type="way" ref="5" role="outer"/>
<tag k="type" v="multipolygon"/><tag k="amenity" v="hospital"/><tag k="name" v="Example Grounds"/></relation>
</osm>""")
            with gzip.open(path / "occurrences.jsonl.gz", "wt") as stream:
                for idx, xy in enumerate(((1.5, 1.5), (1.5, 1.5), (1, 1), (None, None))):
                    item = {"identity": {"facility_id": str(idx), "original_point": {
                        "screen_class": "unusable_original_point" if xy[0] is None else "usable"}},
                        "original": {"source_row": {"name": "Example Hospital", "longitude": xy[0], "latitude": xy[1]}}}
                    stream.write(json.dumps(item) + "\n")
            h = file_digest(fixture)
            with patch.object(address_shortlist, "PBF_SHA", h):
                shapes = address_shortlist.selected_building_shapes(fixture, {"way/5", "relation/6"})
                self.assertTrue(all(shape.contains(Point(1.5, 1.5)) for shape in shapes.values()))
            with patch.object(areas, "PBF_SHA", h):
                areas.extract(fixture, path / "outlines.jsonl")
            outlines = [json.loads(l) for l in (path / "outlines.jsonl").read_text().splitlines()]
            self.assertEqual([r["id"] for r in outlines], ["relation/6"])
            with patch.object(buildings, "PBF_SHA", h), patch.object(buildings, "baseline", return_value={"occurrence_count": 4}):
                buildings.scan(path, fixture, path / "result")
            data = [json.loads(l)["buildings"] for l in (path / "result").read_text().splitlines()]
            self.assertEqual(data[0], data[1])
            self.assertTrue(data[0][0]["interior"] and data[0][0]["exact_name"])
            self.assertFalse(data[2][0]["interior"])
            self.assertEqual([], data[3])

    def test_rollup_rejects_dropped_building(self):
        clinical = {"screen": "usable", "flags": {}, "candidates": [{"id": "way/5", "interior": True, "building": True}]}
        with self.assertRaisesRegex(ValueError, "missing from building pass"):
            rollup.footprint_counts({"a": (clinical, {"buildings": []})}, ["a"])

    def test_v4_rejects_same_size_different_key_set(self):
        with TemporaryDirectory() as name:
            path = Path(name) / "v4.gz"
            with gzip.open(path, "wt") as stream:
                stream.write(json.dumps({"facility_id": "a", "directory_location": {"status": "area_located"}}) + "\n")
            with patch.object(rollup, "V4_SHA", file_digest(path)), patch.object(rollup, "V4_COUNTS", {"area_located": 1}):
                self.assertEqual({"a"}, rollup.v4_area_keys(path, {"a"}))
                with self.assertRaisesRegex(ValueError, "keys differ"):
                    rollup.v4_area_keys(path, {"b"})
