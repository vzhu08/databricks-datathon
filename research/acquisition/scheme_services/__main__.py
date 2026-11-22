"""Offline, hash-bound nationwide scheme scope comparison; all outputs private."""
import argparse
import hashlib
import json
from pathlib import Path
from research.matching.common import digest, require, write_json
from .collector import run


def read_bound(path, expected):
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, str(path), "SHA-256 mismatch")
    return json.loads(raw)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_bytes())
    root = args.manifest.resolve().parent
    inputs = {}
    for key in ("records", "base", "metadata", "duplicate_groups"):
        spec = manifest["inputs"][key]
        inputs[key] = read_bound(root / spec["path"], spec["sha256"])
    for source in manifest["sources"]:
        raw = (root / source["artifact_path"]).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == source["sha256"], "source", "original bytes changed")
    result = run(inputs["records"], manifest["sources"], inputs["base"], inputs["metadata"],
                 as_of=manifest["as_of"], base_sha256=manifest["inputs"]["base"]["sha256"],
                 duplicate_sidecar=inputs["duplicate_groups"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, value in result.items():
        path = args.out_dir / (name + ".json")
        write_json(path, value)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(args.out_dir / "receipt.json", {
        "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        "inputs": manifest["inputs"], "output_sha256": hashes,
        "source_lineage_sha256": digest(manifest["sources"]),
        "disposition": "private working analysis; no source rows admitted or uploaded",
    })
    print(json.dumps({"original_rows": result["summary"]["original_rows"],
                      "decision_count": result["summary"]["decision_count"], "output_sha256": hashes}, sort_keys=True))


if __name__ == "__main__":
    main()
