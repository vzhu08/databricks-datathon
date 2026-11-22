import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event, Lock
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from app.travel.tomtom import (PARAMETERS, PRODUCT, RoutesConfig, TomTomRoutes, TransportFailure,
                               from_environment, http_transport, parse_route)
from tests.travel.helpers import NOW, client, no_route, route


class RouteTests(unittest.TestCase):
    def test_concurrent_out_of_order_completion_is_bound_to_campus_and_within_limit(self):
        first_waiting, release_first, lock = Event(), Event(), Lock()
        active, peak, finished = [0], [0], []
        def send(origin, dest, config):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                if dest == (1, 1):
                    first_waiting.set()
                    self.assertTrue(release_first.wait(2))
                else:
                    self.assertTrue(first_waiting.wait(2))

                return route(dest[0] * 60, dest[0] * 100)
            finally:
                with lock:
                    active[0] -= 1
        c = client(send, concurrency=2)
        self.addCleanup(c.close)
        submit = c._pool.submit
        def observed_submit(fn, fid, point):
            future = submit(fn, fid, point)
            def completed(_):
                with lock:
                    finished.append(fid)
                if fid == "fast":
                    release_first.set()
            future.add_done_callback(completed)
            return future
        c._pool.submit = observed_submit
        result = c.routes((0, 0), [("slow", (1, 1)), ("fast", (2, 2)), ("third", (3, 3))])
        self.assertEqual(result.results["slow"]["estimated_minutes"], 1)
        self.assertEqual(result.results["fast"]["road_metres"], 200)
        self.assertEqual(result.calls_attempted, 3)
        self.assertLess(finished.index("fast"), finished.index("slow"))
        self.assertEqual(result.evaluated_ids, {"slow", "fast", "third"})
        self.assertLessEqual(peak[0], 2)
        self.assertEqual(peak[0], 2)

    def test_fractional_and_explicit_zero_measurements_and_selected_first_route(self):
        for seconds, metres in [(90.5, 800), (0, 0), (1e-9, .5)]:
            with self.subTest(seconds=seconds):
                payload = route(seconds, metres)
                payload["routes"].append({"summary": {"travelTimeInSeconds": 999, "lengthInMeters": 999}})
                row = parse_route(payload, "2026-11-21T20:00:00Z")
                self.assertEqual(row["outcome"], "ok")
                self.assertEqual(row["estimated_minutes"], seconds / 60)
                self.assertEqual(row["road_metres"], metres)

    def test_missing_invalid_summaries_never_default_to_zero(self):
        payloads = [None, [], {}, {"routes": []}, {"routes": [None]}, {"routes": [{}]},
                    {"routes": [{"summary": []}]}]
        for value in (None, -1, True, "90", float("nan"), float("inf"), 10 ** 400):
            payloads.extend([route(value), route(metres=value)])
        payloads.extend([{"routes": [{"summary": {"travelTimeInSeconds": 0}}]},
                         {"routes": [{"summary": {"lengthInMeters": 0}}]}])
        for payload in payloads:
            with self.subTest(payload=payload):
                row = parse_route(payload, "now")
                self.assertEqual(row["outcome"], "unavailable")
                self.assertIsNone(row["estimated_minutes"])
                self.assertFalse(row["fallback_allowed"])

    def test_only_documented_codes_establish_no_route_without_echoing_message(self):
        for code in ("NO_ROUTE_FOUND", "MAP_MATCHING_FAILURE", "BAD_INPUT", "NO_RANGE_FOUND", "unknown"):
            row = parse_route(no_route(code), "now")
            self.assertEqual(row["outcome"], "no_route" if code in ("NO_ROUTE_FOUND", "MAP_MATCHING_FAILURE") else "unavailable")
            self.assertFalse(row["fallback_allowed"])
            self.assertIsNone(row["estimated_seconds"])
            self.assertNotIn("PRIVATE", repr(row))
        self.assertEqual(parse_route({"detailedError": {"message": "NO_ROUTE_FOUND"}}, "now")["outcome"], "unavailable")

    def test_provider_departure_timestamp_or_explicit_request_time(self):
        for departure, expected, source in [("2026-11-22T01:30:00+05:30", "2026-11-21T20:00:00Z", "provider_summary"),
                                             ("wrong", "request", "request_time"),
                                             ("2026-11-21T20:00:00", "request", "request_time")]:
            row = parse_route(route(departureTime=departure), "request")
            self.assertEqual(row["departure_time"], expected)
            self.assertEqual(row["departure_time_source"], source)

    def test_all_coordinates_and_ids_checked_before_any_call(self):
        send = Mock()
        c = client(send)
        self.addCleanup(c.close)
        for point in [(91, 0), (0, -181), (float("nan"), 0), (0, float("inf")), (True, 0), (0,), (None, 0)]:
            with self.subTest(point=point), self.assertRaises(ValueError):
                c.routes((0, 0), [("valid", (0, 0)), ("invalid", point)])
        for destinations in [[("a", (0, 0)), ("a", (1, 1))], [("", (0, 0))], [(None, (0, 0))], [("missing",)], [(str(i), (0, 0)) for i in range(26)]]:
            with self.assertRaises(ValueError):
                c.routes((0, 0), destinations)
        send.assert_not_called()
        self.assertEqual(c.budget.used, 0)

    def test_retry_charges_calls_and_backoff_then_succeeds(self):
        send = Mock(side_effect=[TransportFailure("provider_transient_error"), route()])
        c = client(send)
        c.sleep = Mock()
        self.addCleanup(c.close)
        result = c.routes((0, 0), [("a", (1, 1))])
        self.assertEqual((result.calls_attempted, c.budget.used), (2, 2))
        self.assertEqual(result.results["a"]["outcome"], "ok")
        self.assertEqual(result.errors, [])
        c.sleep.assert_called_once_with(.25)

    def test_query_budget_includes_retries_and_preserves_previous_no_route(self):
        send = Mock(side_effect=[no_route(), TimeoutError("PRIVATE URL/key/coordinates")])
        c = client(send, query_calls=2, max_retries=1)
        self.addCleanup(c.close)
        result = c.routes((0, 0), [("a", (1, 1)), ("b", (2, 2)), ("c", (3, 3))])
        self.assertEqual(result.results["a"]["outcome"], "no_route")
        self.assertEqual(result.results["b"]["reason"], "query_call_budget_exceeded")
        self.assertEqual(result.results["c"]["reason"], "query_call_budget_exceeded")
        self.assertIsNone(result.results["c"]["requested_at"])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(c.budget.used, 2)
        self.assertNotIn("PRIVATE", repr(result))

    def test_concurrent_query_budget_cannot_overshoot(self):
        send = Mock(return_value=route())
        c = client(send, query_calls=7, concurrency=2)
        self.addCleanup(c.close)
        result = c.routes((0, 0), [(str(i), (1, 1)) for i in range(25)])
        self.assertEqual(result.calls_attempted, 7)
        self.assertEqual(send.call_count, 7)
        self.assertEqual(c.budget.used, 7)

    def test_daily_and_monthly_limits_bound_retries_and_later_queries(self):
        for limits, reason in [(dict(daily_calls=1), "daily_call_budget_exceeded"),
                               (dict(monthly_calls=1), "monthly_call_budget_exceeded")]:
            send = Mock(side_effect=TimeoutError("PRIVATE"))
            c = client(send, max_retries=1, **limits)
            self.addCleanup(c.close)
            result = c.routes((0, 0), [("a", (1, 1))])
            self.assertEqual(send.call_count, 1)
            self.assertEqual(result.results["a"]["reason"], reason)
            self.assertEqual(c.routes((0, 0), [("a", (1, 1))]).calls_attempted, 0)
            self.assertNotIn("PRIVATE", repr(result))

    def test_timestamps_bind_actual_send_not_budget_rejected_retry(self):
        c = client(Mock(side_effect=TimeoutError()), query_calls=1)
        self.addCleanup(c.close)
        c.clock = lambda: NOW
        result = c.routes((0, 0), [("a", (1, 1))])
        self.assertEqual(result.requested_at, "2026-11-21T20:00:00Z")
        self.assertEqual(result.results["a"]["requested_at"], result.requested_at)

    def test_auth_stops_queued_calls_and_quota_retries_are_bounded(self):
        for reason, count in [("authentication_failed", 1), ("provider_quota_exceeded", 2)]:
            c = client(Mock(side_effect=TransportFailure(reason)))
            self.addCleanup(c.close)
            result = c.routes((0, 0), [("a", (1, 1)), ("b", (2, 2))])
            self.assertEqual(c.transport.call_count, count)
            self.assertTrue(all(r["reason"] == reason for r in result.results.values()))
            self.assertEqual(result.errors, [reason])

    def test_disabled_and_missing_setup_never_send_or_reserve(self):
        for changes, reason in [(dict(enabled=False), "routing_disabled"), (dict(api_key=""), "missing_credentials"),
                                (dict(account_scope=""), "missing_approved_account"), (dict(product="orbis_v3"), "unverified_product_entitlement"),
                                (dict(daily_calls=0), "missing_call_budget"), (dict(monthly_calls=0), "missing_call_budget")]:
            c = client(Mock(), **changes)
            self.addCleanup(c.close)
            result = c.routes((0, 0), [("a", (1, 1))])
            self.assertEqual(result.results["a"]["reason"], reason)
            self.assertIsNone(result.requested_at)
            c.transport.assert_not_called()
            self.assertEqual(c.budget.used, 0)
        c = client(Mock())
        self.addCleanup(c.close)
        c.budget = None
        self.assertEqual(c.routes((0, 0), [("a", (1, 1))]).errors, ["missing_budget_store"])

    def test_budget_store_failure_fails_closed_and_redacts_exception(self):
        c = client(Mock())
        self.addCleanup(c.close)
        c.budget.acquire = Mock(side_effect=OSError("PRIVATE"))
        result = c.routes((0, 0), [("a", (1, 1))])
        self.assertEqual(result.errors, ["budget_store_unavailable"])
        c.transport.assert_not_called()
        self.assertNotIn("PRIVATE", repr(result))


