"""The planning simulation on the Storm page. Every plan here is invented, including its geography."""
import copy
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import storm_plan

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def plan():
    """Six invented patients, three invented facilities. One dialysis place is the binding constraint."""
    return {
        "schema_version": "storm-plan-v1",
        "geography": {"name": "Invented district", "selection": "Invented for the tests.",
                      "source": "Invented coordinates.", "verification": "None.", "venue": "Tests only",
                      "location_basis": "public_source",
                      "roster_sha256": "ab" * 32,
                      "attribution": [{"text": "Example map credit", "url": "https://example.invalid/copyright"}]},
        "scenario": {"seed": 3, "priorities": ["emergency", "urgent", "routine"], "horizon": "One invented shift.",
                     "objective": "Place the most patients, highest priority first.",
                     "travel_basis": "Invented minutes.", "simulated": "Patients, services and staffed places."},
        "facilities": [
            {"id": "F1", "label": "Invented clinic one", "latitude": 10.0, "longitude": 20.0,
             "precision": "mapped_point", "resources": [{"service": "dialysis", "slots": 2}],
             "source": {"publisher": "Example publisher", "license": "Example licence", "id": "node/1",
                        "url": "https://example.invalid/node/1"}},
            {"id": "F2", "label": "Invented clinic two", "latitude": 10.2, "longitude": 20.3,
             "precision": "campus_anchor", "resources": [{"service": "dialysis", "slots": 1},
                                                         {"service": "mri", "slots": 2}],
             "source": {"publisher": "Example publisher", "license": "Example licence"}},
            {"id": "F3", "label": "Invented clinic three", "latitude": 10.1, "longitude": 20.1,
             "precision": "area", "resources": [],
             "source": {"publisher": "Another publisher", "license": "Example licence"}},
        ],
        "patients": [
            {"id": "P1", "priority": "routine", "service": "dialysis", "latitude": 10.01, "longitude": 20.01},
            {"id": "P2", "priority": "routine", "service": "dialysis", "latitude": 10.02, "longitude": 20.02},
            {"id": "P3", "priority": "emergency", "service": "dialysis", "latitude": 10.03, "longitude": 20.03},
            {"id": "P4", "priority": "urgent", "service": "mri", "latitude": 10.15, "longitude": 20.25},
            {"id": "P5", "priority": "routine", "service": "mri"},
            {"id": "P6", "priority": "urgent", "service": "trauma_care"},
        ],
        "policies": {
            "nearest_first": {
                "assignments": [
                    {"patient": "P1", "facility": "F1", "service": "dialysis", "travel_minutes": 4},
                    {"patient": "P2", "facility": "F1", "service": "dialysis", "travel_minutes": 5},
                    {"patient": "P4", "facility": "F2", "service": "mri", "travel_minutes": 6.5},
                    {"patient": "P5", "facility": "F2", "service": "mri", "travel_minutes": 9}],
                "unserved": [{"patient": "P3", "reason": "nearest_facility_full"},
                             {"patient": "P6", "reason": "no_facility_offers_service"}]},
            "exact_optimum": {
                "assignments": [
                    {"patient": "P3", "facility": "F1", "service": "dialysis", "travel_minutes": 5},
                    {"patient": "P1", "facility": "F1", "service": "dialysis", "travel_minutes": 4},
                    {"patient": "P2", "facility": "F2", "service": "dialysis", "travel_minutes": 31},
                    {"patient": "P4", "facility": "F2", "service": "mri", "travel_minutes": 6.5},
                    {"patient": "P5", "facility": "F2", "service": "mri", "travel_minutes": 9}],
                "unserved": [{"patient": "P6", "reason": "no_facility_offers_service"}]},
        },
    }


def changed(change):
    found = plan()
    change(found)
    return found


TEST_ROSTER = "ab" * 32  # the invented plans count as an approved roster only inside these tests


