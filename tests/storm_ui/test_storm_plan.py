"""The planning simulation on the Storm page. Every plan here is invented, including its geography."""
import copy
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
                                                         {"service": "mri", "slots": 2}]},
            {"id": "F3", "label": "Invented clinic three", "latitude": 10.1, "longitude": 20.1,
             "precision": "area", "resources": []},
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


class PlanTests(unittest.TestCase):
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

        for change in (twice, wrong_service, other_need, over, lost, both, precision, link, script, no_objective,
                       one_policy, version, far, order):
            with self.subTest(change=change.__name__), self.assertRaises((ValueError, KeyError, TypeError)):
                storm_plan.checked(changed(change))
        self.assertIs(type(storm_plan.checked(plan())), dict)

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
                      "Example publisher (node/1)", "Example licence", "Not given", "Roster SHA-256", "Tests only",
                      "No roads or background map are drawn"):
            self.assertIn(words, page)
        self.assertIn("simulated", storm_plan.NOTICE)
        self.assertIn("not a record of a real storm", storm_plan.NOTICE)
        self.assertEqual(page.count('href="'), 3)  # the map credit twice and one facility source
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))

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
