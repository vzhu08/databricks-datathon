import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from matching_fixtures import (AT, LATER, REVIEWER, ROOT, base_row, envelope, ext, mapping, match_for, snapshot, square)
from merge import plan_merge

from research.geography.checks import coordinate_status, duplicate_clusters, low_precision
from research.geography.distance import haversine_m, point_to_polygons_m, polygons_of
from research.geography.footprints import (building_snapshot, load_buildings, observe, select_cases)
from research.geography.overture import extract_sql
from research.geography.postal import aggregate, join
from research.matching.base_adapter import base_views, external_views
from research.matching.common import MatchingError
from research.matching.review import apply
from research.matching.run import execute

STATE = "Synthetic State"
LAT, LON = 20.0, 77.0


class CoordinateTests(unittest.TestCase):
    def test_status_flags_without_repair(self):
        self.assertEqual(["coordinates_missing"], coordinate_status(None, None)["flags"])
        self.assertEqual(["coordinates_incomplete"], coordinate_status(LAT, None)["flags"])
        self.assertFalse(coordinate_status("20.0", 77.0)["usable"])
        self.assertFalse(coordinate_status(True, 77.0)["usable"])
        self.assertFalse(coordinate_status(float("nan"), 77.0)["usable"])
        self.assertEqual(["coordinates_outside_wgs84"], coordinate_status(120.0, 200.0)["flags"])
        swapped = coordinate_status(77.0, 20.0)
        self.assertTrue(swapped["usable"])
        self.assertEqual((77.0, 20.0), (swapped["lat"], swapped["lon"]))  # original retained
        self.assertEqual((20.0, 77.0), (swapped["proposed"]["latitude"], swapped["proposed"]["longitude"]))
        self.assertIn("null_island", coordinate_status(0, 0)["flags"])
        self.assertEqual(["outside_india_envelope"], coordinate_status(51.5, -0.1)["flags"])
        self.assertEqual([], coordinate_status(LAT, LON)["flags"])

    def test_clusters_and_precision(self):
        points = [("a", LAT, LON, "one"), ("b", LAT, LON, "two"), ("c", LAT, LON, "three"),
                  ("d", LAT + 1, LON, "x"), ("e", LAT + 1, LON, "x"), ("f", LAT + 1, LON, "x")]
        clusters = duplicate_clusters(points)
        self.assertEqual(1, len(clusters))  # three records with one shared name are not a cluster cue
        self.assertEqual(["a", "b", "c"], clusters[0]["record_ids"])
        self.assertTrue(low_precision(20.0, 77.5))
        self.assertFalse(low_precision(20.01234, 77.5))

    def test_distances_are_metres(self):
        self.assertAlmostEqual(111195, haversine_m(0, 0, 1, 0), delta=50)
        footprint = polygons_of(square(LAT, LON, 20))
        self.assertEqual((0.0, True), point_to_polygons_m(LAT, LON, footprint))
        distance, inside = point_to_polygons_m(LAT + 45 / 111320.0, LON, footprint)
        self.assertFalse(inside)
        self.assertAlmostEqual(25.0, distance, delta=0.5)
        hole = copy.deepcopy(square(LAT, LON, 50))
        hole["coordinates"].append(square(LAT, LON, 10)["coordinates"][0])
        distance, inside = point_to_polygons_m(LAT, LON, polygons_of(hole))
        self.assertFalse(inside)  # inside the courtyard hole
        self.assertAlmostEqual(10.0, distance, delta=0.5)
        multi = {"type": "MultiPolygon", "coordinates": [square(LAT + 1, LON)["coordinates"], square(LAT, LON)["coordinates"]]}
        self.assertTrue(point_to_polygons_m(LAT, LON, polygons_of(multi))[1])
        self.assertIsNone(polygons_of({"type": "LineString", "coordinates": [[LON, LAT], [LON, LAT + 1]]}))
        self.assertIsNone(polygons_of({"type": "Polygon", "coordinates": [[[LON, LAT], [LON, 95.0], [LON, LAT]]]}))