class PlanTests(unittest.TestCase):
    def setUp(self):
        approved = mock.patch.object(storm_plan, "APPROVED_ROSTERS", {TEST_ROSTER})
        approved.start()
        self.addCleanup(approved.stop)

    def test_every_figure_is_counted_from_the_assignments(self):
        found = storm_plan.view(storm_plan.checked(plan()))
        nearest, best = found["results"]
        self.assertEqual((found["patients"], found["facilities"], found["places"]), (6, 3, 5))
        self.assertEqual((nearest["assigned"], nearest["unmet"], best["assigned"], best["unmet"]), (4, 2, 5, 1))
        self.assertEqual(nearest["by_priority"], {"emergency": 0, "urgent": 1, "routine": 3})
        self.assertEqual(best["by_priority"], {"emergency": 1, "urgent": 1, "routine": 3})
        self.assertEqual(dict(nearest["reasons"]), {"Nearest facility full": 1, "No facility offers service": 1})
        self.assertEqual((nearest["travel_total"], nearest["travel_mean"], nearest["travel_longest"]),
                         ("24.5", "6.1", "9"))
        self.assertEqual((best["travel_total"], best["travel_longest"]), ("55.5", "31"))
        self.assertEqual((nearest["full"], best["full"]), (2, 3))
        self.assertEqual(found["say"],
                         "On identical inputs the exact optimum placed 1 more simulated patient than nearest first.")
        self.assertEqual([(kind, count) for kind, _, count in found["precision"]],
                         [("mapped_point", 1), ("campus_anchor", 1), ("area", 1)])

    def test_a_plan_that_does_not_hold_together_is_refused(self):
        def twice(found):
            found["policies"]["exact_optimum"]["assignments"].append(
                {"patient": "P1", "facility": "F2", "service": "dialysis", "travel_minutes": 3})

        def wrong_service(found):
            found["policies"]["nearest_first"]["assignments"][0]["facility"] = "F3"

        def other_need(found):
            found["policies"]["nearest_first"]["assignments"][2]["service"] = "dialysis"

        def over(found):
            found["facilities"][0]["resources"][0]["slots"] = 1

        def lost(found):
            found["policies"]["nearest_first"]["unserved"].pop()

        def both(found):
            found["policies"]["nearest_first"]["unserved"].append({"patient": "P1", "reason": "x"})

        def precision(found):
            found["facilities"][0]["precision"] = "entrance"

        def link(found):
            found["geography"]["attribution"][0]["url"] = "http://example.invalid"

        def script(found):
            found["facilities"][0]["source"]["url"] = "javascript:alert(1)"

        def no_objective(found):
            found["scenario"]["objective"] = " "

        def one_policy(found):
            del found["policies"]["exact_optimum"]

        def version(found):
            found["schema_version"] = "storm-plan-v0"

        def far(found):
            found["facilities"][1]["latitude"] = 190

        def order(found):
            found["scenario"]["priorities"] = ["emergency", "routine"]

        def area_endpoint(found):
            found["facilities"][2]["resources"] = [{"service": "mri", "slots": 1}]
            found["policies"]["nearest_first"]["assignments"][3]["facility"] = "F3"

        def stored_total(found):
            found["policies"]["exact_optimum"]["metrics"] = {"assigned": 6, "unmet": 0}

        for change in (twice, wrong_service, other_need, over, lost, both, precision, link, script, no_objective,
                       one_policy, version, far, order, area_endpoint, stored_total):
            with self.subTest(change=change.__name__), self.assertRaises((ValueError, KeyError, TypeError)):
                storm_plan.checked(changed(change))
        self.assertIs(type(storm_plan.checked(plan())), dict)

    def test_the_planner_output_shape_is_read_with_buckets_seconds_and_urgency_codes(self):
        """Several appointment buckets of one service at a facility, whole travel seconds, urgency codes."""
        found = plan()
        del found["scenario"]["priorities"]
        codes = {"emergency": "highest", "urgent": "time_sensitive", "routine": "routine"}
        for patient in found["patients"]:
            patient["urgency"] = codes[patient.pop("priority")]
            patient.update(arrival_minute=0, deadline_minute=240, required_tools=[])
        found["facilities"][0]["resources"] = [
            {"slot_id": "F1-d-0", "resource_id": "F1-d", "service": "dialysis", "tools": [], "start_minute": 0,
             "slots": 1},
            {"slot_id": "F1-d-60", "resource_id": "F1-d", "service": "dialysis", "tools": [], "start_minute": 60,
             "slots": 1}]
        found["facilities"][1]["resources"] = [
            {"slot_id": "F2-d-0", "resource_id": "F2-d", "service": "dialysis", "tools": [], "start_minute": 0,
             "slots": 1},
            {"slot_id": "F2-m-0", "resource_id": "F2-m", "service": "mri", "tools": [], "start_minute": 0, "slots": 2}]
        slot = {("F1", 0): "F1-d-0", ("F1", 1): "F1-d-60", ("F2", "dialysis"): "F2-d-0", ("F2", "mri"): "F2-m-0"}
        for result in found["policies"].values():
            at_first = 0
            for row in result["assignments"]:
                if row["facility"] == "F1":
                    row["slot_id"], at_first = slot[("F1", at_first)], at_first + 1
                else:
                    row["slot_id"] = slot[("F2", row["service"])]
                row["travel_seconds"] = int(row["travel_minutes"] * 60)
                row["slot_start_minute"] = 0
            result["metrics"] = {"assigned": len(result["assignments"]), "unmet": len(result["unserved"])}
        seen = storm_plan.view(storm_plan.checked(found))
        self.assertEqual(seen["order"], ["highest", "time_sensitive", "routine"])
        self.assertEqual([result["assigned"] for result in seen["results"]], [4, 5])
        self.assertEqual(seen["results"][0]["travel_total"], "24.5")
        self.assertEqual(seen["places"], 5)
        self.assertEqual(seen["resources"][0], {"facility": "Invented clinic one", "service": "dialysis", "slots": 2,
                                                "basis": "Simulated", "used": [2, 2]})
        self.assertIn("Time sensitive", storm_plan.markup(found))
        # Two patients in one single-place bucket is refused even though the facility has two places in all.
        crowded = copy.deepcopy(found)
        crowded["policies"]["nearest_first"]["assignments"][1]["slot_id"] = "F1-d-0"
        with self.assertRaises(ValueError):
            storm_plan.checked(crowded)
        # So is a slot that belongs to another facility.
        elsewhere = copy.deepcopy(found)
        elsewhere["policies"]["nearest_first"]["assignments"][0]["slot_id"] = "F2-d-0"
        with self.assertRaises(ValueError):
            storm_plan.checked(elsewhere)

    def test_load_gives_one_state_for_every_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "plan.json"
            with self.assertRaises(storm_plan.Unavailable):
                storm_plan.load(path)
            for text in ("", "[]", "{}", json.dumps(changed(lambda found: found["patients"].pop()))):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text[:20]), self.assertRaises(storm_plan.Unavailable):
                    storm_plan.load(path)
            path.write_text(json.dumps(plan()), encoding="utf-8")
            self.assertEqual(6, len(storm_plan.load(path)["patients"]))

    def test_the_section_labels_what_is_real_and_what_is_simulated(self):
        page = storm_plan.markup(plan())
        for words in ("Real facility locations · simulated patients, services, staffed places and travel",
                      "4 of 6 placed", "5 of 6 placed", "Mapped facility point", "Campus simulation anchor",
                      "Area only", "None of these is a building entrance", "Example map credit",
                      "Example publisher (node/1)", "Example licence", "Another publisher", "Roster SHA-256",
                      "Tests only",
                      "No roads or background map are drawn"):
            self.assertIn(words, page)
        self.assertIn("simulated", storm_plan.NOTICE)
        self.assertIn("not a record of a real storm", storm_plan.NOTICE)
        self.assertEqual(page.count('href="'), 3)  # the map credit twice and one facility source
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))

    def test_one_patient_the_shared_cohort_and_the_planner_note_are_counted_from_the_rows(self):
        found = storm_plan.view(storm_plan.checked(plan()))
        case = found["difference"]
        self.assertEqual((case["id"], case["priority"], case["service"], case["reason"], case["near"]),
                         ("P3", "emergency", "dialysis", "Nearest facility full", None))
        self.assertEqual(case["best"], {"label": "Invented clinic one", "precision": "mapped facility point",
                                        "minutes": "5", "start": None, "basis": "simulated"})
        self.assertIsNone(case["holder"])  # this plan names no slots, so nobody is named as holding the place
        self.assertEqual(found["shared"], {"patients": 4, "near": "24.5", "best": "50.5"})
        self.assertEqual(found["advice"], [
            "Assigning the same staffed places differently placed 1 more of the 6 simulated patients, 1 of them "
            "emergency priority, with no added capacity.",
            "Even at the optimum 1 had no place, 1 of them needing trauma care, which no site in this file offers. "
            "That is the gap to test next: where that service could be staffed."])
        page = storm_plan.markup(plan())
        for words in ("One simulated patient, two decisions", 'data-case="P3"', "not placed (nearest facility full)",
                      "placed at Invented clinic one (mapped facility point; service and capacity simulated), "
                      "5 minutes of modelled travel", "For a district planner", "not treatment outcomes",
                      "The 4 patients placed under both policies travelled 24.5 minutes in total under nearest first "
                      "and 50.5 under the exact optimum", "To reproduce.", "Seed 3."):
            self.assertIn(words, page)

        def slotted(found):  # named slots: the optimum gives P3 the place nearest first gave to P2
            found["facilities"][0]["resources"] = [
                {"slot_id": "a", "service": "dialysis", "slots": 1, "start_minute": 0},
                {"slot_id": "b", "service": "dialysis", "slots": 1, "start_minute": 60}]
            found["facilities"][1]["resources"][0]["slot_id"] = "c"
            for patient, minute in (("P1", 1), ("P2", 2), ("P3", 30)):
                next(row for row in found["patients"] if row["id"] == patient)["arrival_minute"] = minute
            near, best = found["policies"]["nearest_first"], found["policies"]["exact_optimum"]
            near["assignments"][0]["slot_id"], near["assignments"][1]["slot_id"] = "a", "b"
            best["assignments"][0]["slot_id"], best["assignments"][1]["slot_id"] = "b", "a"
            best["assignments"][2]["slot_id"] = "c"

        seen = storm_plan.view(storm_plan.checked(changed(slotted)))["difference"]
        self.assertEqual(seen["holder"], {"id": "P2", "priority": "routine", "arrival": 2})
        self.assertEqual((seen["arrival"], seen["best"]["start"]), (30, 60))
        page = storm_plan.markup(changed(slotted))
        self.assertIn("Under nearest first that same place went to P2, a routine-priority patient, who arrived at "
                      "minute 2.", page)
        self.assertIn("in the place starting at minute 60", page)

        def same(found):  # identical results: nothing to single out, and the note says the places were enough
            found["policies"]["nearest_first"] = copy.deepcopy(found["policies"]["exact_optimum"])
            found["patients"] = [row for row in found["patients"] if row["id"] != "P6"]
            for result in found["policies"].values():
                result["unserved"] = []

        level = storm_plan.view(storm_plan.checked(changed(same)))
        self.assertIsNone(level["difference"])
        self.assertEqual(level["advice"], ["Both policies placed every simulated patient, so in this scenario the "
                                           "staffed places were enough."])
        self.assertNotIn("One simulated patient, two decisions", storm_plan.markup(changed(same)))

    def test_each_patient_class_and_service_is_counted_with_its_own_unmet_reasons(self):
        kinds = {"P1": "routine_scheduled", "P2": "routine_scheduled", "P3": "high_acuity_trauma",
                 "P4": "minor_injury", "P5": "routine_scheduled", "P6": "minor_injury"}

        def classed(found):
            for patient in found["patients"]:
                patient["patient_class"] = kinds[patient["id"]]
            found["facilities"][1]["resources"][1]["basis"] = "vf_only_record_text"

        found = storm_plan.checked(changed(classed))
        seen = storm_plan.view(found)
        self.assertEqual(seen["by_class"]["rows"], [
            {"group": "routine_scheduled", "patients": 3, "placed": [3, 3]},
            {"group": "high_acuity_trauma", "patients": 1, "placed": [0, 1]},
            {"group": "minor_injury", "patients": 2, "placed": [1, 1]}])
        self.assertEqual(seen["by_class"]["unmet"], [
            {"group": "high_acuity_trauma", "reason": "Nearest facility full", "counts": [1, 0]},
            {"group": "minor_injury", "reason": "No facility offers service", "counts": [1, 1]}])
        self.assertEqual(seen["by_service"]["rows"], [
            {"group": "dialysis", "patients": 3, "placed": [2, 3]},
            {"group": "mri", "patients": 2, "placed": [2, 2]},
            {"group": "trauma_care", "patients": 1, "placed": [0, 0]}])
        self.assertEqual([row["basis"] for row in seen["resources"]], ["Simulated", "Simulated", "Vf only record text"])
        page = storm_plan.markup(found)
        for words in ("By patient class", "High acuity trauma", "Minor injury", "Routine scheduled",
                      "By service needed", "<th>Patient class</th><th>Reason</th>", "Service and capacity basis",
                      "Vf only record text"):
            self.assertIn(words, page)
        # Without classes the same tables are by service, and no class table is drawn.
        plain_page = storm_plan.markup(plan())
        self.assertIsNone(storm_plan.view(plan())["by_class"])
        self.assertNotIn("By patient class", plain_page)
        self.assertIn("<th>Service</th><th>Reason</th>", plain_page)
        self.assertIn("By service needed", plain_page)

    def test_generated_sites_are_never_presented_as_real(self):
        def producer_fixture(found):  # the shape of the planner's default, synthetic output
            found["geography"].update(location_basis="synthetic", attribution=[])
            found["geography"].pop("roster_sha256")
            for facility in found["facilities"]:
                facility["precision"] = "point" if facility["precision"] != "area" else "area"
                facility.pop("source")

        found = storm_plan.checked(changed(producer_fixture))
        page = storm_plan.markup(found)
        self.assertFalse(storm_plan.real(found))
        self.assertIn('data-locations="simulated"', page)
        self.assertIn("no real place is shown", page)
        self.assertIn(storm_plan.SITES_NOTE, page)
        self.assertIn("Where the simulated sites are", page)
        self.assertIn("Not given", page)
        self.assertNotIn("Real facility locations", page)
        self.assertNotIn("Where the facilities are", page)
        self.assertEqual(storm_plan.choice(found), "Planning simulation: 6 simulated patients, simulated sites")
        self.assertIn("no actual hospital is represented", storm_plan.NOTICE_SYNTHETIC)
        self.assertNotIn("locations are real", storm_plan.NOTICE_SYNTHETIC)
        self.assertTrue(storm_plan.real(plan()))
        self.assertIn('data-locations="real"', storm_plan.markup(plan()))

    def test_only_the_approved_public_roster_with_its_provenance_is_shown_as_real(self):
        def pending(found):
            found["geography"]["location_basis"] = "pending_review"

        def unstated(found):
            del found["geography"]["location_basis"]

        def no_pin(found):
            del found["geography"]["roster_sha256"]

        def other_roster(found):
            found["geography"]["roster_sha256"] = "cd" * 32

        def no_credit(found):
            found["geography"]["attribution"] = []

        def generic_point(found):
            found["facilities"][0]["precision"] = "point"

        def no_source(found):
            del found["facilities"][1]["source"]

        def half_source(found):
            del found["facilities"][2]["source"]["license"]

        for change in (pending, unstated, no_pin, other_roster, no_credit, generic_point, no_source, half_source):
            with self.subTest(change=change.__name__), self.assertRaises((ValueError, KeyError)):
                storm_plan.checked(changed(change))
        storm_plan.checked(plan())
        # Outside these tests the invented plan is not an approved roster, whatever it claims.
        with mock.patch.object(storm_plan, "APPROVED_ROSTERS", {"b6" * 32}), self.assertRaises(ValueError):
            storm_plan.checked(plan())
        # The one roster approved in the code is the Pune public-source roster read back on the issue.
        self.assertEqual(type(storm_plan.APPROVED_ROSTERS), set)

    def test_the_code_approves_exactly_the_pune_roster(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.stopall()
        self.assertEqual(storm_plan.APPROVED_ROSTERS,
                         {"b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35"})
        with self.assertRaises(ValueError):
            storm_plan.checked(plan())

    def test_words_from_the_file_cannot_add_markup(self):
        def hostile(found):
            found["geography"]["name"] = "<script>alert(1)</script>"
            found["facilities"][0]["label"] = '<img src=x onerror="alert(1)">'
            found["policies"]["nearest_first"]["unserved"][0]["reason"] = "<b>full</b>"

        page = storm_plan.markup(storm_plan.checked(changed(hostile)))
        for mark in ("<script", "<img", "<b>"):
            self.assertNotIn(mark, page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_map_draws_each_precision_differently_and_patients_only_where_given(self):
        drawing = storm_plan.chart(plan())
        self.assertEqual(drawing.count("<title>"), 3)
        self.assertEqual(drawing.count("stroke-dasharray"), 1)  # the area-only ring
        self.assertEqual(drawing.count("<rect"), 1)  # the campus anchor
        self.assertEqual(drawing.count('r="2"'), 4)  # four of the six patients gave a starting point
        self.assertNotIn("href", drawing)

    def test_no_results_file_is_committed(self):
        self.assertFalse(storm_plan.FILE.exists(), "results appear only after the actual run, placed at deployment")


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")

def road_layer(**changes):
    """An invented road layer in the shape the view reads. No real road, name or credit."""
    layer = {
        "type": "FeatureCollection",
        "attribution": [{"text": "© Invented <map> contributors", "url": "https://example.invalid/copyright"},
                        {"text": "Invented distributor", "url": "https://example.invalid/distributor"}],
        "features": [
            {"type": "Feature", "properties": {"highway": "primary", "name": "Invented <Main> Road"},
             "geometry": {"type": "LineString", "coordinates": [[19.9, 10.16], [20.15, 10.16], [20.4, 10.17]]}},
            {"type": "Feature", "properties": {"highway": "residential", "name": "Invented Lane"},
             "geometry": {"type": "MultiLineString", "coordinates": [[[20.05, 10.05], [20.2, 10.06]],
                                                                     [[20.1, 10.0], [20.1, 10.2]]]}},
            {"type": "Feature", "properties": {"highway": "trunk", "name": "Far Away Highway"},
             "geometry": {"type": "LineString", "coordinates": [[40.0, 30.0], [40.5, 30.5]]}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [20.1, 10.1]}},
        ],
    }
    layer.update(changes)
    return layer


class RoadTests(unittest.TestCase):
    """Roads under the map of real locations: one reviewed file, pinned by its bytes, or no road at all."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "roads.geojson"
        self.raw = json.dumps(road_layer()).encode("utf-8")

    def approved(self, raw=None):
        return mock.patch.object(storm_plan, "APPROVED_ROADS", {hashlib.sha256(raw or self.raw).hexdigest()})

    def loaded(self, layer=None):
        raw = json.dumps(layer).encode("utf-8") if layer is not None else self.raw
        self.path.write_bytes(raw)
        with self.approved(raw):
            return storm_plan.load_roads(self.path)

    def test_the_road_file_is_not_in_the_repository_and_without_it_the_map_is_plain(self):
        self.assertFalse(storm_plan.ROADS_FILE.exists(), "the road layer is packaged at deployment, not committed")
        self.assertEqual(storm_plan.FILE.parent, storm_plan.ROADS_FILE.parent)
        self.assertIsNone(storm_plan.load_roads(self.path))
        page = storm_plan.markup(plan())
        self.assertNotIn("data-roads", page)
        self.assertNotIn("data-scale", page)
        self.assertIn("No roads or background map are drawn.", page)

    def test_only_the_reviewed_bytes_are_read(self):
        self.path.write_bytes(self.raw)
        self.assertIsNone(storm_plan.load_roads(self.path), "an unpinned file draws nothing")
        with self.approved():
            roads = storm_plan.load_roads(self.path)
            self.assertEqual(4, len(roads["lines"]))  # the point feature is ignored
            self.path.write_bytes(self.raw + b" ")
            self.assertIsNone(storm_plan.load_roads(self.path), "one changed byte draws nothing")
        self.assertEqual(64, len(next(iter(storm_plan.APPROVED_ROADS))))

    def test_a_layer_without_a_usable_credit_or_line_is_refused(self):
        for layer in (road_layer(attribution=[]), road_layer(features=[]),
                      road_layer(attribution=[{"text": "Credit", "url": "http://example.invalid/"}]),
                      road_layer(attribution=[{"text": " ", "url": "https://example.invalid/"}]),
                      {key: value for key, value in road_layer().items() if key != "attribution"},
                      road_layer(features=[{"type": "Feature", "properties": {}, "geometry": {
                          "type": "LineString", "coordinates": [[20.0, 10.0], [20.1, float("nan")]]}}]),
                      [1, 2]):
            with self.subTest(layer=str(layer)[:70]):
                self.assertIsNone(self.loaded(layer))
        self.path.write_bytes(b"x" * (storm_plan.ROADS_MAX_BYTES + 1))
        self.assertIsNone(storm_plan.load_roads(self.path))

    def test_roads_are_drawn_under_the_sites_with_a_scale_a_credit_and_a_plain_note(self):
        roads = self.loaded()
        drawing = storm_plan.chart(plan(), roads)
        self.assertIn('data-roads="shown"', drawing)
        self.assertEqual(2, drawing.count('stroke-linecap="round"'))  # one path for each road class in view
        self.assertLess(drawing.index('stroke-linecap="round"'), drawing.index("<circle"))
        self.assertLess(drawing.rindex('stroke-linecap="round"'), drawing.index("Invented clinic one"))
        self.assertRegex(drawing, r'data-scale="(0\.5|1|2|5|10|20|50) km"')
        self.assertIn("© Invented &lt;map&gt; contributors</text>", drawing)
        self.assertIn("Roads are drawn underneath for orientation.", drawing)
        # A main road is named once, escaped. A side street and a road outside the frame are not named.
        self.assertEqual(1, drawing.count("Invented &lt;Main&gt; Road</text>"))
        self.assertNotIn("<Main>", drawing)
        self.assertNotIn("Invented Lane", drawing)
        self.assertNotIn("Far Away Highway", drawing)

        page = storm_plan.markup(plan(), roads)
        self.assertIn(storm_plan.ROADS_NOTE, page)
        self.assertNotIn("No roads or background map are drawn.", page)
        self.assertIn('<a href="https://example.invalid/copyright" target="_blank" rel="noopener noreferrer">'
                      "© Invented &lt;map&gt; contributors</a>.", page)
        self.assertIn("Invented distributor</a>.", page)
        self.assertIn("</svg> road", page)

    def test_roads_can_be_left_out_and_are_never_drawn_under_simulated_sites(self):
        roads = self.loaded()
        self.assertNotIn("data-roads", storm_plan.markup(plan(), False))
        invented = changed(lambda found: found["geography"].update(location_basis="synthetic"))
        self.assertNotIn("data-roads", storm_plan.chart(invented, roads))
        self.assertNotIn("data-roads", storm_plan.markup(invented, roads))

    def test_a_layer_far_from_the_sites_draws_nothing_and_a_dense_one_drops_its_smallest_roads(self):
        far = self.loaded(road_layer(features=road_layer()["features"][2:3]))
        self.assertNotIn("data-roads", storm_plan.chart(plan(), far))
        roads = self.loaded()
        with mock.patch.object(storm_plan, "ROAD_BUDGET", 60):
            drawing = storm_plan.chart(plan(), roads)
        self.assertEqual(1, drawing.count('stroke-linecap="round"'))
        self.assertIn(f'stroke="{storm_plan.ROAD_TIERS[3][1]}"', drawing)  # the primary road stays

    def test_the_size_limit_is_firm_and_counts_the_line_drawing_as_written(self):
        import re
        bends = [[20.0 + step * 0.0002, 10.1 + (step % 2) * 0.0001] for step in range(1500)]
        dense = self.loaded(road_layer(features=[{"type": "Feature", "properties": {"highway": "primary"},
                                                  "geometry": {"type": "LineString", "coordinates": bends}}]))

        def written(drawing):
            return sum(len(path) for path in re.findall(r'<path d="([^"]*)" fill="none" stroke="[^"]*" '
                                                        r'stroke-width="[^"]*" stroke-linecap', drawing))

        full = written(storm_plan.chart(plan(), dense))
        self.assertGreater(full, 4000)
        for limit in (full, full - 1, full * 2 // 3, full // 2):
            with self.subTest(limit=limit), mock.patch.object(storm_plan, "ROAD_BUDGET", limit):
                drawing = storm_plan.chart(plan(), dense)
                self.assertLessEqual(written(drawing), limit)
                self.assertIn('data-roads="shown"', drawing)  # drawn more coarsely, not dropped
        with mock.patch.object(storm_plan, "ROAD_BUDGET", 20):  # not even the only road class fits: no road at all
            drawing = storm_plan.chart(plan(), dense)
        self.assertNotIn("data-roads", drawing)
        self.assertIn("No roads or background are drawn.", drawing)

    def test_the_published_edition_carries_its_distributor_and_licence_credits(self):
        edition = next(iter(storm_plan.APPROVED_ROADS))
        extra = storm_plan.ROAD_EDITION_CREDITS[edition]
        self.assertEqual(["Road extract distributed by Geofabrik GmbH", "Open Database License (ODbL) 1.0"],
                         [credit["text"] for credit in extra])
        self.assertTrue(all(credit["url"].startswith("https://") for credit in extra))
        digest = hashlib.sha256(self.raw).hexdigest()
        self.path.write_bytes(self.raw)
        with self.approved(), mock.patch.dict(storm_plan.ROAD_EDITION_CREDITS, {digest: extra + (
                {"text": "Invented distributor", "url": "https://example.invalid/again"},)}):
            roads = storm_plan.load_roads(self.path)
            page = storm_plan.markup(plan(), roads)
        self.assertEqual(["© Invented <map> contributors", "Invented distributor",
                          "Road extract distributed by Geofabrik GmbH", "Open Database License (ODbL) 1.0"],
                         [credit["text"] for credit in roads["attribution"]])  # a credit the file gives is not repeated
        self.assertIn('<a href="https://www.geofabrik.de/" target="_blank" rel="noopener noreferrer">'
                      "Road extract distributed by Geofabrik GmbH</a>.", page)
        self.assertIn("No patient routes are shown", page)


class WordingTests(unittest.TestCase):
    def test_codes_become_words_and_medical_initials_stay_in_capitals(self):
        self.assertEqual("MRI", storm_plan._plain("mri"))
        self.assertEqual("Time sensitive", storm_plan._plain("time_sensitive"))
        self.assertEqual("CT scan", storm_plan._plain("ct_scan"))
        self.assertEqual("MRI", storm_plan._inline("mri"))
        self.assertEqual("trauma care", storm_plan._inline("trauma_care"))
        self.assertEqual("highest", storm_plan._inline("highest"))

    def test_an_observation_time_is_written_out_in_utc_and_anything_else_is_left_alone(self):
        self.assertEqual("22 November 2026, 17:40 UTC", storm_plan._when("2026-11-22T17:40:00Z"))
        self.assertEqual("22 November 2026, 17:40 UTC", storm_plan._when("2026-11-22T23:10:00+05:30"))
        self.assertEqual("2026-11-22T17:40:00", storm_plan._when("2026-11-22T17:40:00"))
        self.assertEqual("soon", storm_plan._when("soon"))

    def test_a_long_hash_can_wrap_on_a_narrow_screen(self):
        self.assertIn(".sp-facts li { margin-bottom: 0.3rem; overflow-wrap: anywhere; }", storm_plan.STYLE)


class ScreenTests(unittest.TestCase):
    def setUp(self):
        bare = ("find_care", "data_access", "ranking", "patient_ui", "patient_intake", "storm_page", "storm_plan")
        saved = {name: module for name, module in sys.modules.items() if name.split(".")[0] in bare}
        for name in saved:
            del sys.modules[name]
        sys.path.insert(0, str(APP))

        def restore():
            sys.path.remove(str(APP))
            for name in [name for name in sys.modules if name.split(".")[0] in bare]:
                del sys.modules[name]
            sys.modules.update(saved)

        self.addCleanup(restore)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABRICKS_", "FIND_CARE_", "PATIENT_"))}
        env["FIND_CARE_DATA"] = "demo"
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        self.file = Path(folder) / "plan.json"
        import storm_plan as bare_plan
        self.plan = bare_plan
        approved = mock.patch.object(bare_plan, "APPROVED_ROSTERS", {TEST_ROSTER})
        approved.start()
        self.addCleanup(approved.stop)
        placed = mock.patch.object(bare_plan, "FILE", self.file)
        placed.start()
        self.addCleanup(placed.stop)

    def storm(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return self.run_(next(radio for radio in app.radio if radio.key == "view").set_value("Storm demo (simulated)"))

    def run_(self, action):
        app = action.run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def views(app):
        return [radio for radio in app.radio if radio.key == "storm_view"]

    def test_without_results_the_storm_page_is_the_checked_replay_alone(self):
        app = self.storm()
        self.assertEqual(self.views(app), [])
        self.assertEqual(len(app.get("iframe")), 1)
        self.assertFalse([node for node in app.markdown if "data-plan=" in node.value])

    def test_a_file_that_does_not_hold_together_is_not_offered(self):
        broken = copy.deepcopy(plan())
        broken["policies"]["exact_optimum"]["assignments"][0]["facility"] = "F3"
        self.file.write_text(json.dumps(broken), encoding="utf-8")
        app = self.storm()
        self.assertEqual(self.views(app), [])
        self.assertEqual(len(app.get("iframe")), 1)

    def test_with_results_the_replay_stays_first_and_the_plan_is_one_choice_away(self):
        import storm_page as page
        self.file.write_text(json.dumps(plan()), encoding="utf-8")
        app = self.storm()
        switch = self.views(app)[0]
        self.assertEqual(switch.options, [page.REPLAY, "Planning simulation: 6 simulated patients, real locations"])
        self.assertEqual(switch.value, page.REPLAY)
        self.assertEqual(len(app.get("iframe")), 1)
        self.assertEqual([warning.value for warning in app.warning], [page.SIMULATED])
        app = self.run_(switch.set_value(switch.options[1]))
        self.assertEqual([warning.value for warning in app.warning], [self.plan.NOTICE])
        self.assertEqual(len(app.get("iframe")), 0)
        section = [node.value for node in app.markdown if "data-plan=" in node.value]
        self.assertEqual(len(section), 1)
        self.assertIn("Invented district: 6 simulated patients, 3 facilities, 5 staffed places", section[0])
        self.assertIn("5 of 6 placed", section[0])
        self.assertEqual(dict(app.session_state["patient"]), {"visit": 0})
        # Back to the checked replay, then to the other screens.
        app = self.run_(self.views(app)[0].set_value(page.REPLAY))
        self.assertEqual(len(app.get("iframe")), 1)
        app = self.run_(next(radio for radio in app.radio if radio.key == "view").set_value("Check symptoms"))
        self.assertFalse([node for node in app.markdown if "data-plan=" in node.value])


if __name__ == "__main__":
    unittest.main()
