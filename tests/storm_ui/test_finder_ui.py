import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

from app.storm_ui import build_finder

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "storm_ui"


def _has_travel():
    try:
        return importlib.util.find_spec("app.travel.finder") is not None
    except ModuleNotFoundError:
        return False


class FinderUiTests(unittest.TestCase):
    def _bundle(self):
        text = build_finder.TARGET.read_text(encoding="utf-8")
        return text, json.loads(text[text.index("{"):text.rindex(";")])

    @unittest.skipUnless(_has_travel(), "app.travel is needed to regenerate the finder examples")
    def test_committed_examples_are_current(self):
        self.assertEqual(build_finder.TARGET.read_text(encoding="utf-8"), build_finder.render())

    def test_examples_are_invented_and_hold_no_request_secrets(self):
        text, bundle = self._bundle()
        self.assertIs(bundle["synthetic"], True)
        self.assertEqual({key for key, *_ in build_finder.EXAMPLES}, {example["key"] for example in bundle["examples"]})
        for example in bundle["examples"]:
            self.assertNotIn("candidates", example["request"])
            for row in example["response"]["routing"]["results"]:
                self.assertTrue(row["facility_id"].startswith("SYNTHETIC-"))
        for marker in ("SYNTHETIC-KEY", "api_key", "key=", "account_scope"):
            self.assertNotIn(marker, text)

    def test_page_stays_offline_and_calls_out_only_on_search(self):
        for name in ("finder.html", "finder.css", "finder.js", "finder_state.js"):
            text = (PAGE / name).read_text(encoding="utf-8")
            for marker in ("http://", "https://", "//cdn", "@import", "fetch(", "XMLHttpRequest", "WebSocket",
                           "setInterval", "setTimeout", "localStorage", "sessionStorage", "indexedDB"):
                self.assertNotIn(marker, text, f"{name} must not contain {marker}")
        script = (PAGE / "finder.js").read_text(encoding="utf-8")
        # The hosting backend's transport is called in exactly one place: the Search button's handler.
        self.assertEqual(1, script.count("transport(current.request)"))
        self.assertEqual(1, script.count('addEventListener("click", search)'))
        self.assertIn("if (!transport || current.inFlight || !current.request) return;", script)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the page-state checks")
    def test_display_logic_against_every_example(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/finder_check.js")], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ checks")


if __name__ == "__main__":
    unittest.main()
