"""The area-view fallback (#270), on a synthetic aggregate of the proposed shape. No real counts live here."""
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.facility_evidence_demo import area, loader, walkthrough

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURE = HERE / "synthetic_area.json"
RAW = FIXTURE.read_bytes()
SHA = hashlib.sha256(RAW).hexdigest()
DISPLAY = HERE / "synthetic_display.json"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


def load_bytes(raw, sha=None):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "area.json"
        path.write_bytes(raw)
        return area.load({area.PATH_SETTING: str(path)}, expected_sha256=sha or hashlib.sha256(raw).hexdigest())


def edited(change):
    data = json.loads(RAW)
    change(data)
    return json.dumps(data).encode("utf-8")


class AreaLoaderTests(unittest.TestCase):
    def test_pin_is_the_cleared_edition_and_never_the_fixture(self):
        self.assertEqual("0ac26497a9914aa2c42b445f37a2c0e2399fe1c232e3fea38a073d0f5802032f", area.AREA_REAL_SHA256)
        self.assertEqual(area.AREA_REAL_SHA256, area.AREA_PINNED_SHA256)
        self.assertNotEqual(SHA, area.AREA_PINNED_SHA256)
        loaded = area.load({area.PATH_SETTING: str(FIXTURE)})
        self.assertEqual("unavailable", loaded["status"])
        self.assertIn("fingerprint", loaded["reason"])

    def test_nothing_is_shown_without_a_pin(self):
        with mock.patch.object(area, "AREA_PINNED_SHA256", None):
            loaded = area.load({area.PATH_SETTING: str(FIXTURE)})
        self.assertEqual("unavailable", loaded["status"])
        self.assertIn("cleared for this audience", loaded["reason"])

    def test_missing_file_is_unavailable(self):
        loaded = area.load({area.PATH_SETTING: "/nonexistent/area-display.json"})
        self.assertEqual("unavailable", loaded["status"])

    def test_synthetic_file_loads_and_is_labelled_synthetic(self):
        loaded = load_bytes(RAW, SHA)
        self.assertEqual("ok", loaded["status"])
        self.assertTrue(loaded["synthetic"])

    def test_refusals(self):
        cases = {
            "facility point": lambda d: d.update(facility_points=[[17.4, 78.4]]),
            "travel time": lambda d: d.update(point_eta_minutes=12),
            "area names": lambda d: d["precision"].update(names=["Example"]),
            "missing level": lambda d: d["precision"].pop("district"),
            "levels do not sum": lambda d: d["precision"].update(city=31),
            "campus basis does not sum": lambda d: d["campus_basis"].update(matching_address=11),
            "reasons do not sum": lambda d: d["unresolved_reasons"].update(other=12),
            "more ids than records": lambda d: d.update(distinct_upstream_ids=1001),
            "negative": lambda d: d["precision"].update(district=-1),
        }
        for name, change in cases.items():
            with self.subTest(name):
                self.assertEqual("unavailable", load_bytes(edited(change))["status"])

    def test_wrong_fingerprint(self):
        self.assertEqual("unavailable", load_bytes(RAW, "0" * 64)["status"])

    def test_schema_is_closed_and_has_no_point_or_name_fields(self):
        keys = []

        def walk(spec):
            self.assertFalse(spec.get("additionalProperties", True))
            for key, item in spec["properties"].items():
                keys.append(key)
                if item["type"] == "object":
                    walk(item)
        walk(area.SCHEMA)
        for key in keys:
            for word in ("lat", "lon", "coord", "point", "eta", "travel", "rank", "capacity", "service", "boundary"):
                self.assertNotIn(word, key)


class AreaWordingTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(RAW)
        self.view = area.build(self.data)

    def test_every_record_is_counted_once_in_precision_order(self):
        self.assertEqual([key for key, _, _ in area.LEVELS], [row["key"] for row in self.view["rows"]])
        self.assertEqual(self.data["originals"], sum(row["count"] for row in self.view["rows"]))
        self.assertEqual("730 of 1,000", self.view["headline"])

    def test_city_reads_city_and_claims_nothing_narrower(self):
        city = next(row for row in self.view["rows"] if row["key"] == "city")
        self.assertEqual("City only", city["label"])
        self.assertIn("No neighbourhood or point is inferred", city["meaning"])

    def test_campus_is_a_category_not_a_verified_building(self):
        campus = self.view["rows"][0]
        self.assertIn("not an independently verified building or entrance", campus["meaning"])
        self.assertEqual("240 named map listings and 10 matching addresses.", campus["note"])

    def test_numbers_come_from_the_file_and_no_percentages(self):
        allowed = set()
        allowed.update(int(n) for n in re.findall(r"\d+", json.dumps(self.data)))
        shown = {k: v for k, v in self.view.items() if k != "rows"}
        shown["rows"] = [{k: v for k, v in row.items() if k != "share"} for row in self.view["rows"]]
        allowed.add(sum(self.data["precision"][k] for k in area.AREA_ONLY))  # the area-only subtotal
        text = json.dumps(shown, ensure_ascii=False)
        self.assertNotIn("%", text)
        for number in re.findall(r"\d[\d,]*", text):
            self.assertIn(int(number.replace(",", "")), allowed, number)


@unittest.skipUnless(HAS_STREAMLIT, "streamlit is not installed")
class AreaScreenTests(unittest.TestCase):
    def run_app(self, area_sha):
        from streamlit.testing.v1 import AppTest
        display_sha = hashlib.sha256(DISPLAY.read_bytes()).hexdigest()
        env = {loader.PATH_SETTING: str(DISPLAY), area.PATH_SETTING: str(FIXTURE)}
        with mock.patch.dict("os.environ", env, clear=False), \
                mock.patch.dict(sys.modules, {"loader": loader, "walkthrough": walkthrough, "area": area}), \
                mock.patch.object(loader, "PINNED_SHA256", display_sha), \
                mock.patch.object(area, "AREA_PINNED_SHA256", area_sha):
            app = AppTest.from_file(str(ROOT / "app/facility_evidence_demo/app.py"), default_timeout=30)
            app.run()
        return app, " ".join(m.value for m in app.markdown)

    def test_area_view_renders_as_a_labelled_section(self):
        app, text = self.run_app(SHA)
        self.assertFalse(app.exception)
        self.assertIn("Where the records place facilities", text)
        self.assertIn("City only", text)
        self.assertIn("730 of 1,000", text)
        self.assertIn("Every figure in this section is invented", text)
        self.assertIn("What the private search can do", text)
        self.assertNotIn("Area data unavailable", text)

    def test_unpinned_area_is_unavailable_without_hiding_the_walkthrough(self):
        app, text = self.run_app(None)
        self.assertFalse(app.exception)
        self.assertIn("Area data unavailable", text)
        self.assertIn("No facility can be recommended yet", text)
        self.assertNotIn("730 of 1,000", text)


if __name__ == "__main__":
    unittest.main()
