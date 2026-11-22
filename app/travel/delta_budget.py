"""Shared TomTom admission backed by one operator-provisioned UC Delta row."""

import json
import logging
import re
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from functools import cached_property
from http.client import HTTPSConnection
from time import monotonic, sleep
from urllib.parse import urlsplit

from .budget import ALLOCATIONS, ALLOWANCE, EXPLORER_DAY, EXPLORER_RECEIPT, PRODUCT, SAFETY_MARGIN, Admission

_API = "/api/2.0/sql/statements"
_LIMIT = 1024 * 1024
_SQL_WAIT_SECONDS = 15
_HTTP_TIMEOUT_SECONDS = 8
_POLL_INTERVAL_SECONDS = 1
_POLL_LIMIT = 14
_PENDING_STATES = {"PENDING", "RUNNING"}
_TERMINAL_FAILURES = {"FAILED": "sql_failed", "CANCELED": "sql_canceled", "CLOSED": "sql_result_closed"}
_STATEMENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_ID = re.compile(r"[a-f0-9]{32}")
_TABLE_PART = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
_CONFLICT = re.compile(r"\[DELTA_CONCURRENT_(?:APPEND|DELETE_READ|DELETE_DELETE|WRITE)\b")
_LOG = logging.getLogger(__name__)


class BudgetStoreUnavailable(OSError):
    """A failed or unconfirmed ledger operation cannot authorize a send."""


class _WriteConflict(Exception):
    """An explicitly failed Delta transaction can be retried on a fresh read."""


class _Statements:
    @cached_property
    def config(self):
        from databricks.sdk.config import Config

        return Config(auth_type="oauth-m2m", http_timeout_seconds=_HTTP_TIMEOUT_SECONDS, retry_timeout_seconds=1)

    @staticmethod
    def _request(host, headers, method, path, deadline, body=None):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError
        with closing(HTTPSConnection(host.hostname, host.port,
                                     timeout=min(remaining, _HTTP_TIMEOUT_SECONDS))) as connection:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("SQL request did not return a result")
            raw = response.read(_LIMIT + 1)
        if len(raw) > _LIMIT:
            raise ValueError("Oversized SQL result")
        if monotonic() >= deadline:
            raise TimeoutError
        return json.loads(raw)

    def __call__(self, warehouse, statement, parameters):
        body = json.dumps({
            "warehouse_id": warehouse, "statement": statement,
            "format": "JSON_ARRAY", "disposition": "INLINE", "row_limit": 2,
            "wait_timeout": "5s", "on_wait_timeout": "CONTINUE",
            "parameters": [{"name": k, "value": v} for k, v in parameters.items()],
        })
        started = monotonic()
        deadline = started + _SQL_WAIT_SECONDS
        operation = "update" if statement.lstrip().upper().startswith("UPDATE ") else "select"
        submissions = polls = 0
        reason = "sql_auth_unavailable"
        try:
            config = self.config
            host = urlsplit(config.host)
            if (host.scheme != "https" or not host.hostname or host.username or host.password
                    or host.path not in ("", "/") or host.query or host.fragment):
                raise ValueError("Invalid SQL service URL")
            headers = {**config.authenticate(), "Content-Type": "application/json"}
            # A SQL POST may commit before its acknowledgment is lost. This
            # transport submits once; it follows no redirects and retries no POSTs.
            if monotonic() >= deadline:
                raise TimeoutError
            reason = "sql_submit_unconfirmed"
            submissions = 1
            payload = self._request(host, headers, "POST", _API, deadline, body)
            reason = "sql_result_invalid"
            state = payload["status"]["state"]
            statement_id = payload.get("statement_id")
            if state in _PENDING_STATES:
                if not isinstance(statement_id, str) or not _STATEMENT_ID.fullmatch(statement_id):
                    raise ValueError("Missing or invalid statement ID")
                path = f"{_API}/{statement_id}"
                while state in _PENDING_STATES:
                    reason = "sql_poll_deadline"
                    if polls >= _POLL_LIMIT or monotonic() + _POLL_INTERVAL_SECONDS >= deadline:
                        raise TimeoutError
                    sleep(_POLL_INTERVAL_SECONDS)
                    if monotonic() >= deadline:
                        raise TimeoutError
                    reason = "sql_poll_unconfirmed"
                    polls += 1
                    payload = self._request(host, headers, "GET", path, deadline)
                    reason = "sql_result_invalid"
                    if payload.get("statement_id") != statement_id:
                        raise ValueError("SQL status returned a different statement ID")
                    state = payload["status"]["state"]
            if state in _TERMINAL_FAILURES:
                reason = _TERMINAL_FAILURES[state]
            if state == "FAILED" and _CONFLICT.search(payload["status"].get("error", {}).get("message", "")):
                raise _WriteConflict
            if state != "SUCCEEDED" or payload["manifest"].get("truncated"):
                raise ValueError("SQL result is not confirmed")
            result = payload["result"]
            if (result.get("next_chunk_index") is not None or result.get("next_chunk_internal_link")
                    or result.get("row_offset", 0) != 0):
                raise ValueError("Incomplete SQL result")
            rows = result["data_array"]
            level = logging.INFO if polls else logging.DEBUG
            _LOG.log(level, "Routing budget SQL operation=%s outcome=confirmed submissions=%d polls=%d elapsed_ms=%d",
                     operation, submissions, polls, round((monotonic() - started) * 1000))
            return rows
        except _WriteConflict:
            _LOG.info("Routing budget SQL operation=%s outcome=write_conflict submissions=%d polls=%d elapsed_ms=%d",
                      operation, submissions, polls, round((monotonic() - started) * 1000))
            raise
        except Exception:
            # SDK, HTTP and SQL messages can contain workspace details.
            if reason == "sql_poll_unconfirmed" and monotonic() >= deadline:
                reason = "sql_poll_deadline"
            _LOG.warning("Routing budget SQL operation=%s outcome=%s submissions=%d polls=%d elapsed_ms=%d",
                         operation, reason, submissions, polls, round((monotonic() - started) * 1000))
            raise BudgetStoreUnavailable(f"Routing budget SQL unavailable ({reason})") from None


