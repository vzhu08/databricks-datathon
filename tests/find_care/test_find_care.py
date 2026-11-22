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
from app import finding_provenance as provenance
from app.ranking import search_facilities

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "contracts/fixtures/search.json").read_text(encoding="utf-8"))
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
APP = ROOT / "app"
WAREHOUSE = {"DATABRICKS_WAREHOUSE_ID": "test-warehouse", "DATABRICKS_PREPARED_TABLE": "test_catalog.test_schema.prepared",
             "DATABRICKS_HOST": "https://workspace.example.invalid", "DATABRICKS_CLIENT_ID": "test-client",
             "DATABRICKS_CLIENT_SECRET": "test-secret"}
SETTINGS = ("DATABRICKS_", words.DATA_SETTING, "TOMTOM_", "FIND_CARE_")


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
                     "Record reference: https://example.invalid/north-campus", "Before travelling"):
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
        self.assertIn("Phone first: Example Community Clinic (under 100 m)", words.referral_note(leads, True))
        self.assertNotIn("0.0 km", words.referral_note(leads, True))
        down = words.present({"status": "unavailable", "direct_results": [], "indirect_leads": [],
                              "location_choices": [], "approximate_location": False,
                              "message": "The facility warehouse is unavailable. Try again shortly."},
                             "mri", {"pin": "302001"}, 50)
        self.assertEqual("The facility records cannot be reached right now.", down["headline"])
        _, missing = _run({"service": "mri", "location": {"pin": "999999"}})
        self.assertEqual("That place could not be located.", missing["headline"])

    def test_every_answer_says_what_it_does_not_tell_you(self):
        _, ok = _run({"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}})
        self.assertEqual([words.NEAREST_NOT_BEST, words.STRAIGHT_LINE, words.NO_DATE], ok["limits"])
        self.assertIn("not a judgement that it is the best place", ok["limits"][0])
        self.assertIn("Limits: nearest match, not a quality judgement.", words.referral_note(ok, True))
        # A department or a specialist is never worded as the service.
        for service, part in (("dialysis", "not a working dialysis unit"), ("mri", "not a working MRI scanner"),
                              ("trauma_care", "not a trauma service")):
            related = words.limits("needs_confirmation", service, 50, {})
            self.assertIn(part, related[0])
            self.assertEqual([words.STRAIGHT_LINE, words.NO_DATE], related[1:])
        _, leads = _run({"service": "dialysis", "location": {"pin": "302001"}, "radius_km": 2})
        self.assertIn("not a working dialysis unit", leads["limits"][0])
        self.assertIn("not a working dialysis unit", words.referral_note(leads, True))
        # Not mentioned is not the same as not offered.
        seen = 0
        for case in FIXTURE["cases"]:
            _, view = _run(case["query"])
            if view["status"] == "no_match":
                seen += 1
                self.assertEqual(1, len(view["limits"]), case["id"])
                self.assertIn("That is not the same as no facility offering it", view["limits"][0])
            if view["status"] in ("ambiguous_location", "invalid_input"):
                self.assertEqual([], view["limits"], case["id"])
        self.assertGreater(seen, 0)

    def test_the_limits_on_real_records_carry_no_facility_field(self):
        for case in FIXTURE["cases"]:
            query = case["query"]
            response = search_facilities(**query, facilities=FIXTURE["facilities"])
            view = words.present(words.withheld(response), query["service"], query["location"],
                                 query.get("radius_km", 50))
            told = " ".join(view["limits"])
            for text in restricted(response):
                self.assertNotIn(text, told, case["id"])
            if response["status"] == "ok":
                self.assertEqual([words.UNCHECKED_CLAIM], view["limits"], case["id"])
            if response["status"] == "needs_confirmation":
                self.assertEqual([words.NOT_THE_SERVICE[query["service"]], words.UNCHECKED_CLAIM], view["limits"])
            if response["status"] == "no_match":
                self.assertIn("That is not the same as no facility offering it", told)

    def test_a_location_warning_is_a_slot_that_stays_empty_until_a_search_supplies_one(self):
        query = {"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}}
        response, view = _run(query)
        cards = [view["top"], *view["backups"], *view["leads"]]
        self.assertEqual([None] * len(cards), [card["location_warning"] for card in cards])
        self.assertNotIn("Check the address", words.referral_note(view, True))
        self.assertIsNone(words.location_warning(None))
        self.assertIsNone(words.location_warning([]))
        flagged = json.loads(json.dumps(response))
        flagged["direct_results"][0]["location_warning"] = ["no_building_nearby", "far_from_town"]
        flagged["direct_results"][1]["location_warning"] = "a_code_this_screen_does_not_know"
        view = words.present(flagged, "dialysis", query["location"], 50)
        self.assertEqual("The map pin for this facility may be wrong: no building is mapped near its map pin, and "
                         "its map pin is far from the town in its address. Confirm the address by phone. The "
                         "distance shown may be off.", view["top"]["location_warning"])
        self.assertIn("it failed a location check", view["backups"][0]["location_warning"])
        self.assertIn("Check the address: The map pin", words.referral_note(view, True))
        # The order is the search's own: a warning never moves a facility.
        self.assertEqual([card["facility_id"] for card in response["direct_results"]],
                         [card["facility_id"] for card in [view["top"], *view["backups"]]])
        # Real records keep no card, so they keep no warning either.
        self.assertNotIn("location_warning", json.dumps(words.withheld(flagged)))

    def _claims(self, query, group):
        response, _ = _run(query)
        mapped = provenance.project_find_care(response, query["service"], mode="demo")
        return [words.claim_view(finding, query["service"], "Jaipur, Rajasthan, 302001")
                for finding in mapped["findings"] if finding["result_group"] == group]

    def test_each_demonstration_card_gets_its_own_location_and_service_claim(self):
        """#302: the lines word B's mapper, name the synthetic publisher and never confirm a service."""
        query = {"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}, "radius_km": 50}
        first, backup = self._claims(query, "direct_results")
        self.assertEqual(("direct_results", 0, 1), (first["result_group"], first["index"], backup["index"]))
        location, service = first["location"], first["service"]
        self.assertEqual("Reported as a map point in the record's latitude / longitude field: "
                         "Jaipur, Rajasthan, 302001. Building and entrance unverified.", location["line"])
        self.assertEqual("Unconfirmed · Reported · Fixture statement names North Campus. Physical branch unverified. "
                         "Service date unknown.", service["line"])
        # Each card keeps its own branch wording and its own reference. The backup inherits neither.
        self.assertIn("Fixture statement names South Campus. Physical branch unverified.", backup["service"]["line"])
        self.assertEqual("capabilities field", backup["service"]["sources"][0]["field"])
        self.assertIsNone(backup["service"]["sources"][0]["reference"])
        self.assertNotIn("branch unknown", json.dumps(first).lower() + json.dumps(backup).lower())
        for claim in (location, service):
            self.assertEqual("1 record, 1 known supporting origin", claim["counts"])
            self.assertTrue(claim["missing_check"])
            self.assertIsNone(claim["review"])
            for source in claim["sources"]:
                self.assertEqual(provenance.SYNTHETIC, source["publisher"])
                self.assertEqual("unknown", source["date"])
                self.assertIn("invented demonstration record", source["origin"])
                self.assertIsNone(source["citation"])
        source = service["sources"][0]
        self.assertEqual(("Supports dialysis", "The North Campus provides hemodialysis.", "procedures field"),
                         (source["role"], source["fact"], source["field"]))
        self.assertEqual("https://example.invalid/north-campus", source["reference"])  # a record reference, as text
        self.assertIsNone(location["sources"][0]["reference"])

        query = {"service": "dialysis", "location": {"pin": "302001"}, "radius_km": 2}
        lead = self._claims(query, "indirect_leads")[0]["service"]
        self.assertEqual("Unconfirmed · No evidence of onsite dialysis · Related specialty in the fictional record. "
                         "Onsite scope unknown. Service date unknown.", lead["line"])
        self.assertEqual("1 record, 0 known supporting origins", lead["counts"])
        self.assertEqual(["Context for dialysis"], [source["role"] for source in lead["sources"]])
        # The service named is the one asked for, never another.
        response, _ = _run(query)
        mapped = provenance.project_find_care(response, "mri", mode="demo")["findings"][0]
        mri = words.claim_view(mapped, "mri")["service"]
        self.assertEqual("MRI scan", mri["label"])
        self.assertNotIn("dialysis", mri["line"] + mri["missing_check"])

    def test_unknown_lineage_and_missing_counts_are_said_to_be_unknown(self):
        claim = provenance.summarize_claim("service", "Named branch", [provenance.Observation(
            "A publisher", "A statement", "Named branch", role="support")], service="mri")
        finding = {"result_group": "direct_results", "index": 0, "service": claim,
                   "location": provenance.summarize_claim("location", "Named branch", None, precision="unknown")}
        view = words.claim_view(finding, "mri")
        self.assertEqual("1 record, known supporting origins unknown", view["service"]["counts"])
        self.assertEqual("unknown", view["service"]["sources"][0]["origin"])
        self.assertEqual("records unknown, known supporting origins unknown", view["location"]["counts"])
        self.assertIn("Evidence not measured as an unknown precision", view["location"]["line"])

    def test_the_packaged_mapper_is_bs_file_unchanged(self):
        source = ROOT / "research/acquisition/national_facility_evidence/finding_provenance.py"
        self.assertEqual(source.read_bytes(), (APP / "finding_provenance.py").read_bytes())

    def test_the_withheld_summary_names_no_facility_and_lists_no_source(self):
        fixture = FIXTURE["facilities"]
        for query, words_found in (({"service": "dialysis", "location": {"city": "Jaipur", "state": "Rajasthan"}},
                                    "mention dialysis."),
                                   ({"service": "dialysis", "location": {"pin": "302001"}, "radius_km": 2},
                                    "something related to dialysis")):
            kept = words.withheld(search_facilities(**query, facilities=fixture))
            mapped = provenance.project_find_care(kept, "dialysis", mode="warehouse")
            self.assertEqual([], mapped["findings"])
            summary = words.withheld_summary(mapped["summary"], "dialysis")
            self.assertIn("Unconfirmed", summary["line"])
            self.assertIn(words_found, summary["line"])
            self.assertIn("Independent corroboration unknown", summary["detail"])
            for text in restricted():
                self.assertNotIn(text, json.dumps(summary))
        for status in ("no_match", "unavailable", "ambiguous_location"):
            mapped = provenance.project_find_care({"status": status, "withheld": True}, "dialysis", mode="warehouse")
            self.assertIsNone(words.withheld_summary(mapped["summary"], "dialysis"))
        # A response that was not withheld is never summarised as if it had been.
        mapped = provenance.project_find_care({"status": "withheld", "evidence": "direct"}, "dialysis", mode="warehouse")
        self.assertIsNone(words.withheld_summary(mapped["summary"], "dialysis"))

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
        # review of #269: a prefix never costs a coordinate its sign
        for typed, expected in (("near -12.5, 77.6", {"latitude": -12.5, "longitude": 77.6}),
                                ("around -12.5 -77.6", {"latitude": -12.5, "longitude": -77.6}),
                                ("near 26.92, -75.82.", {"latitude": 26.92, "longitude": -75.82})):
            self.assertEqual(expected, words.parse_location(typed), typed)
        # a six-digit run touching letters or a decimal point is not a PIN, and two PINs are never guessed between
        for typed, message in (("AB560034", "PIN code on its own"), ("Flat560034, Pune", "PIN code on its own"),
                               ("560034XY", "PIN code on its own"), ("12.560034", "PIN code on its own"),
                               ("560034 and 302001", "Type one PIN code."), ("PIN 560 034 or 560-035", "Type one PIN code.")):
            with self.assertRaises(ValueError) as refused:
                words.parse_location(typed)
            self.assertIn(message, str(refused.exception), typed)

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
        bare = ("find_care", "finding_provenance", "data_access", "ranking", "patient_ui", "patient_intake",
                "find_capacity", "find_decision", "capacity_recommendation", "simulation", "travel", "storm_page")
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
            # The patient screen opens first. These tests are about Find care, the second choice.
            switch = app.radio(key="view")
            app = switch.set_value("Find care").run()
            source = app.radio(key="lookup_source")
            target = "Simulated scenarios" if words.data_mode(self.env)["mode"] == "demo" else "Private warehouse lookup"
            self.assertEqual(source.options, ["Public facility evidence", target])
            self.assertEqual(source.value, "Public facility evidence")
            app = source.set_value(target).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def test_public_source_miss_after_leaving_simulation(self):
        app = self._app()
        app = self._step(app.button(key="find").click())
        self.assertIn("Send the patient to Campus B.", self._text(app))
        app = self._step(app.radio(key="lookup_source").set_value("Public facility evidence"))
        self.assertEqual("Pune", next(field for field in app.text_input if field.label == "City").value)
        app = self._step(next(button for button in app.button if button.label == "Search public sources").click())
        self.assertIn("KEM Hospital, Pune", self._text(app))
        self.assertIn("Current availability, staffing, appointment acceptance and exact entrance are unknown.",
                      self._text(app))
        self.assertEqual(1, len(app.get("link_button")))
        next(field for field in app.text_input if field.label == "City").set_value("Atlantis")
        app = self._step(next(button for button in app.button if button.label == "Search public sources").click())
        self.assertIn("This collection has no reviewed public claim", app.info[0].value)
        self.assertNotIn("Send the patient", self._text(app))
        self.assertFalse(app.get("link_button"))

    def _lookup(self, app):
        """The demonstration opens on the recommendation. The record lookup is its second, separate job."""
        return self._step(app.radio(key="mode").set_value("lookup"))

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

    def test_the_record_lookup_on_demonstration_data_directs_nobody(self):
        app = self._app()
        text = self._text(app)
        self.assertIn("Data: demonstration.", text)
        self.assertIn("six invented facilities", text)
        self.assertIn("The recommendation appears here.", text)
        app = self._lookup(app)
        self.assertIn("Nothing here is a referral or a recommendation.", self._text(app))
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        text = self._text(app)
        for part in ("Provisional lead: Example Regional Hospital. Confirm before anyone travels.",
                     "Provisional · Synthetic demo record. A lead to check by phone. This is not a referral or a "
                     "recommendation, and nothing is reserved.", "North Campus provides hemodialysis",
                     "procedures field", "Phone the facility with the confirmation call script",
                     "How this was decided", "example.invalid",
                     "Other records that state the service", "Why this lead comes first", "What its record says",
                     "About 6.7 km away, in a straight line."):
            self.assertIn(part, text)
        for part in ("What this does not tell you", "Service statement dated: unknown.",
                     "The journey by road can be much longer",
                     "Each is a provisional lead to confirm, in the same order as above. The order says nothing "
                     "about quality."):
            self.assertIn(part, text)
        # #304: the lookup is not a destination. No directive, no referral note, no campus from the model.
        for part in ("Send the patient", "Send to", "Referral note", "cannot take the patient", "Campus B",
                     "Check the address"):
            self.assertNotIn(part, self._everything(app))
        # #330: the one thing to save is a confirmation call script, never a referral.
        self.assertEqual((1, 1), (len(app.code), len(app.get("download_button"))))
        self.assertTrue(app.code[0].value.startswith("Confirmation call script (demonstration data"))
        # An example fills the form, so the form always shows what the answer is for.
        self.assertEqual(("dialysis", "Jaipur, Rajasthan", 50),
                         (app.radio(key="service").value, app.text_input(key="where").value,
                          app.select_slider(key="radius").value))
        self.assertNotIn("You changed the request", text)
        # #302: every card carries its own location and service lines, and the sources behind them.
        for part in ("How well this is supported", "Why this finding?", "Synthetic demo record",
                     'data-claims="direct_results-0"', 'data-claims="direct_results-1"',
                     "Dialysis</strong> · Unconfirmed · Reported · Fixture statement names North Campus. "
                     "Physical branch unverified.", "Fixture statement names South Campus.",
                     "Source of this statement: the procedures field",
                     "Record reference: https://example.invalid/north-campus", words.RECORD_LINK_NOTE):
            self.assertIn(part, text)
        # The demonstration address is a record reference shown as text: never a link, never called the source.
        for part in ("href=", "Source: ", "branch unknown", "Branch and service date unknown"):
            self.assertNotIn(part, text.replace('href="https://www.openstreetmap.org', ""))
        self.assertNotIn("Virtue Foundation", text)
        app = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click())
        self.assertIn('data-claims="indirect_leads-0"', self._text(app))
        self.assertIn("No evidence of onsite dialysis · Related specialty in the fictional record.", self._text(app))
        self.assertIn("It mentions a related specialty, not the service itself.", self._text(app))
        self.assertIn("No facility within 2 km clearly offers dialysis.", self._text(app))
        self.assertIn("A kidney department or a kidney specialist is not a working dialysis unit.", self._text(app))
        self.assertEqual(("302001", 2), (app.text_input(key="where").value, app.select_slider(key="radius").value))

    def _note(self, app):
        self.assertEqual((1, 1), (len(app.code), len(app.get("download_button"))))
        return app.code[0].value

    def test_submit_recovers_the_current_campus_lead_after_an_allocator_or_route_exception(self):
        import find_capacity as capacity
        import travel.hosted as hosted

        app = self._step(self._app(**self.LIVE).radio(key="traffic").set_value(False))
        app = self._step(app.button(key="find").click())
        self.assertIn("Send the patient to Campus B.", self._text(app))
        with mock.patch.object(capacity, "recommend_capacity", side_effect=RuntimeError("test failure")):
            app = self._step(app.button(key="find").click())
        self.assertIn("The capacity model could not finish checking this request.", self._text(app))
        self.assertIn("Call: Campus A, simulated Jaipur", self._note(app))
        self.assertIn("8 min (Synthetic Jaipur storm travel fixture)", self._note(app))
        self.assertNotIn("Referral note", self._text(app))

        app = self._step(app.radio(key="traffic").set_value(True))
        with mock.patch.object(hosted, "demo_car_travel", side_effect=TimeoutError("test failure")) as lookup:
            app = self._step(app.button(key="find").click())
            self._step(app)
        lookup.assert_called_once()
        self.assertIn("Provisional lead: Campus A.", self._text(app))
        self.assertIn("request time unknown", self._text(app))
        self.assertNotIn("no request was sent", self._text(app))
        self.assertIn("Road time could not be fetched.", self._note(app))
        self.assertIn("Call: Campus A, simulated Jaipur", self._note(app))
        self.assertNotIn(" min", self._note(app))
        self.assertNotIn("Referral note", self._text(app))
        self.assertNotIn("fallback", [button.key for button in app.button])

    def test_emergency_result_ends_at_the_diversion_instruction(self):
        import find_capacity as capacity

        app = self._step(self._app().button(key="find").click())
        self.assertIn("Referral note", self._text(app))
        with mock.patch.object(capacity, "recommend_capacity",
                               return_value={"status": "emergency", "reason": "emergency_stop"}):
            app = self._step(app.button(key="find").click())
        self.assertIn("Emergency: call 112 now.", self._text(app))
        for fragment in ("Referral note", "Confirmation call script", "Next step", "How this was decided"):
            self.assertNotIn(fragment, self._text(app))
        self.assertNotIn("fallback", [button.key for button in app.button])
        self.assertEqual((0, 0), (len(app.code), len(app.get("download_button"))))

    def test_the_recommendation_and_its_referral_note_name_the_models_campus_and_no_other(self):
        """#304: a routine case names B in the result and the note, the highest urgency names A in both."""
        app = self._app()
        text = self._text(app)
        self.assertIn("Road time with traffic is switched off here", text)
        self.assertIn("call 112 now", text)
        self.assertIn("four simulated starting areas in Jaipur", text)
        # No typed place or search distance exists here to be silently swapped for a default starting area.
        self.assertEqual((0, 0), (len(app.text_input), len(app.select_slider)))
        self.assertEqual("central", app.radio(key="origin").value)

        app = self._step(app.button(key="capacity-Routine dialysis: keeps a scarce station free").click())
        text, note = self._text(app), self._note(app)
        for part in ("Send the patient to Campus B.", "12 min (simulated). 2 free staffed places",
                     "Fastest with a free place: Campus A, 8 min. Not recommended for this patient.",
                     "Campus B is 4 min further.", "monitored dialysis station", "Simulated drive minutes",
                     "If Campus B cannot take the patient", "Campus C (14 min)", "Why this campus",
                     "an invented campus at a simulated point", "Nothing is booked", "How this was decided"):
            self.assertIn(part, text)
        self.assertIn("Send to: Campus B", note)
        self.assertNotIn("Send to: Campus A", note)
        self.assertEqual("routine", app.radio(key="urgency").value)
        # The catalogue hospitals never appear beside the recommendation, in any element or kept state.
        for part in ("Example Regional Hospital", "Example Community Clinic", "example.invalid", "km away"):
            self.assertNotIn(part, self._everything(app))

        app = self._step(app.button(key="capacity-Highest urgency dialysis: fastest free place").click())
        text, note = self._text(app), self._note(app)
        self.assertIn("Send the patient to Campus A.", text)
        self.assertIn("Highest urgency: it is the fastest campus", text)
        self.assertIn("Send to: Campus A", note)
        self.assertNotIn("Send the patient to Campus B", text)
        self.assertNotIn("Send to: Campus B", note)

        app = self._step(app.button(key="capacity-Dialysis from the south: nearest campus capacity unknown").click())
        self.assertIn("Send the patient to Campus C.", self._text(app))
        self.assertIn("free staffed places unknown or out of date", self._text(app))
        self.assertEqual("south", app.radio(key="origin").value)
        self.assertIn("Send to: Campus C", self._note(app))

        # Any change to the request removes the earlier destination and its note until the next press.
        for change in (lambda a: a.radio(key="urgency").set_value("highest"),
                       lambda a: a.radio(key="origin").set_value("west"),
                       lambda a: a.checkbox(key="needs_tool").set_value(True),
                       lambda a: a.radio(key="service").set_value("mri")):
            changed = self._step(change(app))
            everything = self._everything(changed)
            self.assertIn("the earlier recommendation was removed", self._text(changed))
            for part in ("Send the patient", "Send to", "Campus C", "Referral note"):
                self.assertNotIn(part, everything)
            self.assertEqual((0, 0), (len(changed.code), len(changed.get("download_button"))))
            self.assertNotIn("capacity", changed.session_state)
            app = self._step(changed.button(key="capacity-Dialysis from the south: nearest campus capacity unknown").click())
            self.assertIn("Send to: Campus C", self._note(app))
        app.radio(key="urgency").set_value("highest")
        app.radio(key="origin").set_value("central")
        again = self._step(app.button(key="find").click())
        self.assertIn("Send the patient to Campus A.", self._text(again))
        self.assertEqual({"service": "dialysis", "urgency": "highest", "origin_id": "central", "needs_tool": False,
                          "traffic": False}, again.session_state["capacity"]["asked"])
        # Switching to the record lookup takes the recommendation and its note off the screen.
        lookup = self._lookup(again)
        self.assertNotIn("Send the patient", self._text(lookup))
        self.assertEqual(0, len(lookup.code))

    LIVE = {"TOMTOM_ENABLED": "true", "TOMTOM_COPYRIGHT_CAPTION": "Caption <b>supplied</b> by the operator",
            "TOMTOM_COPYRIGHT_NOTICES": "Complete supplier notices.\nSecond line of the notices."}

    def _stub_travel(self, sent="2026-11-22T15:40:00Z"):
        """A's adapter replaced by a stub: nothing in these tests can reach the provider."""
        import travel.hosted as hosted
        calls, answers = [], {}

        def stub(request, snapshot, *, origin_id, provider=None):
            calls.append(origin_id)
            return {row["facility_id"]: dict(answers.get(row["facility_id"]) or
                                             {"status": "unavailable", "minutes": None, "source": "stub",
                                              "reason": "provider_unavailable", "outcome": "unavailable",
                                              "requested_at": sent if row["facility_id"] != "F" else None})
                    for row in snapshot["candidates"]}

        patcher = mock.patch.object(hosted, "demo_car_travel", stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls, answers

    def test_road_time_needs_all_three_operator_settings(self):
        """#304: without the switch, the caption and the complete notices, no road-time source is offered."""
        for missing in self.LIVE:
            app = self._app(**{key: value for key, value in self.LIVE.items() if key != missing})
            with self.subTest(missing=missing):
                self.assertIn("Road time with traffic is switched off here", self._text(app))
                self.assertEqual([], [radio.key for radio in app.radio if radio.key == "traffic"])
                calls, _ = self._stub_travel()
                app = self._step(app.button(key="find").click())
                self.assertEqual([], calls)
                self.assertIn("Send the patient to Campus B.", self._text(app))
                self.assertIn("12 min (simulated)", self._text(app))
                self.assertIn("Simulated drive minutes", self._text(app))
                for part in ("supplied", "Complete supplier notices", "data-attribution", "data-notices"):
                    self.assertNotIn(part, self._everything(app))

    def test_road_time_is_the_default_source_and_a_failed_request_leaves_no_destination(self):
        """#304: stubbed provider. One ordinary press asks for road time. A failed time is never replaced."""
        app = self._app(**self.LIVE)
        calls, answers = self._stub_travel()
        text = self._text(app)
        self.assertIs(True, app.radio(key="traffic").value)  # the live source is selected without an opt-in
        self.assertIn("No patient details are sent. One batch of requests per press", text)
        self.assertIn("Examples always use simulated minutes and send no road-time request.", text)
        for part in ("supplied", "Complete supplier notices"):  # shown with a road-time result only
            self.assertNotIn(part, text)
        self.assertEqual([], calls)  # opening the page sends nothing

        failed = self._step(app.button(key="find").click())  # the ordinary submission, no second press
        text, everything = self._text(failed), self._everything(failed)
        self.assertEqual(["central"], calls)
        self.assertIn("No campus is recommended.", text)
        self.assertIn("No simulated time is used in their place.", text)
        self.assertIn("Campus A: road time unavailable (provider unavailable), requested at 15:40:00 UTC on 22 Nov 2026.",
                      text)
        self.assertIn("Campus F: road time unavailable (provider unavailable), no request was sent.", text)
        # The caption and the complete notices come with a failed result too, as escaped plain text.
        self.assertIn('data-attribution="traffic">Caption &lt;b&gt;supplied&lt;/b&gt; by the operator', text)
        self.assertIn("Map data copyright notices", text)
        self.assertIn("Complete supplier notices.\nSecond line of the notices.", text)
        self.assertNotIn("<b>supplied", text)
        for part in ("Send the patient", "Send to", "Referral note", "min (simulated)", "12 min", "8 min"):
            self.assertNotIn(part, everything)
        # #330: on that same result, with no second search, the best supported campus is a named provisional
        # lead from the evidence the model read for this request. It is never worded as a destination.
        for part in ('data-fallback="campus"', "Provisional lead: Campus A. Confirm before anyone travels.",
                     'data-decision="provisional">Provisional · Synthetic demo record. A lead to check by phone. '
                     "This is not a referral, and nothing is reserved.",
                     "“The scenario record marks dialysis as running at this campus.” (scenario service record field",
                     "Service statement dated: 2026-11-22. Independent sources for the service: 1.",
                     "Citation: Synthetic Jaipur storm scenario, Campus A service record.",
                     "Its record states the service, and that statement has been reviewed.",
                     "A free staffed place was reported when checked. Road time could not be fetched. No simulated "
                     "or straight-line time is used in its place.",
                     "Road travel time to a permitted destination is unknown.",
                     "Phone the facility with the confirmation call script before anyone travels.",
                     "Other campuses with a record for this service", "Campus E · Provisional · Synthetic demo "
                     "record.", "Free staffed places: unknown.", "Campus D · Verification lead"):
            self.assertIn(part, text)
        script = self._note(failed)
        for part in ("Confirmation call script (demonstration data", "This is not a referral and nothing is reserved.",
                     "Call: Campus A, simulated Jaipur", "Service statement dated: 2026-11-22.",
                     "Citation: Synthetic Jaipur storm scenario, Campus A service record.",
                     "Road time could not be fetched.", "Next step: Phone the facility"):
            self.assertIn(part, script)
        for part in ("Referral note", "Send to:", "Send the patient", "booked", " min"):
            self.assertNotIn(part, script)
        self.assertEqual([], [button.key for button in failed.button if button.key == "fallback"])
        self._step(failed)  # drawing the screen again asks the provider nothing
        self.assertEqual(["central"], calls)

        # A used-up allowance is a failure like any other: said plainly, with no destination and no stand-in time.
        spent = {"status": "unavailable", "minutes": None, "source": "stub", "outcome": "unavailable",
                 "reason": "daily_call_budget_exceeded", "requested_at": None}
        answers.update({key: spent for key in "ABCDEF"})
        empty = self._step(failed.button(key="find").click())
        self.assertEqual(["central", "central"], calls)
        self.assertIn("Campus B: road time unavailable (today's road-time request allowance is used up), "
                      "no request was sent.", self._text(empty))
        self.assertIn("No campus is recommended.", self._text(empty))
        for part in ("Send the patient", "Send to", "min (simulated)", "km"):
            self.assertNotIn(part, self._everything(empty))
        self.assertIn("Provisional lead: Campus A. Confirm before anyone travels.", self._text(empty))
        self.assertTrue(self._note(empty).startswith("Confirmation call script"))
        # A partial result: one campus has no road time. The slip and the note still name one and the same campus.
        known = {"status": "known", "source": "stub", "reason": None, "outcome": "ok",
                 "requested_at": "2026-11-22T15:40:00Z"}
        answers.clear()
        answers.update(B={**known, "minutes": 10.5}, C={**known, "minutes": 19.0})
        worked = self._step(empty.button(key="find").click())
        text, note = self._text(worked), self._note(worked)
        self.assertEqual(["central"] * 3, calls)
        self.assertIn("Send the patient to Campus B.", text)
        self.assertIn("10.5 min (by road, ordinary car with traffic).", text)
        self.assertIn("from TomTom", text)
        self.assertIn("This time was requested at 15:40:00 UTC on 22 Nov 2026.", text)
        self.assertIn("Campus A: road time unavailable (provider unavailable), requested at 15:40:00 UTC", text)
        self.assertIn('data-attribution="traffic">Caption &lt;b&gt;supplied&lt;/b&gt; by the operator', text)
        self.assertIn("Complete supplier notices.", text)
        self.assertNotIn("Simulated drive minutes", text)
        self.assertNotIn("min (simulated)", text)
        self.assertIn("Send to: Campus B", note)
        self.assertEqual(1, note.count("Send to:"))
        self.assertIn("requested at 15:40:00 UTC", note)
        self.assertIn("ordinary car with traffic", note)
        self.assertIn("Map data: Caption <b>supplied</b> by the operator", note)  # plain text in a text block

        # An example is explicit simulated data: it says so, sends nothing and shows no map caption.
        example = self._step(worked.button(key="capacity-Routine dialysis: keeps a scarce station free").click())
        self.assertEqual(["central"] * 3, calls)
        self.assertIs(False, example.radio(key="traffic").value)
        self.assertIn("12 min (simulated)", self._text(example))
        self.assertIn("Simulated drive minutes", self._text(example))
        self.assertNotIn("supplied", self._everything(example))
        self.assertNotIn("Map data:", self._note(example))
        # Choosing the other source removes the earlier answer and sends nothing until the next press.
        switched = self._step(example.radio(key="traffic").set_value(True))
        self.assertNotIn("Campus B", self._everything(switched))
        self.assertEqual(["central"] * 3, calls)
        # The record lookup never asks for a road time.
        lookup = self._step(self._lookup(switched).button(key="find").click())
        self.assertIn("Provisional lead: Example Regional Hospital.", self._text(lookup))
        self.assertEqual(["central"] * 3, calls)

    def test_an_ordinary_search_gives_the_best_supported_lead_with_its_claims_and_a_call_script(self):
        """#330: an unconfirmed record that states the service is a provisional lead, never dropped, never a referral."""
        app = self._step(self._lookup(self._app()).button(key="example-Dialysis near Jaipur, Rajasthan").click())
        text, script = self._text(app), self._note(app)
        # The decision, its label, the source, the unknowns and the next action are all on the screen.
        for part in ("Provisional lead: Example Regional Hospital. Confirm before anyone travels.",
                     'data-decision="provisional">Provisional · Synthetic demo record.',
                     "Its record states the service. Nobody has confirmed the statement.",
                     "Leads are put in order by what their records say about the service",
                     "“The North Campus provides hemodialysis.”", "Source of this statement: the procedures field",
                     'data-claims="direct_results-0"', "Why this finding?",
                     "Not known yet", "Check a dated statement of onsite delivery at the exact branch.",
                     "Confirm current staffed availability for the requested service.",
                     "Free staffed places: unknown.", "Travel time by road: unknown. About 6.7 km away in a straight line.",
                     "Next step", "Phone the facility with the confirmation call script before anyone travels.",
                     "Service statement dated: unknown. Independent sources for the service: 1.",
                     "Record reference: https://example.invalid/north-campus",
                     "Confirmation call script", "How this was decided",
                     "A record that states the service is a provisional lead even when nobody has confirmed it"):
            self.assertIn(part, text)
        self.assertNotIn("VF only", self._everything(app))  # said only for an established VF-only scope
        self.assertNotIn("min", text.split("Not known yet")[1].split("Next step")[0])  # no invented travel time
        # The export carries the same fields: source field, reference, origins, date, precision, reason,
        # what is missing and the next action.
        for part in ("Confirmation call script (demonstration data, invented facilities)",
                     "This is not a referral and nothing is reserved.",
                     "Request: Dialysis near Jaipur, Rajasthan, within 50 km.",
                     "Call: Example Regional Hospital, Jaipur, Rajasthan, 302001",
                     "Status: Provisional · Synthetic demo record",
                     "“The North Campus provides hemodialysis.” (procedures field",
                     "Independent sources for the service: 1. Service statement dated: unknown.",
                     "Citation: https://example.invalid/north-campus. It points to the whole record",
                     "Location evidence: Reported as a map point", "Building and entrance unverified.",
                     "Dialysis evidence: Unconfirmed · Reported · Fixture statement names North Campus. "
                     "Physical branch unverified. Service date unknown. (1 record, 1 known supporting origin.)",
                     "Record reference: https://example.invalid/north-campus",
                     "Why this lead: Its record states the service. Nobody has confirmed the statement.",
                     "Free staffed places: unknown. Travel time by road: unknown.",
                     "1. Do you provide dialysis at this site today, yourselves",
                     "Not known yet:\n- Check the exact physical branch or patient entrance.",
                     "- Road travel time to a permitted destination is unknown.",
                     "Next step: Phone the facility with the confirmation call script before anyone travels.",
                     "Nobody should travel until the facility confirms.", "call 112"):
            self.assertIn(part, script)
        for part in ("Referral note", "Send to:", "Send the patient", "booked", "reserved for", "Campus B"):
            self.assertNotIn(part, script)
        # The other record with the same name is a separate lead with its own claims, not merged into the first.
        self.assertIn('data-claims="direct_results-1"', text)
        self.assertIn("Fixture statement names South Campus.", text)

        # Only an identity or area: a lead to verify, with the missing service evidence named and no script.
        near = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click())
        text = self._text(near)
        for part in ("No facility within 2 km clearly offers dialysis.", 'data-decision="verification_lead"',
                     "Closest lead to verify", "Example Community Clinic</strong> · Verification lead · Synthetic "
                     "demo record.", "Nothing there states the service.",
                     "Verify whether the requested service is delivered onsite at this branch.",
                     "Confirm which facility and branch this record is before relying on it."):
            self.assertIn(part, text)
        self.assertEqual((0, 0), (len(near.code), len(near.get("download_button"))))
        self.assertNotIn("Provisional", text)

        # Nothing found: no lead, no script, and the search's own words say which input to change.
        near.radio(key="service").set_value("trauma_care")
        near.text_input(key="where").set_value("Jaipur, Rajasthan")
        none = self._step(near.button(key="find").click())
        self.assertEqual("no_match", none.session_state["response"]["status"])
        self.assertEqual((0, 0), (len(none.code), len(none.get("download_button"))))
        for part in ("Provisional", "data-decision", "Closest lead to verify"):
            self.assertNotIn(part, self._text(none))

    def test_observation_date_and_reference_scope_match_on_the_card_and_in_the_script(self):
        import finding_provenance as mapper

        app = self._lookup(self._app())
        project = mapper.project_find_care
        pointer = "https://example.invalid/dialysis-service"
        assessment = "2026-11-22"
        for observed_on, scope, wording in (
            ("2022-03-17", "claim", "It points to this statement."),
            (None, "claim", "It points to this statement."),
            (None, None, "The citation scope is unknown."),
        ):
            def project_with_observation(response, service, *, mode):
                projection = project(response, service, mode=mode)
                claim = next(f["service"] for f in projection["findings"] if f["index"] == 0)
                observation = mapper.Observation(
                    mapper.SYNTHETIC, "The North Campus provides hemodialysis.", claim["scope"],
                    role="support", origin="demo_fixture", field="procedures", observed_on=observed_on,
                    citation=pointer, citation_scope=scope)
                claim.update(mapper.summarize_claim(
                    "service", claim["scope"], [observation], service=service, as_of=assessment))
                return projection

            with self.subTest(observed_on=observed_on, scope=scope):
                with mock.patch.object(mapper, "project_find_care", side_effect=project_with_observation):
                    app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
                note = self._note(app)
                screen = self._text(app).removesuffix(note)
                expected = observed_on or "unknown"
                for surface in (screen, note):
                    self.assertIn(f"Service statement dated: {expected}.", surface)
                    self.assertIn(f"Service date {expected}.", surface)
                    self.assertIn(f"{pointer}. {wording}", surface)
                    self.assertNotIn(assessment, surface)
                    self.assertNotIn(f"Record reference: {pointer}", surface)

    def test_a_direct_text_hit_uses_the_joined_verification_decision(self):
        import finding_provenance as mapper

        app = self._lookup(self._app())
        project = mapper.project_find_care
        assessment = "2026-11-22"
        for case, message in (
            ("area", "Verify whether the requested service is delivered onsite at this branch."),
            ("absence", "Check for a later branch-specific change to the reported absence or referral."),
            ("conflict", "Resolve the conflicting service statements for this branch."),
        ):
            def project_with_downgrade(response, service, *, mode):
                projection = project(response, service, mode=mode)
                for finding in projection["findings"]:
                    scope = finding["service"]["scope"]
                    match = {"match": "exact", "observed_on": assessment}
                    observations = []
                    if case == "area":
                        finding["location"]["precision"] = "postal_area"
                    if case == "absence":
                        observations.append(mapper.Observation(
                            mapper.SYNTHETIC, "This branch reports no dialysis service.", scope, role="support",
                            assertion="explicit_absence", **match))
                    if case == "conflict":
                        observations.extend([
                            mapper.Observation(mapper.SYNTHETIC, "The branch reports dialysis service.", scope,
                                               role="support", assertion="onsite_delivery", **match),
                            mapper.Observation(mapper.SYNTHETIC, "The branch reports no dialysis service.", scope,
                                               role="conflict", assertion="explicit_absence", **match),
                        ])
                    finding["service"] = mapper.summarize_claim(
                        "service", scope, observations, service=service, as_of=assessment)
                return projection

            with self.subTest(case=case):
                with mock.patch.object(mapper, "project_find_care", side_effect=project_with_downgrade):
                    app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
                self.assertEqual("ok", app.session_state["response"]["status"])
                screen = self._text(app)
                self.assertIn('role="heading" aria-level="2">Verification lead: Example Regional Hospital.', screen)
                self.assertIn(message, screen)
                self.assertIn("Confirm which facility and branch this record is before relying on it.", screen)
                self.assertNotIn("Nearest record that states the service", screen)
                self.assertNotIn("Other records that state the service", screen)
                self.assertEqual((0, 0), (len(app.code), len(app.get("download_button"))))

    def test_the_first_press_answers_because_the_demonstration_form_starts_filled(self):
        app = self._app()
        app = self._step(app.button(key="find").click())
        self.assertIn("Send the patient to Campus B.", self._text(app))
        app = self._lookup(app)
        self.assertEqual("Jaipur, Rajasthan", app.text_input(key="where").value)
        app = self._step(app.button(key="find").click())
        self.assertIn("Provisional lead: Example Regional Hospital. Confirm before anyone travels.", self._text(app))
        self.assertEqual(0, len(app.error))

    def test_a_changed_lookup_marks_the_answer_out_of_date_and_hides_its_sources(self):
        app = self._lookup(self._app())
        app = self._step(app.button(key="find").click())
        self.assertIn("Other records that state the service", self._text(app))
        for change in (lambda a: a.radio(key="service").set_value("mri"),
                       lambda a: a.text_input(key="where").set_value("302001"),
                       lambda a: a.select_slider(key="radius").set_value(10)):
            changed = self._step(change(app))
            text = self._text(changed)
            self.assertIn("You changed the request. The answer below is for the earlier one.", text)
            self.assertIn("fc-old", text)
            self.assertEqual((0, 0), (len(changed.code), len(changed.get("download_button"))))
            self.assertNotIn("Other records that state the service", text)
            self.assertIn("Dialysis near Jaipur, Rajasthan, within 50 km.", text)  # still says what it answers
            # #302: an out-of-date answer shows no sources, so dialysis evidence never sits under MRI.
            self.assertNotIn("data-claims", text)
            self.assertNotIn("Why this finding?", text)
            # Putting the request back, or asking again, makes the answer current.
            back = self._step(changed.button(key="example-Dialysis near Jaipur, Rajasthan").click())
            self.assertNotIn("You changed the request", self._text(back))
            self.assertIn("data-claims", self._text(back))
            app = back
        app.radio(key="service").set_value("mri")
        app = self._step(app.button(key="find").click())
        text = self._text(app)
        self.assertNotIn("You changed the request", text)
        self.assertIn("MRI scan near Jaipur, Rajasthan, within 50 km.", text)

    def test_demonstration_can_be_chosen_outright_beside_warehouse_settings(self):
        app = self._lookup(self._app(**WAREHOUSE, FIND_CARE_DATA="demo"))
        app = self._step(app.button(key="example-Dialysis near Jaipur, Rajasthan").click())
        self.assertIn("Data: demonstration.", self._text(app))
        self.assertIn("Provisional lead: Example Regional Hospital. Confirm before anyone travels.", self._text(app))

    def test_typed_city_asks_which_place_then_answers(self):
        app = self._lookup(self._app())
        app.text_input(key="where").set_value("Jaipur")
        app = self._step(app.button(key="find").click())
        self.assertIn("More than one place has that name.", self._text(app))
        app = self._step(app.button(key="choice-Jaipur, Rajasthan").click())
        self.assertIn("Provisional lead: Example Regional Hospital. Confirm before anyone travels.", self._text(app))
        self.assertEqual("Jaipur, Rajasthan", app.text_input(key="where").value)
        self.assertNotIn("You changed the request", self._text(app))

    def test_an_empty_location_is_refused_in_plain_words(self):
        app = self._lookup(self._app())
        app = self._step(app.button(key="find").click())
        app.text_input(key="where").set_value("")
        app = self._step(app.button(key="find").click())
        self.assertIn("Type a city or town, a PIN code, or coordinates.", self._text(app))
        self.assertNotIn("Provisional lead", self._text(app))  # the earlier answer is gone, not left standing
        self.assertEqual((0, 0), (len(app.code), len(app.get("download_button"))))

    def test_a_real_town_the_demonstration_does_not_know_is_explained(self):
        app = self._app()
        for mode in [radio for radio in app.radio if radio.key == "mode"]:  # where the record lookup is a second job
            app = self._step(mode.set_value("lookup"))
        app.text_input(key="where").set_value("Mumbai")
        app = self._step(app.button(key="find").click())
        shown = self._text(app)
        self.assertIn("That place could not be located.", shown)
        self.assertIn("only find the places its six invented facilities are recorded in", shown)
        self.assertIn("Jaipur, Rajasthan (PIN 302001)", shown)
        self.assertNotIn("No dataset coordinates", shown)

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
        self.assertIn("What this does not tell you", text)
        self.assertIn(words.UNCHECKED_CLAIM, text)
        self.assertIn("Dialysis · Unconfirmed · Records nearby mention dialysis.", text)
        self.assertIn("Independent corroboration unknown", text)
        self.assertNotIn("data-claims", text)
        # #330: a withheld lead still says what was found, what is missing and the one allowed next action.
        for part in ('data-decision="withheld"',
                     "A lead exists in the real records, but no facility can be named here yet.",
                     "An individual identity and service claim cleared for this audience are required.",
                     "Ask the data owner to review and clear a named destination for this audience.",
                     "Phone a facility through your usual referral contact and ask whether it provides the "
                     "service onsite today and has a free place."):
            self.assertIn(part, text)
        self.assertNotIn("Confirmation call script", text)
        self.assertNotIn("Provisional", text)
        self._assert_nothing_restricted(app, raw)
        self.assertEqual({"request": {"service": "dialysis", "location": location, "radius_km": 50},
                          "data": "warehouse", "status": "withheld"}, json.loads(app.json[0].value))

        # Related-only evidence, a typed ambiguous city and a plain miss are withheld the same way.
        app = self._step(app.button(key="example-Dialysis within 2 km of PIN 302001").click())
        self.assertIn("mention something related to dialysis, but none has been reviewed", self._text(app))
        self.assertIn("A kidney department or a kidney specialist is not a working dialysis unit.", self._text(app))
        self._assert_nothing_restricted(app)
        app.text_input(key="where").set_value("Jaipur")
        app = self._step(app.button(key="find").click())
        self.assertIn("More than one place has that name.", self._text(app))
        self.assertIn("Type the state as well and search again", self._text(app))
        self.assertIn('data-decision="no_usable_evidence"', self._text(app))
        self.assertIn("Clarify which search location is intended.", self._text(app))
        self.assertIn("Change the request and search again.", self._text(app))
        self.assertNotIn("A lead exists in the real records", self._text(app))
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
            self.assertEqual(0, len(app.text_input) + len([radio for radio in app.radio if radio.key not in ("view", "lookup_source")]))
            everything = self._everything(app)
            for value in present.values():
                self.assertNotIn(value, everything)
            self._assert_nothing_restricted(app)
            # Choosing the demonstration outright still works beside the same settings.
            app = self._app(**present, FIND_CARE_DATA="demo")
            self.assertIn("Data: demonstration.", self._text(app))
            self.assertEqual(3, len([button for button in app.button if str(button.key).startswith("capacity-")]))

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
        "assert any('Check your symptoms' in t.value for t in app.title), [t.value for t in app.title]\n"
        "app = app.radio(key='view').set_value('Find care').run()\n"
        "assert not app.exception, app.exception\n"
        "app = app.radio(key='lookup_source').set_value('Simulated scenarios').run()\n"
        "assert any('Data: demonstration.' in m.value for m in app.markdown), [m.value for m in app.markdown]\n"
        "app = app.button(key='find').click().run()\n"
        "assert not app.exception, app.exception\n"
        "assert any('Send the patient to Campus B.' in m.value for m in app.markdown)\n"
        "assert 'Send to: Campus B' in app.code[0].value\n"
        "app = app.radio(key='mode').set_value('lookup').run()\n"
        "app = app.button(key='example-Dialysis near Jaipur, Rajasthan').click().run()\n"
        "assert not app.exception, app.exception\n"
        "assert any('Provisional lead: Example Regional Hospital. Confirm before anyone travels.' in m.value for m in app.markdown)\n"
        "assert app.code[0].value.startswith('Confirmation call script'), app.code[0].value[:80]\n"
        "assert 'Referral note' not in app.code[0].value and 'Send to:' not in app.code[0].value\n"
        "assert any('Fixture statement names North Campus. Physical branch unverified.' in m.value for m in app.markdown)\n"
        "assert any('Record reference: https://example.invalid/north-campus' in m.value for m in app.markdown)\n"
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
