"""Replay pinned editions against every original occurrence, without adjudication."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path
import urllib.request

from .parser import EDITIONS, FAMILY, compact, read_edition, state_key
from research.matching.national import NO_STATE, NOT_A_STATE, STATES as BASE_STATES, state_bucket
from research.matching.normalize import state_key as baseline_state_key


SERVICES = ("dialysis", "mri", "trauma_care")
NATIONAL_BASE_SHA = "27e4a79de42ec56c76cc676ed45494a52497d179858bc50549a461434c45e9d8"
POLICY_URL = "https://sansad.in/poi/privacyPolicy"


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def label_key(row):
    return row["state"], compact(row["name_printed"]), row["resource"]


def compare_editions(observations):
    grouped = defaultdict(list)
    for row in observations:
        grouped[row["edition"]].append(row)
    reports, details = [], []
    for left, right in combinations(sorted(grouped), 2):
        a, b = defaultdict(list), defaultdict(list)
        for r in grouped[left]:
            a[label_key(r)].append(r)
        for r in grouped[right]:
            b[label_key(r)].append(r)
        shared = sorted(set(a) & set(b))
        differences = 0
        paired = 0
        for key in shared:
            if len(a[key]) != 1 or len(b[key]) != 1:
                continue
            x, y = a[key][0], b[key][0]
            paired += 1
            # Distinct dated/undated assertions are retained, not overwritten.
            different = (x["functionality"] != "not_reported"
                         and y["functionality"] != "not_reported"
                         and x["functionality"] != y["functionality"])
            differences += int(different)
            details.append({"left": x["mention_id"], "right": y["mention_id"],
                            "basis": "exact compact printed name, same state and resource; unreviewed",
                            "different_functionality_assertions": different,
                            "same_date_conflict": different and x["effective_date"] is not None
                            and x["effective_date"] == y["effective_date"]})
        reports.append({
            "left": left, "right": right, "shared_label_resource_keys": len(shared),
            "unambiguous_label_pairs": paired,
            "left_only_label_keys": len(set(a) - set(b)),
            "right_only_label_keys": len(set(b) - set(a)),
            "ambiguous_shared_label_keys": len(shared) - paired,
            "different_functionality_assertions": differences,
            "same_origin": True,
            "interpretation": "label comparison only; aliases and historical boundary changes unresolved",
        })
    return reports, details


def national_run(base, observations, as_of):
    date.fromisoformat(as_of)
    ids = [r["facility_id"] for r in base]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Original occurrence keys must be unique and nonblank")
    source_ids = [r["source_row"]["unique_id"] for r in base]
    if any(i is None or not str(i).strip() for i in source_ids):
        raise ValueError("Original upstream IDs must be nonblank")
    by_label = defaultdict(list)
    base_label_ids = defaultdict(set)
    for item in base:
        raw = item["source_row"]
        base_label_ids[state_key(raw.get("address_stateOrRegion")), compact(raw.get("name"))].add(str(raw["unique_id"]))
    for row in observations:
        by_label[row["state"], compact(row["name_printed"])].append(row)
    candidates, decisions, geography = [], [], defaultdict(Counter)
    for bucket in sorted(BASE_STATES | {NO_STATE, NOT_A_STATE}):
        geography[bucket].update({"original_occurrences": 0, "candidate_occurrences": 0,
                                  **{s + "_unconfirmed": 0 for s in SERVICES}})
    reached = defaultdict(set)
    for item in base:
        original, fid = item["source_row"], item["facility_id"]
        state = state_key(original.get("address_stateOrRegion"))
        name = compact(original.get("name"))
        matches = by_label.get((state, name), []) if state and name else []
        bucket = state_bucket(baseline_state_key(original.get("address_stateOrRegion")))
        geography[bucket]["original_occurrences"] += 1
        geography[bucket]["candidate_occurrences"] += bool(matches)
        for row in matches:
            reached[row["edition"]].add(fid)
            candidates.append({"facility_id": fid, "mention_id": row["mention_id"],
                               "resource": row["resource"], "edition": row["edition"],
                               "basis": "exact compact name and normalized original state",
                               "status": "unreviewed_candidate", "campus_confirmed": False,
                               "ambiguous_original_label": len(base_label_ids[state, name]) > 1})
        for service in SERVICES:
            relevant = [r["mention_id"] for r in matches if r["resource"] == service]
            # This is the producer's incremental decision layer. Existing team
            # adjudications are not an input and are not rewritten by this tool.
            decisions.append({"facility_id": fid, "service": service, "status": "unconfirmed",
                              "as_of": as_of, "candidate_mentions": relevant,
                              "reason": "campus_and_service_review_required" if relevant else "no_reviewed_evidence_from_this_package"})
            geography[bucket][service + "_unconfirmed"] += 1
    old = reached.get("freeze65", set())
    new = set().union(*(v for k, v in reached.items() if k != "freeze65")) if reached else set()
    report = {
        "original_occurrences": len(base), "distinct_upstream_ids": len(set(source_ids)),
        "extra_identical_occurrences_preserved": len(base) - len(set(source_ids)),
        "occurrence_service_decisions": len(decisions), "decisions_per_service": len(base),
        "decision_scope": "incremental producer layer only; existing adjudications unchanged",
        "candidate_edges": len(candidates), "candidate_occurrences": len({r["facility_id"] for r in candidates}),
        "ambiguous_label_candidate_occurrences": len({r["facility_id"] for r in candidates if r["ambiguous_original_label"]}),
        "candidate_distinct_upstream_ids": len({str(r["source_row"]["unique_id"]) for r in base if any(r["facility_id"] in s for s in reached.values())}),
        "candidate_occurrences_by_edition": {k: len(reached.get(k, set())) for k in EDITIONS},
        "new_candidate_occurrences_beyond_freeze65": len(new - old),
        "shared_candidate_occurrences_with_freeze65": len(new & old),
        "confirmed_campus_links": 0, "incremental_confirmed_campus_service_pairs": 0,
        "unconfirmed_decisions": len(decisions), "yes_decisions": 0, "no_decisions": 0,
        "geography": {k: dict(v) for k, v in sorted(geography.items())},
        "geography_policy": "Existing national matcher state_bucket over original labels; both missing and non-state buckets retained. Candidate-only source spelling normalization does not rewrite this baseline geography.",
        "candidate_limitations": "Exact label/state comparison is conservative; aliases, renamed campuses, name collisions and historical state changes require Vincent's identity review. Zero candidates is not evidence of absent care.",
    }
    return report, candidates, decisions


def summarize(observations):
    out = {}
    for edition in EDITIONS:
        rows = [r for r in observations if r["edition"] == edition]
        keys = {label_key(r) for r in rows}
        out[edition] = {
            "raw_mentions": len(rows), "unique_label_resource_observations": len(keys),
            "duplicate_label_resource_mentions": len(rows) - len(keys),
            "observed_state_labels_normalized": len({r["state"] for r in rows}),
            "resource_status_counts": dict(sorted(Counter(r["resource"] + ":" + r["functionality"] for r in rows).items())),
            "programme_stage_counts": dict(sorted(Counter(r["programme_stage"] for r in rows).items())),
            "by_state_resource_status": [
                {"state": s, "resource": r, "status": st, "mentions": count}
                for (s, r, st), count in sorted(Counter((r["state"], r["resource"], r["functionality"]) for r in rows).items())],
        }
    keys = {label_key(r) for r in observations}
    old_keys = {label_key(r) for r in observations if r["edition"] == "freeze65"}
    incremental = {(label_key(r), r["functionality"]) for r in observations
                   if r["edition"] != "freeze65" and label_key(r) not in old_keys}
    return {"raw_mentions": len(observations), "unique_label_resource_keys_across_editions": len(keys),
            "new_label_resource_status_keys_beyond_freeze65": dict(sorted(Counter(
                key[2] + ":" + status for key, status in incremental).items())),
            "unique_reviewed_campus_service_pairs": 0, "independent_upstream_origins": 1,
            "source_family": FAMILY, "editions": out,
            "grain_note": "A label-resource key is not a verified campus. Raw mentions remain intact; editions of the same ministry return are one origin."}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = encoded(data)
    path.write_bytes(payload)
    return {"bytes": len(payload), "sha256": sha(payload),
            "records": len(data) if isinstance(data, list) else None}


def acquire(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for key, spec in EDITIONS.items():
        path = directory / spec["file"]
        if path.exists():
            if sha(path.read_bytes()) != spec["sha256"]:
                raise ValueError("Existing source bytes changed; preserve and review a new edition")
            continue
        with urllib.request.urlopen(spec["url"], timeout=45) as response:
            payload = response.read(25_000_001)
        if len(payload) > 25_000_000 or sha(payload) != spec["sha256"]:
            raise ValueError("Upstream bytes differ; review the new edition before parsing")
        path.write_bytes(payload)
        save(directory / (spec["file"] + ".receipt.json"), {
            "file": spec["file"], "url": spec["url"], "bytes": len(payload),
            "sha256": spec["sha256"], "retrieved_at": datetime.now(timezone.utc).isoformat()})


def build(args):
    raw_base = args.base.read_bytes()
    manifest = json.loads(args.prepared_manifest.read_text())
    if sha(raw_base) != NATIONAL_BASE_SHA or manifest["files"]["base.json"] != NATIONAL_BASE_SHA:
        raise ValueError("Not the verified, original occurrence-preserving national base")
    base = json.loads(raw_base)
    if len(base) != 10088 or len({r["source_row"]["unique_id"] for r in base}) != 10077:
        raise ValueError("National denominator changed")
    observations, editions = [], []
    for key, spec in EDITIONS.items():
        receipt_path = args.sources / (spec["file"] + ".receipt.json")
        receipt = json.loads(receipt_path.read_text())
        retrieved = receipt["retrieved_at"]
        if datetime.fromisoformat(retrieved.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("Retrieval timestamp needs a timezone")
        if receipt["sha256"] != spec["sha256"] or receipt["url"] != spec["url"]:
            raise ValueError("Source receipt does not match reviewed edition")
        rows = read_edition(args.sources, key)
        for row in rows:
            row["retrieved_at"] = retrieved
        observations.extend(rows)
        editions.append({"edition": key, **spec, "retrieved_at": retrieved,
                         "bytes": (args.sources / spec["file"]).stat().st_size,
                         "source_family": FAMILY, "raw_mentions": len(rows),
                         "raw_and_printed_text_disposition": "held_local_permission_unconfirmed",
                         "sharing": "provenance and aggregate statistics only",
                         "reuse_policy": POLICY_URL if key != "freeze65" else "https://github.com/vzhu08/databricks-datathon/issues/65#issuecomment-7069678017"})
    report, candidates, decisions = national_run(base, observations, args.as_of)
    comparisons, details = compare_editions(observations)
    report.update({"source_summary": summarize(observations), "edition_comparisons": comparisons,
                   "base_sha256": NATIONAL_BASE_SHA, "as_of": args.as_of,
                   "live_availability": "not_established", "submission": "not_performed"})
    private = args.output / "local-only"
    for name, data in [("observations.json", observations), ("candidate_links.json", candidates),
                       ("service_decisions.json", decisions), ("edition_pairs.json", details)]:
        save(private / name, data)
    # Public-source printed names and original VF values never enter staging.
    shared = args.output / "shareable"
    files = {name: save(shared / name, data) for name, data in
             [("aggregate-report.json", report), ("edition-provenance.json", editions)]}
    # Curated metadata ships with this reader. Never accept an arbitrary input
    # document into a package that promises to exclude source rows and contacts.
    gaps = json.loads(Path(__file__).with_name("source_gaps.json").read_text())
    files["source-gaps.json"] = save(shared / "source-gaps.json", gaps)
    package = {"format": "trauma-support-164-1.0", "issue": 164, "files": files,
               "population": {"occurrences": 10088, "distinct_source_ids": 10077, "decisions": 30264},
               "sharing_scope": "private team: Vincent, Oliver, Andrew, Ayush",
               "contents": "provenance, aggregate statistics and source-access gaps only; no raw PDFs, printed facility names, VF rows or contacts",
               "excluded": "local-only observations, candidates, per-occurrence decisions and edition pairs",
               "original_lineage": {"facilities_delta_version": 0, "base_sha256": NATIONAL_BASE_SHA},
               "replay_code_sha256": {str(p): sha(p.read_bytes()) for p in [
                   Path("research/acquisition/trauma_support/parser.py"),
                   Path("research/acquisition/trauma_support/packet.py"),
                   Path("research/acquisition/trauma_support/source_gaps.json"),
                   Path("research/trauma/national/parser.py"),
                   Path("research/matching/normalize.py"),
                   Path("research/matching/national.py")]},
               "intended_volume": "/Volumes/workspace/default/datathon_vf_research_intake/",
               "remote_verification": "pending writer receipt"}
    saved = save(shared / "manifest.json", package)
    print(json.dumps({"manifest_sha256": saved["sha256"], "mentions": len(observations),
                      "candidate_edges": len(candidates), "decisions": len(decisions)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("acquire")
    download.add_argument("--sources", required=True, type=Path)
    replay = sub.add_parser("build")
    replay.add_argument("--sources", required=True, type=Path)
    replay.add_argument("--base", required=True, type=Path)
    replay.add_argument("--prepared-manifest", required=True, type=Path)
    replay.add_argument("--as-of", required=True)
    replay.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    acquire(args.sources) if args.command == "acquire" else build(args)


if __name__ == "__main__":
    main()
