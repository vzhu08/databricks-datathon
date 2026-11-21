"""Emit a complete offline replay as JSON."""

import argparse
import json
import sys

from .replay import replay
from .scenario import SCENARIOS, make_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="storm")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--detour-minutes", type=int, default=10)
    parser.add_argument("--include-fifo-control", action="store_true",
                        help="Add an arrival-order nearest policy as a separate scheduling control.")
    args = parser.parse_args()
    if args.detour_minutes < 0:
        parser.error("--detour-minutes must be nonnegative")
    result = replay(make_scenario(args.scenario, args.seed), args.detour_minutes,
                    args.include_fifo_control)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
