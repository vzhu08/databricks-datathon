"""Operator entry-point regressions. Use production pins for fail-closed checks."""

from contextlib import redirect_stdout
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
        self.assertIn("Urgency: routine", first)
        self.assertIn("Workflow urgency: prompt review", first)
        self.assertIn("Service checked: trauma care", first)
        self.assertIn("Service checked: mri", second)
        self.assertNotIn("Service checked: trauma care", second)
        for output in (first, second):
            self.assertIn("Facility evidence unavailable", output)
            self.assertIn("Area evidence unavailable", output)

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
