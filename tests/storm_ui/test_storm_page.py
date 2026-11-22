"""The Storm demo page of the hosted app. Everything it shows is the committed synthetic replay."""
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

from app import storm_page
from app.storm_ui import build

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


class PageTests(unittest.TestCase):
    def test_the_headline_is_read_from_the_committed_replay_and_matches_a_fresh_simulation(self):
        committed = storm_page.bundle()
        summary = storm_page.headline(committed)
        self.assertEqual((summary["scenario"], summary["seed"], summary["detour_minutes"]), ("storm", 17, 10))
        self.assertTrue(summary["synthetic"])
        nearest, aware = summary["policies"]
        self.assertEqual((nearest["served"], nearest["requested"], nearest["extra_travel_minutes"]), (7, 8, 0))
        self.assertEqual((aware["served"], aware["requested"], aware["extra_travel_minutes"]), (8, 8, 4))
        # The same numbers come out of the simulation itself, so the page cannot drift from it.
        fresh = storm_page.headline(build.bundle())
        self.assertEqual(summary, fresh)
        # And they are counted from the events, not only stored.
        events = committed["replays"][committed["default"]]["policies"]
        for line in summary["policies"]:
            served = [event for event in events[line["policy"]]["events"] if event["status"] == "assigned"]
            self.assertEqual(len(served), line["served"])
            self.assertEqual(sum(event["extra_travel_minutes"] for event in served), line["extra_travel_minutes"])
        said = storm_page.sentence(summary)
        self.assertIn("Nearest first served 7 of 8 simulated patients with 0 extra travel minutes", said)
        self.assertIn("Urgency-aware served 8 of 8 with 4 extra travel minutes", said)

    def test_a_changed_fixture_changes_the_headline(self):
        found = storm_page.bundle()
        found["replays"][found["default"]]["policies"]["nearest_first"]["metrics"]["assigned"] = 3
        self.assertIn("Nearest first served 3 of 8", storm_page.sentence(storm_page.headline(found)))

    def test_the_embedded_document_is_whole_and_reaches_nothing_outside_itself(self):
        page = storm_page.document()
        self.assertEqual(re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)=', page), [])
        self.assertEqual(re.findall(r'href="(?!#)[^"]*"', page), [])
        self.assertEqual(set(re.findall(r'https?://[^"\'\s)]+', page)), {"http://www.w3.org/2000/svg"})
        self.assertNotIn('url("fonts/', page)
        self.assertEqual(page.count("data:font/woff2;base64,"), 3)
        for name in ("storm.js", "replay_state.js"):
            self.assertIn((APP / "storm_ui" / name).read_text(encoding="utf-8").strip()[:200], page)
        self.assertIn("window.STORM_BUNDLE", page)
        self.assertNotIn('<nav class="steps"', page)  # the sibling offline pages are not served by the hosted app
        self.assertNotIn("index.html", page)
        self.assertIn('id="open-file"', page)  # the replay script wires it at start, so it stays, hidden
        self.assertIn('<div class="field file" hidden', page)
        for control in ('id="play"', 'id="next"', 'id="skip"', 'id="back"', 'id="restart"', 'value="text"'):
            self.assertIn(control, page)
        self.assertIn("is fictional", page)
        for word in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "navigator.sendBeacon", "WebSocket"):
            self.assertNotIn(word, page)

    def test_the_frame_uses_the_newer_element_and_falls_back_on_older_streamlit(self):
        new = mock.Mock(spec=["iframe"])
        storm_page.frame(new, "<p>invented</p>")
        new.iframe.assert_called_once_with("<p>invented</p>", height="content")
        with mock.patch("streamlit.components.v1.html") as html:
            storm_page.frame(mock.Mock(spec=[]), "<p>invented</p>")
            html.assert_called_once_with("<p>invented</p>", height=storm_page.HEIGHT, scrolling=True)

    def test_what_the_page_says_names_everything_as_simulated(self):
        for word in ("simulated", "scenario", "campuses", "locations", "arrive", "travel times", "staffed slots"):
            self.assertIn(word, storm_page.SIMULATED)
        self.assertIn("Text only", storm_page.HOW)


