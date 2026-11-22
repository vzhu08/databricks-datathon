"""Retain literal scheme terms and compare identity candidates nationally.

This is a research ledger, not an enrichment admission or service review.
A source may permit local analysis while its redistribution is held.
"""
from collections import Counter, defaultdict
from datetime import date
import re

from research.matching.common import digest, require
from research.matching.national import STATES, execute_national
from research.matching.normalize import fold
from research.service_status.projection import project
from . import VERSION

TERMS = {
    "dialysis": r"\b(?:ha?emodialysis|dialysis)\b",
    "mri": r"\b(?:MRI|M\.?R\.?I\.?|magnetic\s+resonance(?:\s+imaging)?)\b",
    "trauma_care": r"\btrauma(?:\s+(?:care|cent(?:er|re)))?\b",
    "ct": r"\b(?:CT(?:\s+scan)?|computed\s+tomography)\b",
    "emergency_surgery": r"\bemergency\s+(?:surgery|surgical)\b",
    "orthopedics": r"\bortho(?:pa?edic(?:s|\s+surgery)?|pedic(?:s|\s+surgery)?)\b",
    "neurosurgery": r"\bneuro[\s-]*surg(?:ery|ical)\b",
    "icu": r"\b(?:ICU|intensive\s+care(?:\s+unit)?|critical\s+care)\b",
    "ventilation": r"\b(?:ventilat(?:ion|or|ors|ory))\b",
    "blood_bank": r"\bblood\s+(?:bank|storage|components?)\b",
    "burns": r"\bburns?(?:\s+(?:care|unit))?\b",
    "pediatrics": r"\bpa?ediatric(?:s|\s+surgery)?\b",
}
CUES = {
    "negation_or_exclusion_cue": r"\b(?:no|not|without|except|excluding|excluded|unavailable|unavailability)\b",
    "referral_cue": r"\b(?:refer(?:ral|red)?|transfer(?:red)?|outsourc\w*)\b",
    "planned_or_procurement_cue": r"\b(?:planned|proposed|tender|procurement|installation)\b",
    "scheme_change_cue": r"\b(?:suspend\w*|withdraw\w*|renew\w*|de[ -]?empanel\w*|delist\w*)\b",
}


def mentions(text):
    """Offsets index original Unicode text. Cues are flags, never polarity labels.

    Scope cells often have long exception lists and broken PDF line wraps.
    Flag cues across the entire cell so a distant exclusion cannot become an
    affirmative assertion. Preserve the cell for human interpretation.
    """
    flags = sorted(k for k, pattern in CUES.items() if re.search(pattern, text, re.I))
    out = []
    for service, pattern in TERMS.items():
        for match in re.finditer(pattern, text, re.I):
            out.append({"service": service, "start": match.start(), "end": match.end(),
                        "excerpt": match.group(), "cue_flags": flags,
                        "polarity": "unadjudicated", "claim_class": "scheme_scope_mention",
                        "procedure_count": None, "procedure_unit": None,
                        "clinical_status": "unconfirmed", "live_availability": "unknown"})
    return sorted(out, key=lambda x: (x["start"], x["end"], x["service"]))


