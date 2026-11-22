"""Validate and stratify an immutable, privately held decision frame.

This is L's internal adapter format, not a replacement for D's ledger contract.
No acquisition, linkage, model fitting, or scoring of sealed labels occurs here.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
from pathlib import Path

SERVICES = {"dialysis", "mri", "trauma_care"}
STATUSES = {"yes", "no", "unconfirmed"}
SCHEMA = "l-readiness-frame-v1"
SEED = "service-readiness-audit-168-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identifier(value, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and bool(value.strip()))


def sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate(frame, *, fixture=False):
    require(frame.get("schema") == SCHEMA, "unsupported frame schema")
    require(sha256(frame.get("freeze_sha256")), "freeze SHA-256 required")
    require(sha256(frame.get("original_payload_multiset_sha256")), "original payload multiset SHA-256 required")
    inputs = frame.get("input_hashes")
    require(isinstance(inputs, dict) and inputs and all(identifier(k) and sha256(v) for k, v in inputs.items()),
            "input artifact hashes required")
    rows = frame.get("decisions")
    require(isinstance(rows, list) and rows, "nonempty decision frame required")
    keys, occurrences, identities = set(), defaultdict(set), {}
    for row in rows:
        key, source_id, service = row.get("occurrence_key"), row.get("source_id"), row.get("service")
        require(identifier(key) and identifier(source_id), "occurrence key and source ID required")
        require(service in SERVICES and row.get("status") in STATUSES, "invalid service or status")
        require((key, service) not in keys, "duplicate occurrence/service decision")
        keys.add((key, service))
        occurrences[key].add(service)
        for field in ("state", "region"):
            require(field in row and identifier(row[field], nullable=True), "explicit state and region required")
        identity = (source_id, row["state"], row["region"])
        require(key not in identities or identities[key] == identity, "inconsistent occurrence identity/geography")
        identities[key] = identity
        require("conflict" in row and (row["conflict"] is None or type(row["conflict"]) is bool),
                "conflict must be true, false, or null")
        mentions = row.get("mentions")
        require(isinstance(mentions, list), "mentions must be an array, including when empty")
        mention_ids, origins = set(), set()
        for mention in mentions:
            mid = mention.get("mention_id")
            require(identifier(mid) and mid not in mention_ids, "duplicate or missing mention ID within decision")
            mention_ids.add(mid)
            for field in ("claimant_id", "origin_id", "campus_id", "observation_id"):
                require(field in mention and identifier(mention[field], nullable=True), "explicit mention identity fields required")
            require("observed_on" in mention, "explicit observation date required")
            if mention["observed_on"] is not None:
                require(isinstance(mention["observed_on"], str), "invalid observation date")
                require(date.fromisoformat(mention["observed_on"]).isoformat() == mention["observed_on"], "ISO date required")
            if mention["origin_id"] is not None:
                origins.add(mention["origin_id"])
        independent = row.get("independent_origin_ids")
        require("independent_origin_ids" in row and (independent is None or isinstance(independent, list)),
                "explicit reviewed independent origins or null required")
        if independent is not None:
            require(all(identifier(o) for o in independent), "invalid independent origin ID")
            require(len(set(independent)) == len(independent) and set(independent) <= origins,
                    "independent origins must be distinct, observed origins")
            if independent:
                require(identifier(row.get("independence_review_ref")), "independence review reference required")
    require(all(v == SERVICES for v in occurrences.values()), "every occurrence must retain all three service decisions")
    multiplicities = Counter(Counter(v[0] for v in identities.values()).values())
    if not fixture:
        require(len(occurrences) == 10088 and len(rows) == 30264, "national occurrence/decision denominator mismatch")
        require(multiplicities == {1: 10066, 2: 11}, "national source-ID multiplicities mismatch")
    return {"occurrences": len(occurrences), "distinct_source_ids": sum(multiplicities.values()),
            "decisions": len(rows), "source_id_multiplicities": dict(sorted(multiplicities.items()))}


def time_bucket(mentions, as_of):
    if not mentions:
        return "no_mentions"
    known = [date.fromisoformat(m["observed_on"]) for m in mentions if m["observed_on"] is not None]
    if any(d > as_of for d in known):
        return "future_present"
    if len(known) != len(mentions):
        return "date_unknown" if not known else "partly_undated"
    recent = [0 <= (as_of - d).days <= 365 for d in known]
    return "recent" if all(recent) else "historical" if not any(recent) else "mixed_periods"


def dimensions(row, as_of):
    mentions = row["mentions"]
    claimants = {m["claimant_id"] for m in mentions if m["claimant_id"] is not None}
    origins = Counter(m["origin_id"] for m in mentions if m["origin_id"] is not None)
    claimant_bucket = ("none" if not mentions else "unknown" if any(m["claimant_id"] is None for m in mentions)
                       else "one" if len(claimants) == 1 else "multiple")
    origin_bucket = ("none" if not mentions else "unknown" if any(m["origin_id"] is None for m in mentions)
                     else "reviewed_independent_multiple" if len(row["independent_origin_ids"] or []) >= 2
                     else "multiple_unresolved" if len(origins) > 1 else "single_origin")
    repeated = "present" if any(n > 1 for n in origins.values()) else "unknown" if any(m["origin_id"] is None for m in mentions) else "absent"
    conflict = "unknown" if row["conflict"] is None else "present" if row["conflict"] else "absent"
    return {"service": row["service"], "region": row["region"] or "unknown",
            "status": row["status"], "time": time_bucket(mentions, as_of),
            "claimants": claimant_bucket, "origins": origin_bucket, "repeated_origin": repeated,
            "conflict": conflict}


def coverage(rows, as_of):
    counts = defaultdict(Counter)
    raw = 0
    mentions, observations, origins, independent_origins = set(), set(), set(), set()
    unattributed = 0
    for row in rows:
        for field, value in dimensions(row, as_of).items():
            counts[field][value] += 1
        counts["state"][row["state"] or "unknown"] += 1
        independent_origins.update(row["independent_origin_ids"] or [])
        for m in row["mentions"]:
            raw += 1
            mentions.add(m["mention_id"])
            if m["origin_id"] is not None:
                origins.add(m["origin_id"])
            if m["campus_id"] is not None and m["observation_id"] is not None:
                observations.add((m["campus_id"], row["service"], m["observation_id"]))
            else:
                unattributed += 1
    return {"decision_margins": {k: dict(sorted(v.items())) for k, v in sorted(counts.items())},
            "mention_assignments": raw, "unique_mention_ids": len(mentions),
            "attributed_campus_service_observations": len(observations),
            "unattributed_mention_assignments": unattributed,
            "known_origins": len(origins), "reviewed_independent_origin_ids": len(independent_origins),
            "incremental_coverage": None, "incremental_coverage_reason": "requires baseline comparison and approved campus links"}


def build_plan(frame, *, as_of, target=30, seed=SEED, fixture=False):
    denominator = validate(frame, fixture=fixture)
    day = date.fromisoformat(as_of)
    require(type(target) is int and target > 0 and identifier(seed), "positive target and nonempty seed required")
    rows = frame["decisions"]
    # Canonical order makes input serialization order irrelevant; the CLI also pins exact bytes.
    frame_hash = digest({**frame, "decisions": sorted(rows, key=lambda r: (r["occurrence_key"], r["service"]))})
    groups = defaultdict(list)
    for row in rows:
        groups[canonical(dimensions(row, day)).decode()].append(row)
    allocation = {key: min(2, len(members)) for key, members in groups.items()}
    minimum = sum(allocation.values())
    budget = min(target, len(rows))
    require(budget >= minimum, f"sample budget {budget} cannot cover {len(groups)} strata; minimum {minimum}; revise design or obtain a larger review allocation")
    capacities = {key: len(members) - allocation[key] for key, members in groups.items()}
    remaining = budget - minimum
    total_capacity = sum(capacities.values())
    if remaining:
        quotients = {key: divmod(remaining * capacity, total_capacity) for key, capacity in capacities.items()}
        for key, (whole, _) in quotients.items():
            allocation[key] += whole
        leftover = budget - sum(allocation.values())
        for key in sorted(groups, key=lambda k: (-quotients[k][1], k))[:leftover]:
            allocation[key] += 1
    strata, sample, review_forms = [], [], []
    for encoded, members in sorted(groups.items()):
        population = len(members)
        n = allocation[encoded]
        sid = digest(json.loads(encoded))[:20]
        strata.append({"stratum_id": sid, "dimensions": json.loads(encoded), "population": population,
                       "sample": n, "inclusion_probability": n / population, "weight": population / n})
        def rank(row):
            return digest([seed, frame["freeze_sha256"], frame_hash, row["occurrence_key"], row["service"]])
        for row in sorted(members, key=lambda r: (rank(r), r["occurrence_key"], r["service"]))[:n]:
            audit_id = rank(row)
            sample.append({"audit_id": audit_id, "occurrence_key": row["occurrence_key"], "service": row["service"],
                           "status": row["status"], "stratum_id": sid, "weight": population / n})
            # Two separate reviewers receive copies of this form, never the private plan.
            review_forms.append({"audit_id": audit_id, "occurrence_key": row["occurrence_key"], "service": row["service"],
                                 "reviewer": None, "reviewed_at": None, "independence_attested": False,
                                 "finding": None, "evidence_refs": [], "rationale": None})
    plan = {"schema": "l-readiness-plan-v1", "fixture_only": fixture, "as_of": as_of, "seed": seed,
            "frame_sha256": frame_hash, "freeze_sha256": frame["freeze_sha256"],
            "input_hashes": frame["input_hashes"], "original_payload_multiset_sha256": frame["original_payload_multiset_sha256"],
            "denominator": denominator, "target_sample": target, "actual_sample": len(sample),
            "coverage": coverage(rows, day), "strata": strata, "sample": sorted(sample, key=lambda r: r["audit_id"]),
            "human_review_count": 0, "validated_accuracy": None, "accuracy_interval": None,
            "audit_state": "awaiting_two_independent_human_reviews_and_adjudication",
            "uncertainty": {"unreviewed": len(sample), "unreachable": None, "unresolved": None,
                            "note": "Unreachable and unresolved are unmeasured until review; neither is zero or excluded."}}
    return plan, sorted(review_forms, key=lambda r: r["audit_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--frame-sha256", required=True, help="Exact input byte hash supplied by the handoff")
    parser.add_argument("--freeze-sha256", required=True, help="Expected D freeze manifest hash")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--target", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    raw = args.frame.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == args.frame_sha256, "input frame byte hash mismatch")
    frame = json.loads(raw)
    require(frame.get("freeze_sha256") == args.freeze_sha256, "D freeze manifest hash mismatch")
    plan, forms = build_plan(frame, as_of=args.as_of, target=args.target)
    plan["frame_file_sha256"] = args.frame_sha256
    # Refuse replacement of an earlier sample or reviewer response.
    args.out_dir.mkdir(parents=True, exist_ok=False)
    for name, value in (("private-plan.json", plan), ("reviewer-1.json", forms), ("reviewer-2.json", forms)):
        (args.out_dir / name).write_bytes(canonical(value) + b"\n")
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out_dir.iterdir())}
    (args.out_dir / "manifest.json").write_bytes(canonical({"schema": "l-readiness-package-v1", "files": files}) + b"\n")
    print(json.dumps({"denominator": plan["denominator"], "sample": plan["actual_sample"], "validated_accuracy": None}))


if __name__ == "__main__":
    main()
