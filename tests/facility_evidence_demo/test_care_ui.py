"""The interactive care flow at the top of the judge page (#287), driven through Streamlit's AppTest.

Uses the synthetic editions with their own hashes; the real decision function, never a mock.
"""
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

from app.facility_evidence_demo import area, care_decision, loader, walkthrough

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DISPLAY = HERE / "synthetic_display.json"
AREA = HERE / "synthetic_area.json"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(HAS_STREAMLIT, "streamlit is not installed")
class CareFlowTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.patches = [
            mock.patch.dict("os.environ", {loader.PATH_SETTING: str(DISPLAY), area.PATH_SETTING: str(AREA)}),
            mock.patch.dict(sys.modules, {"loader": loader, "walkthrough": walkthrough, "area": area,
                                          "care_decision": care_decision}),
            mock.patch.object(loader, "PINNED_SHA256", sha(DISPLAY)),
            mock.patch.object(area, "AREA_PINNED_SHA256", sha(AREA)),
        ]
        for patch in self.patches:
            patch.start()
        sys.modules.pop("care_ui", None)
        self.app = AppTest.from_file(str(ROOT / "app/facility_evidence_demo/app.py"), default_timeout=30)
        self.app.run()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        sys.modules.pop("care_ui", None)

    def pick(self, key, value):
        self.app.radio(key=f"care_{key}").set_value(value)
        self.app.run()
        self.assertFalse(self.app.exception)

    def text(self):
        return " ".join(m.value for m in self.app.markdown)

    def asked(self):
        return [r.key for r in self.app.radio]

    def test_starts_with_only_the_danger_question(self):
        self.assertEqual(["care_danger"], self.asked())
        self.assertNotIn("Get emergency help now", self.text())

    def test_reported_danger_interrupts_at_once(self):
        self.pick("danger", "yes")
        self.assertIn("Get emergency help now", self.text())
        self.assertIn("dial 112", self.text())
        self.assertEqual(["care_danger"], self.asked())  # no further questions

    def test_emergency_shows_without_any_evidence_file(self):
        with mock.patch.dict("os.environ", {loader.PATH_SETTING: "/nonexistent", area.PATH_SETTING: "/nonexistent"}):
            self.pick("danger", "no")
            self.pick("urgency", "emergency")
            self.assertIn("Get emergency help now", self.text())
            self.assertEqual(["care_danger", "care_urgency"], self.asked())

    def test_conflicting_priorities_are_shown_side_by_side(self):
        self.pick("danger", "no")
        self.pick("urgency", "routine")
        self.pick("concern", "injury")
        self.pick("injury_kind", "unsure")
        self.pick("severity", "severe")
        text = self.text()
        self.assertIn("Service checked: Trauma care", text)
        self.assertIn('<span class="fe-prio-k">You chose</span><span class="fe-prio-v">Routine</span>', text)
        self.assertIn('<span class="fe-prio-k">Automatic check</span><span class="fe-prio-v">Prompt review</span>', text)
        self.assertIn('<span class="fe-prio-k">Combined</span><span class="fe-prio-v">Prompt review</span>', text)
        self.assertIn("No reviewed facility yet", text)

    def test_dialysis_shows_its_dated_case_and_area_context(self):
        self.pick("danger", "no")
        self.pick("urgency", "soon")
        self.pick("concern", "dialysis")
        self.pick("severity", "moderate")
        text = self.text()
        self.assertIn("What the evidence shows for dialysis", text)
        self.assertIn("A dated public case", text)
        self.assertIn("730 of 1,000 records can be placed only to an area", text)
        self.assertIn("Synthetic test file", text)

    def test_named_injury_is_specific_and_carries_no_trauma_counts(self):
        self.pick("danger", "no")
        self.pick("urgency", "routine")
        self.pick("concern", "injury")
        self.pick("injury_kind", "burn")
        self.pick("severity", "moderate")
        text = self.text()
        self.assertIn("outside what the evidence covers", text)
        self.assertIn("burn care", text)
        self.assertNotIn("What the evidence shows for", text)

    def test_injury_kind_does_not_survive_a_change_of_need(self):
        self.pick("danger", "no")
        self.pick("urgency", "routine")
        self.pick("concern", "injury")
        self.pick("injury_kind", "burn")
        self.pick("concern", "mri")
        self.assertNotIn("care_injury_kind", self.asked())
        self.pick("severity", "mild")
        self.assertIn("Service checked: MRI", self.text())
        self.assertNotIn("burn", self.text())

    def test_missing_evidence_file_says_data_unavailable(self):
        with mock.patch.dict("os.environ", {loader.PATH_SETTING: "/nonexistent"}):
            self.pick("danger", "no")
            self.pick("urgency", "routine")
            self.pick("concern", "dialysis")
            self.pick("severity", "mild")
            text = self.text()
        self.assertIn("Data unavailable", text)
        self.assertNotIn("What the evidence shows for", text)

    def test_start_over_clears_every_answer(self):
        self.pick("danger", "yes")
        self.app.button(key="care_start_over").click()
        self.app.run()
        self.assertIsNone(self.app.radio(key="care_danger").value)
        self.assertNotIn("Get emergency help now", self.text())


if __name__ == "__main__":
    unittest.main()
