#!/usr/bin/env python3
"""NAT-C01 nationwide run: one output row for every original base row.

    python -m research.matching.national --base <file> --external <batch> --output-dir <path>

Wraps `research.matching.run.execute`. Base rows that repeat one full payload
under different row handles are matched once, and that result is copied to
every handle in the group. A repeated row therefore never competes with its
own copy and never counts as independent evidence or as a second campus.
Inputs are never modified. Outputs describe retrieval, not reviewed identity.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import MATCHER_VERSION
from .base_adapter import base_views, check_mapping, default_mapping, mapping_from_source_metadata
from .common import (MatchingError, base_check, canonical, digest, file_digest, load, require,
                     write_json)
from .normalize import state_key
from .run import execute

NATIONAL_VERSION = "national-matching-1.0.0"
OUTCOMES = ("confirmed", "ambiguous", "candidate_only", "unmatched")
NO_STATE = "(no state label)"
AMBIGUOUS_REASONS = {"ambiguous_campus", "identifier_not_unique", "identifier_campus_conflict",
                     "identifier_conflict"}
RUN_OUTPUTS = ("batch", "candidates", "review_worksheet", "geography_report", "report")
NATIONAL_OUTPUTS = ("base_rows", "duplicate_groups", "missed_sample", "national_report")


def payload_digest(row):
    """Hash of everything in a base row except its row handle."""
    return digest({key: value for key, value in row.items() if key != "facility_id"})


def duplicate_groups(base):
    """Groups of two or more base rows that carry one identical payload.

    The first handle in sorted order stands for the group in matching. Members
    are interchangeable copies; the choice carries no meaning.
    """
    buckets = defaultdict(list)
    for row in base:
        buckets[payload_digest(row)].append(row["facility_id"])
    groups = []
    for key, members in buckets.items():
        if len(members) > 1:
            members = sorted(members)
            groups.append({"group_id": f"base-payload:{key}", "representative": members[0],
                           "members": members, "multiplicity": len(members)})
    return sorted(groups, key=lambda g: g["group_id"])


def sidecar_groups(sidecar):
    """Row-handle sets from D's duplicate-group sidecar.

    Accepts an array of groups, or an object holding exactly one such array.
    A group is an array of handles or an object with exactly one array of handles.
    """
    def handles(value, path):
        if isinstance(value, dict):
            lists = [v for v in value.values() if isinstance(v, list) and v and all(isinstance(x, str) for x in v)]
            require(len(lists) == 1, path, "a group object needs exactly one array of row handles")
            value = lists[0]
        require(isinstance(value, list) and len(value) > 1 and all(isinstance(x, str) and x for x in value)
                and len(set(value)) == len(value), path, "a group needs two or more distinct row handles")
        return frozenset(value)

    if isinstance(sidecar, dict):
        arrays = [v for v in sidecar.values() if isinstance(v, list) and all(isinstance(x, (list, dict)) for x in v)]
        require(len(arrays) == 1, "duplicate_groups", "expected one array of groups")
        sidecar = arrays[0]
    require(isinstance(sidecar, list), "duplicate_groups", "expected an array of groups")
    found = [handles(item, f"duplicate_groups[{position}]") for position, item in enumerate(sidecar)]
    require(len(set(found)) == len(found), "duplicate_groups", "a group is listed twice")
    return set(found)


def _source_keys(external_batches):
    snapshots, by_external = {}, {}
    for batch in external_batches:
        for snap in batch.get("source_snapshots", []):
            snapshots[snap["snapshot_id"]] = snap["source_key"]
    for batch in external_batches:
        for row in batch.get("external_facilities", []):
            by_external[row["external_facility_id"]] = snapshots.get(row["snapshot_id"], "(unknown source)")
    return by_external


def _outcome(candidates):
    if not candidates:
        return "unmatched"
    if any(c["auto_confirmed"] for c in candidates):
        return "confirmed"
    if any("ambiguous_campus" in c["flags"] or c["review_reason"] in AMBIGUOUS_REASONS for c in candidates):
        return "ambiguous"
    return "candidate_only"


def _tally(rows, key):
    """Outcome counts per `key(row)` with both denominators."""
    table = {}
    for row in rows:
        for label in key(row):
            entry = table.setdefault(label, {"original_rows": 0, "distinct_payloads": 0, "rows_with_input_problem": 0,
                                             **{outcome: 0 for outcome in OUTCOMES}})
            entry["original_rows"] += 1
            entry["distinct_payloads"] += row["facility_id"] == row["matched_as"]
            entry["rows_with_input_problem"] += bool(row["input_problems"])
            entry[row["outcome"]] += 1
    return dict(sorted(table.items()))


def _missed_sample(rows, limit):
    """Up to `limit` unmatched rows, round-robin across states. Order inside a
    state is the SHA-256 of the row handle: arbitrary and repeatable."""
    require(isinstance(limit, int) and limit >= 0, "missed_sample_size", "non-negative integer required")
    by_state = defaultdict(list)
    for row in rows:
        if row["outcome"] == "unmatched" and row["facility_id"] == row["matched_as"]:
            by_state[row["state"]].append(row)
    for members in by_state.values():
        members.sort(key=lambda r: digest(r["facility_id"]))
    chosen, depth, states = [], 0, sorted(by_state)
    while len(chosen) < limit and any(depth < len(by_state[s]) for s in states):
        for s in states:
            if depth < len(by_state[s]) and len(chosen) < limit:
                chosen.append(by_state[s][depth])
        depth += 1
    return {"unit": "unmatched distinct payloads", "available": sum(len(m) for m in by_state.values()),
            "sampled": len(chosen), "method": "round-robin across states; SHA-256 order of the row handle inside a state",
            "rows": [{k: r[k] for k in ("facility_id", "state", "input_problems", "duplicate_group")} for r in chosen]}


def execute_national(base, external_batches, mapping=None, attributes=None, policy=None, postal=None,
                     postal_mapping=None, config=None, sample_size=50, source_metadata=None,
                     duplicate_sidecar=None, expect_duplicate_groups=None, state=None, missed_sample_size=50):
    """Pure function behind the CLI. `state` limits the run to base rows with
    that state label (the scoped pilot); identical copies always stay together."""
    index = base_check(base)
    before = digest(base)
    if source_metadata is not None:
        mapping = {**mapping_from_source_metadata(source_metadata, base), **(mapping or {})}
    mapping = check_mapping(mapping, base) if mapping is not None else default_mapping(base)

    groups = duplicate_groups(base)
    if duplicate_sidecar is not None:
        require(sidecar_groups(duplicate_sidecar) == {frozenset(g["members"]) for g in groups}, "duplicate_groups",
                "the sidecar disagrees with the identical-payload groups found in the base")
    if expect_duplicate_groups is not None:
        require(len(groups) == expect_duplicate_groups, "duplicate_groups",
                f"found {len(groups)} identical-payload groups, expected {expect_duplicate_groups}")
    group_of = {member: group for group in groups for member in group["members"]}

    views = {view["id"]: view for view in base_views(base, mapping)}
    scope = {"state": None, "unit": "all original base rows"}
    in_scope = base
    if state is not None:
        wanted = state_key(state)
        require(wanted is not None, "state", "a state name is required")
        in_scope = [row for row in base if views[row["facility_id"]]["state"] == wanted]
        require(bool(in_scope), "state", "no base row carries this state label")
        scope = {"state": wanted, "unit": "original base rows with this state label"}
    representative = lambda fid: group_of[fid]["representative"] if fid in group_of else fid
    unique_rows = [row for row in in_scope if representative(row["facility_id"]) == row["facility_id"]]

    result = execute(unique_rows, external_batches, mapping, attributes, policy, postal, postal_mapping,
                     config, sample_size)
    require(digest(base) == before and len(base) == len(index), "base", "base changed during the run")

    source_of = _source_keys(external_batches)
    by_base = defaultdict(list)
    for candidate in result["candidates"]:
        by_base[candidate["facility_id"]].append(candidate)
    problems = defaultdict(set)
    for item in result["batch"]["review_queue"]:
        if item["facility_id"] is not None and item["match_id"] is None and item["reason_code"].startswith("base_") \
                and item["reason_code"] != "base_duplicate_coordinate_cluster":
            problems[item["facility_id"]].add(item["reason_code"][len("base_"):])
    for view in views.values():
        if not view["names"]:
            problems[view["id"]].add("name_missing")
        if "coordinates_missing" in view["coord"]["flags"]:
            problems[view["id"]].add("coordinates_missing")

    rows = []
    for row in in_scope:
        fid = row["facility_id"]
        matched_as = representative(fid)
        found = by_base.get(matched_as, [])
        group = group_of.get(fid)
        per_source = {}
        for key in sorted({source_of[c["external_facility_id"]] for c in found}):
            per_source[key] = _outcome([c for c in found if source_of[c["external_facility_id"]] == key])
        rows.append({
            "facility_id": fid, "matched_as": matched_as,
            "duplicate_group": group["group_id"] if group else None,
            "duplicate_multiplicity": group["multiplicity"] if group else 1,
            "state": views[fid]["state"] or NO_STATE,
            "outcome": _outcome(found), "candidate_count": len(found),
            "outcome_by_source": per_source,
            "confirmed_external_facility_ids": sorted(c["external_facility_id"] for c in found if c["auto_confirmed"]),
            "input_problems": sorted(problems.get(matched_as, ())),
        })
    require(len(rows) == len(in_scope) and len({r["facility_id"] for r in rows}) == len(rows), "base_rows",
            "every original row in scope must have exactly one output row")

    by_source = {}
    reference_counts = result["report"]["external"]["by_source_key"]
    retrieved = Counter(source_of[e] for e in {c["external_facility_id"] for c in result["candidates"]})
    for key in sorted(reference_counts):
        entry = {"reference_rows": reference_counts[key], "reference_rows_retrieved": retrieved.get(key, 0),
                 "original_rows": len(rows), "distinct_payloads": len(unique_rows),
                 **{outcome: 0 for outcome in OUTCOMES}}
        for row in rows:
            entry[row["outcome_by_source"].get(key, "unmatched")] += 1
        by_source[key] = entry
    overlap = Counter(len(row["outcome_by_source"]) for row in rows)
    in_scope_groups = [g for g in groups if g["representative"] in {r["facility_id"] for r in rows}]
    national_report = {
        "national_version": NATIONAL_VERSION, "matcher_version": MATCHER_VERSION,
        "interpretation": "Retrieval outcomes only. 'confirmed' means an automatic shared-identifier confirmation "
                          "under the supplied identity policy; nothing here is a reviewed identity decision. "
                          "Identical repeated rows share one result and are not independent evidence.",
        "scope": scope,
        "denominators": {"original_rows": len(rows), "distinct_payloads": len(unique_rows),
                         "original_rows_in_base_file": len(base),
                         "identical_payload_groups": len(in_scope_groups),
                         "rows_in_identical_payload_groups": sum(g["multiplicity"] for g in in_scope_groups)},
        "outcomes": {"unit": "original rows", **{o: sum(r["outcome"] == o for r in rows) for o in OUTCOMES}},
        "outcomes_distinct_payloads": {"unit": "distinct payloads",
                                       **{o: sum(r["outcome"] == o and r["facility_id"] == r["matched_as"] for r in rows)
                                          for o in OUTCOMES}},
        "input_problems": {"unit": "original rows; a row can have several problems and also have candidates",
                           "rows_with_any": sum(bool(r["input_problems"]) for r in rows),
                           "by_problem": dict(sorted(Counter(p for r in rows for p in r["input_problems"]).items()))},
        "by_state": _tally(rows, lambda r: [r["state"]]),
        "by_source": by_source,
        "source_overlap": {"unit": "original rows by number of sources that returned a candidate",
                           **{str(n): overlap[n] for n in sorted(overlap)}},
        "base_sha256": before,
        "run_report": {k: result["report"][k] for k in ("matches", "review_queue", "identity_policy_namespaces",
                                                        "base_mapping_roles", "settings", "table_counts")},
    }
    return {**{name: result[name] for name in RUN_OUTPUTS}, "base_rows": rows,
            "duplicate_groups": groups, "missed_sample": _missed_sample(rows, missed_sample_size),
            "national_report": national_report}


def _peak_memory_mb():
    try:
        import resource
    except ImportError:          # not available on Windows
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.matching.national", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="D's base adapter file: JSON array with unique facility_id")
    parser.add_argument("--external", required=True, action="append", help="Contract v1.0.0 producer envelope; repeatable")
    parser.add_argument("--output-dir", required=True, help="Directory for outputs; keep real runs under data/local/")
    parser.add_argument("--source-metadata", help="D's source_metadata.json for this base")
    parser.add_argument("--base-mapping", help="JSON object: role -> observed base column; adds to --source-metadata")
    parser.add_argument("--external-attributes", help="JSON sidecar keyed by external_facility_id")
    parser.add_argument("--identity-policy", help="D-format namespace policy enabling shared-identifier confirmation")
    parser.add_argument("--postal", help="JSON array of postal directory rows")
    parser.add_argument("--postal-mapping", help="JSON object: pin/state/district -> observed postal column")
    parser.add_argument("--config", help="JSON object overriding retrieval settings")
    parser.add_argument("--duplicate-groups", help="D's duplicate-group sidecar; must agree with the groups found in the base")
    parser.add_argument("--expect-duplicate-groups", type=int, help="Fail unless exactly this many identical-payload groups exist")
    parser.add_argument("--state", help="Limit the run to base rows with this state label (scoped pilot)")
    parser.add_argument("--sample-size", type=int, default=50, help="Candidate review sample limit (default 50)")
    parser.add_argument("--missed-sample-size", type=int, default=50, help="Unmatched-row sample limit (default 50)")
    args = parser.parse_args(argv)
    try:
        optional = lambda path: load(path) if path else None
        inputs = {"base": args.base, "external": args.external, "base_mapping": args.base_mapping,
                  "source_metadata": args.source_metadata, "external_attributes": args.external_attributes,
                  "identity_policy": args.identity_policy, "postal": args.postal,
                  "postal_mapping": args.postal_mapping, "config": args.config,
                  "duplicate_groups": args.duplicate_groups}
        out = Path(args.output_dir)
        named = [p for value in inputs.values() if value for p in (value if isinstance(value, list) else [value])]
        require(out.resolve() not in {Path(p).resolve().parent for p in named}, "output-dir",
                "must not be a directory that holds an input file")
        started = time.perf_counter()
        base, external = load(args.base), [load(p) for p in args.external]
        loaded = time.perf_counter()
        result = execute_national(base, external, optional(args.base_mapping), optional(args.external_attributes),
                                  optional(args.identity_policy), optional(args.postal),
                                  optional(args.postal_mapping), optional(args.config), args.sample_size,
                                  optional(args.source_metadata), optional(args.duplicate_groups),
                                  args.expect_duplicate_groups, args.state, args.missed_sample_size)
        finished = time.perf_counter()
        hashes = {name: write_json(out / f"{name}.json", result[name]) for name in RUN_OUTPUTS + NATIONAL_OUTPUTS}
        # Timing and memory depend on the machine, so they stay out of the hashed outputs.
        manifest = {"national_version": NATIONAL_VERSION, "matcher_version": MATCHER_VERSION,
                    "inputs_sha256": {key: ([file_digest(p) for p in value] if isinstance(value, list)
                                            else file_digest(value) if value else None)
                                      for key, value in sorted(inputs.items())},
                    "outputs_sha256": hashes, "state": args.state, "sample_size": args.sample_size,
                    "missed_sample_size": args.missed_sample_size,
                    "expect_duplicate_groups": args.expect_duplicate_groups}
        write_json(out / "manifest.json", manifest)
        write_json(out / "timing.json", {"load_seconds": round(loaded - started, 2),
                                         "match_seconds": round(finished - loaded, 2),
                                         "peak_memory_mb": _peak_memory_mb(),
                                         "note": "Machine-dependent; not part of the reproducible outputs."})
        report = result["national_report"]
        print(canonical({"status": "ok", "denominators": report["denominators"], "outcomes": report["outcomes"],
                         "input_problems": report["input_problems"]["rows_with_any"],
                         "match_seconds": round(finished - loaded, 2), "peak_memory_mb": _peak_memory_mb(),
                         "outputs_sha256": hashes}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
