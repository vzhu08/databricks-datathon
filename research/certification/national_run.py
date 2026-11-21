"""Acquire, finalize or replay a separate held-out national-register run."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .common import SourceError, canonical, read, require, save, sha
from .fetch import Fetcher
from .national_build import build
from .national_capture import VERSION, capture
from .run import local_path

OUTPUTS = ("batch", "ledger", "occurrences", "unresolved_groups", "discrepancies", "report", "audit", "empty_base")


def recheck(root, as_of, fetcher=None):
    root = local_path(root)
    require(not (root / "national_recheck.json").exists(), "national_recheck_already_exists")
    data = build(root, as_of)
    source = read(root / "national_capture.json")
    client = fetcher or Fetcher(root)
    checks = []
    for key in sorted({r["document_key"] for r in data["discrepancies"]["source_rows"]}):
        original = source["documents"][key]
        result = {"source_document_key": key, "original_sha256": original["sha256"], "url": original["url"]}
        try:
            doc = client.get(original["url"])
            result.update(document=doc, raw_bytes_unchanged=doc["sha256"] == original["sha256"])
        except SourceError as error:
            result["failure"] = str(error)
        checks.append(result)
    save(root / "national_recheck.json", {"checks": checks, "attempt_log": client.attempt_log})
    return checks


def finalize(root, as_of):
    root = local_path(root)
    date.fromisoformat(as_of)
    filenames = [k + ".json" for k in OUTPUTS]
    require(all(not (root / name).exists() for name in filenames + ["national_run_manifest.json"]), "national_outputs_already_exist")
    data = build(root, as_of)
    for key in OUTPUTS:
        save(root / (key + ".json"), data[key])
    files = filenames + ["national_capture.json"]
    if (root / "national_recheck.json").exists():
        files.append("national_recheck.json")
    report = data["report"]
    limited = (bool(report["capture_blockers"]) or report["map_parse_error"] is not None
               or not report["status_views_multiset_equals_all"]
               or any(not v["complete"] or not v["parsed_equals_advertised"] for v in report["views"].values()))
    manifest = {"run_version": VERSION, "status": "complete_with_source_limitations" if limited else "complete",
                "artifact_root": str(root), "as_of": as_of, "files": {name: sha((root / name).read_bytes()) for name in files}}
    save(root / "national_run_manifest.json", manifest)
    return {"status": manifest["status"], "table_counts": report["table_counts"], "source_rows": report["source_row_occurrences"],
            "audit_counts": report["audit_counts"], "manifest_sha256": sha((root / "national_run_manifest.json").read_bytes())}


def acquire(root, as_of, max_pages=100):
    root = local_path(root)
    date.fromisoformat(as_of)
    require(not root.exists(), "national_output_already_exists")
    root.mkdir(parents=True)
    capture(root, max_pages)
    recheck(root, as_of)
    return finalize(root, as_of)


def replay(root):
    root = local_path(root)
    manifest = read(root / "national_run_manifest.json")
    require(manifest["run_version"] == VERSION, "unknown_national_run_version")
    require(manifest["artifact_root"] == str(root), "national_run_relocated_requires_explicit_republication")
    expected = {k + ".json" for k in OUTPUTS} | {"national_capture.json"}
    if "national_recheck.json" in manifest["files"]:
        expected.add("national_recheck.json")
    require(set(manifest["files"]) == expected, "national_manifest_file_set_changed")
    for name, digest in manifest["files"].items():
        require(sha((root / name).read_bytes()) == digest, "national_file_hash_mismatch:" + name)
    data = build(root, manifest["as_of"])
    for key in OUTPUTS:
        require((root / (key + ".json")).read_bytes() == canonical(data[key]) + b"\n", "national_replay_changed:" + key)
    return {"status": "byte_identical_replay", "network_requests": 0, "verified_derived_files": len(OUTPUTS),
            "table_counts": data["report"]["table_counts"], "manifest_sha256": sha((root / "national_run_manifest.json").read_bytes())}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("acquire", "recheck", "finalize", "replay"):
        c = sub.add_parser(name)
        c.add_argument("--run-dir", required=True)
        if name != "replay":
            c.add_argument("--as-of", required=True)
        if name == "acquire":
            c.add_argument("--max-pages", type=int, default=100)
    args = p.parse_args(argv)
    try:
        if args.command == "acquire":
            result = acquire(args.run_dir, args.as_of, args.max_pages)
        elif args.command == "replay":
            result = replay(args.run_dir)
        else:
            result = {"result": (recheck if args.command == "recheck" else finalize)(args.run_dir, args.as_of)}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("National-register run failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
