"""Build a private lookup from a D-prepared base and an explicitly reviewed evidence ledger."""
import argparse
import hashlib
import json
from pathlib import Path

from research.matching.common import canonical, file_digest, load, require, write_json
from .projection import project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True,
                        help="JSON array of adjudicated claims; [] for an empty-evidence check")
    parser.add_argument("--batch", type=Path, action="append", default=[], help="accepted v1 envelope")
    parser.add_argument("--identity-rows", type=Path, help="C's frozen national base_rows.json")
    parser.add_argument("--identity-sha256", help="C's independently recorded base_rows.json file hash")
    parser.add_argument("--identity-report", type=Path, help="the matching national_report.json for the same run")
    parser.add_argument("--checked-source", action="append", default=[])
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out-dir", type=Path, required=True, help="authorized private location")
    args = parser.parse_args()
    base_bytes = args.base.read_bytes()
    base_hash = hashlib.sha256(base_bytes).hexdigest()
    identity_options = (args.identity_rows, args.identity_sha256, args.identity_report)
    require(all(identity_options) or not any(identity_options), "identity", "provide rows, pinned hash and report together")
    identity = None
    if args.identity_rows:
        raw_identity = args.identity_rows.read_bytes()
        require(hashlib.sha256(raw_identity).hexdigest() == args.identity_sha256, "identity", "frozen rows hash mismatch")
        identity = json.loads(raw_identity)
    result = project(json.loads(base_bytes), load(args.metadata), load(args.reviews),
                     [load(p) for p in args.batch], as_of=args.as_of,
                     checked_sources=args.checked_source, base_file_sha256=base_hash,
                     identity_rows=identity, identity_report=load(args.identity_report) if identity is not None else None)
    result["identity_rows_file_sha256"] = args.identity_sha256
    output_hash = hashlib.sha256((canonical(result) + "\n").encode("utf-8")).hexdigest()
    path = args.out_dir / (output_hash + ".json")
    if path.exists():
        require(file_digest(path) == output_hash, "output", "existing artifact differs from its hash")
    else:
        write_json(path, result)
    print(canonical({"sha256": output_hash, "occurrences": result["occurrences"],
                     "decision_count": result["decision_count"], "coverage": result["coverage"]}))


if __name__ == "__main__":
    main()