def _nonnegative(value):
    return type(value) is int and value >= 0


def _day(value):
    return date.fromisoformat(value).isoformat() == value


def _checked_state(raw):
    state = json.loads(raw)
    if (set(state) != {"version", "allowance", "receipt", "last_clock", "strikes", "cooldown",
                       "daily", "active", "completed", "runs"}
            or type(state["version"]) is not int or state["version"] != 1
            or state["allowance"] != ALLOWANCE or state["receipt"] != EXPLORER_RECEIPT
            or not _nonnegative(state["last_clock"]) or not _nonnegative(state["cooldown"])
            or type(state["strikes"]) is not int or state["strikes"] not in (0, 1)
            or state["daily"][EXPLORER_DAY]["routine"] < 5):
        raise ValueError("Unrecognized quota state")
    for day, usage in state["daily"].items():
        if not _day(day) or not set(usage) <= ALLOCATIONS.keys() or any(
                not _nonnegative(used) or used > (100 if profile == "routine" else ALLOCATIONS[profile])
                for profile, used in usage.items()):
            raise ValueError("Invalid quota counters")
    ticks = list(state["active"].values()) + state["completed"]
    if (len(state["active"]) > 2 or len(state["completed"]) > 60
            or not all(_ID.fullmatch(token) for token in state["active"])
            or not all(_nonnegative(tick) and tick <= state["last_clock"] for tick in ticks)):
        raise ValueError("Invalid quota permits")
    for token, run in state["runs"].items():
        if (not _ID.fullmatch(token) or set(run) != {"month", "open", "remaining", "spent"}
                or not _day(run["month"] + "-01") or type(run["open"]) is not bool
                or not all(_nonnegative(run[k]) for k in ("remaining", "spent"))
                or run["remaining"] + run["spent"] > ALLOCATIONS["validation"]
                or (not run["open"] and run["remaining"])):
            raise ValueError("Invalid validation reservation")
    return state


def _monthly(state, month):
    return {profile: sum(usage.get(profile, 0) for day, usage in state["daily"].items()
                         if day.startswith(month)) for profile in ALLOCATIONS}


def _held(state, month):
    return sum(run["remaining"] for run in state["runs"].values()
               if run["month"] == month and run["open"])


