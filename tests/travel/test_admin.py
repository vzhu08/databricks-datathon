from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.travel.admin import main
from app.travel.budget import ALLOWANCE, PRODUCT, SQLiteBudget

NOW = datetime(2026, 11, 22, 1, tzinfo=timezone.utc)


class OperatorTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "usage.sqlite"
        self.env = {"TOMTOM_ACCOUNT_SCOPE": "synthetic-account", "TOMTOM_PRODUCT": PRODUCT,
                    "TOMTOM_VERIFIED_MONTHLY_ALLOWANCE": "20000", "TOMTOM_DEPLOYMENT_MODE": "single_host",
                    "TOMTOM_BUDGET_DB": str(self.path), "TOMTOM_PROFILE": "validation"}

    def invoke(self, args, env):
        out, err = StringIO(), StringIO()
        with patch.dict("os.environ", env, clear=True), redirect_stdout(out), redirect_stderr(err), \
                patch("app.travel.admin.datetime") as clock, \
                patch("http.client.HTTPSConnection", side_effect=AssertionError("operator command sent HTTP")):
            clock.now.return_value = NOW
            code = main(args)
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_cli_dry_run_needs_no_settings_or_ledger_and_rejects_unbounded_run(self):
        code, result = self.invoke(["dry-run", "--campuses", "25", "--searches", "20"], {})
        self.assertEqual(code, 0)
        self.assertEqual(result["worst_case_calls"], 1000)
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.invoke(["dry-run", "--searches", "61"], {})[0], 2)

    def test_reserve_use_release_and_status_preserve_sent_attempts(self):
        self.assertEqual(self.invoke(["initialize"], self.env)[1]["used"], 5)
        code, run = self.invoke(["reserve", "--campuses", "25", "--searches", "20"], self.env)
        self.assertEqual(code, 0)
        self.assertEqual(run["reserved_calls"], 1000)
        b = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        permit = b.acquire("synthetic-account", PRODUCT, NOW, profile="validation", daily_limit=3000,
                           monthly_limit=3000, run_id=run["run_id"])
        b.finish(permit.token, NOW)
        code, released = self.invoke(["release", "--run-id", run["run_id"]], self.env)
        self.assertEqual((code, released), (0, {"released": 999, "spent": 1}))
        code, result = self.invoke(["status"], self.env)
        self.assertEqual(code, 0)
        self.assertEqual(result["used"], 6)
        self.assertEqual(result["reserved"]["validation_active_runs"], 0)
        self.assertEqual(result["reserved"]["demo_remaining"], 2000)

    def test_only_initialize_creates_a_new_store_and_never_overwrites_it(self):
        for action in (["status"], ["reserve"], ["release", "--run-id", "missing"], ["adopt-legacy"]):
            self.assertEqual(self.invoke(action, self.env)[0], 2)
            self.assertFalse(self.path.exists())
        self.assertEqual(self.invoke(["initialize"], self.env)[0], 0)
        self.assertEqual(self.invoke(["initialize"], self.env)[0], 2)
        self.assertEqual(self.invoke(["status"], self.env)[1]["used"], 5)

    def test_explicit_legacy_adoption_retains_attempts_and_reservations(self):
        self.assertEqual(self.invoke(["initialize"], self.env)[0], 0)
        b = SQLiteBudget(self.path, verified_allowance=ALLOWANCE)
        permit = b.acquire("synthetic-account", PRODUCT, NOW)
        run = b.reserve_run("synthetic-account", PRODUCT, NOW, 20)
        with sqlite3.connect(str(self.path)) as db:
            db.execute("PRAGMA application_id=0")
            db.execute("PRAGMA user_version=0")
        self.assertEqual(self.invoke(["status"], self.env)[0], 2)
        code, result = self.invoke(["adopt-legacy"], self.env)
        self.assertEqual(code, 0)
        self.assertEqual((result["used"], result["active"]), (6, 1))
        self.assertEqual(result["reserved"]["validation_active_runs"], 20)
        self.assertEqual(self.invoke(["adopt-legacy"], self.env)[0], 2)
        b.finish(permit.token, NOW)
        self.assertEqual(b.release_run("synthetic-account", PRODUCT, run["run_id"])["released"], 20)

    def test_operator_profile_and_verified_configuration_are_required(self):
        for env in ({}, {**self.env, "TOMTOM_PROFILE": "routine"},
                    {**self.env, "TOMTOM_VERIFIED_MONTHLY_ALLOWANCE": "20001"},
                    {**self.env, "TOMTOM_DEPLOYMENT_MODE": "multi_host"}):
            self.assertEqual(self.invoke(["reserve"], env)[0], 2)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
