"""Read visually identified institutional tables in a hash-pinned Rajasthan DHIS PDF."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import date
import json
from pathlib import Path
import re

from .adip import exact_name_overlap
from .common import AcquisitionError, canonical, digest, envelope, file_digest, public_url, publish_json_directory, read_json, review, validate


STATES = {"registration", "onboarding", "eligibility", "incentive_claimed", "incentive_approved", "incentive_paid", "unknown"}
HEADER = ["s. no.", "district", "name"]


def words(value):
    return " ".join((value or "").casefold().split())


def read_table(cells, section):
    normalized_header = [words(v) for v in section.get("header", HEADER)]
    if len(normalized_header) != 3 or len(set(normalized_header)) != 3:
        raise AcquisitionError("dhis_invalid_header")
    if not cells or [words(v) for v in cells[0]] != normalized_header:
        raise AcquisitionError("dhis_table_header_changed")
    rows = []
    for physical_row, raw_cells in enumerate(cells[1:], 2):
        if len(raw_cells) != 3 or any(v is not None and not isinstance(v, str) for v in raw_cells):
            raise AcquisitionError("dhis_unexpected_facility_columns")
        if [words(v) for v in raw_cells] == normalized_header or not any(words(v) for v in raw_cells):
            continue
        serial, district, name = raw_cells
        if not words(serial) and not words(district) and words(name) and rows:
            rows[-1]["name_original"] += "\n" + name
            rows[-1]["last_table_row"] = physical_row
            continue
        if not re.fullmatch(r"[0-9]+", (serial or "").strip()) or not words(name):
            raise AcquisitionError("dhis_incomplete_facility_row")
        locator = f"annexure={section['annexure']};page={section['page']};table={section['table']};row={physical_row}"
        rows.append({
            "annexure": section["annexure"], "page": section["page"], "table": section["table"],
            "first_table_row": physical_row, "last_table_row": physical_row,
            "serial_original": serial, "district_original": district, "name_original": name,
            "record_locator": locator, "administrative_status": section["status"],
            "status_heading": section["heading"], "heading_page": section["heading_page"],
        })
    if not rows:
        raise AcquisitionError("dhis_empty_selected_table")
    return rows


def audit_sample(rows, limit=20):
    pages = defaultdict(lambda: defaultdict(deque))
    for row in sorted(rows, key=lambda r: (r["page"], r["table"], r["first_table_row"])):
        pages[row["annexure"]][row["page"]].append(row["record_locator"])
    sections = deque(deque(group.values()) for group in pages.values())
    selected = []
    while sections and len(selected) < limit:
        group = sections.popleft()
        page = group.popleft()
        selected.append(page.popleft())
        if page:
            group.append(page)
        if group:
            sections.append(group)
    return selected


def district_check(row, district_labels):
    original = words(row["district_original"])
    if original not in district_labels:
        return "printed_district_unrecognized", []
    normalized_name = words(row["name_original"])
    mentions = sorted(d for d in district_labels if d != original
                      and re.search(r"(?<!\w)" + re.escape(d) + r"(?!\w)", normalized_name))
    if mentions:
        return "name_mentions_another_district", mentions
    return "no_disagreement_detected", []


def compile_reference(rows, snapshot, layout, source_pages):
    batch = envelope()
    batch["source_snapshots"].append(snapshot)
    district_labels = {words(v) for v in layout["district_labels"] if words(v)}
    if not district_labels:
        raise AcquisitionError("dhis_missing_district_vocabulary")
    selected = audit_sample(rows)
    review_inputs = layout.get("audit", {})
    if set(review_inputs) - set(selected):
        raise AcquisitionError("dhis_unexpected_audit_locator")
    audit_results = []
    outcomes = Counter()
    by_annexure = Counter()
    by_status = Counter()
    for row in rows:
        by_annexure[row["annexure"]] += 1
        by_status[row["administrative_status"]] += 1
        original_fields = [row["serial_original"], row["district_original"], row["name_original"], row["administrative_status"]]
        row_digest = digest(canonical(original_fields))
        eid = "dhis-institution:" + digest(canonical([snapshot["snapshot_id"], row["record_locator"], row_digest]))
        result, mentions = district_check(row, district_labels)
        outcomes[result] += 1
        row.update(external_facility_id=eid, fields_sha256=row_digest, district_result=result,
                   other_district_names_in_source_name=mentions)
        batch["external_facilities"].append({
            "external_facility_id": eid, "snapshot_id": snapshot["snapshot_id"],
            "source_record_id": row["serial_original"], "record_locator": row["record_locator"],
            "name_original": row["name_original"], "name_normalized": words(row["name_original"]),
            "address_original": None, "facility_type": "unknown", "city": None, "state": "Rajasthan",
            "pin": None, "latitude": None, "longitude": None, "coordinate_method": None,
            "quality_flags": ["campus_unconfirmed", "programme_identity_only", result],
        })
        if result != "no_disagreement_detected":
            batch["review_queue"].append(review(result, eid, eid, "Review the original district and campus name before linking."))
        if row["record_locator"] in review_inputs:
            item = review_inputs[row["record_locator"]]
            if (not item.get("reviewer") or not item.get("reason") or item.get("outcome") not in {"pass", "uncertain", "fail"}
                    or item.get("fields_sha256") != row_digest):
                raise AcquisitionError("dhis_invalid_audit_record")
            if item["outcome"] == "fail":
                raise AcquisitionError("dhis_failed_visual_audit_requires_correction")
            if item["outcome"] == "uncertain":
                batch["review_queue"].append(review("visual_audit_uncertain", eid, eid, item["reason"]))
            audit_results.append({"record_locator": row["record_locator"], **item})
    validate(batch)
    report = {
        "pdf_pages": source_pages, "rows": len(rows), "by_annexure": dict(by_annexure),
        "by_administrative_status": dict(by_status), "district_review": dict(outcomes),
        "district_vocabulary": sorted(district_labels), "audit_eligible": len(rows),
        "audit_sample": selected, "audit_reviewed": len(audit_results),
        "audit_outcomes": dict(Counter(x["outcome"] for x in audit_results)),
        "audit_state": "pending_visual_checks" if len(audit_results) < len(selected) else "sample_reviewed",
        "live_vf_matches": 0, "current_services": "unknown",
    }
    return {"batch.json": batch, "institutions.json": rows, "audit.json": audit_results, "report.json": report}


def extract(pdf, layout, explicit_batch=None):
    import pdfplumber

    raw_hash = file_digest(pdf)
    if raw_hash != layout["sha256"]:
        raise AcquisitionError("dhis_wrong_source_bytes")
    date.fromisoformat(layout["document_date"])
    snapshot = {
        "snapshot_id": "rajasthan_dhis:" + raw_hash, "source_key": "rajasthan_nhm_dhis",
        "publisher": "National Health Mission, Rajasthan", "source_family": "rajasthan_nhm_dhis",
        "url": public_url(layout["url"]), "retrieved_at": layout["retrieved_at"],
        "published_date": layout["document_date"], "license": layout.get("license"),
        "attribution": "National Health Mission, Rajasthan, Department of Medical, Health & Family Welfare",
        "sha256": raw_hash, "artifact_uri": layout["artifact_uri"], "parser_version": "dhis-tables-1.0.0",
        "independence_status": "unassessed",
    }
    rows, seen = [], set()
    with pdfplumber.open(pdf) as document:
        page_count = len(document.pages)
        if not layout.get("tables"):
            raise AcquisitionError("dhis_no_facility_tables_selected")
        for section in sorted(layout["tables"], key=lambda t: (t["page"], t["table"])):
            page, table, heading_page = section["page"], section["table"], section["heading_page"]
            if (not section.get("reviewer") or not section.get("annexure") or not words(section.get("heading"))
                    or section["status"] not in STATES or type(page) is not int or type(heading_page) is not int
                    or not 1 <= heading_page <= page <= page_count or type(table) is not int or table < 1
                    or (page, table) in seen):
                raise AcquisitionError("dhis_invalid_visual_table_selection")
            seen.add((page, table))
            if "visual_transcript" in section:
                # Image-only tables require a reviewer to transcribe the heading and three institutional columns.
                cells = section["visual_transcript"]
            else:
                heading_text = document.pages[heading_page - 1].extract_text() or ""
                if words(section["heading"]) not in words(heading_text):
                    raise AcquisitionError("dhis_heading_requires_visual_review")
                tables = document.pages[page - 1].extract_tables()
                if table > len(tables):
                    raise AcquisitionError("dhis_table_requires_visual_review")
                cells = tables[table - 1]
            rows.extend(read_table(cells, section))
    results = compile_reference(rows, snapshot, layout, page_count)
    if explicit_batch is not None:
        overlap = exact_name_overlap(results["batch.json"], read_json(explicit_batch))
        counts = [len(row["exact_normalized_name_candidates"]) for row in overlap["rows"]]
        overlap["unmatched_reference_rows"] = counts.count(0)
        overlap["multiple_name_candidates"] = sum(count > 1 for count in counts)
        results["overlap.json"] = overlap
    results["manifest.json"] = {
        "source_sha256": raw_hash, "layout_sha256": digest(canonical(layout)),
        "files": {name: digest(canonical(payload) + b"\n") for name, payload in results.items()},
    }
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", required=True, type=Path)
    p.add_argument("--layout", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--explicit-batch", type=Path)
    args = p.parse_args()
    results = extract(args.pdf, read_json(args.layout), args.explicit_batch)
    publish_json_directory(args.output_dir, results, "dhis_existing_output_not_identical")
    print(json.dumps(results["report.json"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
