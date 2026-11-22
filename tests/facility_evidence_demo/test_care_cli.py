"""Operator entry-point regressions. Use production pins for fail-closed checks."""

from contextlib import redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.facility_evidence_demo import __main__ as cli


class CareCommandTests(unittest.TestCase):
    def run_cli(self, *args, env=None):
        output = io.StringIO()
        with patch.dict(os.environ, env or {}, clear=True), redirect_stdout(output):
            cli.main(args)
        return output.getvalue()

    def test_package_help(self):
        process = subprocess.run(
            [sys.executable, "-m", "app.facility_evidence_demo", "--help"],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True,
        )
        self.assertIn("--urgency", process.stdout)
        self.assertIn("FACILITY_EVIDENCE_DISPLAY", process.stdout)

    def test_both_interrupts_precede_file_io(self):
        with patch.object(cli, "load_local", side_effect=AssertionError("unexpected file read")):
            for args in (("--urgency", "emergency"), ("--danger", "yes", "--urgency", "routine")):
                with self.subTest(args=args):
                    self.assertIn("Action: interrupt", self.run_cli(*args))

    def test_replay_with_missing_inputs_and_changed_selection(self):
        common = ("--urgency", "routine", "--severity", "severe", "--danger", "no")
        first = self.run_cli("--concern", "injury", *common)
        second = self.run_cli("--concern", "mri", *common)
        self.assertIn("Self-rated urgency: routine", first)
        self.assertIn("Combined workflow urgency: prompt review", first)
        self.assertIn("Service checked: trauma care", first)
        self.assertIn("Service checked: mri", second)
        self.assertNotIn("Service checked: trauma care", second)
        for output in (first, second):
            self.assertIn("Facility evidence unavailable", output)
            self.assertIn("Area evidence unavailable", output)

    def test_self_rating_and_safety_inputs_change_distinct_priorities(self):
        def priorities(severity, urgency, danger="no"):
            text = self.run_cli("--concern", "injury", "--severity", severity,
                                "--urgency", urgency, "--danger", danger)
            fields = dict(line.strip().split(": ", 1) for line in text.splitlines() if ": " in line)
            self.assertEqual(fields["Self-rated urgency"], urgency)
            return fields["Automatic assessment priority"], fields["Combined workflow urgency"]

        self.assertEqual(priorities("moderate", "routine"), ("standard", "standard"))
        self.assertEqual(priorities("moderate", "soon"), ("standard", "prompt review"))
        self.assertEqual(priorities("severe", "routine"), ("prompt review", "prompt review"))
        self.assertEqual(priorities("moderate", "routine", danger="yes"), ("emergency", "emergency"))
        self.assertEqual(priorities("moderate", "emergency"), ("standard", "emergency"))

    def test_changing_injury_kind_and_concern(self):
        common = ("--severity", "moderate", "--urgency", "soon", "--danger", "no")
        dialysis = self.run_cli("--concern", "dialysis", "--injury-kind", "burn", *common)
        self.assertIn("Injury kind: unsure", dialysis)
        for kind, capability in (("head", "assessment for head injuries"), ("burn", "burn care")):
            with self.subTest(kind=kind):
                output = self.run_cli("--concern", "injury", "--injury-kind", kind, *common)
                self.assertIn("Injury kind: " + kind, output)
                self.assertIn("Outcome: no supported service", output)
                self.assertNotIn("Service checked:", output)
                next_check = next(line for line in output.splitlines() if line.startswith("Next check:"))
                self.assertIn(capability, next_check)
                self.assertIn("branch", next_check)

    def test_pinned_fixture_render_and_cross_service_scope(self):
        directory = Path(__file__).parent
        display = directory / "synthetic_display.json"
        area = directory / "synthetic_area.json"
        env = {cli.loader.PATH_SETTING: str(display), cli.area.PATH_SETTING: str(area)}
        with patch.object(cli.loader, "PINNED_SHA256", hashlib.sha256(display.read_bytes()).hexdigest()), \
             patch.object(cli.area, "AREA_PINNED_SHA256", hashlib.sha256(area.read_bytes()).hexdigest()):
            common = ("--severity", "mild", "--urgency", "soon", "--danger", "no")
            dialysis = self.run_cli("--concern", "dialysis", *common, env=env)
            mri = self.run_cli("--concern", "mri", *common, env=env)
        self.assertIn("Separate historical case:", dialysis)
        self.assertNotIn("Separate historical case:", mri)
        self.assertIn("National location coverage:", mri)
        self.assertIn("Eligible destinations: 0", mri)

    def test_volume_configuration_cannot_trigger_sdk(self):
        env = {cli.loader.PATH_SETTING: "dbfs:/Volumes/example/display.json",
               cli.area.PATH_SETTING: "/Volumes/example/area.json"}
        with patch.object(cli.loader, "read_bytes", side_effect=AssertionError("unexpected SDK path")):
            result = self.run_cli("--concern", "dialysis", "--severity", "mild",
                                  "--urgency", "routine", "--danger", "no", env=env)
        self.assertIn("Facility evidence unavailable", result)
        self.assertIn("Area evidence unavailable", result)
        self.assertIn("local copy", result)


if __name__ == "__main__":
    unittest.main()
