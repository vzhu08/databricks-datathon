import importlib.util
import unittest

if any(importlib.util.find_spec(name) is None for name in ("osmium", "shapely")):
    raise unittest.SkipTest("Campus geometry uses the pinned optional research packages")

from shapely.geometry import Point, Polygon

from research.acquisition.issuer_campus_geometry.compare import (
    OUTCOMES, address_matches, classify, match_feature, relation_geometry,
)
from research.acquisition.issuer_campus_geometry.scan import names, norm


def row(address="12 Example Street, Imaginary City, 123456", points=True):
    return {"name": "Example Hospital", "premises_key": "synthetic",
            "premises_address": address, "pin": "123456", "points": [None] if points else []}


def candidate(source, ident, geometry, tags):
    feature = {"osm_id": ident, "edition": "geofabrik_2026-11-01",
               "tags": tags, "geometry": geometry}
    point = Point(0, 0) if source["points"] else None
    return match_feature(source, feature, point, norm(source["name"]),
                         names(tags), address_matches(source, tags))


def box(x1, x2):
    return Polygon([(x1, -.0005), (x2, -.0005), (x2, .0005), (x1, .0005)])


class GeometryControls(unittest.TestCase):
    def test_branch_swap_same_postal_code_is_not_exact_agreement(self):
        source = row()
        correct = {"name": "Example Hospital", "addr:housenumber": "12",
                   "addr:street": "Example Street", "addr:postcode": "123456"}
        wrong = {**correct, "addr:housenumber": "22"}
        exact = candidate(source, "way/1", box(-.001, .001), correct)
        swapped = candidate(source, "way/2", box(.0011, .002), wrong)
        self.assertEqual(classify(source, [exact]), OUTCOMES[0])
        self.assertFalse(swapped["same_address"])
        self.assertEqual(classify(source, [swapped]), OUTCOMES[2])
        self.assertEqual(classify(source, [exact, swapped]), OUTCOMES[2])
        conflict_inside = candidate(source, "way/3", box(-.001, .001), wrong)
        self.assertEqual(classify(source, [conflict_inside]), OUTCOMES[2])
        source_suite = row("12 Example Street, Floor 2, Imaginary City, 123456")
        self.assertFalse(address_matches(source_suite, correct))

    def test_multiple_buildings_within_named_campus_do_not_create_conflict(self):
        source = row()
        tags = {"name": "Example Hospital", "healthcare": "hospital"}
        campus = candidate(source, "relation/10", box(-.002, .002), tags)
        west = candidate(source, "way/20", box(-.0015, -.0005), tags)
        east = candidate(source, "way/30", box(.0005, .0015), tags)
        self.assertEqual(classify(source, [west, east, campus]), OUTCOMES[1])

    def test_unrelated_polygon_or_point_cannot_upgrade_campus(self):
        source = row()
        nearby = candidate(source, "node/1", Point(0, 0), {"name": "Other Campus"})
        self.assertTrue(nearby["point_repeats_osm_node"])
        self.assertEqual(classify(source, [nearby]), OUTCOMES[3])
        self.assertEqual(classify(source, []), OUTCOMES[4])

    def test_missing_point_can_use_exact_name_and_address_only(self):
        source = row(points=False)
        name = {"name": "Example Hospital"}
        without_address = candidate(source, "way/1", box(-.001, .001), name)
        exact = candidate(source, "way/1", box(-.001, .001),
                          {**name, "addr:full": source["premises_address"]})
        self.assertEqual(classify(source, [without_address]), OUTCOMES[2])
        self.assertEqual(classify(source, [exact]), OUTCOMES[0])
        self.assertEqual(classify({**source, "premises_key": None}, []), OUTCOMES[5])

    def test_multipolygon_inner_ring_is_not_campus(self):
        item = {"tags": {"type": "multipolygon"}, "members": [["w", 1, "outer"], ["w", 2, "inner"]]}
        refs = {"1": [1, 2, 3, 4, 1], "2": [5, 6, 7, 8, 5]}
        coordinates = dict(zip(map(str, range(1, 9)),
                               [(-2,-2),(2,-2),(2,2),(-2,2),(-1,-1),(1,-1),(1,1),(-1,1)]))
        campus = relation_geometry(item, refs, coordinates)
        self.assertFalse(campus.covers(Point(0, 0)))
        self.assertTrue(campus.covers(Point(1.5, 0)))
        self.assertIsNone(relation_geometry(item, {"1": refs["1"]}, coordinates))


if __name__ == "__main__":
    unittest.main()
