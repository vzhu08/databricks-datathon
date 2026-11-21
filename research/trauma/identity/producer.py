"""Build a v1.0.0 producer envelope and an auditable B1-to-B2 candidate ledger."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .crosswalk import Campus, build_crosswalk
from .rghs import extract_pdf, normalize_words, parse_date


CONTRACT = "1.0.0"
PARSER = "b2-identity/1.0.0"
TABLE_IDS = {
    "source_snapshots": "snapshot_id",
    "external_facilities": "external_facility_id",
    "facility_matches": "match_id",
    "facility_evidence": "evidence_id",
    "review_queue": "review_id",
}
STATE_SOURCE = "rajasthan_trauma"
SCHEMA = Path(__file__).resolve().parents[3] / "contracts/enrichment/schema.json"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_id(namespace: str, value) -> str:
    return f"{namespace}:{hashlib.sha256(json_bytes(value)).hexdigest()}"


def empty_batch() -> dict:
    return {"contract_version": CONTRACT, **{table: [] for table in TABLE_IDS}}


def make_snapshot(source: dict, path: Path, published: str | None) -> dict:
    digest = checksum(path)
    return {
        "snapshot_id": f"{source['source_key']}:{digest}",
        "source_key": source["source_key"],
        "publisher": source["publisher"],
        "source_family": source["source_family"],
        "url": source["url"],
        "retrieved_at": source["retrieved_at"],
        "published_date": published,
        "license": source.get("license"),
        "attribution": source["attribution"],
        "sha256": digest,
        "artifact_uri": path.as_uri(),
        "parser_version": PARSER,
        "independence_status": source.get("independence_status", "unassessed"),
    }


def facility(snapshot: dict, row: dict) -> dict:
    address = row.get("address")
    flags = set(row.get("flags", []))
    pin_candidates = set(re.findall(r"\bPIN(?:\s*CODE)?\s*[: -]*([1-9][0-9]{5})\b",
                                    address or "", re.I))
    pin_at_end = re.search(r"(?<!\d)([1-9][0-9]{5})[\s.,)]*$", address or "")
    if pin_at_end:
        pin_candidates.add(pin_at_end[1])
    explicit_pin = row.get("pin")
    if explicit_pin:
        pin = explicit_pin if re.fullmatch(r"[1-9][0-9]{5}", explicit_pin) else None
        if not pin:
            flags.add("invalid_pin")
        elif pin_candidates - {pin}:
            flags.add("conflicting_pin")
            pin = None
    else:
        pin = next(iter(pin_candidates)) if len(pin_candidates) == 1 else None
        if len(pin_candidates) > 1:
            flags.add("ambiguous_address_pin")
    if not address:
        flags.add("missing_address")
    if not row.get("name"):
        flags.add("missing_name")
    if not row.get("district"):
        flags.add("missing_district")
    return {
        "external_facility_id": stable_id("b2-facility", [snapshot["snapshot_id"], row]),
        "snapshot_id": snapshot["snapshot_id"],
        "source_record_id": row.get("identifier"),
        "record_locator": row["locator"],
        "name_original": row.get("name"),
        "name_normalized": " ".join(normalize_words(row.get("name"))) or None,
        "address_original": address,
        "facility_type": row.get("facility_type", "hospital"),
        "city": row.get("city"),
        "state": row.get("state"),
        "pin": pin,
        "latitude": None,
        "longitude": None,
        "coordinate_method": None,
        "quality_flags": sorted(flags),
    }


def identity_evidence(snapshot: dict, external: dict, claim: dict) -> dict:
    effective_date = claim.get("effective_date")
    item = {
        "external_facility_id": external["external_facility_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "facility_id": None,
        "match_id": None,
        "claim_type": "identity",
        "service": None,
        "polarity": "supports",
        "assertion": claim["assertion"],
        "excerpt": claim["excerpt"],
        "observation": None,
        "locator": claim["locator"],
        "source_url": snapshot["url"],
        "effective_date": effective_date,
        "valid_until": None,
        "temporal_status": "dated" if effective_date else "undated",
        "reviewer": None,
        "reviewed_at": None,
    }
    return {"evidence_id": stable_id("b2-evidence", item), **item}


def rghs_source(source: dict, path: Path) -> tuple[list[dict], dict, str | None]:
    rows, issues, metadata = extract_pdf(path)
    if not rows:
        issues.append({"locator": "PDF document", "code": "no_recognized_hospital_rows"})
    published = {entry["date"] for entry in metadata["published_date"] if entry["date"]}
    if len(published) > 1:
        issues.append({"locator": "PDF document", "code": "conflicting_publication_dates"})
    return [
        {
            **row.fields,
            "state": row.fields.get("state") or source.get("state"),
            "locator": row.record_locator,
            "identifier_label": row.identifier_label,
            "flags": row.flags,
            "reported_effective_date": parse_date(row.fields.get("effective")),
            "reported_valid_until": parse_date(row.fields.get("expiry")),
            "claims": [{
                "excerpt": row.fields["name"],
                "locator": row.locator + ", facility name cell",
                "assertion": "The RGHS document identifies a facility under this recorded name.",
            }] if row.fields.get("name") else [],
        }
        for row in rows
    ], {"issues": issues, **metadata}, next(iter(published)) if len(published) == 1 else None


def reviewed_source(source: dict, path: Path) -> tuple[list[dict], dict, str | None]:
    """Verify reviewed excerpts against the cited HTML selection or physical PDF page."""
    if not source["records"]:
        raise ValueError(f"Reviewed source has no records: {path}")
    if path.suffix.casefold() == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    else:
        from bs4 import BeautifulSoup

        document = BeautifulSoup(path.read_bytes(), "html.parser")
    for row in source["records"]:
        if not row["claims"]:
            raise ValueError(f"Reviewed record has no claims: {row['locator']}")
        for claim in row["claims"]:
            if path.suffix.casefold() == ".pdf":
                page = claim["page"]
                haystack = pages[page - 1] if 1 <= page <= len(pages) else ""
            else:
                haystack = "\n".join(node.get_text(" ", strip=True)
                                      for node in document.select(claim["selector"])
                                      if "line" not in claim or node.sourceline == claim["line"])
            if not claim["excerpt"].strip() or claim["excerpt"] not in haystack:
                raise ValueError(f"Excerpt missing at {path}: {claim['locator']}")
    return source["records"], {"issues": []}, source.get("published_date")


def read_b1(path: Path, ledger_path: Path | None) -> list[Campus]:
    batch = read_json(path)
    validate(batch)
    district_rows = read_json(ledger_path) if ledger_path else []
    district_by_id = {row["external_facility_id"]: row for row in district_rows}
    accepted_snapshots = {item["snapshot_id"] for item in batch["source_snapshots"]
                          if item["source_key"] == STATE_SOURCE}
    accepted_rows = [row for row in batch["external_facilities"]
                     if row["snapshot_id"] in accepted_snapshots]
    if ledger_path and (
        len(district_by_id) != len(district_rows)
        or set(district_by_id) != {row["external_facility_id"] for row in accepted_rows}
    ):
        raise ValueError("B1 campus ledger and envelope contain different facility IDs")
    rows = [
        Campus(row["external_facility_id"], STATE_SOURCE, row["record_locator"],
               row["name_original"], district_by_id.get(row["external_facility_id"], {}).get(
                   "district_original"
               ),
               row["city"], row["address_original"], row["pin"])
        for row in accepted_rows
    ]
    if not rows:
        raise ValueError("B1 input contains no Rajasthan trauma directory facilities")
    return rows


def review_item(reason: str, external_id: str | None, action: str, identity) -> dict:
    return {
        "review_id": stable_id("b2-review", [reason, external_id, action, identity]),
        "facility_id": None,
        "external_facility_id": external_id,
        "evidence_id": None,
        "match_id": None,
        "reason_code": reason,
        "severity": "medium",
        "status": "open",
        "next_action": action,
        "resolution": None,
    }


def validate(batch: dict, allowed_external: set[str] | None = None) -> None:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(read_json(SCHEMA),
                                    format_checker=Draft202012Validator.FORMAT_CHECKER)
    validator.validate(batch)
    ids = {}
    for table, id_field in TABLE_IDS.items():
        ids[table] = {item[id_field] for item in batch[table]}
        if len(ids[table]) != len(batch[table]):
            raise ValueError(f"Duplicate ID in {table}")
    for table in ("external_facilities", "facility_evidence"):
        for item in batch[table]:
            if item["snapshot_id"] not in ids["source_snapshots"]:
                raise ValueError(f"Unknown snapshot in {table}")
    for item in batch["facility_evidence"]:
        if item["external_facility_id"] not in ids["external_facilities"]:
            raise ValueError("Unknown external facility in evidence")
    for item in batch["review_queue"]:
        if item["external_facility_id"] is not None and item["external_facility_id"] not in (
            ids["external_facilities"] | (allowed_external or set())
        ):
            raise ValueError("Unknown external facility in review queue")


def build(manifest_path: Path, state: list[Campus]) -> tuple[dict, list[dict], dict]:
    manifest = read_json(manifest_path)
    batch = empty_batch()
    references = []
    report = {"sources": [], "crosswalk_input": "B1 contract batch" if state else "pending B1"}
    for source in manifest["sources"]:
        path = (manifest_path.parent / source["path"]).resolve(strict=True)
        readers = {"rghs_pdf": rghs_source, "reviewed": reviewed_source}
        rows, details, published = readers[source["mode"]](source, path)
        source_report = {"source_key": source["source_key"], "path": str(path),
                         "sha256": checksum(path), "row_count": len(rows), "rows": [], **details}
        report["sources"].append(source_report)
        if not rows:
            continue
        snapshot = make_snapshot(source, path, published)
        source_report["snapshot_id"] = snapshot["snapshot_id"]
        batch["source_snapshots"].append(snapshot)
        for row in rows:
            external = facility(snapshot, row)
            external_id = external["external_facility_id"]
            batch["external_facilities"].append(external)
            source_report["rows"].append({**row, "external_facility_id": external_id})
            references.append(Campus(
                external_id, source["source_key"], row["locator"], row.get("name"),
                row.get("district"), row.get("city"), row.get("address"), external["pin"],
                row.get("institution"), external["facility_type"],
            ))
            batch["facility_evidence"].extend(identity_evidence(snapshot, external, claim)
                                              for claim in row["claims"])
        for issue in details["issues"]:
            batch["review_queue"].append(review_item(
                "b2_rghs_parse_issue", None,
                f"Inspect the raw document at {issue['locator']} for {issue['code']}.",
                [snapshot["snapshot_id"], issue],
            ))
    ledger = build_crosswalk(state, references)
    for entry in ledger:
        batch["review_queue"].append(review_item(
            f"b2_campus_{entry['status']}", entry["state_external_facility_id"],
            "Check the B2 crosswalk ledger and verify the hospital campus against official evidence.",
            entry,
        ))
    validate(batch, {row.external_id for row in state})
    report["crosswalk_counts"] = dict(Counter(entry["status"] for entry in ledger))
    report["crosswalk_total"] = len(ledger)
    report["batch_counts"] = {table: len(batch[table]) for table in TABLE_IDS}
    return batch, ledger, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--state-batch", type=Path)
    parser.add_argument("--state-districts", type=Path)
    args = parser.parse_args()
    if args.state_districts and not args.state_batch:
        parser.error("--state-districts requires --state-batch")
    state = read_b1(args.state_batch, args.state_districts) if args.state_batch else []
    batch, ledger, report = build(args.manifest, state)
    report["crosswalk_inputs"] = {
        label: {"path": str(path.resolve()), "sha256": checksum(path)}
        for label, path in (("batch", args.state_batch), ("campus_ledger", args.state_districts))
        if path is not None
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in [
        ("crosswalk.json", ledger), ("parse-report.json", report), ("batch.json", batch),
    ]:
        target = args.output_dir / name
        temporary = target.with_suffix(".json.tmp")
        temporary.write_bytes(json_bytes(payload))
        temporary.replace(target)


if __name__ == "__main__":
    main()
