"""Lossless register ledger, conservative v1 projection and within-source audit."""
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
import re

from .build import TABLES, checked_raw
from .common import FAMILY, SourceError, canonical, identity, read, require, sha
from .episodes import parse_date
from .national_capture import VERSION
from .national_tables import map_summary, page
from .tables import POLICY


def validate_cutoff(as_of):
    # Newer Python versions also accept compact and week-date ISO forms.
    # String comparisons with the canonical source dates require this exact form.
    require(isinstance(as_of, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of) is not None,
            "national_cutoff_must_be_YYYY_MM_DD")
    date.fromisoformat(as_of)


def date_class(parsed, as_of):
    validate_cutoff(as_of)
    values = parsed["candidates"]
    if not values:
        return "unknown"
    if max(values) < as_of:
        return "expired_under_all_parses"
    if min(values) > as_of:
        return "end_in_future_under_all_parses"
    if set(values) == {as_of}:
        return "end_on_cutoff"
    return "ambiguous_at_cutoff"


def challenge_sample(records, limit=20):
    groups = defaultdict(list)
    for r in records:
        groups[(r["status_original"], r["date_class"], r["end"]["status"], r["repeated_campus_label"])].append(r)
    groups = [sorted(rs, key=lambda r: r["record_id"]) for _, rs in sorted(groups.items())]
    selected = []
    while groups and len(selected) < limit:
        remaining = []
        for rs in groups:
            if len(selected) < limit:
                selected.append(rs.pop(0))
            if rs:
                remaining.append(rs)
        groups = remaining
    return selected


