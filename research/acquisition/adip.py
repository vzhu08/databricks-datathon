"""Bounded institutional-only ADIP panel extraction from a locally supplied PDF.

The audited split offsets are local artifacts, not facility records in Git.
No doctor, contact or email columns enter the output. This is an identity lead,
not a service finding. Redistribution permission remains a separate decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

from .common import AcquisitionError, canonical, digest, envelope, file_digest, publish_json_directory, read_json, review, validate, write_json

VERSION = "adip-institutions-1.0.0"
HEADER = ["Sr. No.", "State", "Name of Hospital"]


def institutions(tables):
    """Require the observed six-column layout; never fill down missing states."""
    result = []
    for page, table_number, table in tables:
        if not table or [str(c or "").strip() for c in table[0][:3]] != HEADER:
            raise AcquisitionError("adip_table_header_changed")
        for row_number, cells in enumerate(table, 1):
            if len(cells) != 6:
                raise AcquisitionError("adip_table_width_changed")
            institutional = cells[:3]
            if [str(c or "").strip() for c in institutional] == HEADER:
                continue
            if not any(str(c or "").strip() for c in institutional):
                continue  # Blank row inserted by layout extraction; no contact content retained.
            serial, state, institution = institutional
            if state is None or not str(state).strip():
                raise AcquisitionError("adip_missing_state_requires_review")
            if str(state).strip().casefold() != "rajasthan":
                continue
            if not isinstance(serial, str) or not re.fullmatch(r"[0-9]+", serial.strip()) or not isinstance(institution, str) or not institution.strip():
                raise AcquisitionError("adip_incomplete_institution")
            result.append({"serial_original": serial, "state_original": state,
                           "institution_original": institution, "page": page,
                           "table": table_number, "extracted_table_row": row_number,
                           "record_locator": f"pdf:page={page};table={table_number};row={row_number};serial={serial.strip()}"})
    if not result:
        raise AcquisitionError("adip_empty_rajasthan_subset")
    return result


def make_reference(rows, snapshot, audit):
    if audit["raw_sha256"] != snapshot["sha256"]:
        raise AcquisitionError("adip_audit_hash_mismatch")
    bindings = {r["record_locator"]: r for r in audit["rows"]}
    if len(bindings) != len(audit["rows"]) or set(bindings) != {r["record_locator"] for r in rows}:
        raise AcquisitionError("adip_audit_coverage_mismatch")
    batch = envelope(); batch["source_snapshots"] = [snapshot]
    sidecar = []
    for row in rows:
        binding = bindings[row["record_locator"]]
        original = row["institution_original"]
        offset = binding["name_end"]
        if (binding.get("institution_sha256") != digest(original.encode("utf-8"))
                or binding.get("visually_checked") is not True or type(offset) is not int
                or not 0 < offset < len(original)):
            raise AcquisitionError("adip_unaudited_or_changed_institution")
        name, address = original[:offset], original[offset:]
        if not name.strip() or not address.strip():
            raise AcquisitionError("adip_invalid_split")
        eid = "acq-external:" + digest(canonical([snapshot["snapshot_id"], row["record_locator"], original]))
        flags = ["historical_panel_not_current_service_evidence", "campus_identity_unconfirmed",
                 "redistribution_permission_unconfirmed", "coordinates_missing", "district_not_in_source"]
        if binding.get("campus_ambiguity"):
            flags.append("multiple_institution_or_group_wording")
        batch["external_facilities"].append({
            "external_facility_id": eid, "snapshot_id": snapshot["snapshot_id"],
            "source_record_id": row["serial_original"], "record_locator": row["record_locator"],
            "name_original": name, "name_normalized": " ".join(unicodedata.normalize("NFKC", name).casefold().split()),
            "address_original": address, "facility_type": "hospital", "city": None,
            "state": row["state_original"], "pin": None, "latitude": None, "longitude": None,
            "coordinate_method": None, "quality_flags": sorted(flags)})
        batch["review_queue"].append(review("campus_identity_unconfirmed", eid, eid,
            "Inspect the dated institutional panel and address before linking a campus; no service inference."))
        sidecar.append({**row, "external_facility_id": eid, "name_end": offset,
                        "campus_ambiguity": binding.get("campus_ambiguity", False)})
    batch["external_facilities"].sort(key=lambda r: r["external_facility_id"])
    batch["review_queue"].sort(key=lambda r: r["review_id"])
    validate(batch)
    return batch, sidecar


def exact_name_overlap(reference, regional):
    """A reproducible name-equality diagnostic; never emits a campus match."""
    from .rajasthan import words
    indexed = {}
    for row in regional["external_facilities"]:
        normalized = words(row["name_original"])
        if normalized:
            indexed.setdefault(normalized, []).append(row["external_facility_id"])
    rows = [{"reference_id": row["external_facility_id"], "record_locator": row["record_locator"],
             "exact_normalized_name_candidates": sorted(indexed.get(words(row["name_original"]), [])),
             "campus_status": "unresolved"} for row in reference["external_facilities"]]
    return {"method": "Exact equality under research.acquisition.rajasthan.words; name equality is a review lead, not a campus match. No fuzzy or address matching.",
            "reference_rows": len(rows), "explicit_rajasthan_rows": len(regional["external_facilities"]),
            "reference_rows_with_exact_name_candidate": sum(bool(r["exact_normalized_name_candidates"]) for r in rows),
            "candidate_pairs": sum(len(r["exact_normalized_name_candidates"]) for r in rows),
            "confirmed_campuses": 0, "rows": rows}


def publish_overlap(destination, result):
    """Preserve existing files, including an accidentally selected input batch."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".adip-overlap-", dir=destination.parent) as temp:
        staged = Path(temp) / "overlap.json"
        write_json(staged, result)
        try:
            os.link(staged, destination)
        except FileExistsError:
            if not destination.is_file() or file_digest(destination) != file_digest(staged):
                raise AcquisitionError("adip_existing_overlap_not_identical")


