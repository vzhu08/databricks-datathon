"""Single-host atomic TomTom admission ledger. Stores counters, never route content."""

import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ALLOWANCE = 20000
ALLOCATIONS = {"routine": 500, "demo": 2000, "validation": 3000}
SAFETY_MARGIN = 1000
PRODUCT = "tomtom_maps_v1"
EXPLORER_RECEIPT = "jaipur-explorer-2026-11-22-five-attempts"
EXPLORER_DAY = "2026-11-22"


@dataclass(frozen=True)
class Admission:
    token: str = None
    reason: str = None
    retry_after: float = 0.0


def utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("The budget clock must be timezone aware")
    return value.astimezone(timezone.utc)


def dry_run(candidate_count, retries=1):
    """Pure worst-case calculation, with no I/O, ledger mutation or HTTP."""
    if type(candidate_count) is not int or not 0 <= candidate_count <= 25 or type(retries) is not int or not 0 <= retries <= 1:
        raise ValueError("A search supports at most 25 campuses and one retry")
    return {"candidate_count": candidate_count, "max_retries": retries,
            "worst_case_calls": candidate_count * (1 + retries), "provider_calls": 0}


class SQLiteBudget:
    """All keys and processes on ONE host must use this same durable database.

    Multi-host live operation requires a shared atomic store, not separate files.
    In-flight permits have no automatic expiry: after a crash, an operator must
    confirm that the old requests ended before releasing their tokens. A restart
    cannot accidentally free a still-running call or restore spent attempts.
    """
    def __init__(self, path, *, verified_allowance=None):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("The routing budget file must use an absolute path")
        self.verified_allowance = verified_allowance

    @contextmanager
    def _transaction(self):
        with closing(sqlite3.connect(str(self.path), timeout=1)) as c, c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS scopes (
                    account TEXT, product TEXT, allowance INTEGER, last_clock REAL DEFAULT 0,
                    strikes INTEGER DEFAULT 0, cooldown REAL DEFAULT 0, PRIMARY KEY(account,product));
                CREATE TABLE IF NOT EXISTS usage (
                    account TEXT, product TEXT, profile TEXT, kind TEXT, period TEXT, used INTEGER,
                    PRIMARY KEY(account,product,profile,kind,period));
                CREATE TABLE IF NOT EXISTS receipts (
                    account TEXT, product TEXT, receipt TEXT, PRIMARY KEY(account,product,receipt));
                CREATE TABLE IF NOT EXISTS attempts (
                    token TEXT PRIMARY KEY, account TEXT, product TEXT, profile TEXT, started REAL,
                    active INTEGER, run_id TEXT);
                CREATE INDEX IF NOT EXISTS recent_attempts ON attempts(account,product,started);
                CREATE TABLE IF NOT EXISTS reservations (
                    run_id TEXT PRIMARY KEY, account TEXT, product TEXT, month TEXT,
                    total INTEGER, remaining INTEGER, spent INTEGER, state TEXT);
            """)
            c.execute("BEGIN IMMEDIATE")
            yield c

    def _scope(self, c, account, product, now):
        if self.verified_allowance != ALLOWANCE or product != PRODUCT or not isinstance(account, str) or not account.strip():
            return "unverified_allocation"
        c.execute("INSERT OR IGNORE INTO scopes(account,product,allowance) VALUES(?,?,?)", (account, product, ALLOWANCE))
        allowance, last = c.execute("SELECT allowance,last_clock FROM scopes WHERE account=? AND product=?", (account, product)).fetchone()
        if allowance != ALLOWANCE:
            return "unverified_allocation"
        # Never roll counters/rate windows backwards after a clock correction.
        if now.timestamp() < last - 1:
            return "local_clock_regressed"
        c.execute("UPDATE scopes SET last_clock=? WHERE account=? AND product=?", (max(last, now.timestamp()), account, product))
        inserted = c.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?)", (account, product, EXPLORER_RECEIPT)).rowcount
        if inserted:
            self._charge(c, account, product, "routine", EXPLORER_DAY, 5)
        return None

    @staticmethod
    def _charge(c, account, product, profile, day, calls):
        for kind, period in (("day", day), ("month", day[:7])):
            c.execute("INSERT INTO usage VALUES(?,?,?,?,?,?) ON CONFLICT(account,product,profile,kind,period) "
                      "DO UPDATE SET used=used+excluded.used", (account, product, profile, kind, period, calls))

    @staticmethod
    def _used(c, account, product, profile, kind, period):
        row = c.execute("SELECT used FROM usage WHERE account=? AND product=? AND profile=? AND kind=? AND period=?",
                        (account, product, profile, kind, period)).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _reserved(c, account, product, month):
        return c.execute("SELECT coalesce(sum(remaining),0) FROM reservations WHERE account=? AND product=? AND month=? AND state='open'",
                         (account, product, month)).fetchone()[0]

    def acquire(self, account, product, now, *, profile="routine", daily_limit=100, monthly_limit=500, run_id=None):
        now = utc(now)
        day, month, tick = now.date().isoformat(), now.strftime("%Y-%m"), now.timestamp()
        if (profile not in ALLOCATIONS or type(daily_limit) is not int or type(monthly_limit) is not int or
                not 1 <= monthly_limit <= ALLOCATIONS[profile] or
                not 1 <= daily_limit <= (100 if profile == "routine" else ALLOCATIONS[profile])):
            return Admission(reason="invalid_operator_budget")
        with self._transaction() as c:
            refusal = self._scope(c, account, product, now)
            if refusal:
                return Admission(reason=refusal)
            if self._used(c, account, product, profile, "day", day) >= daily_limit:
                return Admission(reason="daily_call_budget_exceeded")
            if self._used(c, account, product, profile, "month", month) >= monthly_limit:
                return Admission(reason="monthly_call_budget_exceeded")
            total = sum(self._used(c, account, product, p, "month", month) for p in ALLOCATIONS)
            if total >= ALLOWANCE - SAFETY_MARGIN:
                return Admission(reason="protected_allowance_exhausted")
            if profile == "validation":
                run = c.execute("SELECT month,remaining,state FROM reservations WHERE run_id=? AND account=? AND product=?",
                                (run_id, account, product)).fetchone()
                if not run or run[2] != "open":
                    return Admission(reason="validation_reservation_required")
                if run[0] != month:
                    return Admission(reason="reservation_month_mismatch")
                if run[1] <= 0:
                    return Admission(reason="reserved_budget_exhausted")
            elif run_id is not None:
                return Admission(reason="invalid_operator_budget")
            cooldown = c.execute("SELECT cooldown FROM scopes WHERE account=? AND product=?", (account, product)).fetchone()[0]
            if cooldown > tick:
                return Admission(reason="shared_provider_cooldown", retry_after=cooldown - tick)
            active = c.execute("SELECT count(*) FROM attempts WHERE account=? AND product=? AND active=1", (account, product)).fetchone()[0]
            if active >= 2:
                return Admission(reason="local_inflight_limit", retry_after=.05)
            for window, cap in ((1, 2), (60, 60)):
                starts = [r[0] for r in c.execute("SELECT started FROM attempts WHERE account=? AND product=? AND started>? ORDER BY started",
                                                (account, product, tick - window))]
                if len(starts) >= cap:
                    return Admission(reason="local_rate_limited", retry_after=max(.001, starts[-cap] + window - tick))
            token = uuid.uuid4().hex
            c.execute("INSERT INTO attempts VALUES(?,?,?,?,?,1,?)", (token, account, product, profile, tick, run_id))
            self._charge(c, account, product, profile, day, 1)
            if profile == "validation":
                c.execute("UPDATE reservations SET remaining=remaining-1,spent=spent+1 WHERE run_id=?", (run_id,))
            return Admission(token=token)

    def finish(self, token, now, *, quota=False, success=False):
        """Release exactly once; repeated 429s cause a shared, durable 30s cooldown."""
        tick = utc(now).timestamp()
        with self._transaction() as c:
            row = c.execute("SELECT account,product,active FROM attempts WHERE token=?", (token,)).fetchone()
            if not row or not row[2]:
                return
            account, product, _ = row
            c.execute("UPDATE attempts SET active=0 WHERE token=?", (token,))
            strikes, cooldown = c.execute("SELECT strikes,cooldown FROM scopes WHERE account=? AND product=?", (account, product)).fetchone()
            if quota:
                strikes += 1
                if strikes >= 2:
                    cooldown, strikes = max(cooldown, tick + 30), 0
            elif success:
                strikes = 0
            c.execute("UPDATE scopes SET strikes=?,cooldown=? WHERE account=? AND product=?", (strikes, cooldown, account, product))

    def reserve_run(self, account, product, now, calls):
        """Trusted operator API: reserve a finite validation run atomically."""
        if type(calls) is not int or not 1 <= calls <= ALLOCATIONS["validation"]:
            raise ValueError("Reserve between 1 and 3000 worst-case calls")
        now = utc(now)
        month = now.strftime("%Y-%m")
        with self._transaction() as c:
            reason = self._scope(c, account, product, now)
            if reason:
                return {"reason": reason, "run_id": None}
            used = self._used(c, account, product, "validation", "month", month)
            if calls + used + self._reserved(c, account, product, month) > ALLOCATIONS["validation"]:
                return {"reason": "validation_allocation_exhausted", "run_id": None}
            run_id = uuid.uuid4().hex
            c.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,0,'open')", (run_id, account, product, month, calls, calls))
            return {"reason": None, "run_id": run_id, "reserved_calls": calls, "month": month}

    def release_run(self, account, product, run_id):
        """Release unsent reservations only; spent attempts remain charged."""
        with self._transaction() as c:
            row = c.execute("SELECT remaining,spent,state FROM reservations WHERE run_id=? AND account=? AND product=?",
                            (run_id, account, product)).fetchone()
            if not row:
                return {"reason": "unknown_reservation"}
            c.execute("UPDATE reservations SET remaining=0,state='closed' WHERE run_id=?", (run_id,))
            return {"released": row[0], "spent": row[1]}

    def status(self, account, product, now):
        now = utc(now)
        month, day = now.strftime("%Y-%m"), now.date().isoformat()
        with self._transaction() as c:
            reason = self._scope(c, account, product, now)
            if reason:
                return {"reason": reason}
            used = {p: self._used(c, account, product, p, "month", month) for p in ALLOCATIONS}
            held = self._reserved(c, account, product, month)
            available = {p: max(0, limit - used[p] - (held if p == "validation" else 0)) for p, limit in ALLOCATIONS.items()}
            return {"reason": None, "month": month, "verified_allowance": ALLOWANCE,
                    "used": sum(used.values()), "used_by_profile": used,
                    "routine_remaining": available["routine"],
                    "routine_day_remaining": max(0, 100 - self._used(c, account, product, "routine", "day", day)),
                    "reserved": {"demo_remaining": available["demo"],
                                 "validation_remaining": ALLOCATIONS["validation"] - used["validation"],
                                 "validation_active_runs": held, "safety_margin": SAFETY_MARGIN},
                    "available": available, "unallocated_do_not_use": ALLOWANCE - sum(ALLOCATIONS.values()) - SAFETY_MARGIN,
                    "active": c.execute("SELECT count(*) FROM attempts WHERE account=? AND product=? AND active=1", (account, product)).fetchone()[0]}
