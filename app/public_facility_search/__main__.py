"""Print the same public evidence records consumed by Find care."""

import argparse
import json

from . import search_public_facilities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--place", required=True, help="City name")
    parser.add_argument("--service", required=True, help="Requested service")
    args = parser.parse_args()
    print(json.dumps(search_public_facilities(args.place, args.service), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
