"""Coverage counts distinct facilities and keeps different denominators explicit."""
from collections import Counter
from datetime import date

from common import counts


def distribution(values, denominator, unit):
    return {"denominator": denominator, "unit": unit,
            "counts": dict(sorted(Counter("unknown" if v is None else v for v in values).items()))}


def coverage(batch, base, as_of):
    today = date.fromisoformat(as_of)
    external, evidence = batch["external_facilities"], batch["facility_evidence"]
    snapshots = {s["snapshot_id"]: s for s in batch["source_snapshots"]}
    matches = batch["facility_matches"]
    confirmed = {m["facility_id"] for m in matches if m["status"] == "confirmed"}
    trauma = [e for e in evidence if e["service"] == "trauma_care"]
    linked_trauma = {e["facility_id"] for e in trauma if e["facility_id"] is not None}
    supported_trauma = {e["facility_id"] for e in trauma
                        if e["facility_id"] is not None and e["polarity"] == "supports"}
    age = []
    for row in evidence:
        effective = row["effective_date"]
        if effective is None:
            age.append("unknown")
        else:
            days = (today - date.fromisoformat(effective)).days
            age.append("future" if days < 0 else "0-365_days" if days <= 365 else "over_365_days")
    return {
        "as_of": as_of, "validation_errors": 0, "quarantined_rows": 0,
        "error_policy": "Fail entire run on any validation error; no silent row quarantine.",
        "table_counts": counts(batch),
        "base": {"denominator": len(base), "unit": "distinct original facilities",
                 "confirmed_identity": len(confirmed), "identity_unknown": len(base) - len(confirmed),
                 "linked_trauma_any_polarity": len(linked_trauma),
                 "linked_supporting_trauma_including_historical": len(supported_trauma),
                 "trauma_unknown": len(base) - len(linked_trauma)},
        "external_by_state": distribution((r["state"] for r in external), len(external), "external facility rows"),
        "external_by_type": distribution((r["facility_type"] for r in external), len(external), "external facility rows"),
        "matches_by_status": distribution((r["status"] for r in matches), len(matches), "match rows"),
        "external_by_source_family": distribution((snapshots[r["snapshot_id"]]["source_family"] for r in external), len(external), "external facility rows"),
        "evidence_by_source_family": distribution((snapshots[r["snapshot_id"]]["source_family"] for r in evidence), len(evidence), "evidence rows (claim source, not identity source)"),
        "snapshots_by_independence": distribution((s["independence_status"] for s in snapshots.values()), len(snapshots), "source snapshots (URLs do not imply independence)"),
        "trauma_by_polarity": distribution((e["polarity"] for e in trauma), len(trauma), "trauma evidence rows"),
        "evidence_by_temporal_status": distribution((e["temporal_status"] for e in evidence), len(evidence), "evidence rows"),
        "evidence_by_effective_age": distribution(age, len(evidence), "evidence rows; effective date, not retrieval date"),
        "trauma_by_temporal_status": distribution((e["temporal_status"] for e in trauma), len(trauma), "trauma evidence rows"),
        "completeness": {"denominator": len(external), "unit": "external facility rows",
                         **{f"{field}_unknown": sum(r[field] is None for r in external)
                            for field in ("name_original", "state", "pin", "latitude")}},
        "open_reviews": sum(r["status"] == "open" for r in batch["review_queue"]),
        "live_availability": "unknown; no source/table count establishes live availability or clinical quality",
    }