class DeltaBudget:
    """Apply quota changes only after a confirmed compare-and-swap on the Delta row.

    Clock values are integer microseconds from the warehouse, shared by replicas.
    Permits never expire automatically. Recent completions and all active permits
    occupy the rate windows, even if SQL acknowledgment delayed the actual send.
    """

    def __init__(self, warehouse_id, table, *, account_scope, verified_allowance, execute=None):
        if not re.fullmatch(r"[a-fA-F0-9]{16}", warehouse_id):
            raise ValueError("Invalid routing budget warehouse")
        parts = table.split(".")
        if len(parts) != 3 or not all(_TABLE_PART.fullmatch(part) for part in parts):
            raise ValueError("Routing budget requires a three-part table name")
        if not isinstance(account_scope, str) or not account_scope.strip():
            raise ValueError("Routing budget requires an account scope")
        self.warehouse_id = warehouse_id
        self.table = ".".join(f"`{part}`" for part in parts)
        self.account_scope = account_scope
        self.verified_allowance = verified_allowance
        self._execute = _Statements() if execute is None else execute

    def _verified(self, account, product):
        return account == self.account_scope and product == PRODUCT and self.verified_allowance == ALLOWANCE

    def _read(self):
        try:
            rows = self._execute(self.warehouse_id, f"""
                SELECT account_scope, product, revision, quota_state, unix_micros(current_timestamp())
                FROM {self.table} LIMIT 2
            """, {})
            (account, product, revision, raw, micros), = rows
            if not self._verified(account, product) or not _ID.fullmatch(revision):
                raise ValueError("Wrong quota scope")
            tick = int(micros)
            state = _checked_state(raw)
            day = datetime.fromtimestamp(tick // 1000000, timezone.utc).date().isoformat()
            if tick < state["last_clock"]:
                raise BudgetStoreUnavailable("Routing budget clock regressed")
            return revision, state, tick, day
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError, _WriteConflict):
            raise BudgetStoreUnavailable("Routing budget row invalid or missing") from None

    def _change(self, transition):
        for _ in range(3):
            revision, state, tick, day = self._read()
            result, changed = transition(state, tick, day)
            if not changed:
                return result
            state["last_clock"] = tick
            state["completed"] = [end for end in state["completed"] if end > tick - 60000000]
            encoded = json.dumps(state, separators=(",", ":"), allow_nan=False)
            if len(encoded) > _LIMIT // 2:
                raise BudgetStoreUnavailable("Routing budget state exceeds its supported size")
            try:
                rows = self._execute(self.warehouse_id, f"""
                    UPDATE {self.table}
                    SET revision = :new_revision, quota_state = :quota_state
                    WHERE account_scope = :account AND product = :product AND revision = :revision
                      AND unix_micros(current_timestamp()) DIV 86400000000 = CAST(:epoch_day AS BIGINT)
                """, {"new_revision": uuid.uuid4().hex, "quota_state": encoded,
                      "account": self.account_scope, "product": PRODUCT, "revision": revision,
                      "epoch_day": str(tick // 86400000000)})
            except _WriteConflict:
                continue
            if rows == [["1"]]:
                return result
            if rows != [["0"]]:
                raise BudgetStoreUnavailable("Routing budget write was not confirmed")
        raise BudgetStoreUnavailable("Routing budget exceeded its conflict retry limit")

    def acquire(self, account, product, now, *, profile="routine", daily_limit=100, monthly_limit=500, run_id=None):
        if not self._verified(account, product):
            return Admission(reason="unverified_allocation")
        if (profile not in ALLOCATIONS or type(daily_limit) is not int or type(monthly_limit) is not int
                or not 1 <= monthly_limit <= ALLOCATIONS[profile]
                or not 1 <= daily_limit <= (100 if profile == "routine" else ALLOCATIONS[profile])
                or (run_id is not None and (profile != "validation" or not isinstance(run_id, str)))):
            return Admission(reason="invalid_operator_budget")

        def admit(state, tick, day):
            month = day[:7]
            usage = _monthly(state, month)
            daily = state["daily"].setdefault(day, {})
            if daily.get(profile, 0) >= daily_limit:
                return Admission(reason="daily_call_budget_exceeded"), False
            if usage[profile] >= monthly_limit:
                return Admission(reason="monthly_call_budget_exceeded"), False
            if sum(usage.values()) >= ALLOWANCE - SAFETY_MARGIN:
                return Admission(reason="protected_allowance_exhausted"), False
            run = None
            if profile == "validation":
                run = state["runs"].get(run_id)
                if not run or not run["open"]:
                    return Admission(reason="validation_reservation_required"), False
                if run["month"] != month:
                    return Admission(reason="reservation_month_mismatch"), False
                if not run["remaining"]:
                    return Admission(reason="reserved_budget_exhausted"), False
            if state["cooldown"] > tick:
                return Admission(reason="shared_provider_cooldown", retry_after=(state["cooldown"] - tick) / 1000000), False
            active = len(state["active"])
            if active >= 2 or (active and state["strikes"]):
                # When a strike already exists, wait for a pending response that
                # could trigger cooldown before issuing any additional permits.
                return Admission(reason="local_inflight_limit", retry_after=.25), False
            for window, cap in ((1000000, 2), (60000000, 60)):
                ends = sorted(end for end in state["completed"] if end > tick - window)
                if len(ends) + active >= cap:
                    delay = (ends[active - cap] + window - tick) / 1000000
                    return Admission(reason="local_rate_limited", retry_after=max(.001, delay)), False
            token = uuid.uuid4().hex
            state["active"][token] = tick
            daily[profile] = daily.get(profile, 0) + 1
            if run is not None:
                run["remaining"] -= 1
                run["spent"] += 1
            return Admission(token=token), True

        return self._change(admit)

    def finish(self, token, now, *, quota=False, success=False):
        def finish_attempt(state, tick, _day):
            if state["active"].pop(token, None) is None:
                return None, False
            state["completed"].append(tick)
            if quota and state["strikes"]:
                state["cooldown"] = max(state["cooldown"], tick + 30000000)
                state["strikes"] = 0
            elif quota:
                state["strikes"] = 1
            elif success:
                state["strikes"] = 0
            return None, True

        self._change(finish_attempt)

    def reserve_run(self, account, product, now, calls):
        if type(calls) is not int or not 1 <= calls <= ALLOCATIONS["validation"]:
            raise ValueError("Reserve between 1 and 3000 worst-case calls")
        if not self._verified(account, product):
            return {"reason": "unverified_allocation", "run_id": None}

        def reserve(state, _tick, day):
            month = day[:7]
            used = _monthly(state, month)["validation"]
            if calls + used + _held(state, month) > ALLOCATIONS["validation"]:
                return {"reason": "validation_allocation_exhausted", "run_id": None}, False
            token = uuid.uuid4().hex
            state["runs"][token] = {"month": month, "open": True, "remaining": calls, "spent": 0}
            return {"reason": None, "run_id": token, "reserved_calls": calls, "month": month}, True

        return self._change(reserve)

    def release_run(self, account, product, run_id):
        if not self._verified(account, product):
            return {"reason": "unverified_allocation"}

        def release(state, _tick, _day):
            run = state["runs"].get(run_id)
            if run is None:
                return {"reason": "unknown_reservation"}, False
            result = {"released": run["remaining"], "spent": run["spent"]}
            changed = run["open"]
            run.update(remaining=0, open=False)
            return result, changed

        return self._change(release)

    def status(self, account, product, now):
        if not self._verified(account, product):
            return {"reason": "unverified_allocation"}
        _, state, _, day = self._read()
        month = day[:7]
        used = _monthly(state, month)
        held = _held(state, month)
        available = {p: max(0, limit - used[p] - (held if p == "validation" else 0))
                     for p, limit in ALLOCATIONS.items()}
        return {"reason": None, "month": month, "verified_allowance": ALLOWANCE,
                "used": sum(used.values()), "used_by_profile": used,
                "routine_remaining": available["routine"],
                "routine_day_remaining": max(0, 100 - state["daily"].get(day, {}).get("routine", 0)),
                "reserved": {"demo_remaining": available["demo"],
                             "validation_remaining": ALLOCATIONS["validation"] - used["validation"],
                             "validation_active_runs": held, "safety_margin": SAFETY_MARGIN},
                "available": available, "unallocated_do_not_use": ALLOWANCE - sum(ALLOCATIONS.values()) - SAFETY_MARGIN,
                "active": len(state["active"])}
