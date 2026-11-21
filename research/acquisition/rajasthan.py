"""Deterministic, lossless Rajasthan subsets of accepted acquisition snapshots."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from jsonschema.exceptions import ValidationError

from .common import (AcquisitionError, TABLES, canonical, digest, envelope,
                     file_digest, read_json, review, validate, write_json)
from .run import verify_saved

RULES_PATH = Path(__file__).with_name("rajasthan_rules.json")
ID_FIELDS = dict(zip(TABLES, ("snapshot_id", "external_facility_id", "match_id", "evidence_id", "review_id")))


def words(value):
    """Fold Latin accents/case/punctuation; preserve non-Latin vowel marks."""
    output = []
    latin = False
    for char in unicodedata.normalize("NFKD", value or "").casefold():
        if unicodedata.combining(char):
            if not latin:
                output.append(char)
        else:
            latin = "LATIN" in unicodedata.name(char, "")
            output.append(char if char.isalnum() or unicodedata.category(char).startswith("M") else " ")
    return " ".join(unicodedata.normalize("NFC", "".join(output)).split())


@lru_cache(maxsize=8)
def address_aliases(names):
    return tuple(sorted((words(s) for s in names), key=lambda s: (-len(s), s)))


def address_state(address, rules):
    text = words(address)
    # Country and six-digit postal suffixes may occur in either order.
    for _ in range(2):
        text = re.sub(r"(?:^| )(?:india|भारत)$", "", text).strip()
        text = re.sub(r"(?:^| )(?:(?:pin|pincode|pin code) )?[0-9]{6}$", "", text).strip()
    aliases = address_aliases(tuple(rules["address_state_suffixes"]))
    return next((s for s in aliases if text == s or text.endswith(" " + s)), None)


def classify(row, rules):
    state = words(row["state"])
    missing = state in rules["missing_state_tokens"]
    rajasthan = {words(s) for s in rules["rajasthan_aliases"]}
    state_positive = state in rajasthan
    address = address_state(row["address_original"], rules)
    address_positive = address in rajasthan
    geo = rules["geographic_screen"]
    x, y = row["longitude"], row["latitude"]
    inside = None if x is None or y is None else (
        geo["longitude_min"] <= x <= geo["longitude_max"]
        and geo["latitude_min"] <= y <= geo["latitude_max"])
    reasons = []
    if state_positive:
        reasons.append("explicit_rajasthan_state")
    if address_positive:
        reasons.append("explicit_rajasthan_address_suffix")
    conflicts = []
    if address_positive and not missing and not state_positive:
        conflicts.append("state_address_disagreement")
    if state_positive and address is not None and not address_positive:
        conflicts.append("address_state_disagreement")
    if (state_positive or address_positive) and inside is False:
        conflicts.append("explicit_text_outside_geographic_screen")
    if reasons:
        bucket = "additional_review" if conflicts else "explicit"
        reasons.extend(conflicts)
    elif inside:
        bucket = "additional_review"
        reasons.append("missing_state_inside_geographic_screen" if missing else "other_state_inside_geographic_screen")
    else:
        bucket = "excluded"
        reasons.append("no_rajasthan_text_or_geographic_screen_signal")
    return {"bucket": bucket, "reasons": sorted(reasons), "state_missing": missing,
            "coordinate_in_screen": inside, "address_state_suffix_recognized": address is not None}


def combine_inputs(batches):
    """Exact repeated IDs deduplicate; conflicting payloads never overwrite."""
    indexed = {table: {} for table in TABLES}
    occurrences = Counter()
    for batch in batches:
        if batch.get("facility_matches") or batch.get("facility_evidence"):
            raise AcquisitionError("expected_unlinked_acquisition_inputs")
        for row in batch["external_facilities"]:
            occurrences[row["snapshot_id"]] += 1
        for table, key in ID_FIELDS.items():
            for row in batch[table]:
                old = indexed[table].get(row[key])
                if old is not None and canonical(old) != canonical(row):
                    raise AcquisitionError("conflicting_input_payload")
                indexed[table][row[key]] = row
    combined = envelope()
    for table in TABLES:
        combined[table] = [indexed[table][key] for key in sorted(indexed[table])]
    validate(combined)
    # A's inputs are unlinked; do not silently lose base/evidence/match review context.
    if any(r[k] is not None for r in combined["review_queue"] for k in ("facility_id", "evidence_id", "match_id")):
        raise AcquisitionError("unsupported_linked_review_context")
    return combined, occurrences


def extract(batches, rules=None):
    rules = rules or read_json(RULES_PATH)
    rule_hash = digest(canonical(rules))
    national, occurrences = combine_inputs(batches)
    outputs = {name: envelope() for name in ("explicit", "additional_review")}
    # Preserve both source reference rows even if a source contributes zero candidates.
    for output in outputs.values():
        output["source_snapshots"] = copy.deepcopy(national["source_snapshots"])
    selected = {name: set() for name in outputs}
    decisions = []
    per_snapshot = {}
    for snapshot in national["source_snapshots"]:
        sid = snapshot["snapshot_id"]
        per_snapshot[sid] = {"source_key": snapshot["source_key"], "raw_sha256": snapshot["sha256"],
                            "input_occurrences": occurrences[sid], "unique_national_rows": 0,
                            "explicit": 0, "additional_review": 0, "excluded": 0,
                            "reason_counts": Counter()}
    for row in national["external_facilities"]:
        decision = classify(row, rules)
        sid, eid, bucket = row["snapshot_id"], row["external_facility_id"], decision["bucket"]
        counts = per_snapshot[sid]
        counts["unique_national_rows"] += 1
        counts[bucket] += 1
        counts["reason_counts"].update(decision["reasons"])
        decisions.append({"external_facility_id": eid, "snapshot_id": sid, **decision})
        if bucket in outputs:
            outputs[bucket]["external_facilities"].append(copy.deepcopy(row))
            selected[bucket].add(eid)
        if bucket == "additional_review":
            outputs[bucket]["review_queue"].append(review(
                "rajasthan_candidate_review", [rule_hash, eid, decision["reasons"]], eid,
                "Review original state/address and coordinate placement before including this campus in Rajasthan; "
                "the geographic rectangle includes neighboring states and does not prove a source label wrong."))
    for bucket, output in outputs.items():
        for existing in national["review_queue"]:
            if existing["external_facility_id"] is None or existing["external_facility_id"] in selected[bucket]:
                output["review_queue"].append(copy.deepcopy(existing))
        for table, key in ID_FIELDS.items():
            output[table].sort(key=lambda r: r[key])
        validate(output)
    for counts in per_snapshot.values():
        counts["identical_input_occurrences_removed"] = counts["input_occurrences"] - counts["unique_national_rows"]
        counts["partition_reconciles"] = counts["unique_national_rows"] == sum(counts[b] for b in ("explicit", "additional_review", "excluded"))
        counts["reason_counts"] = dict(sorted(counts["reason_counts"].items()))
    if selected["explicit"] & selected["additional_review"]:
        raise AcquisitionError("overlapping_selection_buckets")
    report = {"rule_version": rules["version"], "rule_sha256": rule_hash, "rules": rules,
              "contract_version": "1.0.0", "producer_v1_validation": "passed",
              "snapshot_counts": per_snapshot,
              "totals": {key: sum(c[key] for c in per_snapshot.values()) for key in (
                  "input_occurrences", "identical_input_occurrences_removed", "unique_national_rows",
                  "explicit", "additional_review", "excluded")},
              "output_counts": {bucket: {table: len(rows) for table, rows in output.items() if table in TABLES}
                                for bucket, output in outputs.items()},
              "limitations": ["Candidates are not confirmed matches, clinical evidence, or verified current facilities.",
                              "The geographic screen includes neighboring states; an other-state label inside is not established to be incorrect.",
                              "Name, district/city names, and PIN prefixes are not selection proof; use the complete national batch for recall.",
                              "Raw records, source timestamps, IDs, locators, and source-family independence are unchanged."]}
    return outputs, decisions, report, national


def write_extract(snapshot_dirs, national_path, output_dir):
    national_path = Path(national_path).resolve()
    output = Path(output_dir).resolve()
    paths = [Path(p).resolve() for p in snapshot_dirs]
    for source in paths + [national_path.parent]:
        if output == source or output in source.parents or source in output.parents:
            raise AcquisitionError("output_overlaps_input_storage")
    batches, sources = [], []
    for directory in paths:
        source = read_json(directory / "manifest.json")["source"]
        if source not in {"osm", "nhp"}:
            raise AcquisitionError("unsupported_source")
        manifest, batch, coverage = verify_saved(directory, source)
        batches.append(batch)
        sources.append({"snapshot_id": manifest["snapshot"]["snapshot_id"],
                        "snapshot_directory": str(directory), "raw_sha256": manifest["snapshot"]["sha256"],
                        "batch_sha256": file_digest(directory / "batch.json"),
                        "manifest_sha256": file_digest(directory / "manifest.json"),
                        "raw_input_features": coverage["input"]["rows"],
                        "national_output_rows": coverage["output"]["rows"],
                        "acquisition_exact_duplicates_removed": coverage["exact_duplicates_removed"]})
    outputs, decisions, report, combined = extract(batches)
    supplied, _ = combine_inputs([read_json(national_path)])
    if canonical(supplied) != canonical(combined):
        raise AcquisitionError("national_batch_does_not_match_snapshot_union")
    report["national_recall_input"] = {"path": str(national_path), "sha256": file_digest(national_path),
                                       "preserved": True, "matches_snapshot_union": True}
    report["source_inputs"] = sorted(sources, key=lambda s: (s["snapshot_id"], s["snapshot_directory"]))
    payloads = {"explicit.json": outputs["explicit"], "additional_review.json": outputs["additional_review"],
                "decisions.json": decisions, "report.json": report}
    payloads["manifest.json"] = {"rule_version": report["rule_version"], "rule_sha256": report["rule_sha256"],
                                 "national_sha256": report["national_recall_input"]["sha256"],
                                 "files": {name: digest(canonical(data) + b"\n") for name, data in payloads.items()}}
    if output.exists():
        if not output.is_dir() or set(p.name for p in output.iterdir()) != set(payloads):
            raise AcquisitionError("existing_output_not_identical")
        if any((output / name).read_bytes() != canonical(data) + b"\n" for name, data in payloads.items()):
            raise AcquisitionError("existing_output_not_identical")
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rajasthan-", dir=output.parent) as temp:
        stage = Path(temp)
        for name, value in payloads.items():
            write_json(stage / name, value)
        os.rename(stage, output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, action="append", required=True, help="Accepted snapshot directory; repeat per source")
    parser.add_argument("--national-batch", type=Path, required=True, help="Unmodified national contract envelope retained for recall")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory, or an identical prior extraction for replay")
    args = parser.parse_args(argv)
    try:
        report = write_extract(args.snapshot, args.national_batch, args.output_dir)
    except (AcquisitionError, OSError, ValueError, KeyError, ValidationError) as error:
        reason = str(error) if isinstance(error, AcquisitionError) else "invalid_input_or_io_error"
        print(json.dumps({"status": "failed", "reason": reason}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "complete", "contract_version": report["contract_version"],
                      "rule_sha256": report["rule_sha256"], "counts": report["totals"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
