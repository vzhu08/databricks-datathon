import threading
import unittest
from unittest.mock import Mock

from app.patient_intake.providers.transport import Budget, MAX_RESPONSE, Transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.exchange = Mock(return_value=(200, "application/json", b'{"fictional":"unknown"}'))
        self.transport = Transport(host="fictional.invalid", headers={}, attempts=20,
                                   exchange=self.exchange)
        self.budget = Budget(12)

    def call(self, **options):
        return self.transport.request("POST", "/assessment", encounter=self.budget, **options)

    def test_unknown_payload_preserved_only_as_untrusted_data(self):
        reply = self.call(payload={"invented": "yes"})
        self.assertEqual(reply.data, {"fictional": "unknown"})
        self.assertNotIn("fictional", repr(reply))
        self.assertEqual(self.exchange.call_count, 1)

    def test_limits_before_exchange(self):
        self.assertEqual(self.call(payload={"text": "x" * 17000}).status, "invalid_request")
        self.assertEqual(self.transport.request("GET", "/?text=test", encounter=self.budget).status,
                         "invalid_request")
        self.assertEqual(self.transport.request("GET", "/state", encounter=Budget(0)).status,
                         "budget_exhausted")
        Transport(host="fictional.invalid", headers={}, exchange=self.exchange).request(
            "GET", "/state", encounter=self.budget)
        self.exchange.assert_not_called()

    def test_budgets_span_calls_and_failure_consumes_attempt(self):
        exchange = Mock(side_effect=TimeoutError())
        transport = Transport(host="fictional.invalid", headers={}, attempts=2, exchange=exchange)
        one = Budget(1)
        self.assertEqual(transport.request("GET", "/state", encounter=one).status, "timeout")
        self.assertEqual(transport.request("GET", "/state", encounter=one).status, "budget_exhausted")
        self.assertEqual(transport.request("GET", "/state", encounter=Budget(5)).status, "timeout")
        self.assertEqual(transport.request("GET", "/state", encounter=Budget(5)).status, "budget_exhausted")
        self.assertEqual(exchange.call_count, 2)

    def test_errors_never_leak_bodies_or_retry(self):
        for status, expected in [(302, "provider_error"), (401, "access_denied"),
                                 (429, "rate_limited"), (503, "provider_error")]:
            self.exchange.return_value = (status, "text/html", b"sensitive-test-value")
            self.assertEqual(self.call().status, expected)
        for raw in [b"[]", b"{", b'{"x":0,"x":1}', b'{"x":1e999}', b" " * (MAX_RESPONSE+1)]:
            self.exchange.return_value = (200, "application/json", raw)
            self.assertEqual(self.call().status, "invalid_response")
        self.exchange.side_effect = OSError("sensitive-test-value")
        self.assertEqual(self.call().status, "unavailable")
        self.assertEqual(self.exchange.call_count, 10)

    def test_timed_out_requests_hold_slots_and_spend_quota(self):
        release = threading.Event()
        self.exchange.side_effect = lambda *args: (release.wait(2), "application/json", b"{}")
        try:
            self.assertEqual(self.call(timeout=.02).status, "timeout")
            self.assertEqual(self.call(timeout=.02).status, "timeout")
            self.assertEqual(self.call(timeout=.02).status, "busy")
        finally:
            release.set()
