"""Compile only hash-bound, cleared, reviewed source rows into the v1 contract."""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from research.acquisition.common import canonical, digest, envelope, read_json, write_json
from .parser import extract

ROOT = Path(__file__).resolve().parents[3]
SERVICES = {"dialysis": re.compile(r"\b(?:ha?emodialysis|dialysis)\b", re.I),
            "mri": re.compile(r"\bMRI\b|magnetic\s+resonance", re.I),
            "trauma_care": re.compile(r"\btrauma\b", re.I)}


def scoped_path(root, relative):
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Artifact paths must be relative to the private package")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("Artifact path escapes the private package")
    return path


def stable(prefix, *parts):
    return prefix + ":" + digest(canonical(parts))


def iso_date(value):
    if value is not None:
        date.fromisoformat(value)
    return value


def utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Receipt timestamps must end in Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def compile_rows(rows, capture, metadata, rights):
    """No rights inference: callers must supply an explicit, auditable clearance."""
    if rights.get("status") != "cleared":
        raise ValueError("Source is not cleared for reuse")
    if rights.get("sha256") != capture["sha256"] or rights.get("url") != capture["url"]:
        raise ValueError("Rights clearance does not match the source bytes and URL")
    if rights.get("intended_use") != "private_acquisition_and_team_review":
        raise ValueError("Clearance does not cover the intended private handoff")
    if not all(rights.get(k) for k in ("basis", "basis_uri", "reviewer", "reviewed_at")):
        raise ValueError("Rights clearance requires evidence and a reviewer")
    utc(rights["reviewed_at"])
    utc(capture["retrieved_at"])
    for k in ("publisher", "source_family", "source_key", "layout_reviewer", "layout_reviewed_at"):
        if not metadata.get(k):
            raise ValueError(f"Missing source/layout metadata: {k}")
    utc(metadata["layout_reviewed_at"])
    published = iso_date(metadata.get("published_date"))
    effective = iso_date(metadata.get("effective_date"))
    # A month label is retained verbatim in the sidecar, never invented as day 1.
    sid = stable("ce.snapshot", capture["url"], capture["sha256"])
    batch = envelope()
    batch["source_snapshots"].append(dict(snapshot_id=sid, source_key=metadata["source_key"],
        publisher=metadata["publisher"], source_family=metadata["source_family"], url=capture["url"],
        retrieved_at=capture["retrieved_at"], published_date=published,
        license=f"{rights['basis']} ({rights['basis_uri']}); scope: {rights['intended_use']}",
        attribution=metadata["publisher"], sha256=capture["sha256"],
        artifact_uri=f"urn:sha256:{capture['sha256']}", parser_version="ce-register-1",
        independence_status="unassessed"))
    sidecar = []
    for row in rows:
        locator = row["locator"]
        xid = stable("ce.facility", sid, locator)
        flags = list(row["quality_flags"]) + ["registration_does_not_establish_service", "campus_link_unreviewed"]
        original_pin = row["pin"]
        pin = original_pin if original_pin and re.fullmatch(r"[0-9]{6}", original_pin) else None
        if original_pin and pin is None:
            flags.append("invalid_source_pin")
        # An address number is not silently promoted to an independently supplied PIN.
        name = row["name"]
        batch["external_facilities"].append(dict(external_facility_id=xid, snapshot_id=sid,
            source_record_id=row["registration_id"], record_locator=locator,
            name_original=name, name_normalized=" ".join(name.casefold().split()) if name else None,
            address_original=row["address"], facility_type=row["facility_type"] or "unspecified",
            city=None, state=row["state"], pin=pin, latitude=None, longitude=None,
            coordinate_method=None, quality_flags=sorted(set(flags))))
        sidecar.append(dict(external_facility_id=xid, **row,
                            source_date_text=metadata.get("source_date_text"),
                            source_date_locator=metadata.get("source_date_locator"),
                            published_date=published, effective_date=effective))
        # Explicit wording is captured for adjudication; neither names nor generic
        # multi-specialty categories are positive service evidence.
        wording = row.get("service_wording")
        if wording:
            for service, pattern in SERVICES.items():
                if not pattern.search(wording):
                    continue
                eid = stable("ce.evidence", xid, service, wording)
                batch["facility_evidence"].append(dict(evidence_id=eid, external_facility_id=xid,
                    snapshot_id=sid, facility_id=None, match_id=None, claim_type="service",
                    service=service, polarity="inconclusive",
                    assertion="The source service column contains this wording; onsite capability, polarity, date and campus require review.",
                    excerpt=wording, observation=None, locator=locator + "; field service_wording",
                    source_url=capture["url"], effective_date=effective, valid_until=None,
                    temporal_status="dated" if effective else "undated", reviewer=None, reviewed_at=None))
                batch["review_queue"].append(dict(review_id=stable("ce.review", eid), facility_id=None,
                    external_facility_id=xid, evidence_id=eid, match_id=None, reason_code="explicit_service_wording_requires_review",
                    severity="medium", status="open", next_action="Review exact wording, dates and same-campus attribution before any service decision.", resolution=None))
    return batch, sidecar


