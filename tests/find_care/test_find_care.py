import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from app import find_care as words
from app.ranking import search_facilities

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "contracts/fixtures/search.json").read_text(encoding="utf-8"))
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def _run(query):
    response = search_facilities(**query, facilities=FIXTURE["facilities"])
    return response, words.present(response, query["service"], query["location"], query.get("radius_km", 50))


class WordingTests(unittest.TestCase):
    def test_every_fixture_case_is_worded_without_reordering(self):
        seen = set()
        for case in FIXTURE["cases"]:
            response, view = _run(case["query"])
            seen.add(view["status"])
            self.assertEqual(case["expected"]["status"], view["status"], case["id"])
            shown = [card["facility_id"] for card in [view["top"], *view["backups"]] if card]
            self.assertEqual([card["facility_id"] for card in response["direct_results"]], shown, case["id"])
            self.assertEqual([card["facility_id"] for card in response["indirect_leads"]],
                             [card["facility_id"] for card in view["leads"]], case["id"])
            for card, raw in zip([c for c in [view["top"], *view["backups"]] if c] + view["leads"],
                                 response["direct_results"] + response["indirect_leads"]):
                self.assertEqual(raw["evidence_excerpt"], card["excerpt"], case["id"])
                self.assertEqual(raw["record_source_urls"], card["sources"], case["id"])
            if view["status"] != "ok":
                self.assertIsNone(view["top"], case["id"])
                self.assertIsNone(view["why"], case["id"])
                self.assertNotIn("Send to", words.referral_note(view, True), case["id"])
        self.assertLessEqual({"ok", "needs_confirmation", "no_match", "ambiguous_location", "invalid_input"}, seen)

    def test_a_recommendation_cites_its_record_and_carries_the_caveat(self):
        _, view = _run({"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}})
        self.assertEqual("Send the patient to Example Regional Hospital.", view["headline"])
        self.assertIn("nearest facility within 50 km whose record directly says it offers dialysis", view["why"])
        self.assertEqual("The North Campus provides hemodialysis.", view["top"]["excerpt"])
        self.assertEqual("procedures", view["top"]["field"])
        self.assertIn("Phone to confirm", view["caveat"])
        self.assertIsNotNone(view["approximate_note"])
        note = words.referral_note(view, synthetic=True)
        for part in ("demonstration data", "Send to: Example Regional Hospital", "The North Campus provides hemodialysis.",
                     "Record source: https://example.invalid/north-campus", "Before travelling"):
            self.assertIn(part, note)
        self.assertNotIn("demonstration", words.referral_note(view, synthetic=False))

    def test_only_is_said_exactly_when_one_facility_qualifies(self):
        _, view = _run({"service": "mri", "location": {"latitude": 26.92, "longitude": 75.82}})
        self.assertIn("the only facility", view["why"])
        self.assertEqual([], view["backups"])

    def test_weak_evidence_and_failures_recommend_nothing(self):
        _, leads = _run({"service": "dialysis", "location": {"pin": "302001"}, "radius_km": 2})
        self.assertEqual("No facility within 2 km clearly offers dialysis.", leads["headline"])
        self.assertIn("Phone before sending anyone", leads["subline"])
        self.assertIn("Phone first: Example Community Clinic", words.referral_note(leads, True))
        down = words.present({"status": "unavailable", "direct_results": [], "indirect_leads": [],
                              "location_choices": [], "approximate_location": False,
                              "message": "The facility warehouse is unavailable. Try again shortly."},
                             "mri", {"pin": "302001"}, 50)
        self.assertEqual("The facility records cannot be reached right now.", down["headline"])
        _, missing = _run({"service": "mri", "location": {"pin": "999999"}})
        self.assertEqual("That place could not be located.", missing["headline"])

    def test_typed_locations(self):
        self.assertEqual({"city": "Jaipur"}, words.build_location("city", city=" Jaipur ", state=" "))
        self.assertEqual({"city": "Jaipur", "state": "Rajasthan"}, words.build_location("city", city="Jaipur", state="Rajasthan"))
        self.assertEqual({"pin": "302001"}, words.build_location("pin", pin="302 001"))
        self.assertEqual({"latitude": 26.92, "longitude": 75.82}, words.build_location("coordinates", latitude="26.92", longitude=" 75.82"))
        for mode, typed in (("city", {"city": " "}), ("pin", {"pin": ""}), ("coordinates", {"latitude": "north", "longitude": "1"})):
            with self.assertRaises(ValueError):
                words.build_location(mode, **typed)


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")
class ScreenTests(unittest.TestCase):
    def _app(self, **env):
        from streamlit.testing.v1 import AppTest
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DATABRICKS_")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            app = AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app, {**clean, **env}

    def _step(self, action, env):
        with mock.patch.dict(os.environ, env, clear=True):
            app = action.run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def _text(app):
        return " ".join(node.value for kind in ("title", "header", "subheader", "markdown", "caption", "warning", "error", "code")
                        for node in getattr(app, kind))

    def test_the_judge_path_on_demonstration_data(self):
        app, env = self._app()
        text = self._text(app)
        self.assertIn("six invented facilities", text)
        self.assertIn("The recommendation appears here.", text)
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click(), env)
        text = self._text(app)
        for part in ("Send the patient to Example Regional Hospital.", "North Campus provides hemodialysis",
                     "procedures field", "Phone to confirm", "How this was decided", "example.invalid"):
            self.assertIn(part, text)
        self.assertIn("Send to: Example Regional Hospital", app.code[0].value)
        app = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click(), env)
        self.assertIn("No facility within 2 km clearly offers dialysis.", self._text(app))

    def test_typed_city_asks_which_place_then_answers(self):
        app, env = self._app()
        app.text_input(key="city").set_value("Jaipur")
        app = self._step(app.button(key="FormSubmitter:ask-Find a facility").click(), env)
        self.assertIn("More than one place has that name.", self._text(app))
        app = self._step(app.button(key="choice-Jaipur, Rajasthan").click(), env)
        self.assertIn("Send the patient to Example Regional Hospital.", self._text(app))

    def test_an_empty_location_is_refused_in_plain_words(self):
        app, env = self._app()
        app = self._step(app.button(key="FormSubmitter:ask-Find a facility").click(), env)
        self.assertIn("Type the city or town.", self._text(app))
        self.assertNotIn("Send the patient", self._text(app))

    def test_live_mode_reports_an_unreachable_table_and_recommends_nothing(self):
        app, env = self._app(DATABRICKS_WAREHOUSE_ID="test-warehouse", DATABRICKS_PREPARED_TABLE="c.s.t")
        self.assertIn("Virtue Foundation facility records", self._text(app))
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click(), env)
        text = self._text(app)
        self.assertIn("The facility records cannot be reached right now.", text)
        self.assertNotIn("Send the patient", text)


if __name__ == "__main__":
    unittest.main()