class PostalTests(unittest.TestCase):
    ROWS = [{"Pincode": "900001", "District": "East District", "StateName": STATE, "OfficeName": "A"},
            {"Pincode": "900001", "District": "East District", "StateName": STATE, "OfficeName": "B"},
            {"Pincode": 900001, "District": "Border District", "StateName": STATE, "OfficeName": "C"},
            {"Pincode": "900002", "District": "West District", "StateName": STATE, "OfficeName": "D"},
            {"Pincode": "bad", "District": "West District", "StateName": STATE, "OfficeName": "E"}]
    MAP = {"pin": "Pincode", "district": "District", "state": "StateName", "office": "OfficeName"}

    def test_aggregate_keeps_ambiguity_and_join_cannot_fan_out(self):
        table, profile = aggregate(self.ROWS, self.MAP)
        self.assertEqual(2, profile["distinct_pins"])
        self.assertEqual(1, profile["rows_without_valid_pin"])
        self.assertEqual(3, table["900001"]["office_count"])
        self.assertTrue(table["900001"]["ambiguous_district"])
        self.assertEqual(["border district", "east district"], table["900001"]["districts"])
        records = [{"pin": "900001", "state_key": "synthetic state", "district_key": "east district"},
                   {"pin": "900001", "state_key": "other state", "district_key": "west district"},
                   {"pin": "900009", "state_key": None, "district_key": None},
                   {"pin": None, "state_key": None, "district_key": None}]
        joined = join(records, table)
        self.assertEqual(len(records), len(joined))  # three offices on one PIN did not multiply rows
        self.assertEqual(["pin_spans_multiple_districts"], joined[0]["postal_flags"])
        self.assertLessEqual({"state_disagrees_with_pin", "district_disagrees_with_pin"}, set(joined[1]["postal_flags"]))
        self.assertEqual(["pin_not_in_postal_directory"], joined[2]["postal_flags"])
        self.assertEqual(["pin_missing_or_invalid"], joined[3]["postal_flags"])

    def test_run_with_postal_context_preserves_base_rows(self):
        base = [base_row(1, name="Larkspur Hospital", district="West District", state=STATE, pin="900001",
                         address="4 Fourth Road 900002"),
                base_row(2, name="Marigold Hospital", district="East District", state=STATE, pin="900001")]
        before = copy.deepcopy(base)
        result = execute(base, [envelope([snapshot()], [ext(1, "Larkspur Hospital", snapshot(), pin="900001")])],
                         mapping=mapping(base), postal=self.ROWS, postal_mapping=self.MAP)
        self.assertEqual(before, base)
        self.assertEqual(2, result["geography_report"]["base"]["records"])
        counts = result["geography_report"]["base"]["flag_counts"]
        self.assertEqual(1, counts["district_disagrees_with_pin"])
        self.assertEqual(1, counts["address_pin_disagrees"])
        self.assertEqual(2, counts["pin_spans_multiple_districts"])
        self.assertEqual(3, result["geography_report"]["postal_profile"]["pins_with_multiple_offices"] + 2)
        with self.assertRaisesRegex(MatchingError, "postal_mapping"):
            execute(base, [envelope([snapshot()], [])], mapping=mapping(base), postal=self.ROWS)
        with self.assertRaisesRegex(MatchingError, "only known roles"):
            aggregate(self.ROWS, {"pin": "Pincode", "taluk": "x"})

    def test_duplicate_coordinate_cluster_is_reported_once(self):
        base = [base_row(n, name=f"{word} Hospital", lat=LAT, lon=LON)
                for n, word in enumerate(("Larkspur", "Marigold", "Nettle"), 1)]
        result = execute(base, [envelope([snapshot()], [])], mapping=mapping(base))
        self.assertEqual(1, len(result["geography_report"]["base"]["duplicate_coordinate_clusters"]))
        queued = [r for r in result["batch"]["review_queue"] if r["reason_code"] == "base_duplicate_coordinate_cluster"]
        self.assertEqual(1, len(queued))


