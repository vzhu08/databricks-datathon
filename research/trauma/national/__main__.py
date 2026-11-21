"""Build the B3 contract envelope, claim ledger and artifact inventory."""

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .parser import flatten, read_pdf, text_hashes


REPO = Path(__file__).resolve().parents[3]
SOURCE_KEY = "mohfw_trauma_program"
PARSER_VERSION = "1.0.0"
STATE = "rajasthan"
AUDIT_SECTIONS = ("completed", "under_construction", "construction_not_started", "supported")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest(content):
    return hashlib.sha256(content).hexdigest()


def sha256(path):
    return digest(path.read_bytes())


def stable_id(namespace, *parts):
    return f"{namespace}:{digest(json_bytes(parts))}"


def document_dates(observations):
    """Accept only explicitly attributed report dates from the PDF review."""
    values = {"publication": set(), "status_as_of": set()}
    for item in observations:
        kind, locator, excerpt = item["kind"], item["locator"], item["excerpt"]
        if kind not in values or not locator.strip() or not excerpt.strip():
            raise ValueError("Date observations need a date kind, source locator and excerpt")
        raw = item["date"]
        if date.fromisoformat(raw).isoformat() != raw:
            raise ValueError("Date observations must use YYYY-MM-DD")
        values[kind].add(raw)
    conflicts = [kind for kind, dates in values.items() if len(dates) > 1]
    published, as_of = (next(iter(dates)) if len(dates) == 1 else None
                        for dates in values.values())
    if published and as_of and as_of > published:
        conflicts.append("status_after_publication")
        as_of = None
    return {"published_date": published, "status_as_of": as_of, "valid_until": None,
            "conflicts": conflicts, "observations": observations}


def rajasthan_rows(document):
    return [row for row in document.rows if flatten(row.state).casefold() == STATE]


def reviewed_rows(document, review):
    """Compare the PDF parse against the independent, hash-keyed page transcription."""
    rows = rajasthan_rows(document)
    counts = Counter(row.section.key for row in rows)
    expected = {section: counts[section] for section in AUDIT_SECTIONS}
    actual = {
        row.key: (row.page, row.name, row.printed_level, row.printed_status) for row in rows
    }
    transcribed = {
        row["key"]: (row["page"], row["name"], row["printed_level"], row["printed_status"])
        for row in review["rows"]
    }
    if (expected != review["rajasthan_counts"]
            or actual != transcribed or len(transcribed) != len(review["rows"])
            or review["annexure_1_facility_rows"] != 0
            or review["pages_reviewed"] != list(range(1, len(document.pages) + 1))):
        raise ValueError("Parsed Rajasthan rows disagree with the page-by-page visual review")
    for note in review["issues"]:
        if note["row"] not in actual:
            raise ValueError(f"Visual issue refers to an unknown Rajasthan row: {note['row']}")
    return rows


def compare_documents(primary, older):
    first, second = primary["document"], older["document"]
    first_text, second_text = text_hashes(first), text_hashes(second)
    new_rows = {row.key: row for row in rajasthan_rows(first)}
    old_rows = {row.key: row for row in rajasthan_rows(second)}
    changed = []
    for key in sorted(new_rows.keys() | old_rows.keys()):
        new, old = new_rows.get(key), old_rows.get(key)
        if new is None or old is None or (
            new.name, new.printed_level, new.printed_status
        ) != (old.name, old.printed_level, old.printed_status):
            changed.append(key)
    same_bytes = primary["sha256"] == older["sha256"]
    return {
        "source_family": SOURCE_KEY,
        "primary_sha256": primary["sha256"],
        "older_sha256": older["sha256"],
        "byte_identical": same_bytes,
        "extracted_text_identical": first_text == second_text,
        "primary_page_text_sha256": first_text,
        "older_page_text_sha256": second_text,
        "same_edition": same_bytes or (
            first_text == second_text and not changed and primary["dates"] == older["dates"]
        ),
        "changed_rajasthan_row_locators": changed,
        "date_metadata_differs": primary["dates"] != older["dates"],
    }


