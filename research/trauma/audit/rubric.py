"""Apply B5 review rules to separately recorded observations of the originals."""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime


TABLE_IDS = {
    "source_snapshots": "snapshot_id",
    "external_facilities": "external_facility_id",
    "facility_matches": "match_id",
    "facility_evidence": "evidence_id",
    "review_queue": "review_id",
}
CHECKS = ("locator", "campus", "dates", "specificity", "independence")
OUTCOMES = {"pass", "fail", "uncertain"}
LIMIT = 30


def digest(payload):
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def index_batches(batches):
    tables = {table: {} for table in TABLE_IDS}
    for batch in batches:
        if batch["contract_version"] != "1.0.0":
            raise ValueError("B5 requires acquisition contract 1.0.0")
        for table, key in TABLE_IDS.items():
            for row in batch[table]:
                identifier = row[key]
                prior = tables[table].setdefault(identifier, row)
                if prior != row:
                    raise ValueError(f"Conflicting {table} payload for {identifier}")
    return tables


def review_context(evidence, tables):
    return {
        "evidence": evidence,
        "snapshot": tables["source_snapshots"][evidence["snapshot_id"]],
        "facility": tables["external_facilities"][evidence["external_facility_id"]],
    }


def select_claims(tables, strata=None):
    """Balance lanes, then round-robin their time, wording and campus strata."""
    strata = strata or {}
    buckets = defaultdict(lambda: defaultdict(list))
    for evidence_id, evidence in sorted(tables["facility_evidence"].items()):
        labels = strata.get(evidence_id, {})
        if evidence["claim_type"] != "service" and not (
            evidence["claim_type"] == "accreditation"
            and (evidence["service"] == "trauma_care" or labels.get("wording") == "general_emergency")
        ):
            continue
        context = review_context(evidence, tables)
        lane = labels.get("lane", context["snapshot"]["source_family"])
        group = (
            labels.get("campus", "unassessed"),
            evidence["temporal_status"],
            labels.get("wording", evidence["polarity"]),
            context["snapshot"]["source_family"],
            labels.get("district", context["facility"]["city"] or ""),
        )
        buckets[lane][group].append(evidence_id)

    ranked = {}
    for lane, groups in sorted(buckets.items()):
        risk, controls = [], []
        for group in sorted(groups, key=lambda group: (group[0] != "conflict", group)):
            (risk if group[0] in {"ambiguous", "conflict"} else controls).append(groups[group])
        ranked[lane] = round_robin([round_robin(risk), round_robin(controls)])
    population = list(round_robin(ranked.values()))
    return population[:LIMIT], len(population), {
        lane: sum(map(len, groups.values())) for lane, groups in sorted(buckets.items())
    }


def round_robin(groups):
    active = [iter(group) for group in groups]
    while active:
        remaining = []
        for group in active:
            item = next(group, None)
            if item is not None:
                yield item
                remaining.append(group)
        active = remaining


