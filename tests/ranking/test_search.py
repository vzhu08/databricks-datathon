import json
import math
import unittest
from pathlib import Path

from app.ranking import search_facilities
from app.ranking.evidence import best_evidence
from app.ranking.location import EARTH_RADIUS_KM

FIXTURE = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "search.json"


def campus(facility_id="a", **fields):
    return dict({
        "facility_id": facility_id,
        "name": "Synthetic Hospital",
        "city": "Sample City",
        "state": "Sample State",
        "pin": "001234",
        "latitude": 0.0,
        "longitude": 0.0,
        "procedures": "The clinic performs dialysis.",
    }, **fields)


class SearchTests(unittest.TestCase):
    def test_shared_synthetic_cases(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            with self.subTest(case=case["id"]):
                result = search_facilities(**case["query"], facilities=fixture["facilities"])
                for key, expected in case["expected"].items():
                    actual = result[key]
                    if key in {"direct_results", "indirect_leads"}:
                        self.assertEqual(len(actual), len(expected))
                        for card, expected_fields in zip(actual, expected):
                            self.assertEqual({field: card[field] for field in expected_fields}, expected_fields)
                            self.assertEqual(card["availability"], "unknown")
                            self.assertEqual(card["location"]["city"], "Jaipur")
                    else:
                        self.assertEqual(actual, expected)

    def test_place_normalization_median_and_missing_coordinates(self):
        facilities = [
            campus("a", city=" Sample\tCITY ", state="Sample State", latitude=12, longitude=30),
            campus("b", city="sample city", state="SAMPLE STATE", latitude=16, longitude=34),
            campus("c", city="Sample City", latitude=35, longitude=float("nan")),
            campus("d", city=" Sample City", latitude=14, longitude=32, procedures=None),
        ]
        for query in ({"city": " SAMPLE  city", "state": "sample\tstate"}, {"pin": " 001234 "}):
            with self.subTest(query=query):
                response = search_facilities("dialysis", query, facilities=facilities, radius_km=400)
                self.assertEqual(response["status"], "ok")
                self.assertTrue(response["approximate_location"])
                self.assertEqual({row["facility_id"] for row in response["direct_results"]}, {"a", "b"})
                self.assertTrue(all(300 < row["distance_km"] < 320 for row in response["direct_results"]))

    def test_unresolved_and_ambiguous_even_if_one_state_has_no_coordinates(self):
        facilities = [campus(), campus("b", state="Other State", latitude=None)]
        response = search_facilities("dialysis", {"city": "sample city"}, facilities=facilities)
        self.assertEqual(response["status"], "ambiguous_location")
        self.assertEqual([choice["state"] for choice in response["location_choices"]], ["Other State", "Sample State"])
        for query in ({"city": "Sample City", "state": "Other State"}, {"pin": "999999"}):
            response = search_facilities("dialysis", query, facilities=facilities)
            self.assertEqual(response["status"], "unresolved_location")
            self.assertTrue(response["message"])

    def test_invalid_requests(self):
        origin = {"latitude": 0, "longitude": 0}
        for values in [
            {"location": {"latitude": "NaN", "longitude": 0}},
            {"location": {"latitude": True, "longitude": 0}},
            {"location": {"latitude": 0, "longitude": 181}},
            {"location": {"latitude": 0}},
            {"location": {"city": "Sample City", "pin": "001234"}},
            {"location": {"pin": 123456}},
            {"location": {"pin": "12345"}},
            {"service": "unsupported"},
            {"radius_km": float("inf")},
            {"radius_km": 0},
            {"limit": False},
        ]:
            with self.subTest(values=values):
                query = dict({"service": "dialysis", "location": origin}, **values)
                response = search_facilities(**query, facilities=[campus()])
                self.assertEqual(response["status"], "invalid_input")
                self.assertTrue(response["message"])

    def test_distance_radius_tie_break_and_limit(self):
        boundary = math.degrees(50.0 / EARTH_RADIUS_KM)
        facilities = [
            campus("b", latitude=boundary), campus("a", latitude=-boundary),
            campus("c", latitude=boundary + 0.0005), campus("d", latitude=0.1),
            campus("e", latitude=-0.3), campus("f", longitude="unknown"),
        ]
        origin = {"latitude": 0, "longitude": 0}
        for radius, limit, expected in ((50, 20, ["d", "e", "a"]), (20, 3, ["d"]), (51, 1, ["d"])):
            response = search_facilities("dialysis", origin, facilities=facilities, radius_km=radius, limit=limit)
            self.assertEqual([row["facility_id"] for row in response["direct_results"]], expected)
            self.assertFalse(response["approximate_location"])
        response = search_facilities("dialysis", origin, facilities=[facilities[2]])
        self.assertEqual(response["status"], "no_match")
        response = search_facilities("dialysis", origin, facilities=[facilities[2]], radius_km=51)
        self.assertAlmostEqual(response["direct_results"][0]["distance_km"], 50.0556, places=3)

    def test_antimeridian_and_record_link_normalization(self):
        facilities = [campus(longitude=-179.9, record_source_urls=json.dumps([
            "https://example.invalid/source", "https://example.invalid/source", None, "bad URL",
        ]))]
        result = search_facilities("dialysis", {"latitude": 0, "longitude": 179.9}, facilities=facilities)
        card = result["direct_results"][0]
        self.assertAlmostEqual(card["distance_km"], 22.239, places=3)
        self.assertEqual(card["record_source_urls"], ["https://example.invalid/source"])


class EvidenceTests(unittest.TestCase):
    def test_stronger_synonym_preserves_original_field_and_text(self):
        row = {
            "description": "Nephrology Clinic. We provide Haemodialysis twice daily.",
            "capabilities": "Dialysis available.",
            "procedures": [None, "No maintenance haemodialysis."],
        }
        self.assertEqual(best_evidence(row, "dialysis"), (
            "direct", "We provide Haemodialysis twice daily.", "description",
        ))

    def test_negative_and_referred_out_claims(self):
        for service, text in (
            ("mri", "M.R.I. Scanner is not yet available."),
            ("mri", "The MRI scanner is out of order."),
            ("mri", "MRI\nnot available at this site."),
            ("mri", "MRI will be offered at this hospital."),
            ("mri", "No MRI or dialysis at this campus."),
            ("dialysis", "No MRI or dialysis at this campus."),
            ("dialysis", "Dialysis and MRI are planned."),
            ("dialysis", "Patients are referred for peritoneal dialysis."),
            ("dialysis", "Dialysis referrals only."),
            ("dialysis", "The clinic doesn't provide dialysis."),
            ("dialysis", "The clinic does not have nephrology."),
            ("trauma_care", "Trauma cases are transferred to another trauma center."),
            ("trauma_care", "A Trauma Centre is coming soon."),
            ("trauma_care", "No Emergency Department."),
        ):
            with self.subTest(service=service, text=text):
                self.assertIsNone(best_evidence({"description": text}, service))

    def test_exclusions_preserve_separate_service_claims(self):
        for text, excerpt in (
            ("MRI is provided onsite and dialysis is unavailable.", "MRI is provided onsite"),
            ("We offer MRI and refer patients elsewhere for dialysis.", "We offer MRI"),
            ("MRI is unavailable, but magnetic resonance imaging is provided in Building B.",
             "magnetic resonance imaging is provided in Building B."),
            ("Patients are referred here for MRI.", "Patients are referred here for MRI."),
            ("MRI, dialysis, and trauma care available.", "MRI, dialysis, and trauma care available."),
        ):
            with self.subTest(text=text):
                self.assertEqual(best_evidence({"equipment": text}, "mri"), ("direct", excerpt, "equipment"))
