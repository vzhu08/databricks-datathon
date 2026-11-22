from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.travel.budget import ALLOWANCE, EXPLORER_DAY, PRODUCT, SQLiteBudget, dry_run

NOW = datetime(2026, 11, 22, 1, tzinfo=timezone.utc)


def process_admit(args):
    path, limit, monthly, tick = args
    b = SQLiteBudget(path, verified_allowance=ALLOWANCE)
    return b.acquire("account", PRODUCT, tick, daily_limit=limit, monthly_limit=monthly)


def process_reserve(path):
    return SQLiteBudget(path, verified_allowance=ALLOWANCE).reserve_run("account", PRODUCT, NOW, 400)


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "usage.sqlite"
        self.budget = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)

    def status(self, now=NOW):
        return self.budget.status("account", PRODUCT, now)

    def acquire(self, now=NOW, **kwargs):
        return self.budget.acquire("account", PRODUCT, now, **kwargs)

    def test_multiprocess_global_inflight_rate_limits_and_restart_preserve_permits(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(process_admit, [(str(self.path), 100, 500, NOW)] * 12))
        admitted = [r for r in results if r.token]
        self.assertEqual(len(admitted), 2)
        self.assertEqual(self.status()["used"], 7)  # five Explorer + two attempts
        restarted = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        self.assertEqual(restarted.acquire("account", PRODUCT, NOW + timedelta(seconds=1)).reason, "local_inflight_limit")
        for r in admitted:
            restarted.finish(r.token, NOW, success=True)
        self.assertEqual(self.acquire(NOW + timedelta(seconds=1)).reason, None)
        self.assertEqual(self.acquire(NOW + timedelta(seconds=1)).reason, None)
        self.assertEqual(self.acquire(NOW + timedelta(seconds=1)).reason, "local_inflight_limit")
        self.assertEqual(self.status(NOW + timedelta(seconds=1))["used"], 9)

    def test_concurrent_processes_cannot_overspend_daily_or_monthly_budget(self):
        for daily, monthly, reason in [(6, 500, "daily_call_budget_exceeded"), (100, 6, "monthly_call_budget_exceeded")]:
            path = str(Path(self.directory.name) / (reason + ".sqlite"))
            with ProcessPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(process_admit, [(path, daily, monthly, NOW)] * 10))
            self.assertEqual(sum(bool(r.token) for r in results), 1)
            self.assertEqual(sum(r.reason == reason for r in results), 9)
            self.assertEqual(SQLiteBudget(path, verified_allowance=ALLOWANCE).status("account", PRODUCT, NOW)["used"], 6)

    def test_rolling_second_and_minute_include_finished_attempts(self):
        for second in range(30):
            now = NOW + timedelta(seconds=second)
            for _ in range(2):
                permit = self.acquire(now)
                self.assertIsNotNone(permit.token)
                self.budget.finish(permit.token, now)
            refused = self.acquire(now)
            self.assertEqual(refused.reason, "local_rate_limited")
            self.assertEqual(refused.retry_after, 1)
        refused = self.acquire(NOW + timedelta(seconds=30))
        self.assertEqual(refused.reason, "local_rate_limited")
        self.assertEqual(refused.retry_after, 30)
        self.assertIsNotNone(self.acquire(NOW + timedelta(seconds=60)).token)
        self.assertEqual(self.status(NOW + timedelta(seconds=60))["used"], 66)

    def test_two_429s_create_shared_durable_cooldown_and_do_not_refund(self):
        for _ in range(2):
            permit = self.acquire()
            self.budget.finish(permit.token, NOW, quota=True)
        restarted = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        result = restarted.acquire("account", PRODUCT, NOW + timedelta(seconds=29))
        self.assertEqual((result.reason, result.retry_after), ("shared_provider_cooldown", 1))
        self.assertIsNotNone(restarted.acquire("account", PRODUCT, NOW + timedelta(seconds=30)).token)
        self.assertEqual(self.status(NOW + timedelta(seconds=30))["used"], 8)

    def test_five_attempt_receipt_is_idempotent_across_processes_restarts_actual_utc_day(self):
        for _ in range(3):
            self.assertEqual(SQLiteBudget(self.path, verified_allowance=ALLOWANCE).status("account", PRODUCT, NOW)["used"], 5)
        with sqlite3.connect(str(self.path)) as c:
            days = c.execute("SELECT period,used FROM usage WHERE kind='day'").fetchall()
            self.assertEqual(days, [(EXPLORER_DAY, 5)])
            self.assertEqual(c.execute("SELECT count(*) FROM receipts").fetchone()[0], 1)
            for table in ("scopes", "usage", "receipts", "attempts", "reservations"):
                columns = [r[1] for r in c.execute("PRAGMA table_info(" + table + ")")]
                self.assertFalse(set(columns) & {"api_key", "latitude", "longitude", "response", "origin", "destination"})
        self.assertEqual(self.status()["routine_day_remaining"], 95)

    def test_atomic_finite_validation_reservations_preserve_demo_and_safety(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(process_reserve, [str(self.path)] * 10))
        accepted = [r for r in results if r["run_id"]]
        self.assertEqual(len(accepted), 7)
        usage = self.status()
        self.assertEqual(usage["reserved"]["validation_active_runs"], 2800)
        self.assertEqual(usage["available"]["validation"], 200)
        self.assertEqual(usage["reserved"]["demo_remaining"], 2000)
        self.assertEqual(usage["reserved"]["safety_margin"], 1000)
        self.assertEqual(usage["unallocated_do_not_use"], 13500)
        run_id = accepted[0]["run_id"]
        permit = self.acquire(profile="validation", daily_limit=3000, monthly_limit=3000, run_id=run_id)
        self.assertIsNotNone(permit.token)
        self.budget.finish(permit.token, NOW)
        released = self.budget.release_run("account", PRODUCT, run_id)
        self.assertEqual(released, {"released": 399, "spent": 1})
        self.assertEqual(self.budget.release_run("account", PRODUCT, run_id), {"released": 0, "spent": 1})
        self.assertEqual(self.status()["used"], 6)
        self.assertEqual(self.status()["available"]["validation"], 599)
        self.assertEqual(self.acquire(profile="validation", run_id=run_id).reason, "validation_reservation_required")

    def test_utc_day_month_rollover_and_reservation_cannot_cross_month(self):
        run = self.budget.reserve_run("account", PRODUCT, NOW, 1)["run_id"]
        start = datetime(2026, 11, 30, 23, 59, 58, tzinfo=timezone.utc)
        permit = self.acquire(start, daily_limit=1)
        self.budget.finish(permit.token, start)
        self.assertEqual(self.acquire(start, daily_limit=1).reason, "daily_call_budget_exceeded")
        december = datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(self.status(december)["used"], 0)
        self.assertEqual(self.status(december)["reserved"]["validation_active_runs"], 0)
        self.assertEqual(self.acquire(december, profile="validation", run_id=run).reason, "reservation_month_mismatch")
        self.assertIsNotNone(self.acquire(december, daily_limit=1).token)
        self.assertEqual(self.acquire(NOW).reason, "local_clock_regressed")

    def test_unknown_changed_allocation_and_invalid_profiles_fail_closed(self):
        for allowance in (None, 0, 19999, 20001):
            b = SQLiteBudget(self.path, verified_allowance=allowance)
            self.assertEqual(b.acquire("account", PRODUCT, NOW).reason, "unverified_allocation")
        self.assertEqual(self.budget.acquire("account", "matrix", NOW).reason, "unverified_allocation")
        for kwargs in [dict(profile="public"), dict(daily_limit=101), dict(monthly_limit=501), dict(run_id="unapproved")]:
            self.assertEqual(self.acquire(**kwargs).reason, "invalid_operator_budget")
        self.assertEqual(self.acquire(profile="validation").reason, "validation_reservation_required")
        self.assertEqual(self.status()["used"], 5)

    def test_zero_io_dry_run_and_operator_absolute_path(self):
        with patch("http.client.HTTPSConnection", side_effect=AssertionError("must stay offline")):
            self.assertEqual(dry_run(25), {"candidate_count": 25, "max_retries": 1, "worst_case_calls": 50, "provider_calls": 0})
        self.assertFalse(self.path.exists())
        for count in (26, -1, True):
            with self.assertRaises(ValueError):
                dry_run(count)
        with self.assertRaises(ValueError):
            SQLiteBudget("unconfigured.sqlite")


if __name__ == "__main__":
    unittest.main()
