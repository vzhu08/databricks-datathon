"""Run one normalized facility-finder request from a UTF-8 JSON file or stdin."""

import argparse
import json
import sys
from pathlib import Path

from .urgency import rank_campuses


def _reject_constant(value):
    raise ValueError(f"{value} is not a JSON number")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="JSON request file, or - for stdin")
    parser.add_argument("--urgency", help="Override the request's explicit urgency")
    parser.add_argument("--service", help="Override the requested service")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            request = json.load(sys.stdin, parse_constant=_reject_constant)
        else:
            with Path(args.input).open(encoding="utf-8") as stream:
                request = json.load(stream, parse_constant=_reject_constant)
        if not isinstance(request, dict):
            raise ValueError("Input must be one normalized request object")
        candidates = request.get("candidates")
        if not isinstance(candidates, list) or any(not isinstance(row, dict) for row in candidates):
            raise ValueError("candidates must be an array of campus objects")
        if "limit" in request and request["limit"] is None:
            raise ValueError("The finder limit must be a positive integer")
        if args.urgency is not None:
            request["urgency"] = args.urgency
        if args.service is not None:
            request["service"] = args.service
        result = rank_campuses(**request)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        print(json.dumps({"status": "invalid_input", "message": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