class FootprintTests(unittest.TestCase):
    def setUp(self):
        self.osm, self.registry = snapshot("synthetic_osm", "osm"), snapshot("synthetic_registry_list")
        self.externals = [ext(1, "Larkspur Hospital", self.registry, latitude=LAT, longitude=LON),
                          ext(2, "Marigold Hospital", self.osm, latitude=LAT + 0.01, longitude=LON),
                          ext(3, "Nettle Hospital", self.registry, latitude=LAT + 0.02, longitude=LON),
                          ext(4, "Orchid Hospital", self.registry, latitude=LAT + 0.03, longitude=LON),
                          ext(5, "Poppy Hospital", self.registry, latitude=LAT + 0.04, longitude=LON)]
        self.base = [base_row(n, name=e["name_original"], lat=e["latitude"], lon=e["longitude"])
                     for n, e in enumerate(self.externals, 1)]
        self.source = envelope([self.osm, self.registry], self.externals)
        self.result = execute(self.base, [self.source], mapping=mapping(self.base))
        confirmed = [{"match_id": match_for(self.result, 1, 1)["match_id"], "decision": "confirmed",
                      "reviewer": REVIEWER, "reviewed_at": AT, "rationale": "Synthetic campus review."}]
        self.matches = apply(self.result["batch"], confirmed)["reviewed_batch"]
        features = [
            {"type": "Feature", "id": "synthetic-building-001", "geometry": square(LAT, LON),
             "properties": {"sources": [{"dataset": "Synthetic Open Buildings", "record_id": "x1"}]}},
            {"type": "Feature", "id": "synthetic-building-002", "geometry": square(LAT + 0.01, LON),
             "properties": {"sources": [{"dataset": "OpenStreetMap", "record_id": "w1"}]}},
            {"type": "Feature", "id": "synthetic-building-003", "geometry": square(LAT + 0.02 + 45 / 111320.0, LON),
             "properties": {"sources": None}},
            {"type": "Feature", "id": "synthetic-building-004", "geometry": square(LAT + 0.03, LON),
             "properties": {"sources": [{"dataset": "Synthetic Open Buildings"}], "capture_date": "2012-05-01"}},
            {"type": "Feature", "id": "synthetic-line", "geometry": {"type": "LineString", "coordinates": [[LON, LAT], [LON, LAT + 1]]},
             "properties": {}},
        ]
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "buildings.geojson"
        self.path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        self.buildings, self.skipped = load_buildings(self.path)
        self.snapshot = building_snapshot(self.path, "2026-11-18.0", "2026-11-21T18:30:00Z", "synthetic://buildings",
                                          "https://example.invalid/buildings")
        self.cases = [
            {"case_id": f"case-{n}", "kind": "control" if n < 3 else "disputed",
             "external_facility_id": e["external_facility_id"],
             "facility_id": self.base[n - 1]["facility_id"], "match_id": match_for(self.result, n, n)["match_id"],
             "points": [{"label": "claimed" if n == 1 else "corroborated",
                         "latitude": e["latitude"], "longitude": e["longitude"],
                         "coordinate_basis": "Synthetic base coordinate" if n == 1 else "Synthetic external coordinate"}]}
            for n, e in enumerate(self.externals, 1)]

    def run_observe(self, **kwargs):
        return observe(self.cases, self.buildings, self.snapshot, self.matches, self.source, **kwargs)

    def test_disputed_pair_cannot_inherit_another_campus_confirmation(self):
        winner = match_for(self.result, 1, 1)
        other = dict(winner, match_id="synthetic:competing-match", facility_id=self.base[1]["facility_id"],
                     status="candidate")
        self.matches["facility_matches"].append(other)
        self.cases = [dict(self.cases[0], match_id=other["match_id"], facility_id=other["facility_id"])]
        result = self.run_observe(reviewer=REVIEWER, reviewed_at=AT)
        self.assertEqual(result["batch"]["facility_evidence"], [])
        self.assertTrue(result["ledger"][0]["footprint_found"])
        self.assertFalse(result["ledger"][0]["linked_to_confirmed_match"])

    def test_unbound_claimed_point_remains_in_the_ledger(self):
        case = dict(self.cases[0])
        del case["match_id"], case["facility_id"]
        self.cases = [case]
        result = self.run_observe(reviewer=REVIEWER, reviewed_at=AT)
        self.assertEqual([], result["batch"]["facility_evidence"])
        self.assertTrue(result["ledger"][0]["footprint_found"])

    def test_candidate_base_point_stays_in_ledger_until_confirmed(self):
        self.cases = [self.cases[1]]
        self.cases[0]["points"][0].update(label="claimed", coordinate_basis="Synthetic base coordinate")
        result = self.run_observe(reviewer=REVIEWER, reviewed_at=AT)
        self.assertEqual([], result["batch"]["facility_evidence"])
        self.assertEqual("campus_pair_unresolved_or_disagrees", result["ledger"][0]["withheld_reason"])

    def test_containment_with_unknown_lineage_is_inconclusive(self):
        self.cases = [self.cases[0]]
        for building in self.buildings:
            building["sources"] = None
        result = self.run_observe(reviewer=REVIEWER, reviewed_at=AT)
        self.assertTrue(result["ledger"][0]["contained"])
        self.assertEqual("inconclusive", result["batch"]["facility_evidence"][0]["polarity"])

    def test_loader_skips_unsupported_geometry_and_reads_ndjson(self):
        self.assertEqual(4, len(self.buildings))
        self.assertEqual({"unsupported_or_invalid_geometry": 1}, self.skipped)
        nd = Path(self.tmp.name) / "buildings.ndjson"
        nd.write_text(json.dumps({"id": "b1", "sources": json.dumps([{"dataset": "OpenStreetMap"}]),
                                  "geometry": json.dumps(square(LAT, LON))}) + "\n", encoding="utf-8")
        loaded, skipped = load_buildings(nd)
        self.assertEqual(("b1", [{"dataset": "OpenStreetMap"}]), (loaded[0]["id"], loaded[0]["sources"]))
        self.assertEqual({}, skipped)

    def test_observations_are_location_only_and_absence_is_unknown(self):
        out = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER, stale_before="2020-01-01")
        evidence = {e["external_facility_id"]: e for e in out["batch"]["facility_evidence"]}
        self.assertEqual(4, len(evidence))                       # the fifth case has no footprint: no evidence row
        for row in evidence.values():
            self.assertEqual(("location", None, None), (row["claim_type"], row["service"], row["excerpt"]))
            self.assertEqual("metres", row["observation"]["units"])
            self.assertNotEqual("contradicts", row["polarity"])
            self.assertEqual((REVIEWER, LATER), (row["reviewer"], row["reviewed_at"]))
        inside = evidence["synthetic:external:001"]
        self.assertEqual(("supports", 0.0), (inside["polarity"], inside["observation"]["distance_m"]))
        self.assertEqual("synthetic:base:001", inside["facility_id"])   # linked: its match is confirmed
        self.assertEqual("undated", inside["temporal_status"])
        self.assertIsNone(inside["observation"]["capture_date"])        # unknown stays unknown
        near = evidence["synthetic:external:003"]
        self.assertEqual("inconclusive", near["polarity"])
        self.assertAlmostEqual(25.0, near["observation"]["distance_m"], delta=0.5)
        self.assertIsNone(near["facility_id"])                           # candidate match: evidence stays unlinked
        self.assertIsNone(near["match_id"])
        self.assertIn("Upstream lineage not stated for this feature", near["observation"]["limitations"])
        missing = [e for e in out["ledger"] if e["external_facility_id"] == "synthetic:external:005"][0]
        self.assertFalse(missing["footprint_found"])
        self.assertIsNone(missing["evidence_id"])
        self.assertEqual(1, out["summary"]["footprint_not_found_unknown"])
        reasons = {r["reason_code"] for r in out["batch"]["review_queue"]}
        self.assertEqual({"footprint_not_found", "footprint_shared_origin", "footprint_stale"}, reasons)
        not_found = [r for r in out["batch"]["review_queue"] if r["reason_code"] == "footprint_not_found"][0]
        self.assertIn("unknown, not evidence against", not_found["next_action"])

    def test_osm_derived_footprint_is_not_independent_of_an_osm_identity(self):
        out = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER)
        row = [e for e in out["batch"]["facility_evidence"] if e["external_facility_id"] == "synthetic:external:002"][0]
        self.assertEqual("inconclusive", row["polarity"])               # inside the footprint, yet not corroboration
        self.assertEqual(0.0, row["observation"]["distance_m"])
        self.assertTrue(any("not independent" in text for text in row["observation"]["limitations"]))
        self.assertEqual("shared_origin", self.snapshot["independence_status"])
        self.assertEqual(1, out["summary"]["shares_origin_with_identity_source"])

    def test_stale_footprint_is_historical_and_inconclusive(self):
        out = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER, stale_before="2020-01-01")
        row = [e for e in out["batch"]["facility_evidence"] if e["external_facility_id"] == "synthetic:external:004"][0]
        self.assertEqual(("inconclusive", "historical", "2012-05-01"),
                         (row["polarity"], row["temporal_status"], row["effective_date"]))
        fresh = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER)
        row = [e for e in fresh["batch"]["facility_evidence"] if e["external_facility_id"] == "synthetic:external:004"][0]
        self.assertEqual(("supports", "dated"), (row["polarity"], row["temporal_status"]))

    def test_without_a_reviewer_no_evidence_row_is_emitted(self):
        out = self.run_observe()
        self.assertEqual([], out["batch"]["facility_evidence"])
        self.assertEqual(4, out["summary"]["evidence_rows_held_back_without_reviewer"])
        self.assertEqual(5, len(out["ledger"]))
        with self.assertRaisesRegex(MatchingError, "go together"):
            self.run_observe(reviewer=REVIEWER)

    def test_d_validator_accepts_spatial_evidence(self):
        out = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER)
        plan = plan_merge([self.source, self.matches, out["batch"]], self.base)
        self.assertEqual(4, len(plan["batch"]["facility_evidence"]))
        self.assertEqual(self.base, plan["base"])
        again = self.run_observe(reviewer=REVIEWER, reviewed_at=LATER)
        self.assertEqual(out["batch"], again["batch"])                   # stable IDs, replay is idempotent
        plan_merge([self.source, self.matches, out["batch"], again["batch"]], self.base)

    def test_case_validation_and_radius_bound(self):
        bad = copy.deepcopy(self.cases)
        bad[0]["external_facility_id"] = "synthetic:external:999"
        with self.assertRaisesRegex(MatchingError, "external record in the supplied batches"):
            observe(bad, self.buildings, self.snapshot, self.matches, self.source)
        with self.assertRaisesRegex(MatchingError, "at most 500 m"):
            self.run_observe(radius_m=5000)

    def test_case_selection_is_bounded_and_repeatable(self):
        words = ("Alder Birch Cedar Dahlia Elder Fennel Gorse Hazel Iris Jasmine Kale Lupin Mallow Nutmeg Olive "
                 "Privet Quince Rowan Sorrel Thistle Umber Violet Wisteria Xylia Yarrow Zinnia Aster Bramble "
                 "Clover Daisy").split()
        externals = [ext(n, f"{word} Hospital", self.registry, latitude=LAT + n / 100,
                         longitude=LON + (0.05 if n % 2 else 0.0005)) for n, word in enumerate(words, 1)]
        base = [base_row(n, name=f"{word} Hospital", lat=LAT + n / 100, lon=LON) for n, word in enumerate(words, 1)]
        source = envelope([self.registry], externals)
        result = execute(base, [source], mapping=mapping(base))
        bases, exts = base_views(base, mapping(base)), external_views(source)
        cases, summary = select_cases(result["candidates"], exts, bases)
        self.assertEqual({"disputed": 10, "control": 10}, summary["selected"])
        self.assertEqual({"disputed": 15, "control": 15}, summary["eligible"])
        self.assertEqual(cases, select_cases(list(reversed(result["candidates"])), exts, bases)[0])
        self.assertTrue(all(len(c["points"]) == 2 for c in cases))        # claimed and corroborated differ
        few, summary = select_cases(result["candidates"][:3], exts, bases)
        self.assertEqual(len(few), sum(summary["selected"].values()))     # fewer eligible: all of them
        sql = extract_sql(cases, "2026-11-18.0", "data/local/matching/footprints/buildings.ndjson")
        self.assertIn("release/2026-11-18.0/theme=buildings/type=building", sql)
        self.assertEqual(40, sql.count("bbox.xmax >="))
        for forbidden in ("height", "area", "num_floors"):
            self.assertNotIn(forbidden, sql.lower())

    def test_extract_is_pinned_and_bounded(self):
        with self.assertRaisesRegex(MatchingError, "pin an inspected release"):
            extract_sql(self.cases, "latest", "out.ndjson")
        with self.assertRaisesRegex(MatchingError, "at most 500 m"):
            extract_sql(self.cases, "2026-11-18.0", "out.ndjson", radius_m=2000)
        with self.assertRaisesRegex(MatchingError, "without quotes"):
            extract_sql(self.cases, "2026-11-18.0", "out'; DROP TABLE x; --.ndjson")
        many = [dict(self.cases[0], case_id=f"c{n}", points=[{"label": "claimed", "latitude": LAT + n / 1000,
                 "longitude": LON, "coordinate_basis": "x"}]) for n in range(41)]
        with self.assertRaisesRegex(MatchingError, "between 1 and 40"):
            extract_sql(many, "2026-11-18.0", "out.ndjson")

    def test_footprint_cli(self):
        tmp = Path(self.tmp.name)
        for name, value in (("cases", self.cases), ("snapshot", self.snapshot), ("matches", self.matches),
                            ("source", self.source)):
            (tmp / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
        command = [sys.executable, "-m", "research.geography.footprints", "--cases", str(tmp / "cases.json"),
                   "--buildings", str(self.path), "--snapshot", str(tmp / "snapshot.json"),
                   "--matches", str(tmp / "matches.json"), "--external", str(tmp / "source.json"),
                   "--reviewer", REVIEWER, "--reviewed-at", LATER, "--output-dir", str(tmp / "out")]
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, done.returncode, done.stderr)
        summary = json.loads((tmp / "out/footprint_summary.json").read_text(encoding="utf-8"))
        self.assertEqual((5, 4, 1), (summary["cases"], summary["footprint_found"], summary["buildings_skipped"]["unsupported_or_invalid_geometry"]))
        self.path.write_text(self.path.read_text(encoding="utf-8") + " ", encoding="utf-8")  # extract changed
        changed = subprocess.run(command[:-1] + [str(tmp / "out2")], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(1, changed.returncode)
        self.assertIn("does not match the buildings file", changed.stderr)


if __name__ == "__main__":
    unittest.main()
