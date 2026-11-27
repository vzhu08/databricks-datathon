"""The public-copy notice: shown only when the setting holds an https address, and it opens on Find care."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

from app import public_demo

ROOT = Path(__file__).resolve().parents[2]
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
SOURCE = "https://github.com/vzhu08/databricks-datathon"


class SettingTests(unittest.TestCase):
    def test_unset_or_not_https_is_not_a_public_copy(self):
        for value in (None, "", "  ", "http://example.org", "github.com/x/y", 'https://a"b', "https://a b",
                      "https://a<b"):
            environ = {} if value is None else {public_demo.SETTING: value}
            self.assertEqual("", public_demo.source_url(environ), value)

    def test_an_https_address_is_kept_as_written(self):
        self.assertEqual(SOURCE, public_demo.source_url({public_demo.SETTING: f"  {SOURCE} "}))

    def test_the_notice_says_what_is_real_and_links_the_source(self):
        text = public_demo.markup(SOURCE)
        self.assertIn('data-public-demo="shown"', text)
        self.assertIn(f'href="{SOURCE}"', text)
        self.assertIn("simulated", text)
        self.assertIn("symptom assessment is off", text)


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is not installed")
class ScreenTests(unittest.TestCase):
    def run_app(self, environ):
        from streamlit.testing.v1 import AppTest

        with mock.patch.dict(os.environ, environ, clear=False):
            os.environ.pop(public_demo.SETTING, None) if public_demo.SETTING not in environ else None
            return AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=30).run()

    def test_a_team_deployment_is_unchanged(self):
        at = self.run_app({"FIND_CARE_DATA": "demo"})
        self.assertFalse(at.exception)
        self.assertEqual("Check symptoms", at.radio(key="view").value)
        self.assertFalse(any("data-public-demo" in block.value for block in at.markdown))

    def test_a_public_copy_shows_the_notice_and_opens_on_find_care(self):
        at = self.run_app({"FIND_CARE_DATA": "demo", public_demo.SETTING: SOURCE})
        self.assertFalse(at.exception)
        self.assertEqual("Find care", at.radio(key="view").value)
        self.assertTrue(any("data-public-demo" in block.value for block in at.markdown))
        at.radio(key="view").set_value("Check symptoms").run()
        self.assertFalse(at.exception)
        self.assertEqual("Check symptoms", at.radio(key="view").value)


if __name__ == "__main__":
    unittest.main()