def observations(records, sources, as_of):
    """All revisions remain; latest dated edition is selected within each series."""
    day = date.fromisoformat(as_of)
    index = {s["snapshot_id"]: s for s in sources}
    require(len(index) == len(sources), "sources", "duplicate snapshot IDs")
    require(len({r['record_id'] for r in records}) == len(records), "records", "duplicate record IDs")
    series = defaultdict(list)
    for source in sources:
        require(source.get("local_analysis_allowed") is True, "rights", "local analysis is not authorized")
        require(isinstance(source.get("sharing_allowed"), bool), "rights", "explicit sharing disposition required")
        require(bool(source.get("rights_reason")), "rights", "disposition reason required")
        require(bool(source.get("upstream_origin")), "origin", "upstream lineage required")
        published = source.get("document_date")
        if published and date.fromisoformat(published) <= day:
            series[source["series_key"]].append(source)
    selected = set()
    unresolved = []
    for key, editions in sorted(series.items()):
        latest = max(s["document_date"] for s in editions)
        eligible = [s for s in editions if s["document_date"] == latest]
        if len(eligible) == 1:
            selected.add(eligible[0]["snapshot_id"])
        else:
            unresolved.append(key)
    ledger, rows = [], []
    for row in records:
        source = index[row["snapshot_id"]]
        require(row["source_sha256"] == source["sha256"], "record", "raw source hash mismatch")
        require(row["document_date"] == source["document_date"], "record", "source date mismatch")
        require(isinstance(row.get("scope_raw"), str), "scope", "original scope cell required")
        require(bool(row.get("fragments")) or (isinstance(row.get("locator"), str) and
                bool(row["locator"].strip()) and isinstance(row.get("physical_page"), int) and
                row["physical_page"] > 0), "locator", "original page/table locator required")
        is_selected = row["snapshot_id"] in selected
        identity = digest([fold(row.get("name_raw") or ""), fold(row.get("address_raw") or ""),
                           fold(row.get("city") or ""), fold(row.get("state") or "")])
        # Preserve the full checked transcription, including all non-keyword scope.
        rows.append({"record": row, "selected": is_selected,
                     "identity_proxy": identity, "sharing_allowed": source["sharing_allowed"]})
        for mention in mentions(row["scope_raw"]):
            key = [row["record_id"], "scope_raw", mention["start"], mention["end"], mention["service"]]
            ledger.append({"observation_id": "scheme-mention:" + digest(key), **mention,
                           "record_id": row["record_id"], "snapshot_id": row["snapshot_id"],
                           "field": "scope_raw", "selected": is_selected,
                           "record_kind": row["record_kind"], "identity_proxy": identity,
                           "upstream_origin": source["upstream_origin"],
                           "document_date": source["document_date"], "retrieved_at": source["retrieved_at"],
                           "sharing_allowed": source["sharing_allowed"],
                           "campus_join_quality": "unreviewed", "source_url": source["url"]})
    return rows, ledger, selected, unresolved


def candidate_batch(rows, sources, selected):
    """Private exploratory matcher input. NEVER an accepted producer envelope."""
    batch = {"contract_version": "1.0.0", **{k: [] for k in
             ("source_snapshots", "external_facilities", "facility_matches", "facility_evidence", "review_queue")}}
    for s in sources:
        if s["snapshot_id"] not in selected:
            continue
        batch["source_snapshots"].append({
            "snapshot_id": s["snapshot_id"], "source_key": s["series_key"], "publisher": s["publisher"],
            "source_family": s["upstream_origin"], "url": s["url"], "retrieved_at": s["retrieved_at"],
            "published_date": s["document_date"], "license": None, "attribution": s["publisher"],
            "sha256": s["sha256"], "artifact_uri": s["artifact_path"], "parser_version": VERSION,
            "independence_status": "shared_origin"})
    for item in rows:
        r = item["record"]
        if not item["selected"] or r["record_kind"] != "campus_observation":
            continue
        batch["external_facilities"].append({
            "external_facility_id": r["record_id"], "snapshot_id": r["snapshot_id"],
            "source_record_id": None, "record_locator": "record_id=" + r["record_id"],
            "name_original": r.get("name_raw") or None, "name_normalized": fold(r.get("name_raw") or "") or None,
            "address_original": r.get("address_raw") or None, "facility_type": r.get("institution_type") or "unknown",
            "city": r.get("city") or None, "state": r.get("state") or None,
            "pin": r.get("pin") if re.fullmatch(r"[0-9]{6}", r.get("pin") or "") else None,
            "latitude": None, "longitude": None, "coordinate_method": None,
            "quality_flags": ["scheme_scope_only", "campus_unreviewed", "private_exploration_not_admitted"]})
    return batch


