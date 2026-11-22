"""Trusted operator ledger commands. This module never sends HTTP requests."""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

from .budget import ALLOWANCE, PRODUCT, SQLiteBudget, dry_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dry-run", "initialize", "adopt-legacy", "status", "reserve", "release"))
    parser.add_argument("--campuses", type=int, default=25)
    parser.add_argument("--searches", type=int, default=1)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    try:
        if args.action in ("dry-run", "reserve"):
            calculation = dry_run(args.campuses, args.retries)
            if not 1 <= args.searches <= 3000:
                raise ValueError("Use a finite positive number of searches")
            calculation["searches"] = args.searches
            calculation["worst_case_calls"] *= args.searches
            if calculation["worst_case_calls"] > 3000:
                raise ValueError("The worst-case run exceeds the validation allocation")
            if args.action == "dry-run":
                print(json.dumps(calculation))
                return 0
        env = os.environ
        if (env.get("TOMTOM_VERIFIED_MONTHLY_ALLOWANCE") != str(ALLOWANCE) or
                env.get("TOMTOM_PRODUCT") != PRODUCT or env.get("TOMTOM_DEPLOYMENT_MODE") != "single_host" or
                not env.get("TOMTOM_ACCOUNT_SCOPE") or not env.get("TOMTOM_BUDGET_DB")):
            raise ValueError("An approved account, product, allocation and single-host ledger are required")
        if args.action in ("reserve", "release") and env.get("TOMTOM_PROFILE") != "validation":
            raise ValueError("Reservation changes require the trusted validation operator profile")
        ledger = SQLiteBudget(env["TOMTOM_BUDGET_DB"], verified_allowance=ALLOWANCE)
        account, now = env["TOMTOM_ACCOUNT_SCOPE"], datetime.now(timezone.utc)
        if args.action == "initialize":
            ledger.initialize(account, PRODUCT)
            result = ledger.status(account, PRODUCT, now)
        elif args.action == "adopt-legacy":
            ledger.adopt_legacy(account, PRODUCT)
            result = ledger.status(account, PRODUCT, now)
        elif args.action == "status":
            result = ledger.status(account, PRODUCT, now)
        elif args.action == "reserve":
            result = {**calculation, **ledger.reserve_run(account, PRODUCT, now, calculation["worst_case_calls"])}
        else:
            if not args.run_id:
                raise ValueError("Supply the exact reservation ID")
            result = ledger.release_run(account, PRODUCT, args.run_id)
        print(json.dumps(result))
        return 2 if result.get("reason") else 0
    except (ValueError, OSError, sqlite3.Error):
        print(json.dumps({"reason": "invalid_operator_settings_or_ledger_unavailable"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
