"""Bounded TomTom Maps v1 Calculate Route calls; no response logging or storage."""

import copy
import http.client
import json
import math
import os
import re
import sqlite3
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

if "." in __package__:  # Repository package app.travel
    from ..ranking.location import coordinates
else:  # Databricks ships app/ as the import root
    from ranking.location import coordinates
from .budget import ALLOCATIONS, ALLOWANCE, SQLiteBudget

PROVIDER = "tomtom"
PRODUCT = "tomtom_maps_v1"
MODE = "car"
PREFERENCE = "fastest_traffic"
PARAMETERS = {"routeType": "fastest", "traffic": "true", "departAt": "now",
              "travelMode": MODE, "maxAlternatives": "0", "routeRepresentation": "summaryOnly"}
# Only these sanitized categories can escape the transport boundary.
RETRYABLE = {"provider_timeout", "provider_connection_error", "provider_transient_error",
             "provider_quota_exceeded"}
FAILURES = RETRYABLE | {"authentication_failed", "provider_request_rejected",
                        "provider_response_too_large", "invalid_provider_response"}
NO_ROUTE_CODES = {"NO_ROUTE_FOUND": "no_route_found", "MAP_MATCHING_FAILURE": "point_not_routable"}


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Routing clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RoutesConfig:
    enabled: bool = False
    api_key: str = field(default="", repr=False)
    account_scope: str = ""
    product: str = ""
    daily_calls: int = 0
    monthly_calls: int = 0
    query_calls: int = 50
    concurrency: int = 2
    verified_monthly_allowance: int = 0
    deployment_mode: str = ""
    profile: str = "routine"
    run_id: str = None
    rate_wait_seconds: float = 65.0
    max_retries: int = 1
    timeout_seconds: float = 5.0
    shortlist_limit: int = 25

    def __post_init__(self):
        bounds = ((self.daily_calls, 0, 3000), (self.monthly_calls, 0, 3000),
                  (self.query_calls, 1, 50), (self.concurrency, 1, 2),
                  (self.max_retries, 0, 1), (self.shortlist_limit, 1, 25))
        if any(type(n) is not int or not low <= n <= high for n, low, high in bounds):
            raise ValueError("Routing limits are outside their supported bounds")
        if (type(self.timeout_seconds) not in (int, float) or
                not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 10):
            raise ValueError("Routing timeout must be greater than zero and at most ten seconds")
        if type(self.enabled) is not bool or any(not isinstance(x, str)
                for x in (self.api_key, self.account_scope, self.product)):
            raise ValueError("Invalid backend routing configuration")
        if (self.profile not in ALLOCATIONS or self.monthly_calls > ALLOCATIONS[self.profile] or
                self.daily_calls > (100 if self.profile == "routine" else ALLOCATIONS[self.profile]) or
                type(self.verified_monthly_allowance) is not int or
                type(self.rate_wait_seconds) not in (int, float) or
                not math.isfinite(self.rate_wait_seconds) or not 0 <= self.rate_wait_seconds <= 65 or
                (self.run_id is not None and not isinstance(self.run_id, str))):
            raise ValueError("Invalid trusted operator profile or budget")
        if self.api_key and not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", self.api_key):
            raise ValueError("Invalid backend routing key format")


class TransportFailure(Exception):
    """Never attach an upstream URL, body, message or exception to this error."""
    def __init__(self, reason, retry_after=0):
        self.retry_after = min(5.0, max(0.0, retry_after)) if type(retry_after) in (int, float) and math.isfinite(retry_after) else 0.0
        self.reason = reason if reason in FAILURES else "provider_request_rejected"
        self.retryable = self.reason in RETRYABLE
        super().__init__(self.reason)


def retry_delay(value):
    """Retry-After seconds or HTTP date; never echo the original header."""
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = (parsedate_to_datetime(value) - utc_now()).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    return min(5.0, max(0.0, delay)) if math.isfinite(delay) else 0.0