def run(records, sources, base, metadata, *, as_of, base_sha256, duplicate_sidecar=None,
        expected_rows=10088, expected_ids=10077, expected_duplicates=11):
    require(len(base) == expected_rows, "national", "original occurrence denominator mismatch")
    original_ids = {r["source_row"][metadata["mapping"]["id"]] for r in base}
    require(len(original_ids) == expected_ids, "national", "distinct source ID denominator mismatch")
    rows, ledger, selected, unresolved = observations(records, sources, as_of)
    batch = candidate_batch(rows, sources, selected)
    matched = execute_national(base, [batch], source_metadata=metadata,
                               base_file_sha256=base_sha256, duplicate_sidecar=duplicate_sidecar,
                               expect_duplicate_groups=expected_duplicates, sample_size=0, missed_sample_size=0)
    # Scheme scope supplies no adjudicated onsite/negative reviews, even when
    # identity is a strong candidate. Reproduce the empty-review baseline.
    status = project(base, metadata, [], [], as_of=as_of, checked_sources=[], base_file_sha256=base_sha256,
                     identity_rows=matched["base_rows"], identity_report=matched["national_report"])
    candidates = defaultdict(set)
    for c in matched["candidates"]:
        candidates[c["external_facility_id"]].add(c["facility_id"])
    for obs in ledger:
        obs["candidate_occurrences"] = sorted(candidates.get(obs["record_id"], ())) if obs["selected"] else []
        if obs["candidate_occurrences"]:
            obs["campus_join_quality"] = "candidate_only_not_approved"
    variants = defaultdict(list)
    for item in rows:
        variants[item["identity_proxy"]].append(item["record"])
    scope_variants = [{"identity_proxy": proxy, "record_ids": sorted(r["record_id"] for r in items),
                       "distinct_scope_texts": len({r["scope_raw"] for r in items}),
                       "interpretation": "wording variants; conflict not adjudicated"}
                      for proxy, items in sorted(variants.items()) if len({r["scope_raw"] for r in items}) > 1]
    counts = {}
    for service in TERMS:
        all_terms = [o for o in ledger if o["service"] == service]
        campus = [o for o in all_terms if o["selected"] and o["record_kind"] == "campus_observation"]
        counts[service] = {
            "raw_mentions_all_editions": len(all_terms), "selected_campus_mentions": len(campus),
            "selected_campus_record_service_observations": len({o["record_id"] for o in campus}),
            "exact_name_address_geography_proxies": len({o["identity_proxy"] for o in campus}),
            "observed_upstream_origins": len({o["upstream_origin"] for o in campus}),
            "independent_corroborating_origins": 0,
            "candidate_original_occurrences": len({fid for o in campus for fid in o["candidate_occurrences"]}),
            "approved_vf_campus_service_pairs": 0, "eligible_new_yes": 0, "eligible_new_no": 0}
    state_coverage = {s: {service: {"yes": 0, "no": 0, "unconfirmed": 0}
                          for service in status["coverage"]} for s in sorted(STATES)}
    state_coverage.update(status["coverage_by_state"])
    summary = {"version": VERSION, "as_of": as_of, "original_rows": len(base), "distinct_source_ids": len(original_ids),
               "decision_count": status["decision_count"], "coverage": status["coverage"],
               "coverage_by_state": state_coverage, "service_mentions": counts,
               "source_editions": len(sources), "all_record_observations": len(rows),
               "selected_record_observations": sum(r["selected"] for r in rows),
               "selected_campus_records": len(batch["external_facilities"]),
               "held_for_sharing_editions": sum(not s["sharing_allowed"] for s in sources),
               "undated_or_future_editions": sum(not s.get("document_date") or s["document_date"] > as_of for s in sources),
               "unresolved_latest_series": unresolved, "scope_wording_variant_groups": len(scope_variants),
               "selected_campus_records_by_state": dict(sorted(Counter(
                   r["state"] or "unknown" for r in batch["external_facilities"]).items())),
               "source_editions_summary": [{"snapshot_id": s["snapshot_id"], "url": s["url"],
                    "document_date": s["document_date"], "selected": s["snapshot_id"] in selected,
                    "record_observations": sum(r["record"]["snapshot_id"] == s["snapshot_id"] for r in rows),
                    "raw_mentions": sum(o["snapshot_id"] == s["snapshot_id"] for o in ledger),
                    "sharing_allowed": s["sharing_allowed"]} for s in sources],
               "matcher_outcomes": matched["national_report"]["outcomes"],
               "baseline": "empty-adjudication replay of frozen VF base; compare #147 zero approved service pairs",
               "limitations": ["Term screen is not exhaustive semantic extraction; original scope cells are retained.",
                               "Exact identity proxies are not verified physical campuses.",
                               "Candidates are exploratory, including sharing-held sources, not eligible coverage gains.",
                               "No aggregate performed-procedure counts or operational readiness admitted.",
                               "Source absence, excluded scope and expired empanelment do not establish no onsite service."]}
    return {"records": rows, "mentions": ledger, "scope_wording_variants": scope_variants, "candidate_batch_PRIVATE_NOT_ADMITTED": batch,
            "national_candidates": matched["candidates"], "national_rows": matched["base_rows"],
            "national_report": matched["national_report"], "service_status": status, "summary": summary}
