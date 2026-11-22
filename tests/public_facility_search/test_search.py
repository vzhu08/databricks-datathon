import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from app.public_facility_search import search_public_facilities


ROOT = Path(__file__).resolve().parents[2]


class PublicFacilitySearchTests(unittest.TestCase):
    def test_pune_operator_claims_and_contacts(self):
        results = search_public_facilities(place="  PUNE ", service="DIALYSIS")
        self.assertEqual(
            [(r["operator"], r["service"], r["source_url"], r["contact_phone"]) for r in results],
            [
                ("KEM Hospital, Pune", "Maintenance haemodialysis",
                 "https://www.kemhospitalpune.org/specialities/nephrology/", "+91 20 2621 7300"),
                ("Jehangir Hospital", "Dialysis",
                 "https://www.jehangirhospital.com/nephrology-sp/", "020-6681-9966"),
            ],
        )
        for row in results:
            self.assertEqual("Pune", row["city"])
            self.assertEqual("Operator-reported service", row["evidence_basis"])
            self.assertEqual("City-level location only.", row["location_scope"].split(". ")[1])
            self.assertIsNone(row["source_date"])
            self.assertEqual("2026-11-22", row["checked_on"])
            self.assertEqual("No reviewed VF match asserted", row["vf_match"])
            for field in ("availability", "staffing", "entrance"):
                self.assertEqual("Unknown", row[field])
            self.assertIn("confirm", row["next_action"])
            self.assertNotIn("service_queries", row)

    def test_maintenance_and_modality_need_direct_evidence(self):
        for query in ("haemodialysis", "hemodialysis", "maintenance dialysis",
                      "MAINTENANCE    HAEMODIALYSIS", "maintenance hemodialysis"):
            with self.subTest(query=query):
                rows = search_public_facilities("Pune", query)
                self.assertEqual(["KEM Hospital, Pune"], [r["operator"] for r in rows])

    def test_unsupported_inputs_return_no_records(self):
        for place, service in (("Jaipur", "dialysis"), ("", "dialysis"), ("Pune", ""),
                               ("Pune", "MRI"), ("Pune", "dialysis available now"),
                               ("Pune", "dialysis and trauma"), ("Pune", "home dialysis")):
            with self.subTest(place=place, service=service):
                self.assertEqual([], search_public_facilities(place, service))

    def test_repository_command_returns_the_callable_results(self):
        command = [sys.executable, "-m", "app.public_facility_search", "--place", "Pune",
                   "--service", "dialysis"]
        output = subprocess.check_output(command, cwd=ROOT, text=True)
        self.assertEqual(search_public_facilities("Pune", "dialysis"), json.loads(output))

    def test_deployed_package_runs_without_other_data_or_modules(self):
        with TemporaryDirectory() as directory:
            shutil.copytree(ROOT / "app" / "public_facility_search",
                            Path(directory) / "public_facility_search",
                            ignore=shutil.ignore_patterns("__pycache__"))
            for place in ("Pune", "Jaipur"):
                with self.subTest(place=place):
                    command = [sys.executable, "-E", "-m", "public_facility_search",
                               "--place", place, "--service", "dialysis"]
                    output = subprocess.check_output(command, cwd=directory, text=True)
                    self.assertEqual(search_public_facilities(place, "dialysis"), json.loads(output))
