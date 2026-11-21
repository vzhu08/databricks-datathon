"""Build a local ACQ-B01 B4 release from reviewed source artifacts."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

from .documents import compact, document_pages, parse_certificate, scope_type


IDS = {
    "source_snapshots": "snapshot_id",
    "external_facilities": "external_facility_id",
    "facility_evidence": "evidence_id",
    "review_queue": "review_id",
    "facility_matches": "match_id",
}
FOLLOW_UP = {
    "source_unavailable": "Retry the public source through its ordinary route.",
    "certificate_not_located": "Recheck the public directory with verified campus aliases.",
    "missing_scope": "Locate a scope or a campus-specific service statement.",
    "branch_mismatch": "Resolve the branch/address discrepancy before using the document.",
    "campus_unresolved": "Obtain campus-specific location or affiliation evidence.",
    "expired_scope": "Locate any later scope and verify its campus and stated dates.",
    "future_scope": "Recheck the stated start date and status after the period begins.",
    "unresolved_interpretation": "Recheck complete service wording and local delivery context.",
    "general_emergency": "Look for trauma-specific wording tied to this campus.",
    "planned": "Seek dated evidence of delivery at the named campus.",
    "referral": "Distinguish receiving and referring facilities before any service claim.",
    "no_institution_page_located": "Locate a verifiable institutional page for the campus.",
    "human_service_review_pending": "Have the integration lead review the passage, campus, and limits before changing its polarity.",
}


def stable_id(namespace, *fields):
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return f"{namespace}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def item_path(root, relative):
    path = (root / relative).resolve()
    path.relative_to(root)
    return path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_file(root, entry):
    path = item_path(root, entry["path"])
    if sha256(path) != entry["sha256"]:
        raise ValueError(f"Raw artifact checksum mismatch: {path}")
    return path


def _source_pages(source, path, root, page_reader):
    pages = list(page_reader(path, source["kind"]))
    if source.get("visual_transcript"):
        if source["kind"] != "certificate":
            raise ValueError("Visual transcripts are supported only for certificate PDFs")
        file = _verified_file(root, source["visual_transcript"])
        transcript = json.loads(file.read_text(encoding="utf-8"))
        if transcript["pdf_sha256"] != source["sha256"] or not compact(transcript["reviewer"]):
            raise ValueError("Visual transcript requires a matching source hash and reviewer")
        for entry in transcript["pages"]:
            number = entry["page"]
            pages[number - 1] = _page(pages, number) + "\n" + entry["text"]
    return pages


def _contained(value, page):
    if not value or compact(value) not in compact(page):
        raise ValueError(f"Reviewed text does not occur on the indicated page: {value!r}")


def _page(pages, number):
    if type(number) is not int or not 1 <= number <= len(pages):
        raise ValueError(f"Page {number!r} is outside the source document")
    return pages[number - 1]


def _snapshot(source, path, digest):
    fields = ("source_key", "publisher", "source_family", "url", "retrieved_at",
              "published_date", "license", "attribution", "independence_status")
    return {
        **{field: source[field] for field in fields},
        "snapshot_id": stable_id("b4.snapshot", source["source_key"], source["url"], digest),
        "sha256": digest,
        "artifact_uri": path.as_uri(),
        "parser_version": "b4-1.0.0",
    }


def _temporal(effective, expiry, as_of):
    if expiry and date.fromisoformat(expiry) < as_of:
        return "expired"
    return "dated" if effective or expiry else "undated"


def _facility(snapshot, document, certificate):
    name = document["campus_name"]
    address = document.get("campus_address")
    record = certificate["certificate_number"] if certificate else None
    locator = document["campus_locator"]
    pin = re.findall(r"(?<!\d)[0-9]{6}(?!\d)", address or "")
    return {
        "external_facility_id": stable_id("b4.facility", snapshot["snapshot_id"], record, locator, name, address),
        "snapshot_id": snapshot["snapshot_id"], "source_record_id": record,
        "record_locator": locator, "name_original": name,
        "name_normalized": " ".join(re.findall(r"[^\W_]+", name.casefold())),
        "address_original": address, "facility_type": "hospital", "city": document.get("city"),
        "state": "Rajasthan", "pin": pin[0] if len(set(pin)) == 1 else None,
        "latitude": None, "longitude": None, "coordinate_method": None,
        "quality_flags": [] if address else ["address_missing_or_partial"],
    }


def _evidence(snapshot, facility, document, quote, certificate, as_of):
    excerpt, location, category = quote["excerpt"], quote["locator"], quote["interpretation"]
    if not compact(location):
        raise ValueError("An excerpt requires a source locator")
    locator = f"PDF p. {quote.get('page', 1)} · {location}" if certificate else location
    if category not in {"identity", "certificate_scope"} and category != scope_type(excerpt):
        raise ValueError(f"Reviewed interpretation conflicts with source text: {locator}")
    if category == "certificate_scope" and not certificate:
        raise ValueError("A general certificate scope requires a parsed certificate")
    effective = certificate["effective_date"] if certificate else quote.get("effective_date")
    expiry = certificate["valid_until"] if certificate else quote.get("valid_until")
    temporal = _temporal(effective, expiry, as_of)
    claim_type = "accreditation" if certificate else ("identity" if category == "identity" else "service")
    service = "trauma_care" if claim_type == "service" else None
    polarity = {"identity": "supports", "certificate_scope": "supports", "explicit_trauma": "supports",
                "negated": "contradicts"}.get(category, "inconclusive")
    human_review = quote.get("human_review") if claim_type == "service" else None
    if claim_type == "service" and not human_review:
        polarity = "inconclusive"
    return {
        "evidence_id": stable_id("b4.evidence", facility["external_facility_id"], locator, excerpt, category),
        "external_facility_id": facility["external_facility_id"], "snapshot_id": snapshot["snapshot_id"],
        "facility_id": None, "match_id": None, "claim_type": claim_type, "service": service,
        "polarity": polarity, "assertion": quote["assertion"], "excerpt": excerpt,
        "observation": None, "locator": locator, "source_url": snapshot["url"],
        "effective_date": effective, "valid_until": expiry, "temporal_status": temporal,
        "reviewer": human_review["reviewer"] if human_review else document["reviewer"],
        "reviewed_at": human_review["reviewed_at"] if human_review else document["reviewed_at"],
    }


def _review(case_id, reason, facility=None, evidence=None):
    external_id = facility["external_facility_id"] if facility else None
    evidence_id = evidence["evidence_id"] if evidence else None
    return {
        "review_id": stable_id("b4.review", case_id, external_id, evidence_id, reason),
        "external_facility_id": external_id, "evidence_id": evidence_id, "facility_id": None,
        "match_id": None, "reason_code": reason, "severity": "high" if reason == "branch_mismatch" else "medium",
        "status": "open", "next_action": FOLLOW_UP[reason], "resolution": None,
    }


def _review_document(case_id, document, source, snapshot, pages, as_of):
    campus_page = _page(pages, document.get("campus_page", 1))
    _contained(document["campus_name"], campus_page)
    if document.get("campus_address"):
        _contained(document["campus_address"], campus_page)
    certificate = parse_certificate(campus_page) if source["kind"] == "certificate" else None
    if source["kind"] == "certificate" and (not certificate or not document.get("campus_address")):
        raise ValueError("A certificate scope requires a source address and parseable metadata")

    campus_status = document["campus_status"]
    if campus_status not in {"matched", "branch_mismatch", "campus_unresolved"} or not compact(document["campus_basis"]):
        raise ValueError("Document review requires a campus disposition and its basis")
    if campus_status != "matched":
        return None, [], [_review(case_id, campus_status)], certificate

    facility = _facility(snapshot, document, certificate)
    evidence, reviews = [], []
    for quote in document["quotes"]:
        _contained(quote["excerpt"], _page(pages, quote.get("page", 1)))
        row = _evidence(snapshot, facility, document, quote, certificate, as_of)
        evidence.append(row)
        category = quote["interpretation"]
        if category in FOLLOW_UP:
            reviews.append(_review(case_id, category, facility, row))
        if row["claim_type"] == "service" and category in {"explicit_trauma", "negated"} and not quote.get("human_review"):
            reviews.append(_review(case_id, "human_service_review_pending", facility, row))
        if row["temporal_status"] == "expired":
            reviews.append(_review(case_id, "expired_scope", facility, row))
        if certificate and row["effective_date"] and date.fromisoformat(row["effective_date"]) > as_of:
            reviews.append(_review(case_id, "future_scope", facility, row))
    if certificate and not any(quote["interpretation"] == "explicit_trauma" for quote in document["quotes"]):
        reviews.append(_review(case_id, "missing_scope", facility))
    return facility, evidence, reviews, certificate


def build_release(manifest, root, page_reader=document_pages):
    """Compile reviewed passages and preserve failed lookups in the audit ledger."""
    root = root.resolve()
    as_of = date.fromisoformat(manifest["as_of"])
    cases = manifest["cases"]
    case_ids = {case["case_id"] for case in cases}
    if len(cases) > 20 or len(case_ids) != len(cases):
        raise ValueError("Select at most 20 unique campus candidates")
    batch = {"contract_version": "1.0.0", **{table: [] for table in IDS}}
    sources = manifest["sources"]
    loaded, ledger = {}, []
    for case in cases:
        case_id = case["case_id"]
        reviews = [_review(case_id, reason) for reason in case["gaps"]]
        entries = []
        for document in case["documents"]:
            key = document["source"]
            source = sources[key]
            if key not in loaded:
                path = _verified_file(root, source)
                loaded[key] = (_snapshot(source, path, source["sha256"]), _source_pages(source, path, root, page_reader))
            snapshot, pages = loaded[key]
            facility, evidence, pending, certificate = _review_document(case_id, document, source, snapshot, pages, as_of)
            if facility:
                batch["source_snapshots"].append(snapshot)
                batch["external_facilities"].append(facility)
                batch["facility_evidence"].extend(evidence)
            reviews.extend(pending)
            entries.append({**document, "certificate": certificate, "evidence_ids": [row["evidence_id"] for row in evidence]})
        batch["review_queue"].extend(reviews)
        ledger.append({**case, "documents": entries, "review_reasons": sorted({row["reason_code"] for row in reviews}),
                       "review_ids": sorted({row["review_id"] for row in reviews})})
    for table, field in IDS.items():
        unique = {}
        for row in batch[table]:
            if unique.setdefault(row[field], row) != row:
                raise ValueError(f"Conflicting record ID: {row[field]}")
        batch[table] = [unique[key] for key in sorted(unique)]
    return batch, {"as_of": manifest["as_of"], "selection": manifest["selection"], "cases": ledger,
                   "case_count": len(ledger), "counts_by_district": dict(Counter(case["district"] for case in ledger))}


def validate(batch, schema):
    from jsonschema import Draft202012Validator, FormatChecker

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(batch)
    snapshots = {row["snapshot_id"]: row for row in batch["source_snapshots"]}
    facilities = {row["external_facility_id"]: row for row in batch["external_facilities"]}
    evidence = {row["evidence_id"]: row for row in batch["facility_evidence"]}
    if batch["facility_matches"]:
        raise ValueError("B4 does not own base facility matching")
    for row in facilities.values():
        if row["snapshot_id"] not in snapshots:
            raise ValueError("Unresolved facility snapshot")
    for row in evidence.values():
        facility = facilities.get(row["external_facility_id"])
        if not facility or facility["snapshot_id"] != row["snapshot_id"]:
            raise ValueError("Unresolved or cross-source evidence campus")
        if row["source_url"] != snapshots[row["snapshot_id"]]["url"] or row["facility_id"] or row["match_id"]:
            raise ValueError("Invalid evidence provenance or base link")
    for row in batch["review_queue"]:
        if row["external_facility_id"] and row["external_facility_id"] not in facilities:
            raise ValueError("Unresolved review campus")
        if row["evidence_id"]:
            claim = evidence.get(row["evidence_id"])
            if not claim or row["external_facility_id"] != claim["external_facility_id"]:
                raise ValueError("Unresolved review evidence or campus mismatch")


def _write(path, value):
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with NamedTemporaryFile(dir=path.parent, delete=False) as destination:
        temporary = Path(destination.name)
        destination.write(payload)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=Path("contracts/enrichment/schema.json"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    root = args.manifest.resolve().parent
    batch, ledger = build_release(manifest, root)
    validate(batch, json.loads(args.schema.read_text(encoding="utf-8")))
    raw_dir = root / "raw"
    raw = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
           for path in sorted(raw_dir.rglob("*")) if path.is_file()]
    inputs = [item_path(root, name) for name in manifest.get("review_artifacts", [])]
    inputs.extend(item_path(root, source["visual_transcript"]["path"])
                  for source in manifest["sources"].values() if source.get("visual_transcript"))
    supporting = [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in sorted(set(inputs))]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write(args.output_dir / "lookup-ledger.json", ledger)
    _write(args.output_dir / "batch.json", batch)
    inventory = [{"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path)}
                 for path in (args.manifest, args.output_dir / "lookup-ledger.json", args.output_dir / "batch.json")]
    _write(args.output_dir / "artifact-inventory.json", {"raw": raw, "produced": inventory, "supporting": supporting})
    print(json.dumps({"cases": ledger["case_count"], **{key: len(batch[key]) for key in IDS}}, sort_keys=True))


if __name__ == "__main__":
    main()
