"""App-only Streamlit replay with the real factory and an intercepted exchange."""

import json
import os
import unittest
from collections import deque
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import patient_ui
from patient_intake.providers import databricks_config


ENDPOINT = "databricks-gpt-oss-20b"
SOURCE = "Invented check: discomfort appears during a fictional activity."
BASE_ENV = {
    "PATIENT_PROVIDER_ENDPOINT": ENDPOINT,
    "PATIENT_PROVIDER_LANE": "test",
    "PATIENT_PROVIDER_TEST_ATTEMPTS": "2",
    "PATIENT_PROVIDER_DEMO_ATTEMPTS": "2",
}


class ExchangeScript:
    """Replace only the outbound exchange; record the physical dispatch boundary."""

    def __init__(self, replies):
        self.pending = deque(replies)
        self.requests = []

    def __call__(self, host, method, path, headers, raw, timeout):
        request = json.loads(raw)
        self.requests.append((method, path, request))
        value = self.pending.popleft()
        response = {
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(value)},
            }],
        }
        return 200, "application/json", json.dumps(response).encode(), {}


class FactoryScreenFixture(unittest.TestCase):
    def setUp(self):
        # Each replay starts a fresh simulated server worker. Anything that
        # would reach the real exchange fails in the app-only subprocess guard.
        self.track(patch.object(databricks_config, "_configuration", None))
        self.track(patch.object(databricks_config, "_providers", {}))

    def track(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def connect(self, replies):
        exchange = ExchangeScript(replies)
        constructor = self.track(patch.object(databricks_config, "_WorkspaceExchange", return_value=exchange))
        return exchange, constructor

    def screen(self, settings=None):
        configured = {} if settings is None else settings
        self.track(patch.dict(os.environ, configured))
        app = AppTest.from_file("app.py", default_timeout=20).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def press(self, app, label):
        matches = [button for button in app.button if button.label == label]
        self.assertEqual(len(matches), 1, [button.label for button in app.button])
        matches[0].click()
        app.run()
        self.assertFalse(app.exception, app.exception)

    def save(self, app, source=SOURCE):
        app.checkbox(key="pt-agree-0").check()
        self.press(app, "Start")
        app.text_area(key="pt-description-0").input(source)
        self.press(app, "Save and continue")

    def answer(self, app, choice):
        radios = [radio for radio in app.radio if str(radio.key).startswith("pt-answer-")]
        self.assertEqual(len(radios), 1)
        radios[0].set_value(choice)
        self.press(app, "Send answer")

    @staticmethod
    def shown(app):
        kinds = ("title", "subheader", "text", "markdown", "info", "warning", "error")
        return "\n".join(str(item.value) for kind in kinds for item in getattr(app, kind))

    @staticmethod
    def view(app):
        box = app.session_state[patient_ui.STATE_KEY]
        return box["service"].view(box["handle"])

    def assert_no_hospital(self, app):
        self.assertFalse(any("reviewed hospital" in button.label for button in app.button))


class ExistingFactoryScreenCases(FactoryScreenFixture):
    def test_unconfigured_app_does_not_load_a_workspace_exchange(self):
        exchange, constructor = self.connect([])
        app = self.screen({"FIND_CARE_DATA": "demo"})
        self.save(app)
        self.assertEqual(self.view(app)["state"], "provider_unavailable")
        self.assertNotIn("I agree. Send it for assessment", [button.label for button in app.button])
        self.assert_no_hospital(app)
        constructor.assert_not_called()
        self.assertEqual(exchange.requests, [])

    def test_documentation_mode_still_ends_without_an_assessment(self):
        exchange, constructor = self.connect([
            {"observations": [{"quote": SOURCE, "presence": "present", "temporality": "current"}],
             "topic": "change"},
            {"next": "review_summary"},
        ])
        app = self.screen({**BASE_ENV, "PATIENT_PROVIDER": "databricks-experimental"})
        self.save(app)
        shown = self.shown(app).replace(chr(92), "")
        self.assertIn(ENDPOINT, shown)
        self.assertIn("experimental language model", shown)
        app.run()
        self.assertEqual(exchange.requests, [])
        self.press(app, "I agree. Send it for assessment")
        self.assertEqual(self.view(app)["question"]["evidence"]["label"], SOURCE)
        self.answer(app, "confirm")
        self.assertEqual(len(exchange.requests), 1)
        self.answer(app, "unsure")
        view = self.view(app)
        self.assertEqual(view["state"], "provider_stop")
        self.assertIsNone(view["urgency"])
        self.assertIsNone(view["next_step"])
        self.assertEqual(view["possible_causes"], [])
        self.assert_no_hospital(app)
        app.run()
        constructor.assert_called_once()
        self.assertEqual(len(exchange.requests), 2)
        for method, path, body in exchange.requests:
            self.assertEqual((method, path), ("POST", f"/serving-endpoints/{ENDPOINT}/invocations"))
            self.assertEqual(body["max_tokens"], 1024)