def build(root, manifest):
    combined, sidecar, holds, reports = envelope(), [], [], []
    seen = {}
    for doc in manifest["documents"]:
        capture = read_json(scoped_path(root, doc["capture_receipt"]))
        key = capture["url"]
        if capture["status"] != "fetched":
            holds.append(dict(url=key, reason=capture["status"]))
            continue
        raw_path = scoped_path(root, capture["raw_path"])
        if digest(raw_path.read_bytes()) != capture["sha256"]:
            raise ValueError("Raw artifact differs from its capture receipt")
        if capture["sha256"] in seen:
            holds.append(dict(url=key, reason="byte_identical_source_alias", canonical_url=seen[capture["sha256"]]))
            continue
        rights = doc.get("rights", {})
        if rights.get("status") != "cleared":
            holds.append(dict(url=key, sha256=capture["sha256"], reason=rights.get("status", "reuse_unassessed")))
            continue
        if not doc.get("profile"):
            holds.append(dict(url=key, reason="unreviewed_parser_layout"))
            continue
        parsed = extract(raw_path, doc["profile"])
        # Unknown layouts/continuations never become a silently partial release.
        bad = set(parsed["summary"]["reject_reasons"]) - {"header_or_title", "blank_row"}
        if bad or parsed["summary"]["pages_without_tables"] or parsed["summary"]["missing_serials"]:
            holds.append(dict(url=key, reason="unreconciled_extraction", detail=parsed["summary"]))
            continue
        batch, ledger = compile_rows(parsed["rows"], capture, doc["metadata"], rights)
        seen[capture["sha256"]] = key
        for table in combined:
            if table != "contract_version":
                combined[table].extend(batch[table])
        sidecar.extend(ledger)
        reports.append(dict(url=key, sha256=capture["sha256"], summary=parsed["summary"]))
    # Use D's normative schema and cross-table validator; no source rows in logs.
    sys.path.insert(0, str(ROOT / "databricks/enrichment"))
    from merge import plan_merge
    plan_merge([combined, combined], [])
    return {"batch.json": combined, "identity-sidecar.json": sidecar,
            "release-report.json": dict(accepted_counts={t:len(v) for t,v in combined.items() if isinstance(v,list)},
                                         documents=reports, holds=holds,
                                         hold_reasons=dict(Counter(h["reason"] for h in holds)))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    outputs = build(args.root, read_json(args.manifest))
    from research.acquisition.common import publish_json_directory
    publish_json_directory(args.out, outputs, "existing_release_differs")
    print(canonical(outputs["release-report.json"]["accepted_counts"]).decode())


if __name__ == "__main__":
    main()