def build(root, as_of):
    validate_cutoff(as_of)
    root = Path(root)
    capture = read(root / "national_capture.json")
    require(capture["capture_version"] == VERSION, "unknown_national_capture_version")
    for doc in capture["documents"].values():
        checked_raw(root, doc)
    views, source_pages = {}, {}
    for status, meta in capture["views"].items():
        rows, totals, updates = [], [], []
        for number, key in enumerate(meta["pages"]):
            doc = capture["documents"][key]
            parsed = page(checked_raw(root, doc), doc["url"], number, status)
            totals.append(parsed["advertised_total"])
            updates.append(parsed["updated_till"])
            for r in parsed["rows"]:
                rows.append({**r, "document_key": key, "snapshot_sha256": doc["sha256"],
                             "retrieved_at": doc["retrieved_at"], "source_updated_till": parsed["updated_till"]})
            source_pages[key] = doc
        require(len(rows) == meta["row_count"] and totals == meta["advertised_totals"], "national_capture_counts_changed")
        views[status] = {"rows": rows, "totals": totals, "updates": updates, "complete": meta["complete"]}
    occurrences = views.get("All", {"rows": []})["rows"]
    by_record = defaultdict(list)
    for r in occurrences:
        by_record[r["record_id"]].append(r)
    label_groups = defaultdict(list)
    for rid, locations in sorted(by_record.items()):
        name = locations[0]["facility"]
        key = " ".join(name.casefold().split()) if name else rid
        label_groups[key].append(rid)
    repeated = {rid for ids in label_groups.values() if len(ids) > 1 for rid in ids}
    ledger = []
    for rid, locations in sorted(by_record.items()):
        original = locations[0]
        end = parse_date(original["valid_until_raw"])
        ledger.append({**original, "record_id": rid, "source_family": FAMILY, "end": end, "start": None,
                       "date_class": date_class(end, as_of), "as_of": as_of,
                       "repeated_campus_label": rid in repeated, "campus_identity_verified": False,
                       "formal_renewal_verified": False, "matching_feature_use": "excluded",
                       "occurrences": locations})
    batch = {"contract_version": "1.0.0", **{t: [] for t in TABLES}}
    snapshots = {}
    for item in ledger:
        doc = source_pages[item["document_key"]]
        sid = identity("nqas-national-snapshot", doc["url"], doc["sha256"])
        snapshots[sid] = {"snapshot_id": sid, "source_key": "nqas_national_rajasthan", "source_family": FAMILY,
                          "publisher": "National Health Systems Resource Centre / National Health Mission", "url": doc["url"],
                          "retrieved_at": doc["retrieved_at"], "published_date": None,
                          "license": "NHSRC copyright policy; accurate attributed reuse; third-party exception: " + POLICY,
                          "attribution": "NHSRC, Ministry of Health & Family Welfare, Government of India; one NQAS programme family.",
                          "sha256": doc["sha256"], "artifact_uri": (root / doc["artifact"]).resolve().as_uri(),
                          "parser_version": VERSION, "independence_status": "shared_origin"}
        ext = identity("nqas-national-external", sid, item["record_id"])
        item.update(snapshot_id=sid, external_facility_id=ext)
        flags = ["held_out_nqas_audit", "nin_not_exposed", "category_not_exposed", "district_not_exposed",
                 "department_scope_not_exposed", "start_date_not_exposed", "coordinates_not_exposed"]
        if item["facility"] is None:
            flags.append("missing_name")
        if item["repeated_campus_label"]:
            flags.append("repeated_name_identity_unresolved")
        batch["external_facilities"].append({"external_facility_id": ext, "snapshot_id": sid, "source_record_id": None,
            "record_locator": item["locator"], "name_original": item["facility"],
            "name_normalized": item["facility"].casefold() if item["facility"] else None,
            "address_original": None, "facility_type": "unknown", "city": None, "state": "Rajasthan", "pin": None,
            "latitude": None, "longitude": None, "coordinate_method": None, "quality_flags": sorted(flags)})
        # A known end without a start cannot use v1 'dated' or 'undated'.
        # Emit only certainly expired or entirely undated listings; full intervals stay in the ledger.
        temporal = ("expired" if item["end"]["iso"] else "historical") if item["date_class"] == "expired_under_all_parses" else (
            "undated" if item["end"]["status"] == "missing" else None)
        if not item["status_original"]:
            temporal = None
        eid = None
        if temporal:
            eid = identity("nqas-national-evidence", ext, temporal, item["end"]["iso"])
            batch["facility_evidence"].append({"evidence_id": eid, "external_facility_id": ext, "snapshot_id": sid,
                "facility_id": None, "match_id": None, "claim_type": "accreditation", "service": None,
                "polarity": "supports" if item["status_original"] == "Certified" else "inconclusive",
                "assertion": "The NHSRC national-level register lists this facility with printed status '" + item["status_original"] +
                    "' and validity end '" + item["valid_until_raw"] + "'. Start date and department scope are not supplied; the source page's update label is not an effective date. This is not a current certification, clinical capability or NABH claim.",
                "excerpt": item["original_cells"][2], "observation": None, "locator": item["locator"], "source_url": item["source_url"],
                "effective_date": None, "valid_until": item["end"]["iso"], "temporal_status": temporal,
                "reviewer": None, "reviewed_at": None})
        item["evidence_id"] = eid
        item["v1_evidence_withheld_reason"] = None if temporal else (
            "missing_printed_status" if not item["status_original"] else "end_only_interval_with_missing_start_requires_explicit_ledger")
        batch["review_queue"].append({"review_id": identity("nqas-national-review", ext, eid), "external_facility_id": ext,
            "facility_id": None, "evidence_id": eid, "match_id": None, "reason_code": "held_out_certification_review", "severity": "medium",
            "status": "open", "resolution": None,
            "next_action": "Keep held out until predictions are frozen. Verify the named campus, printed Certified/Conditionality label, absent scope/start and original end date in the accompanying national ledger. Do not infer current status or use in matching features."})
    batch["source_snapshots"] = list(snapshots.values())
    for table, key in zip(TABLES, ("snapshot_id", "external_facility_id", "match_id", "evidence_id", "review_id")):
        batch[table].sort(key=lambda r: r[key])
        require(len({r[key] for r in batch[table]}) == len(batch[table]), "national_duplicate_batch_id")

    audit_rows = []
    for item in challenge_sample(ledger):
        status_view = views.get(item["status_original"], {"rows": [], "complete": False})
        matches = [r for r in status_view["rows"] if r["record_id"] == item["record_id"]]
        audit_rows.append({"record_id": item["record_id"], "status_original": item["status_original"], "date_class": item["date_class"],
                           "end_parse_status": item["end"]["status"], "primary_locator": item["locator"],
                           "primary_sha256": item["snapshot_sha256"], "status_view_complete": status_view["complete"],
                           "result": "displayed_fields_agree" if matches else "unresolved_not_found_in_status_view",
                           "alternate_locators": [{"locator": r["locator"], "sha256": r["snapshot_sha256"]} for r in matches]})
    audit = {"sample_rows": len(audit_rows), "sample_id_sha256": sha(canonical([r["record_id"] for r in audit_rows])),
             "counts": dict(Counter(r["result"] for r in audit_rows)), "by_status": dict(Counter(r["status_original"] for r in audit_rows)),
             "by_date_class": dict(Counter(r["date_class"] for r in audit_rows)), "rows": audit_rows,
             "method": "Deterministic stratified challenge sample, comparing All-status original rows to separately acquired status-filtered original rows; serial is presentation-specific.",
             "independence": "Same NQAS source family; not independent corroboration, blinded human review or a population accuracy estimate."}
    map_data, map_error = None, None
    if "map" in capture["documents"]:
        try:
            map_data = map_summary(checked_raw(root, capture["documents"]["map"]))
            map_data["snapshot_sha256"] = capture["documents"]["map"]["sha256"]
        except SourceError as error:
            map_error = str(error)
    all_totals = views.get("All", {}).get("totals", [])
    reconciliation = {status: {"complete": v["complete"], "advertised_totals": v["totals"], "parsed_occurrences": len(v["rows"]),
        "distinct_record_payloads": len({r["record_id"] for r in v["rows"]}), "advertised_total_stable": len(set(v["totals"])) == 1,
        "parsed_equals_advertised": bool(v["totals"]) and len(set(v["totals"])) == 1 and len(v["rows"]) == v["totals"][0],
        "page_updated_till": v["updates"]} for status, v in views.items()}
    status_union = Counter(r["record_id"] for status, v in views.items() if status != "All" for r in v["rows"])
    primary_counts = Counter(r["record_id"] for r in occurrences)
    discrepancy_ids = set(primary_counts - status_union) | set(status_union - primary_counts)
    discrepancies = {"missing_from_status_views": dict(primary_counts - status_union),
                     "additional_in_status_views": dict(status_union - primary_counts),
                     "source_rows": [{"view": status, **r} for status, v in views.items() for r in v["rows"]
                                     if r["record_id"] in discrepancy_ids]}
    rechecks = []
    if (root / "national_recheck.json").exists():
        for item in read(root / "national_recheck.json")["checks"]:
            if "document" in item:
                checked_raw(root, item["document"])
            rechecks.append(item)
    report = {"as_of": as_of, "source_family": FAMILY, "intended_use": "held_out_accreditation_audit",
        "excluded_from_matching_features": True, "coverage_denominator": "Observed Rajasthan national-register rows; not all campuses or current certifications",
        "views": reconciliation, "capture_blockers": capture["blockers"], "source_row_occurrences": len(occurrences),
        "distinct_record_payloads": len(ledger), "exact_duplicate_occurrences": len(occurrences) - len(ledger),
        "campus_label_groups_unverified": len(label_groups), "repeated_label_groups": sum(len(ids) > 1 for ids in label_groups.values()),
        "unresolved_record_variants_in_repeated_label_groups": len(repeated), "verified_campuses": 0, "verified_renewal_links": 0,
        "status_counts": dict(Counter(r["status_original"] for r in ledger)), "end_parse_status": dict(Counter(r["end"]["status"] for r in ledger)),
        "date_class_counts": dict(Counter(r["date_class"] for r in ledger)), "missing_start_dates": len(ledger),
        "nin_district_category_scope_unavailable": len(ledger), "table_counts": {t: len(batch[t]) for t in TABLES},
        "evidence_withheld_for_v1_temporal_limits": sum(r["evidence_id"] is None for r in ledger),
        "status_views_multiset_equals_all": status_union == primary_counts,
        "status_view_missing_occurrences": sum((primary_counts - status_union).values()),
        "status_view_additional_occurrences": sum((status_union - primary_counts).values()),
        "map": map_data, "map_parse_error": map_error,
        "map_minus_register_observed_rows": map_data["sum_of_displayed_categories"] - len(occurrences) if map_data and map_data["sum_of_displayed_categories"] is not None else None,
        "map_comparison": "Map counts facility categories; register includes printed Certified and Conditionality labels. Shared update labels are recorded, but inclusion/deduplication/expiry rules and campus identifiers are not stated. Difference is unresolved, not reconciled by invention.",
        "audit_sample_rows": audit["sample_rows"], "audit_counts": audit["counts"],
        "discrepancy_rechecks": rechecks,
        "advertised_total_changed_during_capture": len(set(all_totals)) > 1}
    groups = [{"record_ids": ids, "relation": "same_normalized_label_only_unverified_campus_or_renewal"}
              for _, ids in sorted(label_groups.items()) if len(ids) > 1]
    return {"batch": batch, "ledger": ledger, "occurrences": occurrences, "unresolved_groups": groups, "discrepancies": discrepancies,
            "report": report, "audit": audit, "empty_base": []}
