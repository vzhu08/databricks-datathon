"""The capability coverage section of Find care: counts only, checked before a number is shown."""
import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from app import capability_coverage as section

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
RAW = json.loads((APP / section.FILE).read_text(encoding="utf-8"))


class Counts(unittest.TestCase):
    def test_the_packaged_counts_are_the_published_edition(self):
        found = section.load(APP)
        self.assertEqual(10088, found["directory_rows"])
        self.assertEqual((8, 49), (len(found["headline"]), len(found["other"])))
        shown = {row["capability"]: (row["supported"], row["mentions"], row["percent"]) for row in found["headline"]}
        self.assertEqual((1526, 4481, "34.1"), shown["Dental care"])
        self.assertEqual((17, 1047, "1.6"), shown["Dialysis"])
        self.assertEqual((0, 949, "0.0"), shown["MRI"])
        self.assertEqual((12, 1042, "1.2"), shown["Trauma care"])
        self.assertTrue(RAW["source"].startswith("https://github.com/vzhu08/databricks-datathon/issues/40#"))

    def test_every_share_is_the_share_of_its_two_counts(self):
        for row in RAW["headline"] + RAW["other"]:
            with self.subTest(row=row["capability"]):
                self.assertLessEqual(row["supported"], row["mentions"])
                self.assertAlmostEqual(float(row["stated_percent"]), row["supported"] / row["mentions"] * 100, delta=0.051)

    def test_the_file_holds_counts_and_names_of_care_only(self):
        self.assertEqual({"schema", "source", "directory_rows", "headline", "other"}, set(RAW))
        for row in RAW["headline"] + RAW["other"]:
            self.assertEqual({"capability", "supported", "mentions", "stated_percent"}, set(row))

    def test_counts_that_do_not_hold_together_are_never_shown(self):
        def broken(change):
            found = copy.deepcopy(RAW)
            change(found)
            return found

        cases = (
            lambda f: f.update(schema="something-else"),
            lambda f: f["headline"][0].update(supported=f["headline"][0]["mentions"] + 1),
            lambda f: f["headline"][0].update(supported=-1),
            lambda f: f["headline"][0].update(supported="1526"),
            lambda f: f["headline"][0].update(stated_percent="50.0"),
            lambda f: f["headline"][0].update(mentions=0),
            lambda f: f["headline"][0].update(mentions=f["directory_rows"] + 1),
            lambda f: f["headline"][0].update(capability=""),
            lambda f: f["other"].append(dict(f["headline"][0])),
            lambda f: f.update(headline=[]),
            lambda f: f.pop("other"),
            lambda f: f.update(directory_rows=True),
        )
        for number, change in enumerate(cases):
            with self.subTest(case=number):
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    section.checked(broken(change))

    def test_a_missing_or_unreadable_file_is_unavailable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(section.Unavailable):
                section.load(folder)
            (Path(folder) / section.FILE).write_text("{not json", encoding="utf-8")
            with self.assertRaises(section.Unavailable):
                section.load(folder)


class Words(unittest.TestCase):
    def setUp(self):
        self.found = section.load(APP)

    def test_the_section_says_what_a_zero_does_and_does_not_mean(self):
        for demo in (True, False):
            text = section.markup(self.found, demo)
            self.assertIn("It does not mean the care is not offered.", text)
            self.assertIn("It does not confirm the care is running today.", text)
            self.assertIn("name no facility.", text)
            self.assertIn("<td>MRI</td><td class=\"cc-n\">0 of 949</td><td class=\"cc-n\">0.0%</td>", text)
            self.assertIn("1,526 of 4,481", text)
        self.assertIn("not the invented facilities", section.markup(self.found, True))
        self.assertNotIn("invented", section.markup(self.found, False))

    def test_the_full_table_sits_in_an_expandable_part(self):
        text = section.markup(self.found, True)
        head, _, rest = text.partition("<details>")
        self.assertIn("Dental care", head)
        self.assertNotIn("Orthopedics", head)
        self.assertIn(f"{section.MORE} (49)", rest)
        for name in ("Orthopedics", "Ayurveda", "ICSI"):
            self.assertIn(f"<td>{name}</td>", rest)

    def test_nothing_recommends_ranks_or_names_a_facility(self):
        text = section.markup(self.found, True).lower()
        for word in ("recommend", "best", "ranked", "send the patient", "hospital", "clinic", "virtue foundation"):
            self.assertNotIn(word, text)

    def test_a_capability_name_can_never_add_markup(self):
        found = copy.deepcopy(self.found)
        found["headline"][0]["capability"] = "<script>alert(1)</script>"
        self.assertNotIn("<script>", section.markup(found, True))


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is not installed")
class Screen(unittest.TestCase):
    def setUp(self):
        bare = ("find_care", "data_access", "ranking", "patient_ui", "patient_intake", "capability_coverage",
                "storm_page")
        saved = {name: module for name, module in sys.modules.items() if name.split(".")[0] in bare}
        for name in saved:
            del sys.modules[name]
        sys.path.insert(0, str(APP))

        def restore():
            sys.path.remove(str(APP))
            for name in [name for name in sys.modules if name.split(".")[0] in bare]:
                del sys.modules[name]
            sys.modules.update(saved)

        self.addCleanup(restore)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABRICKS_", "FIND_CARE_", "PATIENT_"))}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def shown(app):
        return "\n".join(str(element.value) for element in app.markdown)

    def test_the_section_is_on_find_care_and_not_on_the_patient_screen(self):
        app = self.open()
        self.assertNotIn(section.HEADING, self.shown(app))
        switch = app.radio(key="view")
        app = switch.set_value("Find care").run()
        app = app.radio(key="lookup_source").set_value("Simulated scenarios").run()
        self.assertFalse(app.exception, app.exception)
        text = self.shown(app)
        self.assertIn(section.HEADING, text)
        self.assertIn(section.APART_DEMO, text)
        self.assertIn("17 of 1,047", text)
        self.assertNotIn("Virtue Foundation", text)  # the demonstration page never reads as a real record

    def test_without_its_counts_file_the_section_shows_no_number(self):
        import capability_coverage
        with mock.patch.object(capability_coverage, "FILE", "missing.json"):
            app = self.open()
            switch = app.radio(key="view")
            app = switch.set_value("Find care").run()
            app = app.radio(key="lookup_source").set_value("Simulated scenarios").run()
        self.assertFalse(app.exception, app.exception)
        text = self.shown(app)
        self.assertIn(section.UNAVAILABLE, text)
        self.assertNotIn("of 1,047", text)


if __name__ == "__main__":
    unittest.main()
