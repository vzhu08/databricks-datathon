import argparse
import json

from .comparison import evaluate
from .smoke import synthetic_bundle


def main():
    parser = argparse.ArgumentParser(description="Compare nearest, fixed and learned routing preferences.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--bundle", type=argparse.FileType("r", encoding="utf-8"))
    group.add_argument("--synthetic-smoke", action="store_true")
    group.add_argument("--example-bundle", action="store_true")
    args = parser.parse_args()
    try:
        if args.example_bundle:
            result = synthetic_bundle()
        elif args.bundle:
            with args.bundle as source:
                result = evaluate(json.load(source))
        else:
            result = evaluate(synthetic_bundle() if args.synthetic_smoke else None)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
