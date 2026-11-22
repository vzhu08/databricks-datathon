import unittest

from tests.patient_intake_e2e.app_copy import offline_probe, staged_app


class PatientPackageTests(unittest.TestCase):
    def test_runtime_modules_import_from_app_only(self):
        with staged_app() as source:
            self.assertFalse((source.parent / "contracts").exists())
            self.assertFalse((source.parent / "tests").exists())
            result = offline_probe(source, """
from importlib import import_module
from pathlib import Path
import sys

package_root = Path.cwd() / "patient_intake"
for name in (
    "patient_intake",
    "patient_intake.service",
    "patient_intake.session",
    "patient_intake.interview",
    "patient_intake.handoff",
    "patient_intake.providers.transport",
):
    module = import_module(name)
    assert Path(module.__file__).resolve().is_relative_to(package_root), name

assert not any(
    name in {"intake", "app.intake"} or name.startswith(("intake.", "app.intake."))
    for name in sys.modules
), "Patient runtime imported the fictional intake engine"
""", settings={"FIND_CARE_DATA": "demo"})
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