def http_transport(origin, destination, config):
    """Fixed HTTPS host, no redirects, bounded reads, summary only, sanitized failures."""
    locations = ":".join(",".join(str(float(v)) for v in point) for point in (origin, destination))
    path = "/routing/1/calculateRoute/" + locations + "/json?" + urlencode(
        {**PARAMETERS, "key": config.api_key})
    connection = http.client.HTTPSConnection("api.tomtom.com", timeout=config.timeout_seconds)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status in (401, 403):
            raise TransportFailure("authentication_failed")
        if response.status == 429:
            raise TransportFailure("provider_quota_exceeded", retry_delay(response.getheader("Retry-After")))
        if response.status in (408, 500, 502, 503, 504):
            raise TransportFailure("provider_transient_error", retry_delay(response.getheader("Retry-After")))
        if response.status not in (200, 400):
            raise TransportFailure("provider_request_rejected")
        raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            raise TransportFailure("provider_response_too_large")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise TransportFailure("invalid_provider_response") from None
        if response.status == 400:
            code = error_code(payload)
            if code not in NO_ROUTE_CODES:
                raise TransportFailure("provider_transient_error" if code == "COMPUTE_TIME_LIMIT_EXCEEDED"
                                       else "provider_request_rejected")
        return payload
    except TimeoutError:
        raise TransportFailure("provider_timeout") from None
    except (OSError, http.client.HTTPException):
        raise TransportFailure("provider_connection_error") from None
    finally:
        connection.close()


def error_code(payload):
    error = payload.get("detailedError") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def unknown(reason, requested_at, *, fallback=False):
    return dict(outcome="unavailable", reason=reason, estimated_seconds=None,
                estimated_minutes=None, road_metres=None, requested_at=requested_at,
                departure_time=requested_at, departure_time_source="request_time" if requested_at else None,
                fallback_allowed=fallback)


def parse_route(payload, requested_at):
    """Read only the selected route summary, never infer zero or route absence."""
    code = error_code(payload)
    if code in NO_ROUTE_CODES:
        return {**unknown(NO_ROUTE_CODES[code], requested_at), "outcome": "no_route"}
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if code is not None or not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
        return unknown("invalid_provider_response", requested_at)
    summary = routes[0].get("summary")
    if not isinstance(summary, dict):
        return unknown("missing_route_summary", requested_at)
    seconds, metres = summary.get("travelTimeInSeconds"), summary.get("lengthInMeters")
    try:
        valid = all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (seconds, metres))
    except OverflowError:
        valid = False
    if not valid:
        return unknown("invalid_route_measurement", requested_at)
    row = {**unknown(None, requested_at), "outcome": "ok", "estimated_seconds": seconds,
           "estimated_minutes": seconds / 60, "road_metres": metres}
    departure = summary.get("departureTime")
    if isinstance(departure, str):
        try:
            row["departure_time"] = timestamp(datetime.fromisoformat(departure.replace("Z", "+00:00")))
            row["departure_time_source"] = "provider_summary"
        except ValueError:
            pass  # Request time remains explicit; no invented provider timestamp.
    return row


@dataclass
class RouteResults:
    requested_at: str = None
    results: dict = field(default_factory=dict)
    evaluated_ids: set = field(default_factory=set)
    calls_attempted: int = 0
    errors: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    coalesced: bool = False


