"""Sample a pinned national candidate trace locally. This tool never makes queries."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import unicodedata

from research.matching.common import digest
from research.matching.national import state_bucket
from research.matching.normalize import state_key


SEED = "issue-251-v1"
TYPES = {"hospital", "clinic", "dentist", "doctor", "pharmacy", "nursing_home"}


def name_key(text):
    text = unicodedata.normalize("NFKC", text).casefold() if isinstance(text, str) else ""
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sample(rows, limit):
    groups = defaultdict(list)
    for row in rows:
        groups[row["stratum"]].append(row)
    selected = []
    for stratum in sorted(groups):
        strata = defaultdict(list)
        for row in groups[stratum]:
            strata[row["state"], row["type"]].append(row)
        for bucket in strata.values():
            bucket.sort(key=lambda row: sha(f"{SEED}:{row['occurrence']}".encode()))
        order = sorted(strata, key=lambda k: sha(f"{SEED}:{stratum}:{k}".encode()))
        # Round-robin distinct states before giving another slot to the same state.
        used_representatives = set()
        state_counts, type_counts = Counter(), Counter()
        for _ in range(limit):
            available = [(k, r) for k in order for r in strata[k]
                         if r["representative"] not in used_representatives]
            if not available:
                break
            k, row = min(available, key=lambda item: (
                state_counts[item[0][0]], type_counts[item[0][1]]))
            selected.append(row)
            used_representatives.add(row["representative"])
            state_counts[k[0]] += 1
            type_counts[k[1]] += 1
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--public-controls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base_bytes, trace_bytes = args.base.read_bytes(), args.trace.read_bytes()
    base = json.loads(base_bytes)
    trace = [json.loads(line) for line in gzip.decompress(trace_bytes).splitlines()]
    by_id = {r["facility_id"]: r for r in trace}
    base_ids = {r["facility_id"] for r in base}
    upstream = {r["source_row"]["unique_id"] for r in base}
    if len(base) != 10088 or len(trace) != len(base) or len(base_ids) != len(trace) or set(by_id) != base_ids or len(upstream) != 10077:
        raise ValueError("Frozen occurrence frame does not reconcile")

    controls = json.loads(args.public_controls.read_text())
    control_names = [{name_key(name) for name in control["names"]} - {""} for control in controls]
    control_matches = defaultdict(list)
    frame = []
    for row in base:
        key = row["facility_id"]
        upstream_row = row["source_row"]
        context = by_id[key]
        if digest(upstream_row) != context["original_payload_sha256"]:
            raise ValueError("Frozen original payload differs from trace")
        candidate = context["outcomes"]["joint"]
        if candidate == "unmatched":
            stratum = "older_joint_missed"
        elif "competing_campuses" in context["conflicts"]["joint"]:
            stratum = "older_joint_competing"
        else:
            stratum = "other_reached"
        raw_state = upstream_row.get("address_stateOrRegion")
        raw_type = upstream_row.get("facilityTypeId")
        for i, control in enumerate(controls):
            if (name_key(upstream_row.get("name")) in control_names[i]
                    and str(upstream_row.get("address_zipOrPostcode")).strip() == control["pin"]):
                control_matches[i].append(key)
        frame.append({"occurrence": key, "representative": context["representative"],
                      "stratum": stratum, "state": state_bucket(state_key(raw_state if isinstance(raw_state, str) else None)),
                      "type": raw_type if isinstance(raw_type, str) and raw_type in TYPES else "other_or_unknown",
                      "google_status": "unknown_no_lookup_log"})

    chosen = sample([r for r in frame if r["stratum"] != "other_reached"], 12)
    linked = {keys[0] for keys in control_matches.values() if len(keys) == 1}
    selected_linked = sum(r["occurrence"] in linked for r in chosen)
    summary = {"seed": SEED, "base_sha256": sha(base_bytes), "trace_sha256": sha(trace_bytes),
               "public_controls_sha256": sha(args.public_controls.read_bytes()),
               "occurrences": len(frame), "upstream_ids": len(upstream), "service_decision_denominator": len(frame)*3,
               "frame": dict(Counter(r["stratum"] for r in frame)),
               "sample": dict(Counter(r["stratum"] for r in chosen)),
               "sample_google_status": dict(Counter(r["google_status"] for r in chosen)),
               "sample_state_buckets": len({r["state"] for r in chosen}),
               "sample_type_buckets": dict(Counter(r["type"] for r in chosen)),
               "selected_with_unique_public_control": selected_linked,
               "selected_without_public_control": len(chosen)-selected_linked,
               "public_controls_tested_for_local_linkage": len(controls),
               "public_controls_with_exact_name_pin_candidates": sum(bool(v) for v in control_matches.values()),
               "public_controls_with_one_occurrence_candidate": sum(len(v)==1 for v in control_matches.values())}
    with args.output.open("x") as f:
        json.dump({"summary": summary, "sample_private": chosen}, f, indent=2, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
