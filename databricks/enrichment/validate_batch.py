#!/usr/bin/env python3
"""Validate batches and optionally write a complete deterministic staging plan."""
import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

from common import Invalid, counts, load
from coverage import coverage
from merge import plan_merge


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", required=True, action="append", help="Repeat for independent producer envelopes")
    p.add_argument("--base", required=True)
    p.add_argument("--accepted")
    p.add_argument("--accepted-ledger")
    p.add_argument("--transitions")
    p.add_argument("--identity-policy")
    p.add_argument("--plan-out", help="Restricted local path: plan contains source records, never commit")
    p.add_argument("--as-of", default=datetime.now(timezone.utc).date().isoformat(),
                   help="Coverage assessment date, ISO YYYY-MM-DD; defaults to current UTC date")
    args = p.parse_args(argv)
    try:
        optional = lambda path: load(path) if path else None
        plan = plan_merge([load(path) for path in args.batch], load(args.base),
                          optional(args.accepted), optional(args.transitions),
                          optional(args.accepted_ledger), optional(args.identity_policy))
        report = coverage(plan["batch"], plan["base"], args.as_of)
        if args.plan_out:
            # Refuse accidental overwrite of a producer/base input, even through a symlink.
            inputs = args.batch + [x for x in (args.base, args.accepted, args.accepted_ledger,
                                               args.transitions, args.identity_policy) if x]
            if Path(args.plan_out).resolve() in {Path(x).resolve() for x in inputs}:
                raise Invalid("plan-out: cannot overwrite an input")
            with open(args.plan_out, "x", encoding="utf-8") as stream:
                json.dump(plan, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        print(json.dumps({"status": "valid", "contract_version": plan["contract_version"],
                          "counts": counts(plan["batch"]), "base_rows": len(plan["base"]),
                          "base_sha256": plan["base_sha256"], "ledger_rows": len(plan["ledger"]),
                          "coverage": report}, sort_keys=True, indent=2))
        return 0
    except (Invalid, OSError, ValueError) as error:
        # JSON parser errors include line/column, not the input document.
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
