#!/usr/bin/env python3
"""ACQ-C01 matching run.

    python -m research.matching.run --base <file> --external <batch> --output-dir <path>

Reads D's base adapter file and one or more producer envelopes, retrieves
candidates, confirms only clean shared identifiers, and writes a contract
envelope plus review material. Inputs are never modified.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from research.geography.postal import aggregate
from research.geography.report import base_reviews, cluster_reviews, screen
from . import MATCHER_VERSION
from .base_adapter import base_views, check_mapping, default_mapping, external_views
from .candidates import generate, settings
from .common import (MatchingError, base_check, canonical, combine_external, counts, digest, empty,
                     field_value, file_digest, load, require, schema_check, write_json)
from .decide import build, check_policy
from .review import sample, stratum, worksheet


def cross_check(batch, base_index, external_ids):
    """Local referential checks on C's own envelope (D's validator stays normative)."""
    match_ids = set()
    confirmed = {}
    for index, row in enumerate(batch["facility_matches"]):
        path = f"facility_matches[{index}]"
        require(row["match_id"] not in match_ids, path, "duplicate match ID")
        match_ids.add(row["match_id"])
        require(row["facility_id"] in base_index, path, "base ID not in the base file")
        require(row["external_facility_id"] in external_ids, path, "external ID not in the batches")
        require((row["reviewer"] is None) == (row["reviewed_at"] is None), path, "reviewer and time go together")
        if row["status"] == "confirmed":
            require(row["method"] != "candidate_generation", path, "candidate generation cannot confirm")
            require(confirmed.setdefault(row["external_facility_id"], row["facility_id"]) == row["facility_id"],
                    path, "one external record confirmed for two base rows")
            require(row["method"] == "shared_identifier" or row["reviewer"] is not None, path,
                    "manual confirmation needs review metadata")
        if row["status"] in ("rejected", "conflict"):
            require(row["reviewer"] is not None, path, "rejection/conflict needs review metadata")
    for index, row in enumerate(batch["review_queue"]):
        path = f"review_queue[{index}]"
        require(row["facility_id"] is None or row["facility_id"] in base_index, path, "unknown base ID")
        require(row["match_id"] is None or row["match_id"] in match_ids, path, "unknown match ID")
        require((row["status"] == "resolved") == bool(row["resolution"]), path, "resolution must match status")


def execute(base, external_batches, mapping=None, attributes=None, policy=None, postal=None,
            postal_mapping=None, config=None, sample_size=50):
    """Pure function behind the CLI: returns every output as plain data."""
    base_index = base_check(base)
    base_digest = digest(base)
    external = combine_external(external_batches)
    mapping = check_mapping(mapping, base) if mapping is not None else default_mapping(base)
    policy = check_policy(policy or {})
    config = settings(config)
    bases = base_views(base, mapping)
    externals = external_views(external, attributes)
    postal_table = postal_profile = None
    if postal is not None:
        require(postal_mapping is not None, "postal_mapping", "required with --postal; use the observed postal columns")
        postal_table, postal_profile = aggregate(postal, postal_mapping)

    candidates = generate(bases, externals, policy, config)
    matches, reviews, candidates = build(candidates, bases, externals, policy)

    address_selector = mapping.get("address")
    base_address = lambda v: field_value(v["row"], address_selector) if isinstance(address_selector, str) else None
    base_geo, base_findings = screen(bases, "base", base_address, postal_table)
    external_geo, _ = screen(externals, "external", lambda v: v["row"]["address_original"], postal_table)
    geo_reviews = base_reviews(base_findings) + cluster_reviews(base_geo)

    batch = empty()
    batch["facility_matches"] = matches
    batch["review_queue"] = sorted(reviews + geo_reviews, key=lambda r: r["review_id"])
    schema_check(batch, "output")
    cross_check(batch, base_index, {e["id"] for e in externals})
    require(digest(base) == base_digest and len(base) == len(base_index), "base", "base changed during the run")

    chosen, sampling = sample(candidates, sample_size)
    with_candidates = {c["facility_id"] for c in candidates}
    auto = {c["facility_id"] for c in candidates if c["auto_confirmed"]}
    retrieved_external = {c["external_facility_id"] for c in candidates}
    report = {
        "matcher_version": MATCHER_VERSION, "contract_version": batch["contract_version"],
        "interpretation": "Retrieval coverage only. A candidate is not an identity decision and these counts are "
                          "not match precision. Precision is reported only for reviewed decisions (review_summary.json).",
        "base": {"denominator": len(base), "unit": "original base rows (unchanged)",
                 "rows_with_at_least_one_candidate": len(with_candidates),
                 "rows_with_automatic_shared_identifier_confirmation": len(auto),
                 "rows_without_any_candidate": len(base) - len(with_candidates),
                 "sha256_before": base_digest, "sha256_after": digest(base)},
        "external": {"denominator": len(externals), "unit": "external facility rows",
                     "rows_retrieved_as_candidate": len(retrieved_external),
                     "by_source_key": dict(sorted(Counter(e["source_key"] for e in externals).items()))},
        "matches": {"denominator": len(matches), "unit": "match rows",
                    "by_status": dict(sorted(Counter(m["status"] for m in matches).items())),
                    "by_method": dict(sorted(Counter(m["method"] for m in matches).items())),
                    "by_retrieval_reason": dict(sorted(Counter(c["retrieval_reason"] for c in candidates).items())),
                    "by_name_level": dict(sorted(Counter(c["signals"]["name_level"] for c in candidates).items())),
                    "by_stratum": dict(sorted(Counter(stratum(c) for c in candidates).items())),
                    "flag_counts": dict(sorted(Counter(f for c in candidates for f in c["flags"]).items()))},
        "review_queue": {"denominator": len(batch["review_queue"]), "unit": "open review items",
                         "by_reason": dict(sorted(Counter(r["reason_code"] for r in batch["review_queue"]).items())),
                         "by_severity": dict(sorted(Counter(r["severity"] for r in batch["review_queue"]).items()))},
        "review_sampling": sampling,
        "identity_policy_namespaces": sorted(policy),
        "base_mapping_roles": sorted(mapping),
        "settings": config,
        "table_counts": counts(batch),
    }
    geography = {"base": base_geo, "external": external_geo, "postal_profile": postal_profile,
                 "units": "Distances in match signals are metres (haversine on original coordinates)."}
    ledger = [{k: c[k] for k in ("match_id", "facility_id", "external_facility_id", "rank", "retrieval_reason",
                                 "signals", "flags", "auto_confirmed", "review_reason",
                                 "candidates_found_for_base", "candidates_kept_for_base",
                                 "other_candidates_for_base", "other_serious_candidates_for_base",
                                 "other_bases_for_external", "other_serious_bases_for_external")}
              for c in sorted(candidates, key=lambda c: c["match_id"])]
    return {"batch": batch, "candidates": ledger, "review_worksheet": worksheet(chosen, bases, externals),
            "geography_report": geography, "report": report}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.matching.run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="D's base adapter file: JSON array with unique facility_id")
    parser.add_argument("--external", required=True, action="append",
                        help="Contract v1.0.0 producer envelope; repeat for A and B batches")
    parser.add_argument("--output-dir", required=True, help="Directory for outputs; keep real runs under data/local/")
    parser.add_argument("--base-mapping", help="JSON object: role -> observed base column (dot paths allowed)")
    parser.add_argument("--external-attributes", help="JSON sidecar keyed by external_facility_id: aliases, phones, district")
    parser.add_argument("--identity-policy", help="D-format namespace policy enabling shared-identifier confirmation")
    parser.add_argument("--postal", help="JSON array of postal directory rows")
    parser.add_argument("--postal-mapping", help="JSON object: pin/state/district -> observed postal column")
    parser.add_argument("--config", help="JSON object overriding retrieval settings")
    parser.add_argument("--sample-size", type=int, default=50, help="Review sample limit (default 50)")
    args = parser.parse_args(argv)
    try:
        optional = lambda path: load(path) if path else None
        inputs = {"base": args.base, "external": args.external, "base_mapping": args.base_mapping,
                  "external_attributes": args.external_attributes, "identity_policy": args.identity_policy,
                  "postal": args.postal, "postal_mapping": args.postal_mapping, "config": args.config}
        out = Path(args.output_dir)
        named = [args.base] + args.external + [p for p in (args.base_mapping, args.external_attributes,
                 args.identity_policy, args.postal, args.postal_mapping, args.config) if p]
        require(out.resolve() not in {Path(p).resolve().parent for p in named}, "output-dir",
                "must not be a directory that holds an input file")
        result = execute(load(args.base), [load(p) for p in args.external], optional(args.base_mapping),
                         optional(args.external_attributes), optional(args.identity_policy),
                         optional(args.postal), optional(args.postal_mapping), optional(args.config),
                         args.sample_size)
        hashes = {name: write_json(out / f"{name}.json", result[name])
                  for name in ("batch", "candidates", "review_worksheet", "geography_report", "report")}
        manifest = {"matcher_version": MATCHER_VERSION,
                    "inputs_sha256": {key: ([file_digest(p) for p in value] if isinstance(value, list)
                                            else file_digest(value) if value else None)
                                      for key, value in sorted(inputs.items())},
                    "outputs_sha256": hashes, "sample_size": args.sample_size}
        write_json(out / "manifest.json", manifest)
        print(canonical({"status": "ok", "table_counts": result["report"]["table_counts"],
                         "base": result["report"]["base"], "matches": result["report"]["matches"]["by_status"],
                         "outputs_sha256": hashes}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
