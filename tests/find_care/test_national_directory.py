"""The national directory section of Find care: counts only, pinned to the reviewed edition."""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import national_directory as national

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
# The national totals as published with the edition (aggregates only; no record, name or place).
TIERS = {"previously_findable": 3144, "registry_or_operator": 1538, "agreeing_points": 2181,
         "map_name_and_area": 1032, "unresolved": 2193}
EVIDENCE = {"registry_or_operator": 2662, "agreeing_points": 5375, "registry_or_agreeing_points": 6562,
            "nearby_only_possible_shared_origins": 3715}


def summary(**changes):
    found = {
        "edition": "national-facility-area-display-v1",
        "as_of": "2026-11-22",
        "population": 10088,
        "covered": 7895,
        "coverage_tiers": dict(TIERS),
        "overlapping_evidence": dict(EVIDENCE),
        "source": "Virtue Foundation v0, official NHP and NABH directories, Overture Maps, "
                  "© OpenStreetMap contributors, and the frozen project directory.",
        "osm_attribution_url": "https://www.openstreetmap.org/copyright",
        "method": "Each original record counts once. A named facility can qualify in a registry locality, "
                  "landmark area or PIN, through a map listing in that area, or with agreeing points under 1 km.",
        "limitations": "VF and external maps may share a source. Building accuracy, present-day operation "
                       "and onsite services require separate evidence.",
    }
    found.update(changes)
    return found


