"""Build from immutable private inputs; print aggregate counts and hashes only."""
import argparse
import json
from pathlib import Path

from .ledger import (attach_joint_trace, build, lines, pinned, require, sha, write_release)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--base", type=Path, required=True)
    cli.add_argument("--intake-manifest", type=Path, required=True)
    cli.add_argument("--intake-sha256", required=True)
    cli.add_argument("--coverage-dir", type=Path, required=True)
    cli.add_argument("--coverage-sha256", required=True)
    cli.add_argument("--research-dir", type=Path, required=True)
    cli.add_argument("--joint-dir", type=Path, required=True)
    cli.add_argument("--lane", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    cli.add_argument("--complete-original-statements", action="store_true")
    cli.add_argument("--out-dir", type=Path, required=True)
    args = cli.parse_args()
    intake = json.loads(pinned(args.intake_manifest, args.intake_sha256))
    coverage = json.loads(pinned(args.coverage_dir / "manifest.json", args.coverage_sha256))
    require(coverage["existing_intake_reference"]["sha256"] == args.intake_sha256, "coverage_intake_mismatch")
    for name, meta in coverage["files"].items():
        require(Path(name).name == name, "unsafe_input_member")
        raw = pinned(args.coverage_dir / name, meta["sha256"])
        require(len(raw) == meta["bytes"], "input_size_mismatch")
    datasets = {d["id"]: d for d in intake["datasets"]}
    base_hash = datasets["vf-v0"]["pins"]["base"]["sha256"]
    base = json.loads(pinned(args.base, base_hash))
    source = datasets["vf-campus-service-research-v3"]
    for name, meta in source["file"]["members"].items():
        require(Path(name).name == name, "unsafe_input_member")
        raw = pinned(args.research_dir / name, meta["sha256"])
        require(len(raw) == meta["bytes"], "input_size_mismatch")
    occurrences = lines(args.research_dir / "occurrences.jsonl.gz")
    decisions = lines(args.research_dir / "service-decisions.jsonl.gz")
    require({r["as_of"] for r in decisions} == {coverage["services"]["as_of"]}, "baseline_date_mismatch")
    packages = [json.loads(pinned(path, digest)) for path, digest in args.lane]
    identity_coverage = json.loads((args.research_dir / "coverage.json").read_text())
    artifact = build(base, occurrences, decisions, packages,
                     statements_complete=args.complete_original_statements,
                     geography_buckets=identity_coverage["by_state_or_ut"])
    for row in artifact["report"]["state_service"]:
        expected = identity_coverage["by_state_or_ut"][row["state"]]
        require(row["original_occurrences"] == expected["occurrences"] and
                all(row[s] == expected["by_service"][row["service"]][s] for s in ("yes", "no", "unconfirmed")),
                "frozen_state_service_counts_changed")
    require(artifact["report"]["population"]["original_payload_multiset_sha256"] ==
            datasets["vf-v0"]["pins"]["original_payload_multiset_sha256"], "original_multiset_changed")
    joint_source = datasets["vf-joint-matching"]
    for name, meta in joint_source["file"]["members"].items():
        require(Path(name).name == name, "unsafe_input_member")
        raw = pinned(args.joint_dir / name, meta["sha256"])
        require(len(raw) == meta["bytes"], "input_size_mismatch")
    attach_joint_trace(artifact, lines(args.joint_dir / "occurrence-delta.jsonl.gz"))
    provenance = {"intake_manifest_sha256": args.intake_sha256,
                  "coverage_manifest_sha256": args.coverage_sha256,
                  "base_sha256": base_hash, "research_archive": source["file"],
                  "joint_archive": joint_source["file"],
                  "base_source": datasets["vf-v0"]["path"],
                  "baseline_provenance": {k: source[k] for k in ("publisher", "edition", "rights", "grain", "keys")},
                  "lanes": [{"sha256": digest, "lane": package["lane"]} for (_, digest), package in zip(args.lane, packages)],
                  "code_sha256": {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))}}
    digest = write_release(args.out_dir, artifact, provenance)
    print(json.dumps({"manifest_sha256": digest, "population": artifact["report"]["population"],
                      "original_statement_coverage": artifact["report"]["original_statement_coverage"],
                      "observations_loaded": len(artifact["observations"])}))


if __name__ == "__main__":
    main()
