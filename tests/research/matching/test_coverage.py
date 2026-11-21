"""ACQ-C02 tests. Every record, coordinate and building here is invented: the
points are arbitrary positions inside the screening rectangle, not facilities."""
import copy
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from matching_fixtures import ROOT, envelope, ext, snapshot, square

from research.geography import imagery, open_buildings, overture_read
from research.geography.coverage import (MAX_CASES, STRATA, check_sample, freeze, measure, origin_family)
from research.geography.footprints import load_buildings
from research.geography.overture import bbox
from research.matching.common import MatchingError, canonical

try:
    import pyarrow
    import pyarrow.parquet as pq
except ImportError:  # the range reader's end-to-end test needs pyarrow
    pyarrow = None

LAT, LON = 26.0, 73.0
OSM = snapshot("synthetic_osm", family="osm")


def north(metres):
    return metres / 111320.0


def frame_rows():
    rows = []
    # Isolated controls: fine coordinates, unique names, nothing within 500 m.
    for i in range(7):
        rows.append(ext(100 + i, f"Invented Isolated {i} Hospital", OSM,
                        latitude=LAT + 0.1 * i + 0.1234567, longitude=LON + 0.1234567))
    # Mapped areas: the producer's interior point of a polygon.
    for i in range(6):
        rows.append(ext(200 + i, f"Invented Area {i} Hospital", OSM, latitude=LAT + 1 + 0.1 * i + 0.00123456789,
                        longitude=LON + 1.00123456789, coordinate_method="polygon_representative_point"))
    # Ambiguous: a differently named record 50 m away.
    for i in range(6):
        lat = LAT + 2 + 0.1 * i + 0.1234567
        rows.append(ext(300 + i, f"Invented Shared Site {i} Hospital", OSM, latitude=lat, longitude=LON + 2.1234567))
        rows.append(ext(400 + i, f"Invented Neighbour {i} Clinic", OSM, latitude=lat + north(50),
                        longitude=LON + 2.1234567, facility_type="clinic"))
    # Coarse: four decimals at most.
    for i in range(6):
        rows.append(ext(500 + i, f"Invented Coarse {i} Hospital", OSM, latitude=round(LAT + 3 + 0.1 * i, 4) + 0.0001,
                        longitude=LON + 3.0001))
    rows += [
        ext(600, "Invented Pharmacy", OSM, latitude=LAT + 3.6234567, longitude=LON + 4.1234567, facility_type="pharmacy"),
        ext(601, None, OSM, latitude=LAT + 3.7234567, longitude=LON + 4.1234567),
        ext(602, "Invented Far Hospital", OSM, latitude=12.1234567, longitude=77.1234567),
        ext(603, "Invented Unlocated Hospital", OSM),
        # Eligible but in no stratum: five decimals, and a name used twice.
        ext(604, "Invented Five Decimal Hospital", OSM, latitude=LAT + 3.82345, longitude=LON + 4.12345),
        ext(605, "Invented Repeated Hospital", OSM, latitude=LAT + 3.9234567, longitude=LON + 4.1234567),
        ext(606, "Invented Repeated Hospital", OSM, latitude=LAT + 4.0234567, longitude=LON + 4.1234567),
    ]
    return rows


def frame():
    return envelope([OSM], frame_rows())


def building(identifier, lat, lon, dataset, half_m=15.0, **source):
    sources = None if dataset is None else [{"dataset": dataset, **source}]
    return {"id": identifier, "sources": sources, "subtype": None, "class": None, "geometry": square(lat, lon, half_m)}


def loaded(rows):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "b.ndjson"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return load_buildings(path)[0]


def one_case_sample(stratum="isolated_point_control"):
    sample = freeze(frame(), 1)
    case = next(c for c in sample["cases"] if c["stratum"] == stratum)
    return sample, case, case["points"][0]