def interpretations(row):
    """Record programme history while leaving the service determination inconclusive."""
    if row.level:
        yield ("programme_level", f"MoHFW listed programme level {row.level} in its historical trauma programme.")
    if row.printed_status:
        yield ("reported_functionality",
               f"MoHFW recorded the historical functionality status as {flatten(row.printed_status)}.")
    contexts = {
        "under_construction": "reported construction in progress",
        "construction_not_started": "reported that construction had yet to start",
        "supported": "listed programme support for the twelfth Five-Year Plan",
    }
    if row.section.key in contexts:
        yield ("programme_stage", f"MoHFW {contexts[row.section.key]}.")


def review_item(snapshot_id, code, action, *, external_id=None, severity="medium"):
    return {
        "review_id": stable_id("b3-review", snapshot_id, external_id, code),
        "facility_id": None, "external_facility_id": external_id,
        "evidence_id": None, "match_id": None, "reason_code": code,
        "severity": severity, "status": "open", "next_action": action, "resolution": None,
    }


def add_snapshot(batch, ledger, acquired, registry, lineage, *, comparison_only=False, all_states=False):
    snapshot_id = f"{SOURCE_KEY}:{acquired['sha256']}"
    dates, review, url = acquired["dates"], acquired["review"], acquired["resolved_url"]
    batch["source_snapshots"].append({
        "snapshot_id": snapshot_id, "source_key": SOURCE_KEY,
        "publisher": registry["publisher_hint"], "source_family": registry["source_family_hint"],
        "url": url, "retrieved_at": acquired["retrieved_at"],
        "published_date": dates["published_date"], "license": None,
        "attribution": "Ministry of Health and Family Welfare, Government of India (NPPMTBI programme brief)",
        "sha256": acquired["sha256"], "artifact_uri": acquired["path"].as_uri(),
        "parser_version": PARSER_VERSION, "independence_status": "shared_origin",
    })
    if dates["conflicts"]:
        batch["review_queue"].append(review_item(
            snapshot_id, "conflicting_programme_dates", "Reconcile the cited source dates before dating the claim."
        ))
    if lineage["date_metadata_differs"]:
        batch["review_queue"].append(review_item(
            snapshot_id, "programme_version_date_disagreement",
            "Compare the cited report dates and retain the source-specific chronology.",
        ))
    rows = acquired["document"].rows if all_states else acquired["rows"]
    for row in rows:
        rajasthan = flatten(row.state).casefold() == STATE
        reviewer = review["reviewer"] if rajasthan else None
        reviewed_at = review["reviewed_at"] if rajasthan else None
        external_id = stable_id("b3-facility", snapshot_id, row.key)
        notes = [issue for issue in review["issues"] if issue["row"] == row.key]
        flags = ["historical_programme_listing", "state_from_programme_section"]
        flags.extend(issue["code"] for issue in notes)
        if comparison_only:
            flags.append("shared_origin_variant")
        if not row.name:
            flags.append("missing_name")
        if not row.level:
            flags.append("missing_or_unrecognized_programme_level")
        batch["external_facilities"].append({
            "external_facility_id": external_id, "snapshot_id": snapshot_id, "source_record_id": None,
            "record_locator": row.locator, "name_original": row.name,
            "name_normalized": flatten(row.name).casefold() if row.name else None,
            "address_original": None, "facility_type": "unknown", "city": None,
            "state": "Rajasthan" if rajasthan else flatten(row.state), "pin": None, "latitude": None, "longitude": None,
            "coordinate_method": None, "quality_flags": sorted(set(flags)),
        })
        for issue in notes:
            batch["review_queue"].append(review_item(
                snapshot_id, issue["code"], issue["action"], external_id=external_id,
                severity=issue["severity"],
            ))
        if row.key in lineage["changed_rajasthan_row_locators"]:
            batch["review_queue"].append(review_item(
                snapshot_id, "programme_version_disagreement",
                "Compare the two source rows, report dates and campus attribution before relying on the change.",
                external_id=external_id,
            ))
        evidence_ids = {}
        claims = list(interpretations(row))
        if all_states and not rajasthan and row.section.key == "completed":
            claims.append(("programme_stage", "MoHFW listed construction as completed in its historical programme."))
        for kind, assertion in claims:
            evidence_id = stable_id("b3-evidence", external_id, kind)
            evidence_ids[kind] = evidence_id
            batch["facility_evidence"].append({
                "evidence_id": evidence_id, "external_facility_id": external_id, "snapshot_id": snapshot_id,
                "facility_id": None, "match_id": None, "claim_type": "service", "service": "trauma_care",
                "polarity": "inconclusive", "assertion": assertion, "excerpt": row.excerpt, "observation": None,
                "locator": f"{row.locator}; context: {row.section.locator}; state label on PDF p. {row.state_page}",
                "source_url": url, "effective_date": dates["status_as_of"], "valid_until": None,
                "temporal_status": "historical",
                "reviewer": reviewer, "reviewed_at": reviewed_at,
            })
        ledger.append({
            "external_facility_id": external_id, "snapshot_id": snapshot_id, "row": row.key,
            "locator": row.locator, "section_heading": row.section.heading,
            "section_heading_locator": row.section.locator,
            "state_as_printed": row.state, "state_label_pdf_page": row.state_page,
            "name_and_place_as_printed": row.name, "printed_level": row.printed_level, "level": row.level,
            "printed_functionality": row.printed_status, "programme_stage": row.section.key,
            "excerpt": row.excerpt, "published_date": dates["published_date"],
            "status_as_of": dates["status_as_of"], "valid_until": dates["valid_until"],
            "status_is_historical": True, "eligible_as_current_status": False,
            "date_conflicts": dates["conflicts"], "visual_review": "pass" if rajasthan else "not_individually_reviewed",
            "reviewer": reviewer, "reviewed_at": reviewed_at,
            "unresolved_issues": notes, "evidence_ids": evidence_ids,
        })