def build(pdf, acquisition_metadata, audit_path, output):
    import pdfplumber
    metadata, audit = read_json(acquisition_metadata), read_json(audit_path)
    raw_hash = file_digest(pdf)
    if raw_hash != metadata["raw_sha256"]:
        raise AcquisitionError("adip_raw_hash_mismatch")
    with pdfplumber.open(pdf) as document:
        pages = len(document.pages)
        selected_pages = audit["page_numbers"]
        if not selected_pages or any(type(i) is not int or not 1 <= i <= pages for i in selected_pages) or len(selected_pages) != len(set(selected_pages)):
            raise AcquisitionError("adip_invalid_page_scope")
        rows = institutions((i, j, table) for i in sorted(selected_pages)
                            for j, table in enumerate(document.pages[i - 1].extract_tables(), 1))
    snapshot = {"snapshot_id": "depwd_adip_panel:" + raw_hash, "source_key": "depwd_adip_panel",
                "publisher": "Department of Empowerment of Persons with Disabilities / AYJNISHD(D), Government of India",
                "source_family": "depwd_adip", "url": metadata["url"],
                "retrieved_at": metadata["local_acquired_at"], "published_date": None,
                "license": "Redistribution permission unconfirmed; https://depwd.gov.in/en/copyright-policy/",
                "attribution": "Department of Empowerment of Persons with Disabilities, Ministry of Social Justice & Empowerment, Government of India; ADIP cochlear implant hospital panel.",
                "sha256": raw_hash, "artifact_uri": Path(pdf).resolve().as_uri(),
                "parser_version": VERSION, "independence_status": "unassessed"}
    batch, sidecar = make_reference(rows, snapshot, audit)
    report = {"parser_version": VERSION, "pdfplumber_version": pdfplumber.__version__,
              "pdf_pages": pages, "audited_page_numbers": sorted(selected_pages), "rajasthan_rows": len(rows),
              "rows_by_page": dict(Counter(str(r["page"]) for r in rows)),
              "distinct_serials": len({r["serial_original"] for r in rows}),
              "manually_audited": len(audit["rows"]), "manual_cell_corrections": 0,
              "campus_group_wording": sum(bool(r["campus_ambiguity"]) for r in sidecar),
              "printed_district_field": False, "district_unavailable": len(rows),
              "listing_date": metadata["listing_date"], "document_date": None,
              "date_basis": "Website listing date only; the PDF has no verified issue/as-of date. Filename is not a date.",
              "remote_download_timestamp": None, "local_acquired_at": metadata["local_acquired_at"],
              "source_bytes": "Supplied by integration lead; raw hash verified before local copy.",
              "excluded_columns": ["Name of Doctor", "Contact Details", "Email Id"],
              "release_status": "local_research_only_permission_unconfirmed",
              "scope": "Dated institutional identity leads; no DHIS status, clinical service or current availability assertion.",
              "audit_sha256": file_digest(audit_path), "raw_sha256": raw_hash}
    payloads = {"batch.json": batch, "institutions.json": sidecar, "report.json": report}
    payloads["manifest.json"] = {"files": {name: digest(canonical(data) + b"\n") for name, data in payloads.items()},
                                 "raw_sha256": raw_hash, "audit_sha256": file_digest(audit_path)}
    publish_json_directory(output, payloads, "adip_existing_output_not_identical")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--explicit-batch", type=Path)
    p.add_argument("--overlap-output", type=Path)
    a = p.parse_args()
    if bool(a.explicit_batch) != bool(a.overlap_output):
        p.error("Supply both --explicit-batch and --overlap-output")
    print(json.dumps(build(a.pdf, a.metadata, a.audit, a.output_dir), indent=2))
    if a.explicit_batch:
        publish_overlap(a.overlap_output, exact_name_overlap(read_json(a.output_dir / "batch.json"), read_json(a.explicit_batch)))
