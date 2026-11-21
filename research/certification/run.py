"""Acquire a local held-out reference or verify an existing run without network."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .audit import acquire_audit, compare
from .build import build
from .capture import capture
from .common import ROOT, VERSION, canonical, read, require, save, sha

OUTPUTS = ("batch", "episodes", "relations", "report", "audit_sample", "audit", "empty_base")


def local_path(path):
    root = Path(path).resolve()
    require(root.is_relative_to((ROOT / "data/local").resolve()), "output_must_be_under_ignored_data_local")
    return root


def acquire(path, as_of, max_pages=100):
    date.fromisoformat(as_of)
    root = local_path(path)
    require(not root.exists(), "output_already_exists")
    root.mkdir(parents=True)
    capture(root, max_pages=max_pages)
    result = build(root, as_of)
    result["audit"] = acquire_audit(root, result["episodes"])
    result["empty_base"] = []  # No original population was supplied or inferred.
    for key in OUTPUTS:
        save(root / (key + ".json"), result[key])
    files = [key + ".json" for key in OUTPUTS] + ["capture.json", "audit_capture.json"]
    manifest = {"run_version": VERSION, "status": "complete_with_source_limitations" if result["report"]["blockers"] else "complete",
                "as_of": as_of, "artifact_root": str(root),
                "files": {name: sha((root / name).read_bytes()) for name in files}}
    # Written last. An interrupted acquisition has no completed run manifest.
    save(root / "run_manifest.json", manifest)
    return {"status": manifest["status"], "report": result["report"],
            "audit": {k: v for k, v in result["audit"].items() if k != "rows"},
            "run_manifest_sha256": sha((root / "run_manifest.json").read_bytes())}


def replay(path):
    root = local_path(path)
    manifest = read(root / "run_manifest.json")
    require(manifest["run_version"] == VERSION, "unknown_run_version")
    require(manifest["artifact_root"] == str(root), "run_relocated_absolute_artifact_uris_require_explicit_republication")
    expected = {key + ".json" for key in OUTPUTS} | {"capture.json", "audit_capture.json"}
    require(set(manifest["files"]) == expected, "manifest_file_set_changed")
    for name, digest in manifest["files"].items():
        require(sha((root / name).read_bytes()) == digest, "derived_or_manifest_input_hash_mismatch:" + name)
    result = build(root, manifest["as_of"])
    result["audit"] = compare(root, result["episodes"])
    result["empty_base"] = []
    for key in OUTPUTS:
        require((root / (key + ".json")).read_bytes() == canonical(result[key]) + b"\n", "replay_changed:" + key)
    return {"status": "byte_identical_replay", "network_requests": 0,
            "verified_derived_files": len(OUTPUTS), "table_counts": result["report"]["table_counts"],
            "run_manifest_sha256": sha((root / "run_manifest.json").read_bytes())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    acq = commands.add_parser("acquire")
    acq.add_argument("--output-dir", required=True)
    acq.add_argument("--as-of", required=True)
    acq.add_argument("--max-pages", type=int, default=100)
    rep = commands.add_parser("replay")
    rep.add_argument("--run-dir", required=True)
    args = parser.parse_args(argv)
    try:
        result = acquire(args.output_dir, args.as_of, args.max_pages) if args.command == "acquire" else replay(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Never print source rows; failures identify a path or invariant only.
        print("NQAS run failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