class SampleTests(unittest.TestCase):
    def test_strata_exclusions_and_denominators(self):
        sample = freeze(frame())
        self.assertEqual({"isolated_point_control": 7, "mapped_area_control": 6, "ambiguous_neighbour": 6,
                          "coarse_coordinate": 6}, {s: sample["strata"][s]["eligible"] for s in STRATA})
        self.assertEqual({s: 5 for s in STRATA}, {s: sample["strata"][s]["selected"] for s in STRATA})
        self.assertEqual(20, len(sample["cases"]))
        self.assertEqual({"not_hospital_type": 7, "name_missing": 1, "outside_rajasthan_rectangle": 1,
                          "coordinates_unusable": 1}, sample["frame"]["exclusions"])
        self.assertEqual(3, sample["frame"]["eligible_but_in_no_stratum"])
        self.assertEqual(len(frame_rows()), sample["frame"]["frame_rows"])
        self.assertEqual(sample["frame"]["frame_rows"],
                         sample["frame"]["eligible_rows"] + sum(sample["frame"]["exclusions"].values()))
        for case in sample["cases"]:
            point = case["points"][0]
            self.assertEqual("osm", case["reference_origin"])
            self.assertNotIn("name_original", case)  # no names or labels travel with the sample
            if case["stratum"] == "mapped_area_control":
                self.assertIsNone(point["coordinate_resolution_m"])
                self.assertIn("not an entrance", point["coordinate_basis"])
            if case["stratum"] == "coarse_coordinate":
                self.assertLessEqual(point["coordinate_decimals"], 4)
                self.assertGreaterEqual(point["coordinate_resolution_m"], 11)
            if case["stratum"] == "ambiguous_neighbour":
                self.assertGreaterEqual(case["frame_neighbours_within_150_m"], 1)
            if case["stratum"] == "isolated_point_control":
                self.assertEqual(0, case["frame_neighbours_within_500_m"])

    def test_frozen_sample_is_repeatable_and_order_independent(self):
        first = freeze(frame())
        shuffled = frame()
        shuffled["external_facilities"].reverse()
        self.assertEqual(canonical(first), canonical(freeze(shuffled)))
        check_sample(first)
        changed = copy.deepcopy(first)
        changed["cases"][0]["points"][0]["latitude"] += 0.001
        with self.assertRaisesRegex(MatchingError, "recorded hash"):
            check_sample(changed)

    def test_sample_size_is_bounded(self):
        self.assertEqual(MAX_CASES, 20)
        with self.assertRaisesRegex(MatchingError, "at most 20"):
            freeze(frame(), 6)
        small = freeze(frame(), 2)
        self.assertEqual(8, len(small["cases"]))
        duplicate = frame()
        duplicate["external_facilities"].append(duplicate["external_facilities"][0])
        with self.assertRaisesRegex(MatchingError, "repeated external_facility_id"):
            freeze(duplicate)


