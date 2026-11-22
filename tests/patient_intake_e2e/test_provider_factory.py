import importlib.util
import unittest
from pathlib import Path

from tests.patient_intake_e2e.app_copy import offline_probe, staged_app


@unittest.skipUnless(importlib.util.find_spec("streamlit"), "Streamlit is needed for app-only screen checks")
class ProviderFactoryScreenTests(unittest.TestCase):
    def run_screen_cases(self, case_class, *extra_sources):
        sources = ("provider_factory_cases.py", *extra_sources)
        script = "\n".join(Path(__file__).with_name(name).read_text(encoding="utf-8") for name in sources)
        script += (
            "\nsuite = unittest.defaultTestLoader.loadTestsFromTestCase(" + case_class + ")\n"
            "if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():\n"
            "    raise SystemExit(1)\n"
        )
        with staged_app() as folder:
            result = offline_probe(folder, script, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_factory_modes_from_app_only(self):
        self.run_screen_cases("ExistingFactoryScreenCases")

    def test_assessment_backend_factory_from_app_only(self):
        self.run_screen_cases("AssessmentFactoryRuntimeCases", "assessment_factory_cases.py")
