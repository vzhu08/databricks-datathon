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
    def test_schema_is_closed_everywhere(self):
        def walk(spec, where):
            if spec.get("type") == "object":
                self.assertFalse(spec.get("additionalProperties", True), where)
                for key, item in spec["properties"].items():
                    walk(item, f"{where}.{key}")
            if spec.get("type") == "array":
                walk(spec["items"], where + "[]")
        walk(loader.SCHEMA, "display")

    def test_synthetic_file_loads_and_says_it_is_synthetic(self):
        loaded = load_bytes(RAW, SHA)
        self.assertEqual("ok", loaded["status"])
        self.assertTrue(loaded["synthetic"])

    def test_pinned_hash_is_the_handed_off_edition_and_never_the_fixture(self):
        self.assertEqual("13c7b8736237f43e3461b96e99f58be2233be9db1f7d0154888663a917bfad99", loader.PINNED_SHA256)
        self.assertEqual(loader.REAL_EDITION_SHA256, loader.PINNED_SHA256)
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
            "unknown field": lambda d: d["decision"].update(score=0.9),
            "nested unknown field": lambda d: d["public_case"]["known_at_shared_campus"][0].update(latitude=17.4),
            "travel time filled in": lambda d: d["public_case"].update(travel_minutes=12),
            "address filled in": lambda d: d["public_case"].update(shared_address_display="1 Example Road"),
            "scores filled in": lambda d: d["decision"]["point_rank"].update(scores=[0.9]),
            "rate filled in": lambda d: d["decision"]["evaluation"].update(wrong_branch_rate=0.1),
            "missing field": lambda d: d["vf_trace_case"].pop("same_origin_family"),
            "negative count": lambda d: d["vf_trace_case"].update(reviewed_onsite_pairs=-1),
            "bool as count": lambda d: d["vf_trace_case"].update(reviewed_onsite_pairs=True),
            "float as count": lambda d: d["national"].update(occurrences=10.5),
            "service split does not add up": lambda d: d["vf_trace_case"].update(exact_shared_osm_object_keys=4),
            "destinations listed": lambda d: d["decision"]["point_rank"].update(eligible_destinations_in_cases=2),
            "empty text": lambda d: d["decision"]["verify"].update(highest_value_fact="  "),
            "not an object": lambda d: d.update(national=[]),
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

    def test_answer_is_zero_destinations_and_the_file_s_next_check(self):
        result = self.view["result"]
        self.assertEqual("No facility can be recommended yet", result["headline"])
        self.assertIn("0 eligible destinations", result["line"])
        self.assertEqual(self.data["decision"]["verify"]["highest_value_fact"], result["next_check"])

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
        allowed.add(4)  # the edition's name, "directory v4", not a count
        view = dict(self.view, rungs=None)
        for number in re.findall(r"\d[\d,]*", json.dumps(view, ensure_ascii=False)):
            self.assertIn(int(number.replace(",", "")), allowed, number)

    def test_no_percentages_scores_or_travel(self):
        text = self.text().lower()
        self.assertNotIn("%", text)
        for word in ("km away", "minutes away", "score:", "rank #"):
            self.assertNotIn(word, text)

    def test_trace_keeps_its_limits(self):
        trace = self.view["trace"]
        self.assertIn("share one origin", trace["limits"][0])
        self.assertEqual("partial", trace["rungs"]["independent"])
        self.assertEqual("missing", trace["rungs"]["dated"])
        self.assertIn("(1 dialysis and 2 trauma care)", trace["line"])
        self.assertIn("10 were classified as campus-located in directory v4", trace["line"])
        self.assertNotIn("locate a campus", trace["line"])
        self.assertNotIn("MRI", trace["line"])  # zero counts are left out
        self.assertEqual("team record, needs repository access", trace["source"]["note"])

    def test_public_case_keeps_dates_scope_and_unknowns_apart(self):
        public = self.view["public"]
        self.assertIn("No documented link to a Virtue Foundation record or the accreditation pilot in this case", public["link_line"])
        whens = [f["when"] for f in public["facts"]]
        self.assertEqual(["Reported 2000-01-03, period not stated", "1999-2000", "1999-01-01"], whens)
        self.assertEqual("Synthetic hospital A", public["facts"][-1]["scope"])
        self.assertEqual(5, len(public["unknown"]))
        self.assertTrue(public["reference"]["url"])
        self.assertEqual("missing", public["rungs"]["branch"])

    def test_plain_text_sources_are_not_links(self):
        data = json.loads(RAW)
        data["public_case"]["source"] = "javascript:alert(1)"
        view = walkthrough.build(data)
        self.assertIsNone(view["public"]["facts"][0]["source"]["url"])

    def test_policies_and_unknown_rates_come_from_the_file(self):
        d = self.view["decision"]
        self.assertEqual(4, len(d["policies"]))
        self.assertIn("0 requests could be scored", d["evaluation"])
        self.assertIn("wrong-branch rate", d["evaluation"])


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
        self.assertIn("OpenStreetMap contributors", text)
        self.assertIn("Test edition", text)
        self.assertNotIn("Data unavailable", text)

    def test_missing_file_shows_unavailable_and_nothing_else(self):
        app, text = self.run_app({loader.PATH_SETTING: "/nonexistent/display.json"})
        self.assertFalse(app.exception)
        self.assertIn("Data unavailable", text)
        self.assertNotIn("No facility can be recommended", text)
        self.assertNotIn("Synthetic", text)


if __name__ == "__main__":
    unittest.main()
