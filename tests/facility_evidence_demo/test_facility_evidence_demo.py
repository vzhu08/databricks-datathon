"""The judges' facility evidence walkthrough (#252), on a synthetic file of the real edition's shape.

The real display.json is never in Git. These tests pass the synthetic file's own hash, so the pinned hash is
never satisfied by test data, and check every way the screen must refuse to show anything.
"""
import copy
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from app.facility_evidence_demo import loader, walkthrough

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = HERE / "synthetic_display.json"
RAW = FIXTURE.read_bytes()
SHA = hashlib.sha256(RAW).hexdigest()
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def load_bytes(raw, sha=None):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "display.json"
        path.write_bytes(raw)
        return loader.load({loader.PATH_SETTING: str(path)}, expected_sha256=sha or hashlib.sha256(raw).hexdigest())


def edited(change):
    data = json.loads(RAW)
    change(data)
    return json.dumps(data).encode("utf-8")


class LoaderTests(unittest.TestCase):
    def test_synthetic_file_loads_and_says_it_is_synthetic(self):
        loaded = load_bytes(RAW, SHA)
        self.assertEqual("ok", loaded["status"])
        self.assertTrue(loaded["synthetic"])

    def test_pinned_hash_is_the_handed_off_edition_and_never_the_fixture(self):
        self.assertEqual("13c7b8736237f43e3461b96e99f58be2233be9db1f7d0154888663a917bfad99", loader.PINNED_SHA256)
        self.assertNotEqual(SHA, loader.PINNED_SHA256)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "display.json"
            path.write_bytes(RAW)
            loaded = loader.load({loader.PATH_SETTING: str(path)})
        self.assertEqual("unavailable", loaded["status"])
        self.assertIn("fingerprint", loaded["reason"])

    def test_unset_and_missing_paths_are_unavailable(self):
        self.assertEqual("unavailable", loader.load({})["status"])
        self.assertIn(loader.PATH_SETTING, loader.load({})["reason"])
        self.assertEqual("unavailable", loader.load({loader.PATH_SETTING: "/nonexistent/display.json"})["status"])

    def test_refusals(self):
        cases = {
            "unknown field": lambda d: d["result"].update(score=0.9),
            "nested unknown field": lambda d: d["public_case"]["facts"][0].update(latitude=17.4),
            "travel time": lambda d: d["result"].update(travel_minutes=12),
            "missing field": lambda d: d["vf_trace"].pop("credit"),
            "bad count": lambda d: d["vf_trace"].update(same_object_keys=-1),
            "bool as count": lambda d: d["vf_trace"].update(map_origins=True),
            "bad date": lambda d: d["edition"].update(as_of="yesterday"),
            "plain http link": lambda d: d["national_result"].update(source_url="http://example.org/x"),
            "script link": lambda d: d["vf_trace"]["credit"].update(url="javascript:alert(1)"),
            "service split does not add up": lambda d: d["vf_trace"].update(same_object_keys=4),
            "destinations listed": lambda d: d["result"].update(eligible_destinations=2),
            "empty text": lambda d: d["result"].update(next_check="  "),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertEqual("unavailable", load_bytes(edited(change))["status"])

    def test_not_json_and_oversized(self):
        self.assertEqual("unavailable", load_bytes(b"\xff\xfe not json")["status"])
        self.assertEqual("unavailable", load_bytes(b" " * (loader.MAX_BYTES + 1))["status"])


class WordingTests(unittest.TestCase):
    def setUp(self):
        self.data = load_bytes(RAW, SHA)["data"]
        self.view = walkthrough.build(self.data)

    def text(self):
        return json.dumps(self.view, ensure_ascii=False)

    def test_answer_is_zero_destinations_with_no_numbers_invented(self):
        result = self.view["result"]
        self.assertEqual("No facility can be recommended yet", result["headline"])
        self.assertIn("0 eligible destinations", result["line"])
        self.assertEqual(self.data["result"]["next_check"], result["next_check"])

    def test_every_number_shown_comes_from_the_file(self):
        allowed = set()

        def collect(value):
            if isinstance(value, bool):
                return
            if isinstance(value, int):
                allowed.add(value)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, str):
                allowed.update(int(n) for n in re.findall(r"\d+", value))
        collect(self.data)
        allowed |= {n for n in range(1, len(walkthrough.RUNGS) + 1)}  # step numbers
        view = dict(self.view, rungs=None)
        for number in re.findall(r"\d[\d,]*", json.dumps(view, ensure_ascii=False)):
            self.assertIn(int(number.replace(",", "")), allowed, number)

    def test_no_percentages_scores_or_travel(self):
        text = self.text().lower()
        self.assertNotIn("%", text)
        for word in ("km away", "minutes away", "score:", "rank #"):
            self.assertNotIn(word, text)

    def test_trace_and_public_case_keep_their_limits(self):
        trace = self.view["trace"]
        self.assertIn("same OpenStreetMap lineage", trace["limits"][0])
        self.assertEqual("partial", trace["rungs"]["independent"])
        self.assertEqual("missing", trace["rungs"]["dated"])
        self.assertIn("1 dialysis and 2 trauma care", trace["line"])
        public = self.view["public"]
        self.assertIn("not linked", public["link_line"])
        self.assertEqual("missing", public["rungs"]["branch"])
        self.assertEqual([f["as_of"] for f in self.data["public_case"]["facts"]],
                         [f["as_of"] for f in public["facts"]])

    def test_no_case_clears_the_last_step(self):
        for case in (self.view["trace"], self.view["public"]):
            self.assertEqual("missing", case["rungs"]["branch"])


@unittest.skipUnless(HAS_STREAMLIT, "streamlit is not installed")
class ScreenTests(unittest.TestCase):
    def run_app(self, environ):
        from unittest import mock

        from streamlit.testing.v1 import AppTest
        # app.py imports its siblings as top-level modules; hand it these same module objects.
        with mock.patch.dict("os.environ", environ, clear=False), \
                mock.patch.dict(sys.modules, {"loader": loader, "walkthrough": walkthrough}), \
                mock.patch.object(loader, "PINNED_SHA256", SHA):
            app = AppTest.from_file(str(ROOT / "app/facility_evidence_demo/app.py"), default_timeout=30)
            app.run()
        return app, " ".join(m.value for m in app.markdown)

    def test_synthetic_file_renders_labelled_as_synthetic(self):
        app, text = self.run_app({loader.PATH_SETTING: str(FIXTURE)})
        self.assertFalse(app.exception)
        self.assertIn("Synthetic test file", text)
        self.assertIn("No facility can be recommended yet", text)
        self.assertIn("Synthetic map contributors", text)
        self.assertNotIn("Data unavailable", text)

    def test_missing_file_shows_unavailable_and_nothing_else(self):
        app, text = self.run_app({loader.PATH_SETTING: "/nonexistent/display.json"})
        self.assertFalse(app.exception)
        self.assertIn("Data unavailable", text)
        self.assertNotIn("No facility can be recommended", text)
        self.assertNotIn("Synthetic", text)


if __name__ == "__main__":
    unittest.main()
