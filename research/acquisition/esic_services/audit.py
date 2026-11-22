"""Compare an unadmitted research lane with a frozen occurrence baseline.

This preserves existing service decisions. New clinical decisions require the
separate campus/evidence review workflow; this module cannot create one.
"""
from collections import Counter
import hashlib
import json

SERVICES = ("dialysis", "mri", "trauma_care")


def payload_hash(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def compare(base, frozen, lanes, geographies=()):
    originals = {row["facility_id"]: row for row in base}
    baseline = {row["facility_id"]: row for row in frozen}
    if len(originals) != len(base) or len(baseline) != len(frozen) or set(originals) != set(baseline):
        raise ValueError("Frozen baseline must contain every original occurrence exactly once")
    for key, row in originals.items():
        if payload_hash(row["source_row"]) != baseline[key]["original_payload_sha256"]:
            raise ValueError("Original payload differs from frozen baseline")
        statuses = baseline[key]["baseline_service_context"]
        if set(statuses) != set(SERVICES) or not set(statuses.values()) <= {"yes", "no", "unconfirmed"}:
            raise ValueError("Frozen baseline needs exactly three valid decisions")
    report = {"occurrences": len(base), "lane_comparisons": {}, "service_transitions": [],
              "approved_new_campuses": 0, "approved_new_campus_service_pairs": 0,
              "interpretation": "Research candidates only; no source in this lane has an approved new campus/service decision."}
    ledgers = {}
    for label, rows in lanes.items():
        index = {row["facility_id"]: row for row in rows}
        if len(index) != len(rows) or set(index) != set(originals):
            raise ValueError("Lane dropped or duplicated an original occurrence")
        reached = {key for key, row in index.items() if row["outcome"] != "unmatched"}
        old = {key for key, row in baseline.items() if row["outcomes"]["joint"] != "unmatched"}
        overlap, added = reached & old, reached - old
        geography = {state: {"occurrences": 0, "baseline_reached": 0,
                     "lane_reached": 0, "overlap_reached": 0, "newly_reached": 0}
                     for state in sorted(set(geographies))}
        for key, row in baseline.items():
            state = row["state"]
            count = geography.setdefault(state, {"occurrences": 0, "baseline_reached": 0,
                         "lane_reached": 0, "overlap_reached": 0, "newly_reached": 0})
            count["occurrences"] += 1
            count["baseline_reached"] += key in old
            count["lane_reached"] += key in reached
            count["overlap_reached"] += key in overlap
            count["newly_reached"] += key in added
        report["lane_comparisons"][label] = {"lane_reached": len(reached),
            "baseline_reached": len(old), "overlap_reached": len(reached & old),
            "newly_reached": len(reached - old), "union_reached": len(reached | old),
            "unmatched_in_lane": len(base) - len(reached), "by_geography": geography,
            "outcomes": dict(Counter(row["outcome"] for row in rows))}
        ledger = []
        for source in base:
            key = source["facility_id"]
            for service in SERVICES:
                status = baseline[key]["baseline_service_context"][service]
                ledger.append({"facility_id": key, "service": service, "baseline_status": status,
                    "status": status, "lane_candidate_retrieved": key in reached,
                    "lane_admitted_service_evidence": False,
                    "reason": "No approved new campus/service evidence from this lane; frozen decision retained",
                    "state": baseline[key]["state"],
                    "original_payload_sha256": baseline[key]["original_payload_sha256"]})
        ledgers[label] = ledger
        counts = Counter((r["state"], r["service"], r["baseline_status"], r["status"]) for r in ledger)
        report["service_transitions"].extend({"lane": label, "geography": state,
            "service": service, "baseline_status": status, "status": status,
            "decisions": counts[(state, service, status, status)]}
            for state in sorted(geography) for service in SERVICES for status in ("yes", "no", "unconfirmed"))
    return report, ledgers
