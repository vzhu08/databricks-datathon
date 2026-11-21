"""Private, as-of service assessments from reviewed claims on a preserved VF base."""
from collections import Counter, defaultdict
from datetime import date, datetime

from research.matching.common import base_check, combine_external, digest, require


SERVICES = ("dialysis", "mri", "trauma_care")
FIELDS = {"description", "procedure", "equipment", "capability", "specialties"}
POLICY = "onsite-service-review-v1"
DECISIVE = {"onsite_service": ("yes", "supports"), "explicit_no_onsite": ("no", "contradicts"),
            "referral_only": ("no", "contradicts")}
OTHER = {"campus_conflict", "other_campus", "historical_only", "date_unclear",
         "planned", "equipment_only", "insufficient"}
REASONS = {
    "onsite_service": "Reviewed evidence documents onsite care at this campus.",
    "explicit_no_onsite": "Reviewed evidence explicitly says this campus does not provide the service onsite.",
    "referral_only": "Reviewed evidence says this campus refers all cases for this service elsewhere.",
    "conflicting_claims": "Applicable sources disagree about onsite care at this campus.",
    "disputed_claim": "Reviewers disagree about the campus, time or scope of the cited evidence.",
    "campus_conflict": "The service cannot be attributed to this campus with confidence.",
    "insufficient": "The reviewed material does not establish onsite care at the assessment date.",
    "no_reviewed_evidence": "No reviewed claim establishes the status of this service.",
}


def iso_day(value):
    parsed = date.fromisoformat(value)
    require(value == parsed.isoformat(), "date", "expected YYYY-MM-DD")
    return parsed


def assessed_claim(review, raw, snapshots, evidence, matches, as_of):
    """Resolve a review back to its source; never infer clinical polarity from a word or machine count."""
    finding = review["finding"]
    require(finding in DECISIVE or finding in OTHER, "finding", "unknown review finding")
    require(isinstance(review["reviewer"], str) and review["reviewer"].strip(), "reviewer", "required")
    reviewed = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    require(reviewed.utcoffset() is not None, "reviewed_at", "timezone required")
    require(review["assessed_for"] == as_of.isoformat(), "assessed_for", "review concerns another as-of date")
    ref = review["source"]
    in_period = True
    if ref["kind"] == "original":
        field, start, end = ref["field"], ref["start"], ref["end"]
        require(field in FIELDS, "source.field", "expected an original service field")
        value = raw.get(field)
        require(isinstance(value, str) and type(start) is int and type(end) is int
                and 0 <= start < end <= len(value), "source", "invalid original-field span")
        require(value[start:end] == ref["excerpt"] and ref["excerpt"].strip(),
                "source.excerpt", "original text has changed")
        source_day = ref.get("source_date")
        valid_from, valid_until = ref.get("valid_from"), ref.get("valid_until")
        start_day = iso_day(valid_from) if valid_from else None
        end_day = iso_day(valid_until) if valid_until else None
        require(not (start_day and end_day and end_day < start_day), "source", "reversed effective interval")
        in_period = (start_day is None or start_day <= as_of) and (end_day is None or as_of <= end_day)
        applicable = in_period
        provenance = {"kind": "original", "field": field, "start": start, "end": end,
                      "source_date": source_day, "family": ref.get("source_family"),
                      "valid_from": valid_from, "valid_until": valid_until,
                      "url_scope": "record", "url_field": "source_urls"}
    else:
        require(ref["kind"] == "external", "source.kind", "unknown source kind")
        item = evidence[ref["evidence_id"]]
        snap = snapshots[item["snapshot_id"]]
        require(item["claim_type"] == "service" and item["service"] == review["service"],
                "source.evidence_id", "wrong service or claim type")
        match = matches.get(item["match_id"])
        linked = (match is not None and match["status"] == "confirmed"
                  and match["facility_id"] == item["facility_id"] == review["facility_id"]
                  and match["external_facility_id"] == item["external_facility_id"])
        require(linked, "source.match_id", "a confirmed link to the same campus is required")
        source_day = item["effective_date"] or snap["published_date"]
        usable_until = item["valid_until"] is None or as_of <= iso_day(item["valid_until"])
        in_period = item["temporal_status"] not in {"historical", "expired"} and usable_until
        applicable = item["temporal_status"] == "dated" and usable_until and bool(item["excerpt"])
        if finding in DECISIVE:
            applicable = applicable and item["polarity"] == DECISIVE[finding][1]
        provenance = {"kind": "external", "evidence_id": item["evidence_id"], "match_id": item["match_id"],
                      "snapshot_id": item["snapshot_id"], "source_url": item["source_url"],
                      "locator": item["locator"], "family": snap["source_family"], "publisher": snap["publisher"],
                      "source_date": source_day, "valid_from": item["effective_date"], "valid_until": item["valid_until"],
                      "retrieved_at": snap["retrieved_at"]}
    applicable = bool(source_day) and iso_day(source_day) <= as_of and applicable
    return {"review_id": review["review_id"], "finding": finding,
            "reviewer": review["reviewer"], "reviewed_at": review["reviewed_at"],
            "in_period": in_period and (not source_day or iso_day(source_day) <= as_of),
            "superseded_by": review.get("superseded_by"),
            "decision": DECISIVE[finding][0] if finding in DECISIVE and applicable else None,
            "provenance": provenance}