def encoded(found):
    """The bytes the builder writes (research/matching/facility_area_display.py)."""
    return (json.dumps(found, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def pinned(raw):
    return mock.patch.object(national, "DISPLAY_SHA256", hashlib.sha256(raw).hexdigest())


class SummaryTests(unittest.TestCase):
    def test_the_published_totals_are_the_pinned_edition(self):
        # Built the way the data owner's script builds it, the published totals give exactly the pinned bytes.
        raw = encoded(summary())
        self.assertEqual(1047, len(raw))
        self.assertEqual(national.DISPLAY_SHA256, hashlib.sha256(raw).hexdigest())
        found = national.view(national.read_summary(raw))
        self.assertEqual("7,895 of 10,088 records (78.3%) have outside evidence for where the named facility is.",
                         found["headline"])
        self.assertEqual("2,193 are still open.", found["open"])
        self.assertEqual("as of 22 November 2026", found["as_of"])
        self.assertEqual(("Still open", "2,193", "21.7%", True), found["rows"][-1])
        self.assertEqual(["3,144", "1,538", "2,181", "1,032", "2,193"], [row[1] for row in found["rows"]])
        self.assertIn("3,715", found["evidence"][1])

    def test_the_pin_matches_the_builder_when_it_is_in_the_checkout(self):
        builder = ROOT / "research/matching/facility_area_display.py"
        if not builder.exists():
            self.skipTest("the builder is not on this branch")
        self.assertIn(f'DISPLAY_SHA256 = "{national.DISPLAY_SHA256}"', builder.read_text(encoding="utf-8"))

    def test_any_other_bytes_show_nothing(self):
        raw = encoded(summary())
        for other in (raw + b" ", raw.replace(b"7895", b"7896"), b"", b"{}", b"x" * (national.MAX_BYTES + 1)):
            with self.subTest(size=len(other)), self.assertRaises(national.Unavailable):
                national.read_summary(other)

    def test_counts_that_do_not_add_up_are_refused_even_when_the_bytes_are_pinned(self):
        wrong = [summary(covered=7896), summary(population=10089), summary(population=0, covered=0),
                 summary(coverage_tiers={**TIERS, "unresolved": True}), summary(method=" "),
                 summary(overlapping_evidence={key: EVIDENCE[key] for key in list(EVIDENCE)[:3]}),
                 {key: value for key, value in summary().items() if key != "limitations"}, [1, 2]]
        for found in wrong:
            raw = encoded(found)
            with self.subTest(found=str(found)[:60]), pinned(raw), self.assertRaises(national.Unavailable):
                national.read_summary(raw)

    def test_a_missing_or_oversized_file_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(national.Unavailable):
                national.load(folder)
            (Path(folder) / national.FILE).write_bytes(b" " * (national.MAX_BYTES + 1))
            with self.assertRaises(national.Unavailable):
                national.load(folder)
            (Path(folder) / national.FILE).write_bytes(encoded(summary()))
            self.assertEqual(7895, national.load(folder)["covered"])

    def test_words_from_the_file_cannot_add_markup_and_only_an_https_link_is_offered(self):
        found = summary(method="<script>alert(1)</script>", osm_attribution_url='javascript:alert("x")')
        page = national.markup(national.view(found), demo=True)
        self.assertNotIn("<script", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("javascript:", page)
        self.assertNotIn("<a ", page)
        real = national.markup(national.view(summary()), demo=False)
        self.assertIn('href="https://www.openstreetmap.org/copyright"', real)
        self.assertIn(national.APART_REAL, real)
        self.assertNotIn("invented", real)

    def test_the_summary_file_itself_is_not_in_the_repository(self):
        self.assertFalse((APP / national.FILE).exists(), "the counts file is packaged at deployment, not committed")


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")
class ScreenTests(unittest.TestCase):
    """The real screen, run from a copy of app/ so the packaged file can be present, absent or wrong."""

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.source = Path(folder) / "app"
        shutil.copytree(APP, self.source, ignore=shutil.ignore_patterns("__pycache__", national.FILE))
        bare = ("find_care", "data_access", "ranking", "patient_ui", "patient_intake", "storm_page",
                "national_directory", "capacity_recommendation", "travel", "find_capacity", "simulation",
                "finding_provenance")
        saved = {name: module for name, module in sys.modules.items() if name.split(".")[0] in bare}
        for name in saved:
            del sys.modules[name]
        sys.path.insert(0, str(self.source))

        def restore():
            sys.path.remove(str(self.source))
            for name in [name for name in sys.modules if name.split(".")[0] in bare]:
                del sys.modules[name]
            sys.modules.update(saved)

        self.addCleanup(restore)

    def _find_care(self, **env):
        from streamlit.testing.v1 import AppTest
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("DATABRICKS_", "FIND_CARE_"))}
        self.env = {**clean, **env}
        with mock.patch.dict(os.environ, self.env, clear=True):
            app = AppTest.from_file(str(self.source / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception, app.exception)
            switch = app.radio(key="view")
            app = switch.set_value(switch.options[1]).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def _step(self, action):
        with mock.patch.dict(os.environ, self.env, clear=True):
            app = action.run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def _section(app):
        return [node.value for node in app.markdown if "data-national=" in node.value]

    def test_the_packaged_counts_are_shown_and_do_not_change_with_the_request(self):
        (self.source / national.FILE).write_bytes(encoded(summary()))
        app = self._find_care()
        first = self._section(app)
        self.assertEqual(1, len(first))
        for words in ("National directory", "7,895 of 10,088 records (78.3%)", "2,193 are still open.",
                      "Real Virtue Foundation records · counts only · as of 22 November 2026",
                      "not the six invented facilities", "Building accuracy, present-day operation"):
            self.assertIn(words, first[0])
        self.assertIn('data-national="shown"', first[0])
        # A different service, a finished recommendation and a finished record lookup leave the section as it was.
        app = self._step(app.radio(key="service").set_value("mri"))
        app = self._step(app.button(key="find").click())
        self.assertIn("capacity", app.session_state)
        self.assertEqual(first, self._section(app))
        app = self._step(app.radio(key="mode").set_value("lookup"))
        app = self._step(app.button(key="find").click())
        self.assertIn("response", app.session_state)
        self.assertEqual(first, self._section(app))
        # Nothing from it is kept between runs.
        for key in ("national", "national_directory", "summary"):
            self.assertNotIn(key, app.session_state)

    def test_without_the_file_the_screen_says_so_and_the_search_still_works(self):
        app = self._find_care()
        section = self._section(app)
        self.assertEqual(1, len(section))
        self.assertIn('data-national="unavailable"', section[0])
        self.assertIn(national.UNAVAILABLE, section[0])
        self.assertNotIn("7,895", section[0])
        self.assertNotIn("10,088", section[0])
        app = self._step(app.button(key="find").click())
        self.assertEqual("recommended", app.session_state["capacity"]["result"]["status"])
        app = self._step(app.radio(key="mode").set_value("lookup"))
        app = self._step(app.button(key="find").click())
        self.assertEqual("ok", app.session_state["response"]["status"])

    def test_a_changed_file_shows_no_number(self):
        (self.source / national.FILE).write_bytes(encoded(summary(covered=9000)))
        section = self._section(self._find_care())
        self.assertIn('data-national="unavailable"', section[0])
        self.assertNotIn("9,000", section[0])

    def test_the_other_two_screens_do_not_show_it(self):
        (self.source / national.FILE).write_bytes(encoded(summary()))
        app = self._find_care()
        for choice in (0, 2):
            switch = app.radio(key="view")
            app = self._step(switch.set_value(switch.options[choice]))
            self.assertEqual([], self._section(app))


if __name__ == "__main__":
    unittest.main()
