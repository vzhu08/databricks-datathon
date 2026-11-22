import json
import unittest
from unittest.mock import Mock, patch

from app.patient_intake.providers import databricks_diagnostic as diagnostic
from app.patient_intake.providers.transport import Budget, _https


class DatabricksDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Mock()
        for factory in (patch.object(diagnostic, "_WorkspaceExchange", return_value=self.exchange),
                        patch.object(diagnostic, "_TEST_ATTEMPT", Budget(1))):
            factory.start()
            self.addCleanup(factory.stop)

    def test_single_fixed_request_and_allowlisted_metadata(self):
        self.exchange.return_value = 400, "application/json", json.dumps({
            "error_code": "INVALID_PARAMETER_VALUE",
            "message": "private bearer and echoed material",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.BadRequest", "field_violations": [
                    {"field": "response_format", "description": "private bearer"},
                    {"field": "messages[0].private echo"},
                    {"field": "other private material"}]},
                {"@type": "type.googleapis.com/google.rpc.RequestInfo", "request_id": "private"},
            ],
        }).encode(), {"Set-Cookie": "private"}
        receipt = diagnostic.run_gpt_oss_protocol_diagnostic()
        self.assertEqual(receipt["http_status"], 400)
        self.assertEqual(receipt["error_code"], "INVALID_PARAMETER_VALUE")
        self.assertEqual(receipt["error_fields"], ("messages", "response_format"))
        self.assertNotIn("private", repr(receipt))
        _, method, path, _, body, timeout = self.exchange.call_args.args
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/serving-endpoints/databricks-gpt-oss-20b/invocations")
        self.assertEqual(json.loads(body), {
            "messages": [{"role": "user", "content": "Reply with the single invented label SAMPLE."}],
            "max_tokens": 256,
        })
        self.assertEqual(timeout, 10)
        self.assertEqual(diagnostic.run_gpt_oss_protocol_diagnostic()["status"], "budget_exhausted")
        self.assertEqual(self.exchange.call_count, 1)

    def test_nonstandard_oversize_malformed_and_duplicate_codes_are_withheld(self):
        for media, raw in (
            ("application/json", b'{"error_code":"echoed"}'),
            ("application/json", b'{"error_code":"PERMISSION_DENIED"}'),
            ("application/json", b'{"error_code":400}'),
            ("text/html", b'{"error_code":"BAD_REQUEST"}'),
            ("application/json", b'{"error_code":"BAD_REQUEST"}' + b" " * 4096),
            ("application/json", b'{"error_code":"BAD_REQUEST","error_code":"INVALID_PARAMETER_VALUE"}'),
            ("application/json", b'"unparsed"'),
        ):
            with self.subTest(media=media, raw=raw[:60]):
                self.assertEqual(diagnostic._error_metadata(raw, media, 400), (None, ()))

    def test_success_projects_only_boolean_and_aggregate_usage(self):
        self.exchange.return_value = 200, "application/json", json.dumps({
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "private"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16, "private": True},
        }).encode(), {}
        receipt = diagnostic.run_gpt_oss_protocol_diagnostic()
        self.assertTrue(receipt["assistant_text_received"])
        self.assertEqual(receipt["usage"], {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16})
        self.assertNotIn("private", repr(receipt))

    def test_normal_https_discards_failure_body_and_opt_in_reads_at_most_limit_plus_one(self):
        with patch("app.patient_intake.providers.transport.HTTPSConnection") as tls:
            conn = tls.return_value
            response = conn.getresponse.return_value
            response.status = 400
            response.getheader.side_effect = lambda name, default=None: (
                "application/json; charset=utf-8" if name == "Content-Type" else default)
            response.read.return_value = b'{"error_code":"BAD_REQUEST"}'
            args = ("fictional.invalid", "POST", "/invocations", {}, b"{}", 1)
            self.assertEqual(_https(*args)[2], b"")
            response.read.assert_not_called()
            self.assertEqual(_https(*args, error_body_limit=4096)[2], response.read.return_value)
            response.read.assert_called_once_with(4097)
            response.getheader.side_effect = lambda name, default=None: (
                "text/html" if name == "Content-Type" else default)
            self.assertEqual(_https(*args, error_body_limit=4096)[2], b"")
            self.assertEqual(response.read.call_count, 1)
