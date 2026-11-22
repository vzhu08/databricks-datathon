import argparse
import json
from pathlib import Path

from research.acquisition.common import file_digest
from .collector import collect, publish
from .compare import compare, frozen_reach, reconcile_legacy


def read(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description="Private imaging evidence and full-original national comparison")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--manifest", type=Path, required=True)
    c.add_argument("--annotations", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--base", type=Path, required=True)
    c.add_argument("--metadata", type=Path, required=True)
    c.add_argument("--control", type=Path, action="append", required=True)
    c.add_argument("--addition", type=Path, action="append", required=True)
    c.add_argument("--as-of", required=True)
    c.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("reconcile")
    c.add_argument("--legacy-root", type=Path, required=True)
    c.add_argument("--current-manifest", type=Path)
    c.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("frozen-reach")
    c.add_argument("--base", type=Path, required=True)
    c.add_argument("--ledger-root", type=Path, required=True)
    c.add_argument("--manifest-sha256", required=True)
    c.add_argument("--imaging-rows", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "collect":
        result = collect(args.manifest.parent, read(args.manifest), read(args.annotations))
    elif args.command == "compare":
        result = compare(read(args.base), read(args.metadata), file_digest(args.base),
                         [read(p) for p in args.control], [read(p) for p in args.addition], args.as_of)
    elif args.command == "frozen-reach":
        result = frozen_reach(read(args.base), args.ledger_root, args.manifest_sha256, read(args.imaging_rows))
    else:
        result = {"reconciliation.json": reconcile_legacy(args.legacy_root, args.current_manifest)}
    print(json.dumps({"output_hashes": publish(args.out, result)}, sort_keys=True))


if __name__ == "__main__":
    main()