class TomTomRoutes:
    def __init__(self, config=None, *, transport=http_transport, budget=None,
                 clock=utc_now, sleep=time.sleep):
        self.config = config or RoutesConfig()
        self.transport, self.budget, self.clock, self.sleep = transport, budget, clock, sleep
        # One adapter per backend process: bound outstanding calls across queries.
        self._pool = ThreadPoolExecutor(max_workers=self.config.concurrency)
        self._flights, self._flights_lock = {}, Lock()

    def close(self):
        self._pool.shutdown(wait=True)

    def disabled_reason(self):
        c = self.config
        if not c.enabled:
            return "routing_disabled"
        if c.deployment_mode == "databricks_apps" or (
                c.deployment_mode == "databricks_delta" and isinstance(self.budget, SQLiteBudget)):
            return "unsupported_budget_deployment"
        if c.product != PRODUCT:
            return "unverified_product_entitlement"
        if not c.api_key:
            return "missing_credentials"
        if not c.account_scope.strip():
            return "missing_approved_account"
        if c.deployment_mode not in ("single_host", "databricks_delta"):
            return "unsupported_budget_deployment"
        if c.verified_monthly_allowance != ALLOWANCE:
            return "unverified_allocation"
        if not c.daily_calls or not c.monthly_calls:
            return "missing_call_budget"
        if c.profile == "validation" and not c.run_id:
            return "validation_reservation_required"
        if self.budget is None:
            return "missing_budget_store"
        return None

    def routes(self, origin, destinations, *, request_scope=None):
        """destinations is [(stable campus ID, (latitude, longitude)), ...]."""
        if not isinstance(destinations, (list, tuple)) or len(destinations) > self.config.shortlist_limit:
            raise ValueError("Route destinations exceed the backend shortlist bound")
        points, ids = [origin], []
        for entry in destinations:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("Each destination needs a stable campus ID and coordinates")
            fid, point = entry
            if not isinstance(fid, str) or not fid.strip() or fid in ids:
                raise ValueError("Route campus IDs must be nonempty and unique")
            ids.append(fid)
            points.append(point)
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2 or coordinates(
                    {"latitude": point[0], "longitude": point[1]}) is None:
                raise ValueError("Routing needs valid origin and destination coordinates")
        if request_scope is not None and (not isinstance(request_scope, str) or not request_scope):
            raise ValueError("Request scope must be a trusted nonempty backend identifier")
        # In-memory only, while the call is active. Reuse one long-lived adapter
        # in the backend so simultaneous identical searches share the same work.
        if request_scope is None:
            return self._routes(origin, destinations)
        # Scope must bind authenticated caller AND search operation. Never share
        # TomTom content across users or cache completed responses.
        key = (request_scope, tuple(origin), tuple(sorted((fid, tuple(point)) for fid, point in destinations)))
        with self._flights_lock:
            existing = self._flights.get(key)
            if existing is None:
                self._flights[key] = future = Future()
        if existing is not None:
            result = copy.deepcopy(existing.result())
            result.coalesced = True
            return result
        try:
            result = self._routes(origin, destinations)
            future.set_result(result)
            return result
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._flights_lock:
                self._flights.pop(key, None)

    def _routes(self, origin, destinations):
        result = RouteResults(results={fid: unknown("not_evaluated", None) for fid, _ in destinations})
        if not destinations:
            return result
        disabled = self.disabled_reason()
        if disabled:
            result.results = {fid: unknown(disabled, None) for fid, _ in destinations}
            result.errors = [disabled]
            return result
        c, lock, stop = self.config, Lock(), [None]

        def one_route(fid, destination):
            last_sent_at, waited = None, 0.0
            for attempt in range(c.max_retries + 1):
                while True:
                    with lock:
                        if stop[0]:
                            return unknown(stop[0], last_sent_at, fallback=stop[0] in RETRYABLE or stop[0] == "authentication_failed")
                        if result.calls_attempted >= c.query_calls:
                            stop[0] = "query_call_budget_exceeded"
                            return unknown(stop[0], last_sent_at)
                        now = self.clock()
                        try:
                            admission = self.budget.acquire(c.account_scope, c.product, now,
                                profile=c.profile, daily_limit=c.daily_calls, monthly_limit=c.monthly_calls, run_id=c.run_id)
                        except (OSError, sqlite3.Error):
                            stop[0] = "budget_store_unavailable"
                            return unknown(stop[0], last_sent_at)
                        if admission.token:
                            result.calls_attempted += 1
                            result.evaluated_ids.add(fid)
                            last_sent_at = timestamp(now)
                            if result.requested_at is None:
                                result.requested_at = last_sent_at
                            break
                        if admission.reason not in ("local_rate_limited", "local_inflight_limit", "shared_provider_cooldown"):
                            stop[0] = admission.reason
                            return unknown(stop[0], last_sent_at)
                    delay = admission.retry_after
                    if delay <= 0 or waited + delay > c.rate_wait_seconds:
                        return unknown(admission.reason, last_sent_at)
                    self.sleep(delay)
                    waited += delay
                reason, payload, retryable, retry_after = None, None, False, 0.0
                try:
                    payload = self.transport(origin, destination, c)
                except TransportFailure as exc:
                    reason, retryable, retry_after = exc.reason, exc.retryable, exc.retry_after
                except (TimeoutError, OSError) as exc:
                    reason = "provider_timeout" if isinstance(exc, TimeoutError) else "provider_connection_error"
                    retryable = True
                finally:
                    try:
                        self.budget.finish(admission.token, self.clock(),
                                           quota=reason == "provider_quota_exceeded", success=reason is None)
                    except (OSError, sqlite3.Error):
                        with lock:
                            stop[0] = "budget_store_unavailable"
                if stop[0] == "budget_store_unavailable":
                    return unknown(stop[0], last_sent_at)
                if reason is None:
                    return parse_route(payload, last_sent_at)
                if not retryable or attempt == c.max_retries:
                    # A rejected pair may have invalid input even when other
                    # campuses in this search are routable.
                    if reason in ("authentication_failed", "provider_quota_exceeded"):
                        with lock:
                            if stop[0] is None:
                                stop[0] = reason
                    return unknown(reason, last_sent_at, fallback=reason in RETRYABLE or reason == "authentication_failed")
                self.sleep(max(.25 * (2 ** attempt), retry_after))
            raise AssertionError("Unreachable retry state")

        pending = {self._pool.submit(one_route, fid, point): fid for fid, point in destinations}
        for future in as_completed(pending):
            result.results[pending[future]] = future.result()
        try:
            result.usage = self.budget.status(c.account_scope, c.product, self.clock())
        except (OSError, sqlite3.Error):
            result.usage = {"reason": "budget_store_unavailable"}
        result.errors = sorted({r["reason"] for r in result.results.values() if r["outcome"] == "unavailable"})
        return result


