import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from unittest.mock import Mock, patch

from app.travel.budget import ALLOWANCE, EXPLORER_DAY, EXPLORER_RECEIPT, PRODUCT
from app.travel.delta_budget import BudgetStoreUnavailable, DeltaBudget, _Statements, _WriteConflict
from tests.travel.helpers import client, route

ACCOUNT = "synthetic-account"
WAREHOUSE = "0000000000000000"
TABLE = "catalog.schema.ledger"
SCOPE = (ACCOUNT, PRODUCT)
EXPLORER = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)


class StatementFixture:
    """Fake SQL transport with atomic revision checks and independent readers."""

    def __init__(self):
        self.now = EXPLORER
        self.state = {
            "version": 1, "allowance": ALLOWANCE, "receipt": EXPLORER_RECEIPT,
            "last_clock": 0, "strikes": 0, "cooldown": 0,
            "daily": {EXPLORER_DAY: {"routine": 5}},
            "active": {}, "completed": [], "runs": {},
        }
        self.lock = Lock()
        self.revision = "0" * 32
        self.written = self.missed = 0
        self.first_two_reads = None
        self.reads = 0
        self.write_error = None
        self.read_error = None
        self.change_at_update = timedelta(0)

    def __call__(self, warehouse, statement, params):
        with self.lock:
            if statement.lstrip().startswith("UPDATE"):
                self.now += self.change_at_update
                self.change_at_update = timedelta(0)
                if (params["revision"] != self.revision or
                        params["epoch_day"] != str(int(self.now.timestamp()) // 86400)):
                    self.missed += 1
                    return [["0"]]
                if self.write_error == "explicit_conflict":
                    self.write_error = None
                    raise _WriteConflict
                if self.write_error == "before_commit":
                    raise BudgetStoreUnavailable("write unavailable")
                self.revision = params["new_revision"]
                self.state = json.loads(params["quota_state"])
                self.written += 1
                if self.write_error == "after_commit":
                    raise BudgetStoreUnavailable("write acknowledgement lost")
                return [["1"]]
            if self.read_error:
                raise BudgetStoreUnavailable("read unavailable")
            self.reads += 1
            barrier = self.first_two_reads if self.reads <= 2 else None
            rows = [[*SCOPE, self.revision, json.dumps(self.state),
                     str(int(self.now.timestamp() * 1000000))]] if self.state else []
        if barrier:
            barrier.wait(timeout=3)
        return rows


class DeltaBudgetTests(unittest.TestCase):
    def setUp(self):
        self.sql = StatementFixture()
        self.budget = self.new_client()

    def new_client(self):
        return DeltaBudget(WAREHOUSE, TABLE, account_scope=ACCOUNT,
                           verified_allowance=ALLOWANCE, execute=self.sql)

    def acquire(self, ledger=None, **kwargs):
        return (ledger or self.budget).acquire(*SCOPE, self.sql.now, **kwargs)

    def status(self, ledger=None):
        return (ledger or self.budget).status(*SCOPE, self.sql.now)

    def adapter(self, send):
        adapter = client(send, rate_wait_seconds=0, max_retries=0)
        adapter.budget = self.budget
        adapter.clock = lambda: self.sql.now
        self.addCleanup(adapter.close)
        return adapter

    def test_last_daily_call_is_charged_once_when_clients_race(self):
        contenders = (self.budget, self.new_client())
        self.sql.first_two_reads = Barrier(2)
        with ThreadPoolExecutor(2) as worker:
            a, b = worker.map(lambda budget: self.acquire(budget, daily_limit=6), contenders)
        self.assertCountEqual([a.reason, b.reason], [None, "daily_call_budget_exceeded"])
        self.assertEqual(sum(bool(item.token) for item in (a, b)), 1)
        self.assertEqual(self.sql.missed, 1)
        fresh = self.new_client()
        self.assertEqual(self.status(fresh)["used"], 6)
        self.assertEqual(self.status(fresh)["active"], 1)
        fresh.finish(a.token or b.token, self.sql.now)
        fresh.finish(a.token or b.token, self.sql.now)
        self.assertEqual(self.status(fresh)["active"], 0)
        self.assertEqual(self.status(fresh)["used"], 6)

    def test_explicit_delta_conflict_retries_and_two_permits_are_shared(self):
        self.sql.write_error = "explicit_conflict"
        first = self.acquire()
        self.assertTrue(first.token)
        self.assertTrue(self.acquire(self.new_client()).token)
        self.assertEqual(self.acquire(self.new_client()).reason, "local_inflight_limit")
        self.assertEqual(self.sql.written, 2)
        self.assertEqual(self.status()["used"], 7)

    def test_finish_window_covers_delayed_sends_and_rolls_in_utc(self):
        first, second = self.acquire(), self.acquire(self.new_client())
        # The first caller paused after receiving an admission. The active
        # permits retain both slots, even after the original start window passed.
        self.sql.now += timedelta(seconds=5)
        self.assertEqual(self.acquire().reason, "local_inflight_limit")
        self.budget.finish(first.token, self.sql.now, success=True)
        self.assertEqual(self.acquire().reason, "local_rate_limited")
        self.budget.finish(second.token, self.sql.now, success=True)
        self.sql.now += timedelta(seconds=1)
        self.assertTrue(self.acquire().token)
        self.assertEqual(self.status()["used"], 8)
        self.sql.now += timedelta(days=9)
        self.assertEqual(self.status()["used"], 0)
        self.assertEqual(self.status()["active"], 1)
        self.sql.now -= timedelta(days=9, seconds=1)
        with self.assertRaises(BudgetStoreUnavailable):
            self.acquire()

    def test_minute_limit_is_shared_across_worker_restarts(self):
        for _ in range(30):
            for _ in range(2):
                ledger = self.new_client()
                permit = self.acquire(ledger)
                ledger.finish(permit.token, self.sql.now, success=True)
            self.sql.now += timedelta(seconds=1)
        refusal = self.acquire()
        self.assertEqual((refusal.reason, refusal.retry_after), ("local_rate_limited", 30))
        self.sql.now += timedelta(seconds=30)
        self.assertTrue(self.acquire().token)

    def test_sql_rollover_retries_in_the_correct_utc_day(self):
        self.sql.now = datetime(2026, 11, 30, 23, 59, 59, tzinfo=timezone.utc)
        self.sql.change_at_update = timedelta(seconds=2)
        self.assertTrue(self.acquire().token)
        self.assertEqual(self.sql.missed, 1)
        self.assertEqual(self.sql.state["daily"], {EXPLORER_DAY: {"routine": 5}, "2026-12-01": {"routine": 1}})

    def test_quota_cooldown_survives_restart_and_double_finish(self):
        first, second = self.acquire(), self.acquire()
        self.budget.finish(first.token, self.sql.now, quota=True)
        self.sql.now += timedelta(seconds=3)
        self.assertEqual(self.acquire(self.new_client()).reason, "local_inflight_limit")
        self.new_client().finish(second.token, self.sql.now, quota=True)
        self.new_client().finish(second.token, self.sql.now, quota=True)
        refusal = self.acquire(self.new_client())
        self.assertEqual((refusal.reason, refusal.retry_after), ("shared_provider_cooldown", 30))
        self.sql.now += timedelta(seconds=30)
        self.assertTrue(self.acquire(self.new_client()).token)

    def test_validation_reservations_share_account_and_preserve_spend(self):
        self.assertEqual(self.acquire(profile="validation").reason, "validation_reservation_required")
        reserve = self.budget.reserve_run(*SCOPE, self.sql.now, 2999)
        run_id = reserve["run_id"]
        loaded = self.new_client()
        self.assertEqual(loaded.reserve_run(*SCOPE, self.sql.now, 2)["reason"],
                         "validation_allocation_exhausted")
        permit = self.acquire(loaded, profile="validation", run_id=run_id)
        loaded.finish(permit.token, self.sql.now, success=True)
        self.assertEqual(self.status()["reserved"]["validation_active_runs"], 2998)
        self.assertEqual(loaded.release_run(*SCOPE, run_id), {"released": 2998, "spent": 1})
        self.assertEqual(loaded.release_run(*SCOPE, run_id), {"released": 0, "spent": 1})
        self.assertEqual(self.status()["used_by_profile"]["validation"], 1)
        other = loaded.reserve_run(*SCOPE, self.sql.now, 1)["run_id"]
        self.sql.now += timedelta(days=9)
        self.assertEqual(self.acquire(profile="validation", run_id=other).reason, "reservation_month_mismatch")

    def test_lost_acquire_ack_does_not_send_or_replay_and_restart_sees_the_charge(self):
        self.sql.write_error = "after_commit"
        send = Mock(return_value=route())
        result = self.adapter(send).routes((0, 0), [("c", (1, 1))])
        send.assert_not_called()
        self.assertEqual(result.calls_attempted, 0)
        self.assertEqual(result.errors, ["budget_store_unavailable"])
        self.assertEqual(self.sql.written, 1)
        latest = self.status(self.new_client())
        self.assertEqual((latest["active"], latest["used"]), (1, 6))

    def test_lost_finish_ack_never_refunds_or_applies_quota_twice(self):
        attempt = self.acquire()
        self.sql.write_error = "after_commit"
        with self.assertRaises(BudgetStoreUnavailable):
            self.budget.finish(attempt.token, self.sql.now, quota=True)
        self.sql.write_error = None
        self.new_client().finish(attempt.token, self.sql.now, quota=True)
        self.assertEqual(self.sql.state["strikes"], 1)
        latest = self.status(self.new_client())
        self.assertEqual((latest["active"], latest["used"]), (0, 6))

    def test_unavailable_second_quota_finish_retains_cross_replica_stop(self):
        first, second = self.acquire(), self.acquire()
        self.budget.finish(first.token, self.sql.now, quota=True)
        self.sql.write_error = "before_commit"
        with self.assertRaises(BudgetStoreUnavailable):
            self.budget.finish(second.token, self.sql.now, quota=True)
        self.sql.now += timedelta(seconds=3)
        self.sql.write_error = None
        other = self.new_client()
        self.assertEqual(self.acquire(other).reason, "local_inflight_limit")
        other.finish(second.token, self.sql.now, quota=True)
        self.assertEqual(self.acquire(other).reason, "shared_provider_cooldown")
        self.assertEqual(self.status(other)["used"], 7)

    def test_adapter_charges_before_send_and_releases_on_confirmed_finish(self):
        def transport(*_):
            status = self.status(self.new_client())
            self.assertEqual((status["active"], status["used"]), (1, 6))
            return route()

        send = Mock(side_effect=transport)
        result = self.adapter(send).routes((0, 0), [("c", (1, 1))])
        send.assert_called_once()
        self.assertEqual(result.results["c"]["outcome"], "ok")
        self.assertEqual((result.usage["active"], result.usage["used"]), (0, 6))

    def test_missing_invalid_and_unavailable_store_stop_before_send(self):
        send = Mock(return_value=route())
        adapter = self.adapter(send)
        scenarios = [(self.sql.state, True, None), (None, False, None),
                     ({**self.sql.state, "receipt": None}, False, None),
                     ({**self.sql.state, "daily": {}}, False, None),
                     (self.sql.state, False, "before_commit")]
        for state, read_error, write_error in scenarios:
            with self.subTest(read_error=read_error, write_error=write_error, present=bool(state)):
                self.sql.state, self.sql.read_error, self.sql.write_error = state, read_error, write_error
                result = adapter.routes((0, 0), [("c", (1, 1))])
                self.assertEqual(result.errors, ["budget_store_unavailable"])
                self.assertEqual(result.calls_attempted, 0)
        send.assert_not_called()
        self.assertEqual(self.sql.written, 0)

    def test_scope_and_identifier_are_validated(self):
        with self.assertRaises(ValueError):
            DeltaBudget(WAREHOUSE, "catalog.schema.ledger; SELECT 1", account_scope=ACCOUNT, verified_allowance=ALLOWANCE)
        self.assertEqual(self.budget.acquire("other", PRODUCT, EXPLORER).reason, "unverified_allocation")
        self.assertEqual(self.sql.reads, 0)


class StatementExecutionTests(unittest.TestCase):
    def setUp(self):
        self.statements = _Statements()
        self.statements.config = Mock(host="https://workspace.example")
        self.statements.config.authenticate.return_value = {"Authorization": "Bearer synthetic-token"}
        self.connection = Mock()
        patcher = patch("app.travel.delta_budget.HTTPSConnection", return_value=self.connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.response = self.connection.getresponse.return_value
        self.response.status = 200

    def submit(self, payload):
        self.response.read.return_value = json.dumps(payload).encode()
        return self.statements(WAREHOUSE, "UPDATE test SET revision = :value", {"value": "test"})

    def test_only_complete_success_is_an_ack_and_parameters_are_bound(self):
        self.assertEqual(self.submit({"status": {"state": "SUCCEEDED"}, "manifest": {},
                                      "result": {"data_array": [["1"]]}}), [["1"]])
        method, path, body, headers = self.connection.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/2.0/sql/statements"))
        self.assertIn("Authorization", headers)
        self.assertEqual(json.loads(body)["parameters"], [{"name": "value", "value": "test"}])
        self.assertEqual(json.loads(body)["on_wait_timeout"], "CANCEL")
        self.assertEqual(json.loads(body)["wait_timeout"], "5s")

    def test_timeout_never_resubmits_sql_post(self):
        self.connection.getresponse.side_effect = TimeoutError("PRIVATE")
        with self.assertRaises(BudgetStoreUnavailable) as failure:
            self.submit({})
        self.assertNotIn("PRIVATE", str(failure.exception))
        self.connection.request.assert_called_once()

    def test_only_explicit_terminal_delta_conflict_is_retryable(self):
        with self.assertRaises(_WriteConflict):
            self.submit({"status": {"state": "FAILED",
                                    "error": {"message": "[DELTA_CONCURRENT_WRITE] writer lost"}}})
        for state in ("PENDING", "RUNNING", "CANCELED", "FAILED", "CLOSED"):
            with self.subTest(state=state), self.assertRaises(BudgetStoreUnavailable):
                self.submit({"status": {"state": state, "error": {"message": "unknown"}}})
        with self.assertRaises(BudgetStoreUnavailable):
            self.submit({"status": {"state": "SUCCEEDED"}, "manifest": {"truncated": True},
                         "result": {"data_array": [["1"]]}})


if __name__ == "__main__":
    unittest.main()