def validate_batch(batch):
    schema = read_json(REPO / "contracts/enrichment/schema.json")
    checker = FormatChecker()
    if not {"date", "date-time", "uri"} <= checker.checkers.keys():
        raise RuntimeError("Install jsonschema with the format-nongpl extra for contract format checks")
    Draft202012Validator(schema, format_checker=checker).validate(batch)
    ids = {}
    for table, column in {
        "source_snapshots": "snapshot_id", "external_facilities": "external_facility_id",
        "facility_evidence": "evidence_id", "review_queue": "review_id",
    }.items():
        identifiers = {row[column]: row for row in batch[table]}
        if len(identifiers) != len(batch[table]):
            raise ValueError(f"Duplicate IDs in {table}")
        ids[table] = identifiers
    snapshots, facilities = ids["source_snapshots"], ids["external_facilities"]
    if batch["facility_matches"]:
        raise ValueError("B3 cannot emit base matches")
    for row in facilities.values():
        if row["snapshot_id"] not in snapshots:
            raise ValueError("Unknown facility snapshot")
    for row in batch["facility_evidence"]:
        facility = facilities.get(row["external_facility_id"])
        if not facility or facility["snapshot_id"] != row["snapshot_id"]:
            raise ValueError("Unknown evidence facility or inconsistent snapshot")
        if (row["source_url"] != snapshots[row["snapshot_id"]]["url"]
                or not row["excerpt"] or row["facility_id"] or row["match_id"]):
            raise ValueError("Evidence requires a source excerpt and must remain unlinked to the base")
    for row in batch["review_queue"]:
        if (row["external_facility_id"] is not None and row["external_facility_id"] not in facilities
                or row["evidence_id"] is not None and row["evidence_id"] not in ids["facility_evidence"]
                or row["facility_id"] or row["match_id"]):
            raise ValueError("Unknown or out-of-scope review reference")


def load_acquisitions(manifest_path, review_path, registry):
    manifest, reviews = read_json(manifest_path), read_json(review_path)
    acquired = {}
    documents = {}
    for label, registered_url in (("primary", registry["entry_url"]),
                                  ("older", registry["related_urls"]["older_copy"])):
        item = manifest[label]
        path = (manifest_path.parent / item["file"]).resolve(strict=True)
        checksum = sha256(path)
        if item["registered_url"] != registered_url or checksum != item["sha256"]:
            raise ValueError(f"Registered origin or bytes disagree with the manifest for {label}")
        if checksum not in documents:
            documents[checksum] = read_pdf(path)
        document = documents[checksum]
        review = reviews[checksum]
        acquired[label] = {
            **item, "path": path, "document": document, "review": review,
            "rows": reviewed_rows(document, review), "dates": document_dates(review["date_observations"]),
        }
    return acquired


def artifact(path, checksum, size, role):
    return {"path": str(path.resolve()), "sha256": checksum, "bytes": size, "role": role}


