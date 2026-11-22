from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Lock
import unittest
from unittest.mock import Mock, patch

from app.travel.budget import ALLOWANCE, PRODUCT, SQLiteBudget
from app.travel.finder import find_campuses
from app.travel.tomtom import TransportFailure, http_transport, retry_delay
from tests.travel.helpers import campus, client, no_route, request, route


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 22, 1, tzinfo=timezone.utc)
        self.lock = Lock()
        self.sleeps = []

    def __call__(self):
        with self.lock:
            return self.value

    def sleep(self, delay):
        with self.lock:
            self.sleeps.append(delay)
            self.value += timedelta(seconds=delay)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "usage.sqlite"
        self.clock = Clock()
        SQLiteBudget(self.path, verified_allowance=ALLOWANCE).initialize("synthetic-account", PRODUCT)

    def adapter(self, send, **kwargs):
        c = client(send, **kwargs)
        c.budget = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        c.clock, c.sleep = self.clock, self.clock.sleep
        self.addCleanup(c.close)
        return c

    def test_running_adapter_obeys_shared_rate_limits_with_fake_clock(self):
        sent = []
        def transport(*args):
            sent.append(self.clock().timestamp())
            return route()
        c = self.adapter(transport)
        result = c.routes((0, 0), [(str(i), (1, 1)) for i in range(25)])
        self.assertEqual(result.calls_attempted, 25)
        for tick in sent:
            self.assertLessEqual(sum(tick - 1 < other <= tick for other in sent), 2)
            self.assertLessEqual(sum(tick - 60 < other <= tick for other in sent), 60)
        self.assertEqual(result.usage["used"], 30)
        self.assertEqual(result.usage["active"], 0)
        self.assertEqual(result.usage["routine_remaining"], 470)

    def test_retry_after_is_capped_and_cooldown_shared_by_new_adapter(self):
        send = Mock(side_effect=TransportFailure("provider_quota_exceeded", retry_after=999))
        c = self.adapter(send)
        first = c.routes((0, 0), [("a", (1, 1))])
        self.assertEqual(first.calls_attempted, 2)
        self.assertEqual(first.errors, ["provider_quota_exceeded"])
        self.assertIn(5, self.clock.sleeps)
        blocked = self.adapter(Mock(return_value=route()), rate_wait_seconds=0)
        second = blocked.routes((0, 0), [("a", (1, 1))])
        self.assertEqual(second.errors, ["shared_provider_cooldown"])
        self.assertEqual(second.calls_attempted, 0)
        self.assertFalse(second.results["a"]["fallback_allowed"])
        blocked.transport.assert_not_called()
        self.clock.sleep(30)
        third = blocked.routes((0, 0), [("a", (1, 1))])
        self.assertEqual(third.results["a"]["outcome"], "ok")
        self.assertEqual(third.usage["used"], 8)

    def test_rate_or_local_budget_exhaustion_never_looks_like_outage_or_distance_fallback(self):
        c = self.adapter(Mock(return_value=route()), daily_calls=5, rate_wait_seconds=0)
        data = request([campus("a")])
        data["routing"]["fallback_distance_km"] = 50
        result = find_campuses(data, provider=c)
        self.assertEqual(result["routing"]["errors"], ["daily_call_budget_exceeded"])
        self.assertEqual(result["travel_metric"], "travel_minutes")
        self.assertEqual(result["ranked"], [])
        c.transport.assert_not_called()
        other = self.adapter(Mock(return_value=route()), rate_wait_seconds=0)
        result = other.routes((0, 0), [(str(i), (1, 1)) for i in range(3)])
        self.assertEqual(result.calls_attempted, 2)
        self.assertEqual(result.results["2"]["reason"], "local_rate_limited")

    def test_backend_profile_reservation_is_spent_and_public_privileges_rejected(self):
        ledger = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        run = ledger.reserve_run("synthetic-account", PRODUCT, self.clock(), 2)
        c = self.adapter(Mock(return_value=route()), profile="validation", daily_calls=3000,
                         monthly_calls=3000, run_id=run["run_id"])
        data = request([campus("a"), campus("b"), campus("c")])
        result = find_campuses(data, provider=c)
        self.assertEqual(result["routing"]["counts"]["provider_calls_attempted"], 2)
        self.assertEqual(result["routing"]["errors"], ["reserved_budget_exhausted"])
        self.assertEqual(result["routing"]["usage"]["used_by_profile"]["validation"], 2)
        for key, value in [("profile", "validation"), ("run_id", run["run_id"]), ("daily_calls", 10000),
                           ("request_scope", "another-user"), ("concurrency", 4), ("monthly_calls", 20000)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                find_campuses({**data, "routing": {**data["routing"], key: value}}, provider=c)
        self.assertEqual(c.transport.call_count, 2)

    def test_identical_active_searches_for_same_trusted_scope_share_work_but_not_cache(self):
        entered, release, waiter = Event(), Event(), Event()
        def send(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return route()
        c = self.adapter(Mock(side_effect=send))
        with ThreadPoolExecutor(max_workers=2) as callers:
            first = callers.submit(c.routes, (0, 0), [("a", (1, 1))], request_scope="caller-1:search-1")
            self.assertTrue(entered.wait(2))
            active = next(iter(c._flights.values()))
            original_result = active.result
            def join():
                waiter.set()
                return original_result()
            active.result = join
            second = callers.submit(c.routes, (0, 0), [("a", (1, 1))], request_scope="caller-1:search-1")
            self.assertTrue(waiter.wait(2))
            release.set()
            a, b = first.result(), second.result()
        self.assertEqual(c.transport.call_count, 1)
        self.assertFalse(a.coalesced)
        self.assertTrue(b.coalesced)
        self.assertEqual(a.results, b.results)
        self.assertEqual(c._flights, {})
        c.routes((0, 0), [("a", (1, 1))], request_scope="caller-1:search-1")
        self.assertEqual(c.transport.call_count, 2)  # completed response was not cached

    def test_other_callers_are_not_given_shared_provider_results(self):
        c = self.adapter(Mock(return_value=route()))
        c.routes((0, 0), [("a", (1, 1))], request_scope="caller-1:search")
        c.routes((0, 0), [("a", (1, 1))], request_scope="caller-2:search")
        self.assertEqual(c.transport.call_count, 2)
        self.assertEqual(c._flights, {})

    def test_store_and_entitlement_gate_and_ambiguous_attempts_fail_closed(self):
        for kwargs, reason in [(dict(verified_monthly_allowance=0), "unverified_allocation"),
                               (dict(verified_monthly_allowance=21000), "unverified_allocation"),
                               (dict(deployment_mode="multi_host"), "unsupported_budget_deployment")]:
            c = self.adapter(Mock(), **kwargs)
            self.assertEqual(c.routes((0, 0), [("a", (1, 1))]).errors, [reason])
            c.transport.assert_not_called()
        c = self.adapter(Mock(side_effect=TimeoutError("PRIVATE")), max_retries=0)
        c.budget.finish = Mock(side_effect=OSError("PRIVATE"))
        result = c.routes((0, 0), [("a", (1, 1)), ("b", (2, 2))])
        self.assertEqual(result.calls_attempted, 1)
        self.assertEqual(result.errors, ["budget_store_unavailable"])
        self.assertEqual(result.usage["active"], 1)  # permit was not silently cleared
        self.assertNotIn("PRIVATE", repr(result))

    def test_lost_budget_cannot_restore_allowance_and_recovery_keeps_usage(self):
        send = Mock(return_value=route())
        c = self.adapter(send, daily_calls=6)
        dest = [("a", (1, 1))]
        first = c.routes((0, 0), dest)
        self.assertEqual(first.calls_attempted, 1)
        self.assertEqual(first.usage["used"], 6)
        restored = self.path.with_suffix(".backup")
        self.path.rename(restored)

        def assert_closed():
            result = c.routes((0, 0), dest)
            self.assertEqual(result.errors, ["budget_store_unavailable"])
            self.assertEqual(result.calls_attempted, 0)
            self.assertIsNone(result.requested_at)
            self.assertFalse(result.results["a"]["fallback_allowed"])
            self.assertEqual(send.call_count, 1)

        assert_closed()
        self.assertFalse(self.path.exists())
        self.path.touch()
        assert_closed()
        self.assertEqual(self.path.stat().st_size, 0)
        with sqlite3.connect(str(self.path)) as db:
            db.execute("CREATE TABLE unrelated (value INTEGER)")
        previous_bytes = self.path.read_bytes()
        assert_closed()
        self.assertEqual(self.path.read_bytes(), previous_bytes)
        restored.replace(self.path)
        result = c.routes((0, 0), dest)
        self.assertEqual(result.errors, ["daily_call_budget_exceeded"])
        self.assertEqual(result.usage["used"], 6)
        self.assertEqual(send.call_count, 1)

    def test_http_bad_input_preserves_second_eta_and_charges_both_attempts(self):
        data = request([campus("bad", 75.801), campus("good", 75.82)])
        responses = []
        for status, payload in [(400, no_route("BAD_INPUT")), (200, route(120))]:
            connection = Mock()
            connection.getresponse.return_value.status = status
            connection.getresponse.return_value.read.return_value = json.dumps(payload).encode()
            responses.append(connection)
        c = self.adapter(http_transport)
        with patch("app.travel.tomtom.http.client.HTTPSConnection", side_effect=responses) as https:
            result = find_campuses(data, provider=c)
        self.assertEqual(https.call_count, 2)
        self.assertEqual(result["routing"]["state"], "partial")
        self.assertEqual(result["routing"]["counts"]["provider_calls_attempted"], 2)
        self.assertEqual(result["routing"]["usage"]["used"], 7)
        rows = {row["facility_id"]: row for row in result["routing"]["results"]}
        self.assertEqual(rows["bad"]["reason"], "provider_request_rejected")
        self.assertIsNone(rows["bad"]["estimated_minutes"])
        self.assertEqual(rows["good"]["estimated_minutes"], 2)
        self.assertEqual([row["facility_id"] for row in result["ranked"]], ["good"])
        self.assertNotIn("PRIVATE", repr(result))

    def test_retry_after_seconds_http_date_invalid_and_nonfinite(self):
        with patch("app.travel.tomtom.utc_now", return_value=self.clock()):
            for raw, expected in [("3", 3), ("999999", 5), ("-1", 0), ("nan", 0),
                                  (None, 0), ("PRIVATE", 0), ("Sun, 22 Nov 2026 01:00:04 GMT", 4)]:
                self.assertEqual(retry_delay(raw), expected)


if __name__ == "__main__":
    unittest.main()
