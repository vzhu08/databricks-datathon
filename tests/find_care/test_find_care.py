import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from app import find_care as words
from app.ranking import search_facilities

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "contracts/fixtures/search.json").read_text(encoding="utf-8"))
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
APP = ROOT / "app"
WAREHOUSE = {"DATABRICKS_WAREHOUSE_ID": "test-warehouse", "DATABRICKS_PREPARED_TABLE": "test_catalog.test_schema.prepared",
             "DATABRICKS_HOST": "https://workspace.example.invalid", "DATABRICKS_CLIENT_ID": "test-client",
             "DATABRICKS_CLIENT_SECRET": "test-secret"}
SETTINGS = ("DATABRICKS_", words.DATA_SETTING)


def restricted(response=None):
    """Every facility field a real-record screen must not show: from the fixture rows, or from one response."""
    found = set()
    for row in FIXTURE["facilities"]:
        found |= {row["facility_id"], row["raw_row_ref"], row["name"], *row["record_source_urls"]}
        found |= {entry for field in ("description", "capabilities", "procedures", "equipment")
                  for entry in ([row[field]] if isinstance(row[field], str) else row[field] or [])}
    for card in (response or {}).get("direct_results", []) + (response or {}).get("indirect_leads", []):
        found |= {card["facility_id"], card["name"], card["evidence_excerpt"], *card["record_source_urls"]}
    return {text for text in found if text}


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
        self.assertEqual("About 6.7 km away, in a straight line.", view["top"]["distance"])
        self.assertIn("so they are approximate", view["approximate_note"])
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
        self.assertEqual("Less than 100 m away, in a straight line.", leads["leads"][0]["distance"])
        self.assertIn("Phone first: Example Community Clinic", words.referral_note(leads, True))
        down = words.present({"status": "unavailable", "direct_results": [], "indirect_leads": [],
                              "location_choices": [], "approximate_location": False,
                              "message": "The facility warehouse is unavailable. Try again shortly."},
                             "mri", {"pin": "302001"}, 50)
        self.assertEqual("The facility records cannot be reached right now.", down["headline"])
        _, missing = _run({"service": "mri", "location": {"pin": "999999"}})
        self.assertEqual("That place could not be located.", missing["headline"])

    def test_data_mode_is_explicit_and_a_half_configured_warehouse_is_a_setup_problem(self):
        self.assertEqual({"mode": "demo", "problems": []}, words.data_mode({}))
        self.assertEqual({"mode": "warehouse", "problems": []}, words.data_mode(WAREHOUSE))
        self.assertEqual("demo", words.data_mode({**WAREHOUSE, "FIND_CARE_DATA": "demo"})["mode"])
        self.assertEqual("warehouse", words.data_mode({**WAREHOUSE, "FIND_CARE_DATA": " Warehouse "})["mode"])
        for missing in WAREHOUSE:
            partial = {name: value for name, value in WAREHOUSE.items() if name != missing}
            for environ in (partial, {**partial, missing: "  "}, {**partial, "FIND_CARE_DATA": "warehouse"}):
                mode = words.data_mode(environ)
                self.assertEqual("setup", mode["mode"], missing)
                self.assertEqual(1, len(mode["problems"]), missing)
                self.assertTrue(mode["problems"][0].startswith(missing + " is not set."), mode["problems"])
        self.assertEqual("setup", words.data_mode({"FIND_CARE_DATA": "warehouse"})["mode"])
        # Any one of the five settings on its own means the real records were intended.
        host = {"DATABRICKS_HOST": WAREHOUSE["DATABRICKS_HOST"]}
        identity = {name: WAREHOUSE[name] for name in ("DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET")}
        for present in (host, identity, {**host, **identity}, *({name: WAREHOUSE[name]} for name in WAREHOUSE)):
            mode = words.data_mode(present)
            self.assertEqual("setup", mode["mode"], sorted(present))
            self.assertEqual([name + " is not set." for name in WAREHOUSE if name not in present],
                             [problem.split(" is not set.")[0] + " is not set." for problem in mode["problems"]])
            self.assertEqual("demo", words.data_mode({**present, "FIND_CARE_DATA": "demo"})["mode"], sorted(present))
            for value in present.values():
                self.assertNotIn(value, " ".join(mode["problems"]))
        self.assertEqual("demo", words.data_mode({name: "  " for name in WAREHOUSE})["mode"])
        self.assertEqual(["FIND_CARE_DATA must be demo or warehouse."],
                         words.data_mode({**WAREHOUSE, "FIND_CARE_DATA": "live"})["problems"])
        shaped = words.data_mode({**WAREHOUSE, "DATABRICKS_PREPARED_TABLE": "private_schema.private_table"})
        self.assertEqual(["DATABRICKS_PREPARED_TABLE must be written as catalog.schema.table."], shaped["problems"])
        for mode in (shaped, words.data_mode({"DATABRICKS_WAREHOUSE_ID": "secret-warehouse-id"})):
            self.assertNotIn("private_", " ".join(mode["problems"]))
            self.assertNotIn("secret-warehouse-id", " ".join(mode["problems"]))

    def test_a_withheld_response_keeps_no_facility_field_and_words_no_referral(self):
        for case in FIXTURE["cases"]:
            query = case["query"]
            response = search_facilities(**query, facilities=FIXTURE["facilities"])
            kept = words.withheld(response)
            kept_text = json.dumps(kept)
            for text in restricted(response) | {choice["state"] for choice in response["location_choices"]}:
                self.assertNotIn(json.dumps(text)[1:-1], kept_text, case["id"])
            self.assertEqual(([], [], []), (kept["direct_results"], kept["indirect_leads"], kept["location_choices"]))
            self.assertNotIn(kept["status"], ("ok", "needs_confirmation"), case["id"])
            view = words.present(kept, query["service"], query["location"], query.get("radius_km", 50))
            self.assertEqual((None, [], [], [], None, None),
                             (view["top"], view["backups"], view["leads"], view["choices"], view["why"], view["caveat"]))
            for surface in (view["headline"], view["subline"], words.referral_note(view, False)):
                self.assertNotIn("Send", surface, case["id"])
            if response["status"] in ("ok", "needs_confirmation"):
                self.assertEqual("withheld", kept["status"], case["id"])
                self.assertEqual("No facility is recommended from the real records yet.", view["headline"])
                self.assertIn("none has been reviewed and approved", view["subline"])
        unknown = words.withheld({"status": "future_status", "message": "Example Regional Hospital", "direct_results": [{}]})
        self.assertEqual((None, []), (unknown["message"], unknown["direct_results"]))

    def test_the_demonstration_facilities_inside_the_app_folder_are_the_shared_fixture(self):
        self.assertEqual((ROOT / "contracts/fixtures/search.json").read_bytes(), (APP / "demo_facilities.json").read_bytes())

    def test_one_typed_line_is_read_as_a_city_a_pin_or_coordinates(self):
        for typed, expected in (("Jaipur, Rajasthan", {"city": "Jaipur", "state": "Rajasthan"}),
                                ("  jaipur ", {"city": "jaipur"}), ("St. John's, Kerala", {"city": "St. John's", "state": "Kerala"}),
                                ("302001", {"pin": "302001"}), ("302 001", {"pin": "302001"}),
                                ("26.92, 75.82", {"latitude": 26.92, "longitude": 75.82}),
                                ("26.92 75.82", {"latitude": 26.92, "longitude": 75.82}),
                                ("-12, 77", {"latitude": -12.0, "longitude": 77.0})):
            self.assertEqual(expected, words.parse_location(typed), typed)
            self.assertEqual(expected, words.parse_location(words.location_text(expected)), typed)
        for typed, message in (("", "Type a city or town, a PIN code, or coordinates."), ("   ", "Type a city or town"),
                               ("12345", "A PIN code has six digits."), ("26.92", "latitude, then longitude"),
                               (", Rajasthan", "before the comma")):
            with self.assertRaises(ValueError) as refused:
                words.parse_location(typed)
            self.assertIn(message, str(refused.exception), typed)
        # Every example distance on the screen is one the distance control offers.
        self.assertIn(2, words.RADII)
        self.assertEqual(sorted(words.RADII), list(words.RADII))

    def test_messy_typed_places_are_cleaned_before_the_search(self):
        for typed, expected in (
                ("Pune, MH", {"city": "Pune", "state": "Maharashtra"}), ("Jaipur, rj", {"city": "Jaipur", "state": "Rajasthan"}),
                ("Lucknow, U.P.", {"city": "Lucknow", "state": "Uttar Pradesh"}), ("Cuttack, Orissa", {"city": "Cuttack", "state": "Odisha"}),
                ("Pune Maharashtra", {"city": "Pune", "state": "Maharashtra"}), ("Bhopal Madhya Pradesh", {"city": "Bhopal", "state": "Madhya Pradesh"}),
                ("Pune MH", {"city": "Pune", "state": "Maharashtra"}), ("near Pune", {"city": "Pune"}), ("in Bhopal, MP.", {"city": "Bhopal", "state": "Madhya Pradesh"}),
                ("Pune, India", {"city": "Pune"}), ("Pune city", {"city": "Pune"}), ("Nashik district", {"city": "Nashik"}), ("PUNE.", {"city": "PUNE"}),
                ("Bombay", {"city": "Mumbai"}), ("Calcutta, West Bengal", {"city": "Kolkata", "state": "West Bengal"}), ("madras", {"city": "Chennai"}),
                ("PIN 560034", {"pin": "560034"}), ("Pincode: 560 034", {"pin": "560034"}), ("560-034", {"pin": "560034"}),
                ("560034, India", {"pin": "560034"}), ("Jaipur 302001", {"pin": "302001"}),
                ("near 26.92, 75.82", {"latitude": 26.92, "longitude": 75.82})):
            self.assertEqual(expected, words.parse_location(typed), typed)
        # names that only look like a state code, a state that is also a city, and real names ending in "City" stay whole
        for typed, expected in (("New Delhi", {"city": "New Delhi"}), ("Delhi", {"city": "Delhi"}), ("Goa", {"city": "Goa"}),
                                ("pune mh", {"city": "pune mh"}), ("Bokaro Steel City", {"city": "Bokaro Steel City"}),
                                ("Bangalore", {"city": "Bangalore"}), ("Gurgaon, Haryana", {"city": "Gurgaon", "state": "Haryana"})):
            self.assertEqual(expected, words.parse_location(typed), typed)

    def test_typed_locations(self):
        self.assertEqual({"city": "Jaipur"}, words.build_location("city", city=" Jaipur ", state=" "))
        self.assertEqual({"city": "Jaipur", "state": "Rajasthan"}, words.build_location("city", city="Jaipur", state="Rajasthan"))
        self.assertEqual({"pin": "302001"}, words.build_location("pin", pin="302 001"))
        self.assertEqual({"latitude": 26.92, "longitude": 75.82}, words.build_location("coordinates", latitude="26.92", longitude=" 75.82"))
        for mode, typed in (("city", {"city": " "}), ("pin", {"pin": ""}), ("coordinates", {"latitude": "north", "longitude": "1"})):
            with self.assertRaises(ValueError):
                words.build_location(mode, **typed)