def decision(claims):
    claims = sorted(claims, key=lambda claim: claim["review_id"])
    by_id = {c["review_id"]: c for c in claims}
    active = []
    for claim in claims:
        replacement_id = claim["superseded_by"]
        if replacement_id is None:
            active.append(claim)
            continue
        replacement = by_id.get(replacement_id)
        require(replacement is not None and replacement_id != claim["review_id"]
                and replacement["superseded_by"] is None and replacement["decision"] is not None,
                "superseded_by", "must name an applicable final review of the same occurrence and service")
        original_date = claim["provenance"]["source_date"]
        require(not original_date or iso_day(replacement["provenance"]["source_date"]) >= iso_day(original_date),
                "superseded_by", "replacement evidence predates the superseded observation")
    opinions = defaultdict(list)
    for c in active:
        ref = c["provenance"]
        locator = ((ref["field"], ref["start"], ref["end"]) if ref["kind"] == "original"
                   else (ref["evidence_id"],))
        if c["in_period"]:
            opinions[locator].append(c)
    disputed = set()
    for group in opinions.values():
        if any(c["decision"] for c in group) and any(c["decision"] is None for c in group):
            disputed.update(c["review_id"] for c in group)
    eligible = [c for c in active if c["decision"] and c["review_id"] not in disputed]
    outcomes = {c["decision"] for c in eligible}
    if any(c["finding"] == "campus_conflict" and c["in_period"] for c in active):
        code = "campus_conflict"
    elif len(outcomes) > 1:
        code = "conflicting_claims"
    elif outcomes:
        code = eligible[0]["finding"]
    elif disputed:
        code = "disputed_claim"
    else:
        code = "insufficient" if claims else "no_reviewed_evidence"
    return {"status": DECISIVE[code][0] if code in DECISIVE else "unconfirmed",
            "reason_code": code, "reason": REASONS[code], "reviews": claims}