class TransportTests(unittest.TestCase):
    def response(self, status, payload):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.getheader.return_value = None
        response.read.return_value = json.dumps(payload).encode()
        return connection

    def test_exact_v1_request_and_no_geometry(self):
        config = RoutesConfig(api_key="SYNTHETIC-KEY", product=PRODUCT)
        connection = self.response(200, route())
        with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection) as factory:
            self.assertEqual(http_transport((26.9, 75.8), (26.91, 75.81), config), route())
        factory.assert_called_once_with("api.tomtom.com", timeout=5)
        method, path = connection.request.call_args.args
        self.assertEqual(method, "GET")
        parsed = urlsplit(path)
        self.assertEqual(parsed.path, "/routing/1/calculateRoute/26.9,75.8:26.91,75.81/json")
        self.assertEqual(parse_qs(parsed.query), {k: [v] for k, v in {**PARAMETERS, "key": "SYNTHETIC-KEY"}.items()})
        connection.close.assert_called_once()
        self.assertNotIn("SYNTHETIC-KEY", repr(config))

    def test_http_errors_sanitize_and_classify_without_following_redirects(self):
        for status, reason in [(401, "authentication_failed"), (403, "authentication_failed"),
                               (429, "provider_quota_exceeded"), (500, "provider_transient_error"),
                               (503, "provider_transient_error"), (302, "provider_request_rejected"),
                               (404, "provider_request_rejected"), (400, "provider_request_rejected")]:
            connection = self.response(status, {"message": "PRIVATE"})
            with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection), self.assertRaises(TransportFailure) as caught:
                http_transport((0, 0), (1, 1), RoutesConfig())
            self.assertEqual(str(caught.exception), reason)
            self.assertNotIn("PRIVATE", repr(caught.exception))
            connection.request.assert_called_once()
            connection.close.assert_called_once()

    def test_400_no_route_codes_are_parsed_and_compute_timeout_retries(self):
        for code in ("NO_ROUTE_FOUND", "MAP_MATCHING_FAILURE"):
            connection = self.response(400, no_route(code))
            with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection):
                row = parse_route(http_transport((0, 0), (1, 1), RoutesConfig()), "now")
            self.assertEqual(row["outcome"], "no_route")
        connection = self.response(400, no_route("COMPUTE_TIME_LIMIT_EXCEEDED"))
        with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection), self.assertRaises(TransportFailure) as caught:
            http_transport((0, 0), (1, 1), RoutesConfig())
        self.assertTrue(caught.exception.retryable)

    def test_invalid_oversized_payload_and_network_errors_are_sanitized(self):
        for raw, reason in [(b"invalid PRIVATE", "invalid_provider_response"), (b"x" * 1_048_577, "provider_response_too_large")]:
            connection = self.response(200, {})
            connection.getresponse.return_value.read.return_value = raw
            with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection), self.assertRaises(TransportFailure) as caught:
                http_transport((0, 0), (1, 1), RoutesConfig())
            self.assertEqual(str(caught.exception), reason)
        for error, reason in [(TimeoutError("PRIVATE"), "provider_timeout"), (OSError("PRIVATE"), "provider_connection_error")]:
            connection = self.response(200, {})
            connection.request.side_effect = error
            with patch("app.travel.tomtom.http.client.HTTPSConnection", return_value=connection), self.assertRaises(TransportFailure) as caught:
                http_transport((0, 0), (1, 1), RoutesConfig())
            self.assertEqual(str(caught.exception), reason)

    def test_environment_is_disabled_without_explicit_account_product_and_limits(self):
        c = from_environment({})
        self.addCleanup(c.close)
        self.assertEqual(c.disabled_reason(), "routing_disabled")
        self.assertEqual(c.config.shortlist_limit, 25)
        for env in [{"TOMTOM_QUERY_CALLS": "PRIVATE"}, {"TOMTOM_CONCURRENCY": "9"},
                    {"TOMTOM_API_KEY": "PRIVATE\n"}, {"TOMTOM_TIMEOUT_SECONDS": "nan"}]:
            with self.assertRaises(ValueError) as caught:
                from_environment(env)
            self.assertNotIn("PRIVATE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