def build(manifest_path, review_path, output_dir, *, all_states=False, prior_release=None):
    if all_states and prior_release is None:
        raise ValueError("The all-state extension requires the prior Rajasthan release directory")
    if not all_states and prior_release is not None:
        raise ValueError("--prior-release is used with --all-states")
    if all_states and output_dir.resolve() in {manifest_path.parent.resolve(), review_path.parent.resolve(),
                                               prior_release.resolve()}:
        raise ValueError("Use a separate output directory for the national extension")
    registry = next(item for item in read_json(REPO / "contracts/enrichment/source_registry.json")["sources"]
                    if item["source_key"] == SOURCE_KEY)
    acquired = load_acquisitions(manifest_path, review_path, registry)
    lineage = compare_documents(acquired["primary"], acquired["older"])
    batch = {"contract_version": "1.0.0", "source_snapshots": [], "external_facilities": [],
             "facility_matches": [], "facility_evidence": [], "review_queue": []}
    ledger = []
    add_snapshot(batch, ledger, acquired["primary"], registry, lineage, all_states=all_states)
    if not lineage["same_edition"]:
        add_snapshot(batch, ledger, acquired["older"], registry, lineage, comparison_only=True, all_states=all_states)
    if all_states:
        from .national_release import national_receipt, publish_national
        national = national_receipt(batch, ledger, acquired, prior_release)
    validate_batch(batch)

    coverage = {
        label: {
            "pages": len(item["document"].pages),
            "sections": dict(Counter(row.section.key for row in item["document"].rows)),
            "rajasthan_counts": item["review"]["rajasthan_counts"],
            "date_metadata": item["document"].metadata,
            "date_interpretation": item["dates"],
            "date_review_context": item["review"]["date_context"],
            "annexure_1_facility_rows": item["review"]["annexure_1_facility_rows"],
        } for label, item in acquired.items()
    }
    coverage["batch_counts"] = {key: len(value) for key, value in batch.items() if isinstance(value, list)}
    coverage["levels"] = dict(Counter(row["level"] or "unknown" for row in ledger))
    coverage["functionality"] = dict(Counter(row["printed_functionality"] or "unknown" for row in ledger))
    if all_states:
        coverage["national"] = national
    parts = {
        "temporal_claim_ledger.json": ("claim_ledger", ledger),
        "lineage.json": ("lineage", lineage),
        "coverage.json": ("coverage", coverage),
        "batch.json": ("producer_envelope", batch),
    }
    inventory = []
    for label, item in acquired.items():
        entry = artifact(item["path"], item["sha256"], item["path"].stat().st_size, "raw_pdf")
        inventory.append({**entry, "label": label, "registered_url": item["registered_url"],
                          "resolved_url": item["resolved_url"], "retrieved_at": item["retrieved_at"],
                          "archive_capture_utc": item.get("archive_capture_utc"),
                          "retrieval_attempts": item["retrieval_attempts"]})
    for path, role in ((manifest_path, "acquisition_manifest"), (review_path, "visual_review")):
        inventory.append(artifact(path, sha256(path), path.stat().st_size, role))
    if all_states:
        for name in ("batch.json", "claim_ledger.json"):
            path = prior_release / name
            inventory.append(artifact(path, sha256(path), path.stat().st_size, "prior_rajasthan_release"))
    outputs = {}
    for name, (role, payload) in parts.items():
        encoded = json_bytes(payload)
        outputs[name] = encoded
        inventory.append(artifact(output_dir / name, digest(encoded), len(encoded), role))
    outputs["artifact_inventory.json"] = json_bytes({"artifacts": inventory})
    if all_states:
        publish_national(output_dir, outputs)
        return coverage["batch_counts"]
    output_dir.mkdir(parents=True, exist_ok=True)
    # Publish the envelope last so it can serve as the initial handoff marker.
    for name in ("temporal_claim_ledger.json", "lineage.json", "coverage.json", "artifact_inventory.json",
                 "batch.json"):
        target = output_dir / name
        temporary = target.with_suffix(".json.tmp")
        temporary.write_bytes(outputs[name])
        temporary.replace(target)
    return coverage["batch_counts"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--visual-review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--all-states", action="store_true", help="Emit all states and preserve previous audit decisions")
    parser.add_argument("--prior-release", type=Path, help="Directory with the prior batch.json and claim_ledger.json")
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.visual_review, args.output_dir,
                           all_states=args.all_states, prior_release=args.prior_release), sort_keys=True))


if __name__ == "__main__":
    main()
