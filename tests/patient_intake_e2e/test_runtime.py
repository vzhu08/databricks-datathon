import unittest
from pathlib import Path

from tests.patient_intake_e2e.app_copy import offline_probe, staged_app


class StagedPatientRuntimeTests(unittest.TestCase):
    def run_cases(self, case_class, *extra_sources):
        script = "\n".join(
            Path(__file__).with_name(name).read_text(encoding="utf-8")
            for name in ("runtime_cases.py", *extra_sources)
        )
        script += (
            "\nsuite = defaultTestLoader.loadTestsFromTestCase(" + case_class + ")\n"
            "if not TextTestRunner(verbosity=2).run(suite).wasSuccessful():\n"
            "    raise SystemExit(1)\n"
        )
        with staged_app() as source:
            result = offline_probe(source, script, settings={"FIND_CARE_DATA": "demo"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_journeys_and_failures_from_app_only(self):
        self.run_cases("StagedRuntimeCases")

    def test_v2_forms_and_cleanup_from_app_only(self):
        self.run_cases("StagedV2Cases", "v2_runtime_cases.py")
