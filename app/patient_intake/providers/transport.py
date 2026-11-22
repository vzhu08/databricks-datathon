"""Single-attempt JSON exchange for a server-configured provider.

The adapter owns host, path, headers and clinical schema validation. This module
never selects a host, loads secrets, follows redirects, logs or retries.
"""

import json
import math
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field
from http.client import HTTPException, HTTPSConnection
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
from time import monotonic, time
from typing import Optional

MAX_REQUEST = 16_384
MAX_RESPONSE = 65_536
COOLDOWN_FALLBACK = 60
_RATE_HEADERS = ('Retry-After', 'RateLimit-Limit', 'RateLimit-Remaining', 'RateLimit-Reset')


@dataclass(frozen=True)
class RateMetadata:
    retry_after_seconds: Optional[int] = None
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_seconds: Optional[int] = None


@dataclass(frozen=True)
class Reply:
    status: str
    # Even an unvalidated success may contain sensitive information.
    data: Optional[dict] = field(default=None, repr=False)
    rate: RateMetadata = field(default_factory=RateMetadata)


class Budget:
    """Share one process budget across encounters and keep one per encounter."""

    def __init__(self, attempts):
        if type(attempts) is not int or attempts < 0:
            raise ValueError("invalid attempt limit")
        self._remaining = attempts
        self._lock = Lock()

    def take(self):
        with self._lock:
            if not self._remaining:
                return False
            self._remaining -= 1
            return True


def _https(host, method, path, headers, body, timeout):
    conn = HTTPSConnection(host, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        content_type = response.getheader("Content-Type", "").split(";")[0].strip().lower()
        data = response.read(MAX_RESPONSE + 1) if response.status in (200, 201) else b""
        return response.status, content_type, data, {key: response.getheader(key) for key in _RATE_HEADERS}
    finally:
        conn.close()


def _unique_dict(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate key")
    return obj


def _finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def _nonnegative_int(value):
    if isinstance(value, str) and 1 <= len(value) <= 10 and value.isascii() and value.isdecimal():
        return int(value)
    return None


def _retry_after(value):
    seconds = _nonnegative_int(value)
    if seconds is not None:
        return seconds
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is not None:
            return max(0, math.ceil(stamp.timestamp() - time()))
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _rate_metadata(headers):
    return RateMetadata(
        retry_after_seconds=_retry_after(headers.get("Retry-After")),
        limit=_nonnegative_int(headers.get("RateLimit-Limit")),
        remaining=_nonnegative_int(headers.get("RateLimit-Remaining")),
        reset_seconds=_nonnegative_int(headers.get("RateLimit-Reset")),
    )


def _decode(status, media, raw, rate):
    if status in (401, 403):
        return Reply("access_denied", rate=rate)
    if status == 429:
        return Reply("rate_limited", rate=rate)
    if status == 204:
        return Reply("empty" if not raw else "invalid_response", rate=rate)
    if status not in (200, 201):
        return Reply("provider_error", rate=rate)
    if media != "application/json" or len(raw) > MAX_RESPONSE:
        return Reply("invalid_response", rate=rate)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_dict,
                           parse_constant=_finite_number, parse_float=_finite_number)
    except (ValueError, RecursionError):
        return Reply("invalid_response", rate=rate)
    return Reply("received", value, rate) if isinstance(value, dict) else Reply("invalid_response", rate=rate)


class Transport:
    """One shared instance per server process. A timed-out worker retains its slot."""

    def __init__(self, *, host, headers, attempts=0, exchange=_https, clock=monotonic):
        self._host = host
        self._headers = {**headers, "Content-Type": "application/json"}
        self._exchange = exchange
        self._budget = Budget(attempts)
        self._slots = BoundedSemaphore(2)
        self._clock = clock
        self._gate = Lock()
        self._resume_at = 0

    def request(self, method, path, *, payload=None, encounter, timeout=5):
        # The adapter constructs paths from its own endpoints and validated opaque IDs.
        if (method not in ("POST", "GET") or not isinstance(path, str)
                or not path.startswith("/") or path.startswith("//")
                or "?" in path or "#" in path or (method == "GET" and payload is not None)
                or type(timeout) not in (int, float) or not 0 < timeout <= 10):
            return Reply("invalid_request")
        try:
            body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        except (TypeError, ValueError, RecursionError):
            return Reply("invalid_request")
        if body is not None and len(body) > MAX_REQUEST:
            return Reply("invalid_request")
        if not self._slots.acquire(blocking=False):
            return Reply("busy")
        with self._gate:
            remaining = math.ceil(self._resume_at - self._clock())
            if remaining > 0:
                self._slots.release()
                return Reply("rate_limited", rate=RateMetadata(retry_after_seconds=remaining))
            # Charge conservatively. No refunds for unknown delivery or quota exhaustion.
            if not encounter.take() or not self._budget.take():
                self._slots.release()
                return Reply("budget_exhausted")
        result = Queue(maxsize=1)

        def run():
            try:
                status, media, raw, headers = self._exchange(
                    self._host, method, path, self._headers, body, timeout)
                rate = _rate_metadata(headers)
                if status == 429 or rate.remaining == 0:
                    delay = max(COOLDOWN_FALLBACK, rate.retry_after_seconds or 0, rate.reset_seconds or 0)
                    with self._gate:
                        self._resume_at = max(self._resume_at, self._clock() + delay)
                reply = _decode(status, media, raw, rate)
            except TimeoutError:
                reply = Reply("timeout")
            except (OSError, HTTPException):
                reply = Reply("unavailable")
            except Exception:
                # Vendor/decoder exceptions can echo credentials and patient text.
                reply = Reply("unavailable")
            finally:
                self._slots.release()
            result.put_nowait(reply)

        try:
            Thread(target=run, daemon=True).start()
        except RuntimeError:
            self._slots.release()
            return Reply("unavailable")
        try:
            return result.get(timeout=timeout)
        except Empty:
            return Reply("timeout")