class MeasureTests(unittest.TestCase):
    def test_origin_names_collapse_to_one_family(self):
        self.assertEqual("osm", origin_family("OpenStreetMap"))
        self.assertEqual("google_open_buildings", origin_family("Google Open Buildings"))
        self.assertEqual("microsoft_ml_buildings", origin_family("Microsoft ML Buildings"))
        self.assertEqual("esri_community_maps", origin_family("Esri Community Maps"))
        self.assertEqual("invented_survey", origin_family("Invented Survey"))

    def test_same_origin_footprint_adds_no_support(self):
        sample, case, point = one_case_sample()
        overture = loaded([building("b-osm", point["latitude"], point["longitude"], "OpenStreetMap",
                                    update_time="2020-01-01T00:00:00.000Z", version="2099-01-01"),
                           building("b-far", point["latitude"] + north(300), point["longitude"], "Google Open Buildings")])
        observation = next(o for o in measure(sample, overture)["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual("inside_footprint_of_reference_origin_only", observation["finding"])
        self.assertFalse(observation["supports_building_location_plausibility"])
        self.assertIn("no independent support", observation["inconclusive_reason"])
        nearest = observation["overture"]["nearest"]
        self.assertEqual(("b-osm", 0.0, True, True), (nearest["feature_id"], nearest["distance_m"],
                                                       nearest["contained"], nearest["shares_origin_with_reference"]))
        self.assertEqual("2020-01-01T00:00:00.000Z", nearest["upstream_record_update_time"])
        self.assertEqual({"OpenStreetMap": "2099-01-01"}, nearest["upstream_dataset_versions"])
        self.assertIsNone(observation["capture_date"])  # an update time is never reported as a capture date
        other = observation["overture"]["nearest_other_origin"]
        self.assertEqual("b-far", other["feature_id"])
        self.assertAlmostEqual(285.0, other["distance_m"], delta=1.0)
        self.assertEqual({"google_open_buildings": 1, "osm": 1}, observation["overture"]["features_by_origin"])

    def test_other_origin_supports_location_only(self):
        sample, case, point = one_case_sample()
        overture = loaded([building("b-google", point["latitude"], point["longitude"], "Google Open Buildings")])
        observation = next(o for o in measure(sample, overture)["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual("inside_footprint_of_other_origin", observation["finding"])
        self.assertTrue(observation["supports_building_location_plausibility"])
        self.assertIsNone(observation["inconclusive_reason"])
        self.assertEqual(["google_open_buildings"], observation["other_origins_containing_point"])
        self.assertTrue(any("not healthcare activity" in text for text in observation["limitations"]))

    def test_nearby_missing_and_unstated_cases_stay_inconclusive(self):
        sample, case, point = one_case_sample()
        lat, lon = point["latitude"], point["longitude"]
        near = loaded([building("b-near", lat + north(60), lon, "Microsoft ML Buildings")])
        observation = next(o for o in measure(sample, near)["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual("footprint_nearby_point_outside", observation["finding"])
        self.assertAlmostEqual(45.0, observation["overture"]["nearest"]["distance_m"], delta=1.0)
        self.assertRegex(observation["inconclusive_reason"], r"4[45]\.\d m away")
        self.assertEqual({"25": 0, "100": 1, "500": 1}, observation["overture"]["features_within_band_m"])
        result = measure(sample, [])
        observation = next(o for o in result["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual("no_footprint_within_radius", observation["finding"])
        self.assertIn("unknown", observation["inconclusive_reason"])
        self.assertFalse(observation["supports_building_location_plausibility"])
        unstated = loaded([building("b-unstated", lat, lon, None)])
        observation = next(o for o in measure(sample, unstated)["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual("inside_footprint_of_reference_origin_only", observation["finding"])
        self.assertFalse(observation["overture"]["nearest"]["origin_stated"])

    def test_google_reuse_counts_once_and_unread_cells_stay_unknown(self):
        sample, case, point = one_case_sample()
        lat, lon = point["latitude"], point["longitude"]
        overture = loaded([building("b-reused", lat, lon, "Google Open Buildings", record_id="CODE+1")])
        direct = loaded([building("google_open_buildings_v3:CODE+1", lat, lon, "Google Open Buildings")])
        google = {"buildings": direct, "compared_case_ids": [case["case_id"]], "cells": []}
        result = measure(sample, overture, google)
        observation = next(o for o in result["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual(["google_open_buildings"], observation["other_origins_containing_point"])
        self.assertTrue(observation["google_open_buildings"]["compared"])
        self.assertTrue(observation["google_open_buildings"]["nearest"]["contained"])
        others = [o for o in result["observations"] if o["case_id"] != case["case_id"]]
        self.assertTrue(all(o["google_open_buildings"] == {"compared": False,
                                                           "reason": "outside the bounded comparison subset"}
                            for o in others))
        self.assertEqual(1, result["summary"]["all"]["google_compared_points"])
        overlap = result["summary"]["source_overlap"]
        self.assertEqual((1, 1, 1, 1, 0), (overlap["overture_features"], overlap["overture_features_from_google"],
                                            overlap["of_which_same_record_in_google_files"],
                                            overlap["google_file_features"],
                                            overlap["google_file_features_not_carried_by_overture"]))
        # An OSM footprint plus a direct Google footprint: one other origin, which supports plausibility.
        mixed = measure(sample, loaded([building("b-osm", lat, lon, "OpenStreetMap")]), google)
        observation = next(o for o in mixed["observations"] if o["case_id"] == case["case_id"])
        self.assertEqual(["google_open_buildings", "osm"], observation["origins_containing_point"])
        self.assertEqual("inside_footprint_of_other_origin", observation["finding"])
        self.assertEqual(1, mixed["summary"]["source_overlap"]["google_file_features_not_carried_by_overture"])
        self.assertNotIn("source_overlap", measure(sample, overture)["summary"])

    def test_coarse_and_mapped_area_limitations_and_summary_denominators(self):
        sample = freeze(frame())
        buildings = []
        for index, case in enumerate(sample["cases"]):
            point = case["points"][0]
            if case["stratum"] != "ambiguous_neighbour":
                buildings.append(building(f"b-{index:02d}", point["latitude"], point["longitude"], "OpenStreetMap"))
        result = measure(sample, loaded(buildings), release="2099-01-01.0")
        summary = result["summary"]
        self.assertEqual(20, summary["denominator_points"])
        self.assertEqual(sample["sample_sha256"], summary["sample_sha256"])
        self.assertEqual({s: 5 for s in STRATA}, {s: summary["by_stratum"][s]["points"] for s in STRATA})
        self.assertEqual({"no_footprint_within_radius": 5}, summary["by_stratum"]["ambiguous_neighbour"]["finding"])
        self.assertEqual(15, summary["all"]["overture_point_inside_any_footprint"])
        self.assertEqual(0, summary["all"]["supports_building_location_plausibility"])
        self.assertEqual(sum(summary["all"]["finding"].values()), summary["denominator_points"])
        coarse = next(o for o in result["observations"] if o["stratum"] == "coarse_coordinate")
        self.assertTrue(any("containment within that margin" in text for text in coarse["limitations"]))
        mapped = next(o for o in result["observations"] if o["stratum"] == "mapped_area_control")
        self.assertTrue(any("computed from a mapped area" in text for text in mapped["limitations"]))
        with self.assertRaisesRegex(MatchingError, "500 m"):
            measure(sample, [], radius_m=501)

    def test_cli_freezes_once_and_measures_identically(self):
        sample = freeze(frame())
        point = sample["cases"][0]["points"][0]
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "frame.json").write_text(json.dumps(frame()), encoding="utf-8")
            (folder / "b.ndjson").write_text(json.dumps(
                building("b-1", point["latitude"], point["longitude"], "Microsoft ML Buildings")) + "\n", encoding="utf-8")
            def run(*args):
                return subprocess.run([sys.executable, "-m", "research.geography.coverage", *args], cwd=ROOT,
                                      capture_output=True, text=True)
            first = run("freeze", "--frame", str(folder / "frame.json"), "--output-dir", str(folder / "out"))
            self.assertEqual(0, first.returncode, first.stderr)
            stored = json.loads((folder / "out/sample.json").read_text(encoding="utf-8"))
            self.assertEqual(sample["cases"], stored["cases"])
            again = run("freeze", "--frame", str(folder / "frame.json"), "--output-dir", str(folder / "out"))
            self.assertEqual(1, again.returncode)  # a frozen sample is never overwritten
            arguments = ("measure", "--sample", str(folder / "out/sample.json"), "--overture", str(folder / "b.ndjson"),
                         "--release", "2099-01-01.0", "--output-dir", str(folder / "out"))
            self.assertEqual(0, run(*arguments).returncode)
            before = (folder / "out/observations.json").read_bytes(), (folder / "out/summary.json").read_bytes()
            self.assertEqual(0, run(*arguments).returncode)
            self.assertEqual(before, ((folder / "out/observations.json").read_bytes(),
                                      (folder / "out/summary.json").read_bytes()))
            summary = json.loads(before[1])
            self.assertEqual(0, run("manifest", "--dir", str(folder / "out")).returncode)
            listed = json.loads((folder / "out/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(["sample.json", "observations.json", "summary.json"], [f["path"] for f in listed["files"]])
            self.assertEqual(stored["sample_sha256"], listed["sample_sha256"])
            self.assertEqual(64, len(listed["cases_sha256"]))
            self.assertTrue(all(len(f["sha256"]) == 64 and "/" not in f["path"] for f in listed["files"]))
            self.assertEqual(1, summary["all"]["supports_building_location_plausibility"])
            self.assertEqual("2099-01-01.0", summary["overture_release"])


def wkb_polygon(rings, order="<"):
    data = (b"\x01" if order == "<" else b"\x00") + struct.pack(order + "II", 3, len(rings))
    for ring in rings:
        data += struct.pack(order + "I", len(ring))
        for x, y in ring:
            data += struct.pack(order + "dd", x, y)
    return data


class FakeStore:
    """Serves byte ranges of in-memory objects and records what was asked."""

    def __init__(self, objects):
        self.objects, self.ranges = objects, []

    def get(self, url, headers=None):
        key = url.split("amazonaws.com/", 1)[1]
        data = self.objects[key]
        if headers and "Range" in headers:
            start, end = (int(v) for v in headers["Range"].split("=")[1].split("-"))
            self.ranges.append((key, start, end))
            return data[start:end + 1], {}
        return data, {}


class RangeReaderTests(unittest.TestCase):
    def test_range_file_reads_blocks_once(self):
        data = bytes(range(256)) * 40
        store = FakeStore({"k": data})
        handle = overture_read.RangeFile(overture_read.HOST + "/k", len(data), store.get, block=1000)
        handle.seek(-10, 2)
        self.assertEqual(data[-10:], handle.read())
        self.assertEqual(1, handle.requests)
        handle.seek(950)
        self.assertEqual(data[950:2100], handle.read(1150))
        self.assertEqual([("k", 10000, 10239), ("k", 0, 2999)], store.ranges)  # one coalesced request
        handle.seek(1500)
        self.assertEqual(data[1500:1600], handle.read(100))
        self.assertEqual(2, handle.requests)
        self.assertEqual(1600, handle.tell())
        self.assertEqual(b"", overture_read.RangeFile("u", 0, store.get).read())
        short = overture_read.RangeFile(overture_read.HOST + "/k", len(data) + 5, store.get, block=1000)
        short.seek(-3, 2)
        with self.assertRaisesRegex(MatchingError, "different byte count"):
            short.read()

    def test_wkb_polygons_only(self):
        ring = [(73.0, 26.0), (73.001, 26.0), (73.001, 26.001), (73.0, 26.0)]
        expected = {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}
        self.assertEqual(expected, overture_read.wkb_geojson(wkb_polygon([ring])))
        self.assertEqual(expected, overture_read.wkb_geojson(wkb_polygon([ring], ">")))
        multi = b"\x01" + struct.pack("<II", 6, 2) + wkb_polygon([ring]) + wkb_polygon([ring])
        self.assertEqual({"type": "MultiPolygon", "coordinates": [[[list(p) for p in ring]]] * 2},
                         overture_read.wkb_geojson(multi))
        point = b"\x01" + struct.pack("<Idd", 1, 73.0, 26.0)
        self.assertIsNone(overture_read.wkb_geojson(point))
        self.assertIsNone(overture_read.wkb_geojson(wkb_polygon([ring])[:-4]))
        self.assertIsNone(overture_read.wkb_geojson(wkb_polygon([ring]) + b"\x00"))

    def test_release_listing_follows_pages_and_checks_the_pin(self):
        prefix = overture_read.PREFIX.format(release="2099-01-01.0")
        page = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>{more}</IsTruncated>'
                "{token}<Contents><Key>{prefix}{name}</Key><ETag>&quot;e&quot;</ETag><Size>{size}</Size></Contents>"
                "</ListBucketResult>")
        calls = []

        def get(url, headers=None):
            calls.append(url)
            if "continuation-token" in url:
                return page.format(more="false", token="", prefix=prefix, name="part-1.parquet", size=7).encode(), {}
            return page.format(more="true", token="<NextContinuationToken>t+1</NextContinuationToken>", prefix=prefix,
                               name="part-0.parquet", size=5).encode(), {}

        files = overture_read.list_release("2099-01-01.0", get)
        self.assertEqual([("part-0.parquet", 5, "e"), ("part-1.parquet", 7, "e")],
                         [(f["key"].rsplit("/", 1)[1], f["size"], f["etag"]) for f in files])
        self.assertIn("continuation-token=t%2B1", calls[1])
        with self.assertRaisesRegex(MatchingError, "pin an inspected release"):
            overture_read.list_release("latest", get)

    @unittest.skipIf(pyarrow is None, "pyarrow not installed")
    def test_extract_reads_only_the_row_groups_that_touch_a_point(self):
        def row(identifier, lat, lon, dataset):
            geometry = square(lat, lon, 10)
            ring = [tuple(p) for p in geometry["coordinates"][0]]
            return {"id": identifier, "sources": [{"dataset": dataset, "record_id": identifier}], "subtype": None,
                    "class": None, "geometry": wkb_polygon([ring]),
                    "bbox": {"xmin": min(p[0] for p in ring), "xmax": max(p[0] for p in ring),
                             "ymin": min(p[1] for p in ring), "ymax": max(p[1] for p in ring)}, "height": 3.0}
        groups = [
            [row("far-1", 10.0, 60.0, "OpenStreetMap"), row("far-2", 10.001, 60.0, "OpenStreetMap")],
            [row("hit-inside", LAT, LON, "Google Open Buildings"),
             row("hit-edge", LAT + north(505), LON, "Microsoft ML Buildings"),
             row("same-group-outside", LAT + north(2000), LON, "OpenStreetMap")],
            [row("far-3", 40.0, 90.0, "OpenStreetMap")],
        ]
        schema = pyarrow.schema([
            ("id", pyarrow.string()),
            ("sources", pyarrow.list_(pyarrow.struct([("dataset", pyarrow.string()), ("record_id", pyarrow.string())]))),
            ("subtype", pyarrow.string()), ("class", pyarrow.string()), ("geometry", pyarrow.binary()),
            ("bbox", pyarrow.struct([("xmin", pyarrow.float32()), ("xmax", pyarrow.float32()),
                                     ("ymin", pyarrow.float32()), ("ymax", pyarrow.float32())])),
            ("height", pyarrow.float64())])
        buffer = io.BytesIO()
        with pq.ParquetWriter(buffer, schema) as writer:
            for group in groups:
                writer.write_table(pyarrow.Table.from_pylist(group, schema=schema))
        key = overture_read.PREFIX.format(release="2099-01-01.0") + "part-0.parquet"
        store = FakeStore({key: buffer.getvalue()})
        index = overture_read.build_index("2099-01-01.0", [{"key": key, "size": len(buffer.getvalue()), "etag": "e"}],
                                          store.get, workers=1)
        entry = index["files"][0]
        self.assertEqual((6, 3), (entry["rows"], len(entry["row_groups"])))
        cases = [{"points": [{"latitude": LAT, "longitude": LON}]}]
        box = bbox(LAT, LON, 500.0)
        self.assertEqual([(key, entry["size"], [1])], overture_read.plan(index, [box]))
        rows, stats = overture_read.extract(index, cases, 500.0, store.get)
        # Same predicate as the DuckDB script: a feature's bbox touches the box around the point.
        self.assertEqual(["hit-edge", "hit-inside"], [r["id"] for r in rows])
        self.assertEqual({"type", "coordinates"}, set(rows[0]["geometry"]))
        self.assertEqual(set(overture_read.COLUMNS), set(rows[0]))  # no height or other measure is selected
        self.assertEqual((1, 1, 3, 2), (stats["files_read"], stats["row_groups_read"], stats["rows_scanned"],
                                         stats["features"]))
        with tempfile.TemporaryDirectory() as folder:
            first = overture_read.write_ndjson(Path(folder) / "a.ndjson", rows)
            second = overture_read.write_ndjson(Path(folder) / "b.ndjson", list(reversed(rows))[::-1])
            self.assertEqual(first, second)
            buildings, skipped = load_buildings(Path(folder) / "a.ndjson")
            self.assertEqual((2, {}), (len(buildings), skipped))
        with self.assertRaisesRegex(MatchingError, "at most 500"):
            overture_read.extract(index, cases, 501.0, store.get)
        many = [{"points": [{"latitude": LAT + i * 0.01, "longitude": LON}]} for i in range(41)]
        with self.assertRaisesRegex(MatchingError, "between 1 and 40"):
            overture_read.extract(index, many, 500.0, store.get)


class OpenBuildingsTests(unittest.TestCase):
    def test_wkt_parsing(self):
        self.assertEqual({"type": "Polygon", "coordinates": [[[73.0, 26.0], [73.1, 26.0], [73.1, 26.1], [73.0, 26.0]]]},
                         open_buildings.wkt_geojson("POLYGON((73.0 26.0, 73.1 26.0, 73.1 26.1, 73.0 26.0))"))
        multi = open_buildings.wkt_geojson(
            "MULTIPOLYGON(((73 26, 73.1 26, 73.1 26.1, 73 26)), ((74 27, 74.1 27, 74.1 27.1, 74 27)))")
        self.assertEqual(("MultiPolygon", 2), (multi["type"], len(multi["coordinates"])))
        for bad in ("POINT(73 26)", "POLYGON((73 26, 73.1 26))", "POLYGON((73 26, 73.1 26, x y, 73 26))", ""):
            self.assertIsNone(open_buildings.wkt_geojson(bad))

    def test_cell_choice_is_bounded_and_ordered(self):
        cases = [{"case_id": c} for c in "abcdef"]
        tokens = {"a": "t1", "b": "t1", "c": "t2", "d": "t2", "e": "t3", "f": "t4"}
        sizes = {"t1": 500, "t2": 300, "t3": 250, "t4": None}
        chosen, skipped = open_buildings.choose_cells(cases, tokens, sizes, 900)
        self.assertEqual(["t2", "t1"], chosen)  # equal point counts: the smaller file first
        self.assertEqual({"t3": "outside_download_budget", "t4": "no_published_file_for_cell"}, skipped)

    def test_extract_keeps_only_buildings_near_sample_points(self):
        sample = freeze(frame(), 1)
        points = {c["case_id"]: c["points"][0] for c in sample["cases"]}
        first, second = sorted(points)[:2]

        def token_of(lat, lon):
            return "cellA" if (lat, lon) == (points[first]["latitude"], points[first]["longitude"]) else "cellB"

        def line(lat, lon, code):
            ring = square(lat, lon, 8)["coordinates"][0]
            wkt = "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"
            return f'{lat},{lon},256.0,0.81,"{wkt}",{code}\n'

        p = points[first]
        lines = [line(p["latitude"], p["longitude"], "CODE+IN"), line(p["latitude"] + north(550), p["longitude"], "CODE+MARGIN"),
                 line(p["latitude"] + north(900), p["longitude"], "CODE+OUT"), "not,a,row\n"]
        read = []

        def stream(token, boxes):
            read.append(token)
            return open_buildings.filter_rows(lines, boxes)

        rows, manifest = open_buildings.extract(
            sample, max_bytes=100, metadata=lambda t: {"size": "100" if t == "cellA" else "5000", "md5Hash": "m"},
            stream=stream, token_of=token_of)
        self.assertEqual(["cellA"], read)
        self.assertEqual(["google_open_buildings_v3:CODE+IN", "google_open_buildings_v3:CODE+MARGIN"],
                         [r["id"] for r in rows])
        self.assertEqual("Google Open Buildings", rows[0]["sources"][0]["dataset"])
        self.assertEqual([first], manifest["compared_case_ids"])
        self.assertEqual(3, len(manifest["not_compared_case_ids"]))
        self.assertEqual("outside_download_budget", manifest["cells_not_read"][0]["reason"])
        self.assertEqual((4, 2), (manifest["cells"][0]["rows_read"], manifest["cells"][0]["rows_kept"]))
        self.assertEqual(sample["sample_sha256"], manifest["sample_sha256"])


class ImageryTests(unittest.TestCase):
    def test_visibility_classes(self):
        self.assertEqual("clear", imagery.visibility(5))
        self.assertEqual("clear", imagery.visibility(4))
        for value in (3, 8, 9, 10):
            self.assertEqual("obstructed", imagery.visibility(value))
        for value in (0, 1, 99):
            self.assertEqual("no_observation", imagery.visibility(value))

    def test_scene_order_and_band_edge_fallback(self):
        tree = {
            "sentinel-s2-l2a-cogs/43/R/AA/": ["sentinel-s2-l2a-cogs/43/R/AA/2098/", "sentinel-s2-l2a-cogs/43/R/AA/2099/"],
            "sentinel-s2-l2a-cogs/43/R/AA/2099/": ["sentinel-s2-l2a-cogs/43/R/AA/2099/9/",
                                                   "sentinel-s2-l2a-cogs/43/R/AA/2099/11/"],
            "sentinel-s2-l2a-cogs/43/R/AA/2099/11/": ["sentinel-s2-l2a-cogs/43/R/AA/2099/11/S2X_43RAA_20991103_0_L2A/",
                                                      "sentinel-s2-l2a-cogs/43/R/AA/2099/11/S2X_43RAA_20991117_0_L2A/"],
            "sentinel-s2-l2a-cogs/43/R/AA/2099/9/": ["sentinel-s2-l2a-cogs/43/R/AA/2099/9/S2X_43RAA_20990930_0_L2A/"],
        }
        scenes = imagery.newest_scenes("43/R/AA", 3, lambda prefix: tree.get(prefix, []))
        self.assertEqual(["20991117", "20991103", "20990930"], [s.split("_")[2] for s in scenes])
        self.assertEqual(["43/R/DG", "43/Q/DG", "43/S/DG"], imagery.tile_candidates("43/R/DG"))

    def test_records_keep_obstructed_and_missing_imagery_unknown(self):
        sample = freeze(frame(), 1)
        item = {"id": "scene", "properties": {"datetime": "2099-11-17T05:00:00Z", "eo:cloud_cover": 12.5},
                "links": [{"rel": "license", "href": "https://example.invalid/licence"}]}
        order = sorted(c["case_id"] for c in sample["cases"])
        values = {order[0]: [5], order[1]: [9, 3], order[2]: [9, 4], order[3]: None}
        points = {(c["points"][0]["latitude"], c["points"][0]["longitude"]): c["case_id"] for c in sample["cases"]}
        calls = {}

        def classify(scene, lat, lon):
            case = points[(lat, lon)]
            calls[case] = calls.get(case, 0) + 1
            return values[case][calls[case] - 1], 20.0

        def scenes_of(tile, limit, lister):
            return [] if tile.endswith("/ZZ") else ["a/S2X_T_20991117_0_L2A/", "a/S2X_T_20991114_0_L2A/"][:limit]

        with mock.patch.object(imagery, "newest_scenes", scenes_of):
            records = imagery.collect(
                sample, limit=2, item_of=lambda scene: item, classify=classify,
                tile=lambda lat, lon: "43/R/ZZ" if points[(lat, lon)] == order[3] else "43/R/AA")
        by_case = {r["case_id"]: r for r in records}
        clear = by_case[order[0]]
        self.assertEqual(("clear", "not_vegetated", 10.0, 20.0, 12.5, "https://example.invalid/licence", 1),
                         (clear["visibility_at_point"], clear["class_at_point"], clear["resolution_m"],
                          clear["classification_resolution_m"], clear["scene_cloud_cover_percent"], clear["license"],
                          clear["scenes_checked"]))
        self.assertFalse(clear["can_resolve_building"])
        blocked = by_case[order[1]]
        self.assertEqual(("unknown", None, 2), (blocked["visibility_at_point"], blocked["acquired_at"],
                                                 blocked["scenes_checked"]))
        self.assertIn("not a negative finding", blocked["unknown_reason"])
        self.assertEqual("obstructed", blocked["newest_scene_visibility_at_point"])
        self.assertEqual(("clear", 2, "obstructed"), (by_case[order[2]]["visibility_at_point"],
                                                      by_case[order[2]]["scenes_checked"],
                                                      by_case[order[2]]["newest_scene_visibility_at_point"]))
        self.assertEqual(("unknown", 0), (by_case[order[3]]["visibility_at_point"], by_case[order[3]]["scenes_checked"]))
        measured = measure(sample, [], imagery={r["case_id"]: r for r in records})
        self.assertEqual(4, measured["summary"]["all"]["imagery_recorded"])
        self.assertEqual("clear", measured["observations"][0]["imagery"]["visibility_at_point"])


if __name__ == "__main__":
    unittest.main()
