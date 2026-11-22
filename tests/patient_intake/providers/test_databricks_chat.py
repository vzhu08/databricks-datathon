import json
import unittest
from unittest.mock import Mock

from app.patient_intake.providers.databricks_chat import DatabricksChatProbe
from app.patient_intake.providers.transport import Budget, Transport


class DatabricksProbeTests(unittest.TestCase):
    def setUp(self):
        self.raw = Mock()
        self.transport = Transport(host="fictional.invalid", headers={}, attempts=3, exchange=self.raw)

    def probe(self, **options):
        return DatabricksChatProbe(endpoint="fixture-model", transport=self.transport,
                                   budget=Budget(2), **options)

    def test_disabled_no_calls(self):
        self.assertEqual(self.probe().exchange("test", "invented").status, "unavailable")
        self.raw.assert_not_called()

    def test_payload_privacy_limits_and_untrusted_output(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "invented"}}]}
        self.raw.return_value = 200, "application/json", json.dumps(response).encode(), {}
        probe = self.probe(enabled=True, output_limit_field="max_completion_tokens")
        for _ in range(2):
            reply = probe.exchange("Synthetic test", "Fictional report")
            self.assertEqual(reply.data, {"content": "invented"})
            self.assertNotIn("invented", repr(reply))
        self.assertEqual(probe.exchange("Synthetic test", "Fictional report").status, "budget_exhausted")
        _, method, path, _, body, _ = self.raw.call_args.args
        self.assertEqual((method, path), ("POST", "/serving-endpoints/fixture-model/invocations"))
        data = json.loads(body)
        self.assertEqual(data["max_completion_tokens"], 256)
        self.assertEqual(data["messages"][1]["content"], "Fictional report")
        self.assertEqual(self.raw.call_count, 2)

    def test_truncated_and_tool_output_withheld(self):
        probe = self.probe(enabled=True)
        for reason in ("length", "tool_calls"):
            self.raw.return_value = 200, "application/json", json.dumps({"choices": [{
                "finish_reason": reason, "message": {"role": "assistant", "content": "partial"}}]}).encode(), {}
            self.assertEqual(probe.exchange("instruction", "invented").status, "invalid_response")