class FakeWarehouse:
    """A connection that answers the adapter's three statements from prepared rows, or fails on connect."""

    def __init__(self, rows=None, error=None):
        self.rows, self.error, self.statements = rows or [], error, []

    def __call__(self, _environ):
        if self.error:
            raise self.error
        return self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        pass

    def execute(self, statement, parameters=None):
        self.statements.append(statement)
        place = (parameters or {}).get("place")
        if "trim(pin) = :place" in statement:
            found = [row for row in self.rows if str(row["pin"]).strip() == place]
        elif "= :place" in statement:
            found = [row for row in self.rows if " ".join(str(row["city"]).split()).lower() == place]
        else:
            found = list(self.rows)
        columns = list(found[0]) if found else []
        self.description = [(column,) for column in columns]
        self._found = [tuple(row[column] for column in columns) for row in found]

    def fetchall(self):
        return self._found


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")
class ScreenTests(unittest.TestCase):
    def setUp(self):
        # The screen imports its neighbours by bare name, as it does when app/ is the deployment root.
        # Under test discovery those names can already belong to the test packages, so give them to app/
        # for the length of one test and hand them back afterwards.
        bare = ("find_care", "data_access", "ranking")
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
        import data_access.warehouse as adapter
        self.adapter = adapter

    def _app(self, warehouse=None, **env):
        from streamlit.testing.v1 import AppTest
        clean = {k: v for k, v in os.environ.items() if not k.startswith(SETTINGS)}
        self.env = {**clean, **env}
        patcher = mock.patch.object(self.adapter, "_connect_from_environment",
                                    warehouse or FakeWarehouse(error=AssertionError("no warehouse in this test")))
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.dict(os.environ, self.env, clear=True):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _step(self, action):
        with mock.patch.dict(os.environ, self.env, clear=True):
            app = action.run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def _text(app):
        return " ".join(node.value for kind in ("title", "header", "subheader", "markdown", "caption", "warning", "error", "code")
                        for node in getattr(app, kind))

    @staticmethod
    def _everything(app):
        """Every element the screen sent to the browser, as text, plus all it keeps in session state."""
        def walk(node):
            yield str(getattr(node, "proto", ""))
            for child in getattr(node, "children", {}).values():
                yield from walk(child)
        state = {key: app.session_state[key] for key in ("asked", "response") if key in app.session_state}
        return "\n".join(walk(app._tree)) + "\n" + json.dumps(state, default=str)

    def _assert_nothing_restricted(self, app, response=None):
        shown = self._everything(app)
        self.assertGreater(len(shown), 500)  # the walk really collected the page
        for text in restricted(response):
            self.assertNotIn(text, shown)
            self.assertNotIn(json.dumps(text)[1:-1], shown)
        for surface in ("Send the patient", "Send to", "Referral note", "cannot take the patient", "Record sources",
                        "Phone first", "example.invalid", "evidence_excerpt", "facility_id", "km away", "m away", 'fc-record\\">',
                        'fc-quote\\">', "Why this facility", "What its record says"):
            self.assertNotIn(surface, shown)
        if "response" in app.session_state:
            kept = app.session_state["response"]
            self.assertEqual(([], [], []), (kept["direct_results"], kept["indirect_leads"], kept["location_choices"]))
        self.assertEqual(0, len(app.get("download_button")))
        self.assertEqual(0, len(app.code))
        self.assertEqual([], [button.key for button in app.button if str(button.key).startswith("choice-")])

    def test_the_judge_path_on_demonstration_data(self):
        app = self._app()
        text = self._text(app)
        self.assertIn("Data: demonstration.", text)
        self.assertIn("six invented facilities", text)
        self.assertIn("The recommendation appears here.", text)
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        text = self._text(app)
        for part in ("Send the patient to Example Regional Hospital.", "North Campus provides hemodialysis",
                     "procedures field", "Phone to confirm", "How this was decided", "example.invalid",
                     "cannot take the patient"):
            self.assertIn(part, text)
        for part in ("Why this facility", "What its record says", "About 6.7 km away, in a straight line."):
            self.assertIn(part, text)
        self.assertIn("Send to: Example Regional Hospital", app.code[0].value)
        self.assertEqual(1, len(app.get("download_button")))
        # An example fills the form, so the form always shows what the answer is for.
        self.assertEqual(("dialysis", "Jaipur, Rajasthan", 50),
                         (app.radio(key="service").value, app.text_input(key="where").value,
                          app.select_slider(key="radius").value))
        self.assertNotIn("You changed the request", text)
        app = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click())
        self.assertIn("No facility within 2 km clearly offers dialysis.", self._text(app))
        self.assertEqual(("302001", 2), (app.text_input(key="where").value, app.select_slider(key="radius").value))

    def test_the_first_press_answers_because_the_demonstration_form_starts_filled(self):
        app = self._app()
        self.assertEqual("Jaipur, Rajasthan", app.text_input(key="where").value)
        app = self._step(app.button(key="find").click())
        self.assertIn("Send the patient to Example Regional Hospital.", self._text(app))
        self.assertEqual(0, len(app.error))

    def test_a_changed_request_marks_the_answer_out_of_date_and_takes_the_note_away(self):
        app = self._app()
        app = self._step(app.button(key="find").click())
        self.assertEqual((1, 1), (len(app.code), len(app.get("download_button"))))
        for change in (lambda a: a.radio(key="service").set_value("mri"),
                       lambda a: a.text_input(key="where").set_value("302001"),
                       lambda a: a.select_slider(key="radius").set_value(10)):
            changed = self._step(change(app))
            text = self._text(changed)
            self.assertIn("You changed the request. The answer below is for the earlier one.", text)
            self.assertIn("fc-old", text)
            self.assertEqual((0, 0), (len(changed.code), len(changed.get("download_button"))))
            self.assertNotIn("cannot take the patient", text)
            self.assertIn("Dialysis near Jaipur, Rajasthan, within 50 km.", text)  # still says what it answers
            # Putting the request back, or asking again, makes the answer current.
            back = self._step(changed.button(key="example-Dialysis near Jaipur, Rajasthan").click())
            self.assertNotIn("You changed the request", self._text(back))
            self.assertEqual((1, 1), (len(back.code), len(back.get("download_button"))))
            app = back
        app.radio(key="service").set_value("mri")
        app = self._step(app.button(key="find").click())
        text = self._text(app)
        self.assertNotIn("You changed the request", text)
        self.assertIn("MRI scan near Jaipur, Rajasthan, within 50 km.", text)

    def test_demonstration_can_be_chosen_outright_beside_warehouse_settings(self):
        app = self._app(**WAREHOUSE, FIND_CARE_DATA="demo")
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        self.assertIn("Data: demonstration.", self._text(app))
        self.assertIn("Send the patient to Example Regional Hospital.", self._text(app))

    def test_typed_city_asks_which_place_then_answers(self):
        app = self._app()
        app.text_input(key="where").set_value("Jaipur")
        app = self._step(app.button(key="find").click())
        self.assertIn("More than one place has that name.", self._text(app))
        app = self._step(app.button(key="choice-Jaipur, Rajasthan").click())
        self.assertIn("Send the patient to Example Regional Hospital.", self._text(app))
        self.assertEqual("Jaipur, Rajasthan", app.text_input(key="where").value)
        self.assertNotIn("You changed the request", self._text(app))

    def test_an_empty_location_is_refused_in_plain_words(self):
        app = self._app()
        app = self._step(app.button(key="find").click())
        app.text_input(key="where").set_value("")
        app = self._step(app.button(key="find").click())
        self.assertIn("Type a city or town, a PIN code, or coordinates.", self._text(app))
        self.assertNotIn("Send the patient", self._text(app))  # the earlier answer is gone, not left standing
        self.assertEqual((0, 0), (len(app.code), len(app.get("download_button"))))

    def test_a_direct_statement_in_the_warehouse_never_becomes_a_referral(self):
        """The v0 search answers "ok" here only because a record states the service. The screen withholds it."""
        warehouse = FakeWarehouse(FIXTURE["facilities"])
        location = {"city": "Jaipur", "state": "Rajasthan"}
        with mock.patch.dict(os.environ, WAREHOUSE, clear=True), \
                mock.patch.object(self.adapter, "_connect_from_environment", warehouse):
            raw = self.adapter.search_warehouse("dialysis", location)
        self.assertEqual("ok", raw["status"])
        self.assertEqual(2, len(raw["direct_results"]))
        self.assertTrue(all(card["evidence_strength"] == "direct" and card["evidence_excerpt"]
                            for card in raw["direct_results"]))
        self.assertTrue(any(card["record_source_urls"] for card in raw["direct_results"]))

        app = self._app(warehouse, **WAREHOUSE)
        self.assertIn("Data: real records.", self._text(app))
        self._assert_nothing_restricted(app)
        asked = len(warehouse.statements)
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        self.assertGreater(len(warehouse.statements), asked)  # the stub warehouse really answered
        text = self._text(app)
        self.assertIn("No facility is recommended from the real records yet.", text)
        self.assertIn("Records within 50 km mention dialysis, but none has been reviewed and approved", text)
        self.assertIn("names none, shows no record text or links, and offers no referral note", text)
        self._assert_nothing_restricted(app, raw)
        self.assertEqual({"request": {"service": "dialysis", "location": location, "radius_km": 50},
                          "data": "warehouse", "status": "withheld"}, json.loads(app.json[0].value))

        # Related-only evidence, a typed ambiguous city and a plain miss are withheld the same way.
        app = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click())
        self.assertIn("mention something related to dialysis, but none has been reviewed", self._text(app))
        self._assert_nothing_restricted(app)
        app.text_input(key="where").set_value("Jaipur")
        app = self._step(app.button(key="find").click())
        self.assertIn("More than one place has that name.", self._text(app))
        self.assertIn("Type the state as well and search again", self._text(app))
        self._assert_nothing_restricted(app)
        app.radio(key="service").set_value("trauma_care")
        app.text_input(key="where").set_value("Jaipur, Rajasthan")
        app.select_slider(key="radius").set_value(10)
        app = self._step(app.button(key="find").click())
        self._assert_nothing_restricted(app)
        # A changed request is marked on real records too, and still shows nothing restricted.
        app = self._step(app.radio(key="service").set_value("mri"))
        self.assertIn("You changed the request", self._text(app))
        self._assert_nothing_restricted(app)

    def test_a_half_configured_warehouse_reports_the_setup_problem_and_shows_no_invented_data(self):
        for missing, expected in (("DATABRICKS_PREPARED_TABLE", "DATABRICKS\\_PREPARED\\_TABLE is not set"),
                                  ("DATABRICKS_WAREHOUSE_ID", "DATABRICKS\\_WAREHOUSE\\_ID is not set"),
                                  ("DATABRICKS_CLIENT_SECRET", "DATABRICKS\\_CLIENT\\_SECRET is not set")):
            app = self._app(**{name: value for name, value in WAREHOUSE.items() if name != missing})
            text = self._text(app)
            self.assertIn("Data: not available.", text)
            self.assertIn("its setup is incomplete", text)
            self.assertIn(expected, text)
            self.assertNotIn("demonstration.", text)
            self.assertNotIn("invented facilities, not the real records", text)
            self.assertEqual([], [button.key for button in app.button])
            for value in WAREHOUSE.values():
                self.assertNotIn(value, self._everything(app))
        app = self._app(DATABRICKS_WAREHOUSE_ID="test-warehouse")
        self.assertIn("DATABRICKS\\_PREPARED\\_TABLE is not set", self._text(app))

    def test_the_host_or_the_credentials_alone_are_a_setup_problem_not_a_demonstration(self):
        host = {"DATABRICKS_HOST": "https://made-up-workspace.example.invalid"}
        identity = {"DATABRICKS_CLIENT_ID": "made-up-client", "DATABRICKS_CLIENT_SECRET": "made-up-secret"}
        for present in (host, identity, {**host, **identity}):
            app = self._app(**present)
            text = self._text(app)
            self.assertIn("Data: not available.", text, sorted(present))
            for name in WAREHOUSE:
                said = name.replace("_", "\\_") + " is not set"
                (self.assertNotIn if name in present else self.assertIn)(said, text, sorted(present))
            self.assertNotIn("Data: demonstration.", text)
            self.assertNotIn("invented facilities, not the real records", text)
            self.assertEqual([], [button.key for button in app.button])  # no examples and no search form
            self.assertEqual(0, len(app.text_input) + len(app.radio))
            everything = self._everything(app)
            for value in present.values():
                self.assertNotIn(value, everything)
            self._assert_nothing_restricted(app)
            # Choosing the demonstration outright still works beside the same settings.
            app = self._app(**present, FIND_CARE_DATA="demo")
            self.assertIn("Data: demonstration.", self._text(app))
            self.assertEqual(3, len([button for button in app.button if str(button.key).startswith("example-")]))

    def test_a_warehouse_read_failure_reports_unavailable_and_recommends_nothing(self):
        app = self._app(FakeWarehouse(error=ConnectionError("Example Regional Hospital")), **WAREHOUSE)
        self.assertIn("Data: real records.", self._text(app))
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        text = self._text(app)
        self.assertIn("The facility records cannot be reached right now.", text)
        self.assertIn("The facility warehouse is unavailable. Try again shortly.", text)
        self._assert_nothing_restricted(app)


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")
class DeploymentShapeTests(unittest.TestCase):
    """app.yaml's own command, run from a copy of app/ alone: no repository root, no contracts/ folder."""

    DRIVE = (
        "from streamlit.testing.v1 import AppTest\n"
        "app = AppTest.from_file('app.py', default_timeout=30).run()\n"
        "assert not app.exception, app.exception\n"
        "assert any('Data: demonstration.' in m.value for m in app.markdown), [m.value for m in app.markdown]\n"
        "app = app.button(key='example-Dialysis near Jaipur, Rajasthan').click().run()\n"
        "assert not app.exception, app.exception\n"
        "assert any('Send the patient to Example Regional Hospital.' in m.value for m in app.markdown)\n"
        "print('demonstration answered')\n"
    )

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.source = Path(folder) / "source"
        shutil.copytree(APP, self.source, ignore=shutil.ignore_patterns("__pycache__"))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(SETTINGS) and k != "PYTHONPATH"}

    def test_the_demonstration_answers_from_the_app_folder_alone(self):
        self.assertFalse((self.source.parent / "contracts").exists())
        done = subprocess.run([sys.executable, "-c", self.DRIVE], cwd=self.source, env=self.env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(0, done.returncode, done.stderr[-2000:])
        self.assertIn("demonstration answered", done.stdout)

    def test_the_documented_command_starts_the_server(self):
        command = [line for line in (self.source / "app.yaml").read_text(encoding="utf-8").splitlines()
                   if line.startswith("command:")]
        self.assertEqual(['command: ["streamlit", "run", "app.py"]'], command)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
                                   "--server.address", "127.0.0.1", "--server.port", str(port)],
                                  cwd=self.source, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        deadline, healthy = time.time() + 60, False
        while time.time() < deadline and not healthy and server.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as reply:
                    healthy = reply.status == 200
            except OSError:
                time.sleep(0.5)
        self.assertTrue(healthy, "the server did not come up")


if __name__ == "__main__":
    unittest.main()
