"""Build a private, immutable railway evidence packet from reviewed profiles."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from .compare import compare
from .extract import canonical, digest, extract_profile, require


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def verify_manifest(directory):
    root = Path(directory)
    manifest = load(root / "manifest.json")
    require(manifest["packet_id"] == "railway-activity-" + digest(canonical(manifest["files"])), "packet ID mismatch")
    require({p.name for p in root.iterdir()} == set(manifest["files"]) | {"manifest.json"}, "unmanifested packet contents")
    for name, entry in manifest["files"].items():
        path = root / name
        require(path.resolve().is_relative_to(root.resolve()) and not path.is_symlink(), "unsafe manifest path")
        raw = path.read_bytes()
        require(len(raw) == entry["bytes"] and digest(raw) == entry["sha256"], "packet hash mismatch")
    return manifest


def build(args):
    output = Path(args.output)
    require(not output.exists(), "output exists; use a new immutable edition directory")
    base_bytes = Path(args.base).read_bytes()
    metadata = load(args.metadata)
    require(digest(base_bytes) == metadata["base_file_sha256"], "base hash mismatch")
    base = json.loads(base_bytes)
    require(metadata["row_count"] == len(base), "base metadata count mismatch")
    extracted, observations = [], []
    for pdf, profile in args.edition:
        result = extract_profile(pdf, load(profile))
        extracted.append((pdf, profile, result))
        observations.extend(result["observations"])
    require(len({x[2]['source']['sha256'] for x in extracted}) == len(extracted), "duplicate raw edition/mirror")
    frame, leads, summary = compare(base, observations, metadata["mapping"],
        expected_rows=args.expected_rows, expected_upstream_ids=args.expected_upstream_ids)
    baseline_bytes = Path(args.baseline_manifest).read_bytes()
    baseline = json.loads(baseline_bytes)
    require(baseline["population"]["occurrences"] == len(base)
            and baseline["population"]["distinct_upstream_ids"] == args.expected_upstream_ids,
            "baseline population differs")
    summary.update(raw_observation_mentions=len(observations),
                   retained_metric_cells=sum(x[2]['counts']['source_cells'] for x in extracted),
                   retained_prose_spans=sum(x[2]['counts']['source_spans'] for x in extracted),
                   distinct_observation_ids=len({o['observation_id'] for o in observations}),
                   edition_scoped_campus_strings=len({o['source_campus_key'] for o in observations}),
                   unique_reviewed_campuses=None,
                   source_editions=len(extracted),
                   source_families=sorted({o['source_family'] for o in observations}),
                   upstream_origin_families=sorted({o['upstream_origin_family'] for o in observations}),
                   historical_measure_counts=dict(Counter(o['measure'] for o in observations)),
                   baseline_edition=baseline['edition'], baseline_manifest_sha256=digest(baseline_bytes),
                   baseline_as_of=baseline['services']['as_of'],
                   baseline_confirmed_campus_service_pairs=baseline['services']['distinct_approved_campus_service_pairs'],
                   as_of=args.as_of, new_supported_current_campus_service_pairs=0,
                   current_status_ledger='Not emitted: D owns the reviewed shared projection',
                   live_databricks='not_verified_by_builder', submission='not_attempted')
    output.mkdir(parents=True)
    for i, (pdf, profile, result) in enumerate(extracted):
        shutil.copyfile(pdf, output / f"source-{i}.pdf")
        shutil.copyfile(profile, output / f"profile-{i}.json")
        save(output / f"extraction-{i}.json", result)
    shutil.copyfile(args.metadata, output / "base-source-metadata.json")
    shutil.copyfile(args.baseline_manifest, output / "baseline-manifest.json")
    # Caller supplies only cleared source policy/index and aggregate access/disposition records.
    for i, filename in enumerate(args.support):
        p = Path(filename)
        shutil.copyfile(p, output / f"support-{i}{p.suffix}")
    save(output / "observations.json", observations)
    save(output / "candidate-leads.json", leads)
    save(output / "summary.json", summary)
    with (output / "full-frame-screen.jsonl").open("wb") as f:
        for row in frame:
            f.write(canonical(row) + b"\n")
    files = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
             for p in sorted(output.iterdir()) if p.is_file()}
    save(output / "manifest.json", {
        "format": "railway-activity-v1", "packet_id": "railway-activity-" + digest(canonical(files)),
        "producer_files": {name: digest(Path(__file__).with_name(name).read_bytes())
                           for name in ["extract.py", "compare.py", "run.py"]},
        "files": files, "base_reference": {"sha256": metadata["base_file_sha256"],
            "table": metadata["original_table"], "delta_version": metadata["observed_delta_version"],
            "stored_elsewhere": True},
        "support_sources": [Path(p).name for p in args.support],
        "sharing_scope": "Private Databricks for the authorized project team; no VF/source rows in Git",
        "attribution": "Comptroller and Auditor General of India; terms and exclusions retained in profiles",
        "reader": "python -m research.acquisition.railway_activity.run --verify DIRECTORY",
        "meaning": "Historical source observations and full-frame screen, not accepted links or patient status"})
    verify_manifest(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify")
    parser.add_argument("--base")
    parser.add_argument("--metadata")
    parser.add_argument("--baseline-manifest")
    parser.add_argument("--edition", nargs=2, action="append", metavar=("PDF", "PRIVATE_PROFILE"), default=[])
    parser.add_argument("--support", action="append", default=[])
    parser.add_argument("--output")
    parser.add_argument("--as-of")
    parser.add_argument("--expected-rows", type=int, default=10088)
    parser.add_argument("--expected-upstream-ids", type=int, default=10077)
    args = parser.parse_args()
    if args.verify:
        result = verify_manifest(args.verify)
        print(json.dumps({"packet_id": result["packet_id"], "verified_files": len(result["files"])}))
    else:
        require(all([args.base, args.metadata, args.baseline_manifest, args.edition, args.output, args.as_of]),
                "provide base, metadata, baseline manifest, editions, output and as-of")
        print(json.dumps(build(args), indent=2))


if __name__ == "__main__":
    main()