def project(base, metadata, reviews, batches, *, as_of, checked_sources, base_file_sha256,
            identity_rows=None, identity_report=None):
    """Return one private lookup entry per occurrence, plus aggregate coverage and input lineage."""
    day = iso_day(as_of)
    require(metadata["base_file_sha256"] == base_file_sha256, "base", "base file digest mismatch")
    source = base_check(base)
    require(metadata["row_count"] == len(source), "base", "source row count mismatch")
    id_field = metadata["mapping"]["id"]
    identity = {}
    require((identity_rows is None) == (identity_report is None), "identity", "rows and report must be paired")
    if identity_rows is not None:
        from research.matching.national import CONFLICTS, OUTCOMES
        require(identity_report["base_sha256"] == digest(base) and identity_report["scope"]["state"] is None,
                "identity_report", "expected the unfiltered report bound to this base")
        require(identity_report["denominators"]["original_rows"] == len(source),
                "identity_report", "original denominator mismatch")
        identity = base_check(identity_rows)
        require(identity.keys() == source.keys(), "identity_rows", "must cover every original occurrence exactly")
        for row in identity.values():
            require(row.get("outcome") in OUTCOMES and isinstance(row.get("state"), str)
                    and bool(row["state"].strip()) and isinstance(row.get("conflicts"), list)
                    and all(flag in CONFLICTS for flag in row["conflicts"]),
                    "identity_rows", "invalid national outcome, state or conflict flags")
    require(isinstance(checked_sources, list) and all(isinstance(s, str) and s.strip() for s in checked_sources),
            "checked_sources", "expected a list of source identifiers")
    combined = combine_external(batches)
    snapshots = {s["snapshot_id"]: s for s in combined["source_snapshots"]}
    facts = {e["evidence_id"]: e for e in combined["facility_evidence"]}
    matches = {m["match_id"]: m for m in combined["facility_matches"]}
    grouped = defaultdict(list)
    seen = set()
    for r in reviews:
        fid, service, rid = r["facility_id"], r["service"], r["review_id"]
        require(fid in source and service in SERVICES, "review", "unknown occurrence or service")
        require(isinstance(rid, str) and rid.strip() and rid not in seen, "review_id", "missing or duplicate")
        seen.add(rid)
        claim = assessed_claim(r, source[fid]["source_row"], snapshots, facts, matches, day)
        if claim["decision"] and identity.get(fid, {}).get("conflicts"):
            rationale = r.get("campus_resolution")
            if isinstance(rationale, str) and rationale.strip():
                claim["campus_resolution"] = rationale
            else:
                claim["reviewed_finding"] = claim["finding"]
                claim.update(finding="campus_conflict", decision=None)
        grouped[fid, service].append(claim)
    facilities, coverage = {}, {s: Counter() for s in SERVICES}
    by_state = {}
    for fid, row in source.items():
        services = {s: decision(grouped.get((fid, s), ())) for s in SERVICES}
        geography = identity.get(fid, {}).get("state") or "unknown"
        state_counts = by_state.setdefault(geography, {s: Counter() for s in SERVICES})
        for s, result in services.items():
            coverage[s][result["status"]] += 1
            state_counts[s][result["status"]] += 1
        facilities[fid] = {"source_id": row["source_row"][id_field], "services": services,
                           "state": geography, "identity_conflicts": identity.get(fid, {}).get("conflicts", [])}
    return {"as_of": as_of, "policy": POLICY, "checked_sources": sorted(set(checked_sources)),
            "original_table": metadata["original_table"], "delta_version": metadata["observed_delta_version"],
            "base_file_sha256": base_file_sha256, "metadata_sha256": digest(metadata),
            "reviews_sha256": digest(sorted(reviews, key=lambda r: r["review_id"])),
            "batch_sha256": digest(combined), "occurrences": len(facilities),
            "identity_rows_content_sha256": digest(identity_rows) if identity_rows is not None else None,
            "identity_report_content_sha256": digest(identity_report) if identity_report is not None else None,
            "coverage_by_state": by_state,
            "decision_count": len(facilities) * len(SERVICES),
            "coverage": {s: {k: coverage[s][k] for k in ("yes", "no", "unconfirmed")} for s in SERVICES},
            "facilities": facilities}


def lookup(projection, occurrence_key):
    """Authorized reviewer lookup. Patient-facing callers should use patient_lookup."""
    entry = projection["facilities"][occurrence_key]
    return {"occurrence_key": occurrence_key, "source_id": entry["source_id"],
            "as_of": projection["as_of"], "checked_sources": projection["checked_sources"],
            "services": entry["services"]}


def patient_lookup(projection, occurrence_key):
    """Present dated decisions without private excerpts, record URLs or reviewer notes."""
    entry = projection["facilities"][occurrence_key]
    services = {}
    for name, decision_row in entry["services"].items():
        citations = []
        for review in decision_row["reviews"]:
            ref = review["provenance"]
            citation = {"kind": ref["kind"], "date": ref["source_date"]}
            if ref.get("valid_from") or ref.get("valid_until"):
                citation.update(valid_from=ref.get("valid_from"), valid_until=ref.get("valid_until"))
            if review["superseded_by"]:
                citation["historical"] = True
            if ref["kind"] == "original":
                citation["field"] = ref["field"]
            else:
                citation["publisher"] = ref["publisher"]
            if citation not in citations:
                citations.append(citation)
        services[name] = {"status": decision_row["status"], "reason": decision_row["reason"],
                          "sources": citations}
    return {"as_of": projection["as_of"], "checked_sources": projection["checked_sources"],
            "services": services}
