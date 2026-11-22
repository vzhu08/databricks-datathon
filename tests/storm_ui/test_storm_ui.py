import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from app.storm_ui import build

ROOT = Path(__file__).resolve().parents[2]


class StormUiDataTests(unittest.TestCase):
    def test_committed_bundle_is_current(self):
        self.assertEqual(build.TARGET.read_text(encoding="utf-8"), build.render())
        self.assertEqual(0, subprocess.call([sys.executable, "-m", "app.storm_ui.build", "--check"], cwd=ROOT,
                                            stdout=subprocess.DEVNULL))

    def test_default_replay_is_the_pinned_fixture(self):
        fixture = json.loads((ROOT / "contracts/fixtures/storm_replay.json").read_text(encoding="utf-8"))
        bundle = json.loads(json.dumps(build.bundle()))
        self.assertEqual(fixture, bundle["replays"][bundle["default"]])
        self.assertEqual(len(build.SCENARIOS) * len(build.DETOUR_CAPS), len(bundle["replays"]))
        self.assertTrue(all(replay["synthetic"] is True for replay in bundle["replays"].values()))

    def test_page_assets_stay_offline(self):
        for name in ("index.html", "storm.css", "storm.js", "replay_state.js"):
            path = ROOT / "app" / "storm_ui" / name
            if path.exists():
                # The SVG namespace is an identifier the browser never fetches.
                text = path.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
                for marker in ("http://", "https://", "//cdn", "@import"):
                    self.assertNotIn(marker, text, f"{name} must not load anything from the network")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the page-state checks")
    def test_state_derivation_against_every_embedded_replay(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/state_check.js")], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ checks")


if __name__ == "__main__":
    unittest.main()
