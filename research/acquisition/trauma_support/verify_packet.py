"""Verify a local or Databricks-downloaded aggregate packet against its digest."""
import argparse
import hashlib
import json
from pathlib import Path


FILES = {"aggregate-report.json", "edition-provenance.json", "source-gaps.json"}


def verify(directory, expected_manifest_sha256):
    root = Path(directory)
    raw = (root / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("Manifest digest does not match handoff")
    manifest = json.loads(raw)
    if set(manifest["files"]) != FILES or {p.name for p in root.iterdir()} != FILES | {"manifest.json"}:
        raise ValueError("Unexpected/missing packet files")
    counts = {}
    for name, spec in manifest["files"].items():
        raw = (root / name).read_bytes()
        if len(raw) != spec["bytes"] or hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise ValueError(f"Size/hash mismatch: {name}")
        data = json.loads(raw)
        count = len(data) if isinstance(data, list) else None
        if count != spec["records"]:
            raise ValueError(f"Record-count mismatch: {name}")
        counts[name] = count
    report = json.loads((root / "aggregate-report.json").read_text())
    if (report["original_occurrences"], report["distinct_upstream_ids"], report["occurrence_service_decisions"]) != (10088, 10077, 30264):
        raise ValueError("National denominator mismatch")
    if sum(row["original_occurrences"] for row in report["geography"].values()) != 10088:
        raise ValueError("Geographic totals do not reconcile")
    return {"manifest_sha256": expected_manifest_sha256, "verified_files": 4,
            "original_occurrences": 10088, "decisions": 30264, "records": counts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("manifest_sha256")
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.manifest_sha256), sort_keys=True))
