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

    def radio(self, key):
        """The radio for a question. Widget keys are care_<visit>_<generation>_<question>."""
        return next(r for r in self.app.radio if r.key.split("_", 3)[3] == key)

    def pick(self, key, value):
        self.radio(key).set_value(value)
        self.app.run()
        self.assertFalse(self.app.exception)

    def text(self):
        return " ".join(m.value for m in self.app.markdown)

    def asked(self):
        return [r.key.split("_", 3)[3] for r in self.app.radio]

    def checked(self):
        return {r.key.split("_", 3)[3]: r.value for r in self.app.radio if r.value is not None}

    def test_starts_with_only_the_danger_question(self):
        self.assertEqual(["danger"], self.asked())
        self.assertNotIn("Get emergency help now", self.text())

    def test_reported_danger_interrupts_at_once(self):
        self.pick("danger", "yes")
        self.assertIn("Get emergency help now", self.text())
        self.assertIn("dial 112", self.text())
        self.assertEqual(["danger"], self.asked())  # no further questions

    def test_emergency_shows_without_any_evidence_file(self):
        with mock.patch.dict("os.environ", {loader.PATH_SETTING: "/nonexistent", area.PATH_SETTING: "/nonexistent"}):
            self.pick("danger", "no")
            self.pick("urgency", "emergency")
            self.assertIn("Get emergency help now", self.text())
            self.assertEqual(["danger", "urgency"], self.asked())

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
        self.assertNotIn("injury_kind", self.asked())
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
        old_key = self.radio("danger").key
        self.app.button(key="care_start_over").click()
        self.app.run()
        self.assertIsNone(self.radio("danger").value)
        self.assertNotEqual(old_key, self.radio("danger").key)  # a new widget, so nothing stays checked
        self.assertNotIn("Get emergency help now", self.text())

    def test_danger_twice_with_start_over_between_alerts_both_times(self):
        for _ in range(2):
            self.assertEqual({}, self.checked())
            self.pick("danger", "yes")
            self.assertEqual({"danger": "yes"}, self.checked())
            self.assertIn("Get emergency help now", self.text())
            self.app.button(key="care_start_over").click()
            self.app.run()
            self.assertNotIn("Get emergency help now", self.text())

    def test_either_interrupt_stops_the_page_before_any_evidence_is_read(self):
        for answers in ([("danger", "yes")], [("danger", "no"), ("urgency", "emergency")]):
            with self.subTest(answers=answers), \
                    mock.patch.object(loader, "read_bytes", wraps=loader.read_bytes) as reads, \
                    mock.patch.object(loader, "load", wraps=loader.load) as display_loads, \
                    mock.patch.object(area, "load", wraps=area.load) as area_loads:
                for index, (key, value) in enumerate(answers):
                    if index == len(answers) - 1:  # count only the run that interrupts
                        reads.reset_mock(), display_loads.reset_mock(), area_loads.reset_mock()
                    self.pick(key, value)
                text = self.text()
                self.assertIn("Get emergency help now", text)
                reads.assert_not_called()
                display_loads.assert_not_called()
                area_loads.assert_not_called()
                for below in ("The evidence behind every answer", "No facility can be recommended yet",
                              "Where the records place facilities", "Data unavailable"):
                    self.assertNotIn(below, text)
                self.assertTrue(self.app.button(key="care_start_over"))
                self.app.button(key="care_start_over").click()
                self.app.run()

    def test_interrupt_with_missing_files_shows_only_the_alert(self):
        with mock.patch.dict("os.environ", {loader.PATH_SETTING: "/nonexistent", area.PATH_SETTING: "/nonexistent"}):
            self.pick("danger", "yes")
            self.assertIn("Get emergency help now", self.text())
            self.assertNotIn("unavailable", self.text())

    def test_leaving_an_emergency_asks_the_later_questions_afresh(self):
        self.pick("danger", "no")
        self.pick("urgency", "soon")
        self.pick("concern", "dialysis")
        self.pick("severity", "moderate")
        self.assertIn("Service checked: Dialysis", self.text())
        self.pick("urgency", "emergency")
        self.assertEqual(["danger", "urgency"], self.asked())
        self.pick("urgency", "soon")
        self.assertEqual({"danger": "no", "urgency": "soon"}, self.checked())
        self.assertNotIn("Service checked", self.text())

    def test_result_always_matches_the_answers_on_screen(self):
        self.pick("danger", "no")
        self.pick("urgency", "routine")
        self.pick("concern", "injury")
        self.pick("injury_kind", "head")
        self.pick("severity", "moderate")
        self.assertIn("head injury", self.text())
        self.pick("concern", "dialysis")  # the kind leaves the screen; severity stays checked
        self.assertEqual({"danger": "no", "urgency": "routine", "concern": "dialysis", "severity": "moderate"},
                         self.checked())
        self.assertIn("Service checked: Dialysis", self.text())
        self.pick("concern", "injury")  # the kind is asked afresh, so no result until it is answered
        self.assertNotIn("injury_kind", self.checked())
        self.assertEqual("moderate", self.checked()["severity"])
        self.assertNotIn("Service checked", self.text())
        self.assertNotIn("outside what the evidence covers", self.text())
        self.pick("injury_kind", "burn")
        self.assertIn("burn care", self.text())
        self.assertNotIn("head injury", self.text())

    def test_changing_only_the_self_rating_keeps_the_other_answers(self):
        self.pick("danger", "no")
        self.pick("urgency", "routine")
        self.pick("concern", "mri")
        self.pick("severity", "moderate")
        self.assertIn('<span class="fe-prio-k">Combined</span><span class="fe-prio-v">Standard</span>', self.text())
        self.pick("urgency", "soon")
        text = self.text()
        self.assertIn('<span class="fe-prio-k">Automatic check</span><span class="fe-prio-v">Standard</span>', text)
        self.assertIn('<span class="fe-prio-k">Combined</span><span class="fe-prio-v">Prompt review</span>', text)

    def test_copy_does_not_claim_nothing_is_sent(self):
        self.assertNotIn("stored or sent", self.text())
        self.assertIn("local rules only", self.text())
        self.assertIn("assessment provider stays off", self.text())


if __name__ == "__main__":
    unittest.main()
