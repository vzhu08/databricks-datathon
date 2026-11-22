import json
import shutil
import subprocess
import unittest
from pathlib import Path

from app.ranking.urgency import rank_campuses
from app.storm_ui import build_ask

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "storm_ui"


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require.resolve('playwright')"], capture_output=True).returncode == 0


class AskUiTests(unittest.TestCase):
    def test_committed_answers_are_current(self):
        self.assertEqual(build_ask.TARGET.read_text(encoding="utf-8"), build_ask.render())

    def test_every_answer_is_the_rankers_own_response(self):
        bundle = json.loads(json.dumps(build_ask.bundle()))
        self.assertIs(bundle["synthetic"], True)
        self.assertEqual(len(build_ask.SERVICES) * len(build_ask.PLACES) * len(build_ask.URGENCIES), len(bundle["answers"]))
        for key, answer in bundle["answers"].items():
            fresh = json.loads(json.dumps(rank_campuses(**answer["request"])))
            self.assertEqual(fresh, answer["response"], key)
            for row in answer["response"]["ranked"]:
                self.assertEqual("unknown", row["availability"], key)
            # A campus is a candidate only when its invented record mentions the service.
            service = answer["request"]["service"]
            for candidate in answer["request"]["candidates"]:
                self.assertIn(f"{candidate['facility_id']}|{service}", bundle["records"], key)

    def test_page_stays_offline_and_does_not_rank(self):
        for name in ("index.html", "ask.css", "ask.js", "ask_state.js"):
            text = (PAGE / name).read_text(encoding="utf-8")
            for marker in ("http://", "https://", "//cdn", "@import", "fetch(", "XMLHttpRequest", "WebSocket",
                           "localStorage", "sessionStorage", "indexedDB"):
                self.assertNotIn(marker, text, f"{name} must not contain {marker}")
        self.assertNotIn(".sort(", (PAGE / "ask.js").read_text(encoding="utf-8"))

    def test_fractions_are_rounded_so_every_python_writes_the_same_file(self):
        # Python 3.12 changed how `sum` adds fractions, which moved some scores by about 1e-14.
        # Only fractions may change, and only past the ninth decimal place.
        raw, written = build_ask.bundle(), build_ask.stable(build_ask.bundle())

        def compare(a, b, where):
            self.assertIs(type(a), type(b), where)
            if isinstance(a, dict):
                self.assertEqual(list(a), list(b), where)
                for name in a:
                    compare(a[name], b[name], f"{where}.{name}")
            elif isinstance(a, list):
                self.assertEqual(len(a), len(b), where)
                for index, (x, y) in enumerate(zip(a, b)):
                    compare(x, y, f"{where}[{index}]")
            elif isinstance(a, float):
                self.assertLess(abs(a - b), 1e-9, where)
                self.assertEqual(round(b, build_ask.DECIMALS), b, where)
            else:
                self.assertEqual(a, b, where)

        compare(raw, written, "bundle")
        self.assertEqual(0.1, build_ask.stable(0.1 + 1e-14))
        self.assertEqual({"a": [1, "x", True, None, 2.5]}, build_ask.stable({"a": (1, "x", True, None, 2.5)}))

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the page-state checks")
    def test_wording_against_every_answer(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/ask_check.js")], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ checks")

    @unittest.skipUnless(_has_playwright(), "Node.js with Playwright is needed for the browser check")
    def test_judge_path_in_a_browser(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/ask_browser_check.js")], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ browser checks")


if __name__ == "__main__":
    unittest.main()
