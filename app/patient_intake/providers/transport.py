"""Single-attempt JSON exchange for a server-configured provider.

The adapter owns host, path, headers and clinical schema validation. This module
never selects a host, loads secrets, follows redirects, logs or retries.
"""

import json
from dataclasses import dataclass, field
from http.client import HTTPException, HTTPSConnection
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
from typing import Optional

MAX_REQUEST = 16_384
MAX_RESPONSE = 65_536


@dataclass(frozen=True)
class Reply:
    status: str
    # Even an unvalidated success may contain sensitive information.
    data: Optional[dict] = field(default=None, repr=False)


class Budget:
    """Share the deployment instance across encounters and keep one per encounter."""

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
        data = response.read(MAX_RESPONSE + 1) if response.status == 200 or response.status == 201 else b""
        return response.status, content_type, data
    finally:
        conn.close()


def _unique_dict(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate key")
    return obj


def _finite_number(value):
    import math
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def _decode(status, media, raw):
    if status in (401, 403):
        return Reply("access_denied")
    if status == 429:
        return Reply("rate_limited")
    if status not in (200, 201):
        return Reply("provider_error")
    if media != "application/json" or len(raw) > MAX_RESPONSE:
        return Reply("invalid_response")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_dict,
                           parse_constant=_finite_number, parse_float=_finite_number)
    except (ValueError, RecursionError):
        return Reply("invalid_response")
    return Reply("received", value) if isinstance(value, dict) else Reply("invalid_response")


class Transport:
    """One shared instance per server process. A timed-out worker retains its slot."""

    def __init__(self, *, host, headers, attempts=0, exchange=_https):
        self._host = host
        self._headers = {**headers, "Content-Type": "application/json"}
        self._exchange = exchange
        self._budget = Budget(attempts)
        self._slots = BoundedSemaphore(2)

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
        # Charge conservatively. No refunds for unknown delivery or quota exhaustion.
        if not encounter.take() or not self._budget.take():
            self._slots.release()
            return Reply("budget_exhausted")
        result = Queue(maxsize=1)

        def run():
            try:
                response = self._exchange(self._host, method, path, self._headers, body, timeout)
                reply = _decode(*response)
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