@unittest.skipUnless(HAS_STREAMLIT, "streamlit is not installed")
class ScreenTests(unittest.TestCase):
    def setUp(self):
        bare = ("find_care", "data_access", "ranking", "patient_ui", "patient_intake", "storm_page")
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
        env["FIND_CARE_DATA"] = "demo"
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def switch(app):
        return next(radio for radio in app.radio if radio.key == "view")

    def go(self, app, label):
        app = self.switch(app).set_value(label).run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def shown(app):
        kinds = ("title", "subheader", "markdown", "caption", "text", "info", "warning", "error")
        return "\n".join(str(element.value) for kind in kinds for element in getattr(app, kind))

    def test_the_storm_demo_is_the_third_screen_and_touches_no_patient_or_facility_code(self):
        import patient_ui
        import storm_page as page
        app = self.open()
        self.assertEqual(self.switch(app).options, ["Check symptoms", "Find care", page.STORM])
        self.assertIn("simulated", page.STORM)
        with mock.patch.object(patient_ui, "compose", side_effect=AssertionError("patient code ran")), \
                mock.patch.object(patient_ui, "render", side_effect=AssertionError("patient screen drawn")), \
                mock.patch("ranking.search_facilities", side_effect=AssertionError("facility search ran")), \
                mock.patch("data_access.search_warehouse", side_effect=AssertionError("warehouse read")):
            app = self.go(app, page.STORM)
            text = self.shown(app)
            self.assertEqual([title.value for title in app.title], ["Storm demo"])
            self.assertEqual([warning.value for warning in app.warning], [page.SIMULATED])
            self.assertIn("Nearest first served 7 of 8 simulated patients with 0 extra travel minutes", text)
            self.assertIn("Urgency-aware served 8 of 8 with 4 extra travel minutes", text)
            frames = app.get("iframe")
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].proto.srcdoc, page.document())
            self.assertEqual(frames[0].proto.src, "")
            self.assertEqual(len(app.button) + len(app.text_area) + len(app.text_input) + len(app.selectbox), 0)
            # The only patient state is the unopened box the first screen left: no visit, handle or service.
            self.assertEqual(dict(app.session_state["patient"]), {"visit": 0})
            app = app.run()  # a redraw is the same page again
            self.assertEqual(len(app.get("iframe")), 1)
        # Both other screens still open afterwards, and neither carries the replay.
        app = self.go(app, "Find care")
        self.assertEqual([title.value for title in app.title], ["Find care"])
        self.assertEqual(len(app.get("iframe")), 0)
        app = self.go(app, "Check symptoms")
        self.assertIn("Check your symptoms", self.shown(app))
        self.assertEqual(len(app.get("iframe")), 0)

    def test_a_visit_in_progress_is_untouched_by_a_look_at_the_storm_demo(self):
        import storm_page as page
        app = self.open()
        app.checkbox(key="pt-agree-0").check()
        app = next(button for button in app.button if button.label == "Start").click().run()
        app.text_area(key="pt-description-0").input("Invented statement for the storm page test.")
        app = next(button for button in app.button if button.label == "Save and continue").click().run()
        before = self.shown(app)
        self.assertIn("Invented statement for the storm page test.", before)
        app = self.go(app, page.STORM)
        self.assertNotIn("Invented statement", self.shown(app))
        self.assertNotIn("Invented statement", app.get("iframe")[0].proto.srcdoc)
        app = self.go(app, "Check symptoms")
        self.assertIn("Invented statement for the storm page test.", self.shown(app))

    def test_missing_replay_files_are_said_plainly_and_nothing_is_invented(self):
        import storm_page as page
        with mock.patch.object(page, "SOURCE", APP / "no-such-folder"), \
                mock.patch.object(page.bundle, "__defaults__", (APP / "no-such-folder",)), \
                mock.patch.object(page.document, "__defaults__", (APP / "no-such-folder",)):
            app = self.go(self.open(), page.STORM)
            self.assertEqual([error.value for error in app.error], [page.UNAVAILABLE])
            self.assertEqual(len(app.get("iframe")), 0)
            self.assertNotIn("served", self.shown(app).replace(page.SIMULATED, ""))


if __name__ == "__main__":
    unittest.main()
