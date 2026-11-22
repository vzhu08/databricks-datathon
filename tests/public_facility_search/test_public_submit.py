"""Submit representative public searches in one local session of the release entry point."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest = None


APP = Path(__file__).resolve().parents[2] / "app" / "app.py"
KEM = "KEM Hospital, Pune"
JEHANGIR = "Jehangir Hospital"
SOURCES = {
    KEM: ("https://www.kemhospitalpune.org/specialities/nephrology/", "+91 20 2621 7300"),
    JEHANGIR: ("https://www.jehangirhospital.com/nephrology-sp/", "020-6681-9966"),
}


def submissions():
    yield "Pune", "maintenance haemodialysis", (KEM,)
    yield "  pUnE  ", " DIALYSIS ", (KEM, JEHANGIR)
    for service in ("haemodialysis", "hemodialysis", "maintenance dialysis",
                    "maintenance   hemodialysis"):
        yield "Pune", service, (KEM,)
    for city, service in (("Mumbai", "dialysis"), ("Pune", "MRI"), ("", "dialysis"),
                          ("Pune", " "), (" ", ""), ("Pune", "??!"), ("Pune", "dialisis"),
                          ("Pune", "no dialysis!"), ("Pune", "maintenance peritoneal dialysis"),
                          ("Pune", "dialysis and trauma"), ("Pune", "a kite in a tree"),
                          ("पुणे", "dialysis"), ("Pune", "डायलिसिस"), ("Pune", "dialysis 🪁")):
        yield city, service, ()
    for length in (119, 120):
        yield "x" * length, "dialysis", ()
        yield "Pune", "x" * length, ()
    yield "Pune", "dialysis?", (KEM, JEHANGIR)
    yield "Pune", "maintenance haemodialysis.", (KEM,)
    yield "Pune", "kidney dialysis?", (KEM, JEHANGIR)
    yield "Pune", "no kidney dialysis?", ()
    yield "Pune", "not dialysis", ()
    yield "Pune", "dialysis", (KEM, JEHANGIR)


@unittest.skipUnless(AppTest, "Streamlit is required for local submit testing")
class PublicSubmitTests(unittest.TestCase):
    @patch.dict(os.environ, {"FIND_CARE_DATA": "demo", "PATIENT_PROVIDER": "", "TOMTOM_ENABLED": "false"})
    def test_public_search_and_recovery_in_one_session(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        app.radio(key="view").set_value("Find care").run()
        self.assertEqual("Public facility evidence", app.radio(key="lookup_source").value)
        # Chromium can discard an entire paste at a native widget limit, retaining the previous value.
        self.assertEqual([("City", 0), ("Service", 0)],
                         [(t.label, t.proto.max_chars) for t in app.text_input])
        for city, service, expected in submissions():
            with self.subTest(city=city, service=service):
                app.text_input[0].set_value(city)
                app.text_input[1].set_value(service)
                next(b for b in app.button if b.label == "Search public sources").click().run()
                self.assertFalse(app.exception)
                self.assertEqual([s.value for s in app.subheader], list(expected))
                self.assertEqual([link.proto.url for link in app.get("link_button")],
                                 [SOURCES[name][0] for name in expected])
                if expected:
                    body = "\n".join(item.value for item in app.markdown)
                    for name in expected:
                        self.assertIn(SOURCES[name][1], body)
                    self.assertIn("are unknown", body)
                elif city.strip() and service.strip():
                    self.assertTrue(any("no reviewed public claim" in item.value for item in app.info))
                else:
                    notices = [item.value.lower() for item in (*app.info, *app.warning, *app.error)]
                    for label, value in (("city", city), ("service", service)):
                        if not value.strip():
                            self.assertTrue(any(label in message for message in notices), notices)

        for city, service, label in (("x" * 121, "dialysis", "City"),
                                     ("Pune", "x" * 121, "Service"),
                                     ("x" * 121, "y" * 121, "City and Service")):
            with self.subTest(over_limit=label):
                app.text_input[0].set_value(city)
                app.text_input[1].set_value(service)
                next(b for b in app.button if b.label == "Search public sources").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(any(f"Shorten {label} to 120" in w.value for w in app.warning))
                self.assertFalse(app.subheader)
                self.assertFalse(app.get("link_button"))
        app.text_input[0].set_value("Pune")
        app.text_input[1].set_value("maintenance dialysis")
        next(b for b in app.button if b.label == "Search public sources").click().run()
        self.assertEqual([KEM], [s.value for s in app.subheader])