def assess(context, observation):
    """Record checks on one immutable evidence payload and the attached source context."""
    evidence = context["evidence"]
    fingerprint = digest(context)
    if observation["reviewed_payload_sha256"] != fingerprint:
        raise ValueError(f"Review targets a different payload for {evidence['evidence_id']}")
    timestamp = observation["reviewed_at"]
    if not timestamp.endswith("Z"):
        raise ValueError("reviewed_at must be UTC with a Z suffix")
    datetime.fromisoformat(timestamp[:-1] + "+00:00")
    if "T" not in timestamp or not observation["reviewer"].strip():
        raise ValueError("Review requires a reviewer and a UTC timestamp")

    checks = {}
    for check in CHECKS:
        result = observation["checks"][check]
        if result["outcome"] not in OUTCOMES or not result["reason"].strip():
            raise ValueError(f"Invalid or unexplained {check} outcome")
        checks[check] = result

    # Normalize whitespace only, including PDF wraps and HTML nonbreaking spaces.
    excerpt = " ".join((evidence["excerpt"] or "").split())
    passage = observation.get("located_passage")
    if not excerpt:
        checks["quote"] = finding("fail", "The textual evidence has no excerpt.")
    elif passage is None:
        checks["quote"] = finding("uncertain", "The passage at the locator could not be inspected.")
    elif excerpt not in " ".join(passage.split()):
        checks["quote"] = finding("fail", "The excerpt is absent from the cited passage.")
    else:
        checks["quote"] = finding("pass", "The cited passage contains the excerpt.")

    expected = observation.get("source_temporal_status")
    if expected is not None and evidence["temporal_status"] != expected:
        checks["dates"] = finding(
            "fail",
            f"The original warrants {expected}, but the claim is {evidence['temporal_status']}. "
            + checks["dates"]["reason"],
        )
    issues = [
        f"{check}: {result['reason']}"
        for check, result in checks.items()
        if result["outcome"] != "pass"
    ]
    outcomes = {result["outcome"] for result in checks.values()}
    outcome = "fail" if "fail" in outcomes else "uncertain" if "uncertain" in outcomes else "pass"
    if not observation["reason"].strip():
        raise ValueError("Review requires a claim-specific reason")
    return {
        "evidence_id": evidence["evidence_id"],
        "outcome": outcome,
        "reviewer": observation["reviewer"],
        "reviewed_at": timestamp,
        "reason": " ".join([observation["reason"], *issues]),
        "checks": checks,
        "evidence_sha256": digest(evidence),
        "reviewed_payload_sha256": fingerprint,
        "original": observation["original"],
        "correction_requested": observation.get("correction_requested"),
        "replaces_evidence_id": observation.get("replaces_evidence_id"),
    }


def finding(outcome, reason):
    return {"outcome": outcome, "reason": reason}


def source_dependence(snapshots, annotations=None):
    """Group same family, same raw bytes and documented shared upstream origins."""
    annotations = annotations or {}
    groups = {sid: sid for sid in snapshots}

    def root(sid):
        while groups[sid] != sid:
            sid = groups[sid]
        return sid

    members_by_key = {}
    for sid, snapshot in sorted(snapshots.items()):
        annotation = annotations.get(sid, {})
        keys = [("family", snapshot["source_family"]), ("sha256", snapshot["sha256"])]
        if annotation.get("upstream_origin"):
            keys.append(("upstream", annotation["upstream_origin"]))
        for key in keys:
            first = members_by_key.setdefault(key, sid)
            left, right = sorted((root(first), root(sid)))
            groups[right] = left

    grouped = defaultdict(list)
    for sid, snapshot in sorted(snapshots.items()):
        annotation = annotations.get(sid, {})
        grouped[root(sid)].append({
            "snapshot_id": sid,
            "source_family": snapshot["source_family"],
            "sha256": snapshot["sha256"],
            "url": snapshot["url"],
            "publisher_assessment": snapshot["independence_status"],
            "relationship": annotation.get("relationship", "unassessed"),
            "upstream_origin": annotation.get("upstream_origin"),
            "reason": annotation.get("reason"),
        })
    return [
        {"group": identifier, "members": members, "candidate_origin_count": 1}
        for identifier, members in sorted(grouped.items())
    ]


def queue_batch(tables, reviews):
    """Emit B5's review queue only, referencing the producer envelopes."""
    batch = {"contract_version": "1.0.0", **{table: [] for table in TABLE_IDS}}
    for review in reviews:
        if review["outcome"] == "pass":
            continue
        evidence_id = review["evidence_id"]
        evidence = tables["facility_evidence"][evidence_id]
        batch["review_queue"].append({
            "review_id": "b5:audit:" + digest([evidence_id, review["reviewed_payload_sha256"]]),
            **{key: evidence[key] for key in ("facility_id", "external_facility_id", "match_id")},
            "evidence_id": evidence_id,
            "reason_code": "b5_audit_" + review["outcome"],
            "severity": "high" if review["outcome"] == "fail" else "medium",
            "status": "open",
            "next_action": review["correction_requested"] or "Resolve the audit finding and request re-review.",
            "resolution": None,
        })
    return batch


def outcome_counts(reviews):
    counts = Counter(review["outcome"] for review in reviews)
    return {outcome: counts[outcome] for outcome in sorted(OUTCOMES)}