def from_environment(environ=None):
    """Backend-only settings. Enable only after approved entitlement and Jaipur checks."""
    env = os.environ if environ is None else environ
    mode = env.get("TOMTOM_DEPLOYMENT_MODE", "")
    in_app = any(key in env for key in ("DATABRICKS_APP_NAME", "DATABRICKS_APP_PORT", "DATABRICKS_APP_URL"))
    if in_app and mode != "databricks_delta":
        # App-local SQLite disappears on restart and is private to each replica.
        # Keep even an accidental single_host configuration away from the network.
        if env.get("TOMTOM_ENABLED") == "true":
            return TomTomRoutes(RoutesConfig(enabled=True, product=PRODUCT, deployment_mode="databricks_apps"))
        return TomTomRoutes()
    try:
        config = RoutesConfig(enabled=env.get("TOMTOM_ENABLED") == "true",
                              api_key=env.get("TOMTOM_API_KEY", ""),
                              account_scope=env.get("TOMTOM_ACCOUNT_SCOPE", ""),
                              product=env.get("TOMTOM_PRODUCT", ""),
                              daily_calls=int(env.get("TOMTOM_DAILY_CALLS", "0")),
                              monthly_calls=int(env.get("TOMTOM_MONTHLY_CALLS", "0")),
                              query_calls=int(env.get("TOMTOM_QUERY_CALLS", "50")),
                              concurrency=int(env.get("TOMTOM_CONCURRENCY", "2")),
                              verified_monthly_allowance=int(env.get("TOMTOM_VERIFIED_MONTHLY_ALLOWANCE", "0")),
                              deployment_mode=mode,
                              profile=env.get("TOMTOM_PROFILE", "routine"),
                              run_id=env.get("TOMTOM_RUN_ID"),
                              rate_wait_seconds=float(env.get("TOMTOM_RATE_WAIT_SECONDS", "65")),
                              max_retries=int(env.get("TOMTOM_MAX_RETRIES", "1")),
                              timeout_seconds=float(env.get("TOMTOM_TIMEOUT_SECONDS", "5")),
                              shortlist_limit=int(env.get("TOMTOM_SHORTLIST_LIMIT", "25")))
    except (TypeError, ValueError):
        raise ValueError("Invalid backend routing configuration; check operator settings") from None
    budget = None
    if config.enabled and mode == "databricks_delta":
        warehouse = env.get("TOMTOM_BUDGET_WAREHOUSE_ID")
        table = env.get("TOMTOM_BUDGET_TABLE")
        if warehouse and table and config.account_scope.strip():
            try:
                from .delta_budget import DeltaBudget
            except ModuleNotFoundError as exc:
                if exc.name != f"{__package__}.delta_budget":
                    raise
                return TomTomRoutes(config)  # Incomplete selective deployment; no budget, no sends.
            budget = DeltaBudget(warehouse, table, account_scope=config.account_scope,
                                 verified_allowance=config.verified_monthly_allowance)
    elif config.enabled and mode == "single_host" and env.get("TOMTOM_BUDGET_DB"):
        budget = SQLiteBudget(env["TOMTOM_BUDGET_DB"], verified_allowance=config.verified_monthly_allowance)
    return TomTomRoutes(config, budget=budget)
