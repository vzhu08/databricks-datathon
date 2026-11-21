"""Combine Rajasthan producer batches and freeze a locally reproducible review package."""
import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "contracts/enrichment/schema.json"
TABLES = {
    "source_snapshots": "snapshot_id", "external_facilities": "external_facility_id",
    "facility_matches": "match_id", "facility_evidence": "evidence_id", "review_queue": "review_id",
}
LANES = ("B1", "B2", "B3", "B4")
FORMATS = FormatChecker()


def load_json(path, data=None):
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path.name}: duplicate JSON key {key}")
            result[key] = value
        return result
    raw = path.read_bytes() if data is None else data
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=reject_duplicates)


def digest(row):
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def check_envelope(batch, validator):
    error = next(validator.iter_errors(batch), None)
    if error:
        # Raw records can be subject to source redistribution terms.
        raise ValueError(f"Schema error at {error.json_path} ({error.validator})")
    if batch["facility_matches"]:
        raise ValueError("Developer C owns base identity decisions")
    for table in ("facility_evidence", "review_queue"):
        if any(row["facility_id"] is not None or row["match_id"] is not None for row in batch[table]):
            raise ValueError(f"{table} contains a base link in a B producer batch")


def check_references(tables):
    for row in tables["external_facilities"].values():
        if row["snapshot_id"] not in tables["source_snapshots"]:
            raise ValueError(f"Missing snapshot for {row['external_facility_id']}")
    for row in tables["facility_evidence"].values():
        if row["snapshot_id"] not in tables["source_snapshots"] or row["external_facility_id"] not in tables["external_facilities"]:
            raise ValueError(f"Unresolved source or campus for {row['evidence_id']}")
        if (row["reviewer"] is None) != (row["reviewed_at"] is None):
            raise ValueError(f"Incomplete review metadata for {row['evidence_id']}")
    for row in tables["review_queue"].values():
        for field, table in (("external_facility_id", "external_facilities"), ("evidence_id", "facility_evidence")):
            if row[field] is not None and row[field] not in tables[table]:
                raise ValueError(f"Unresolved {field} for {row['review_id']}")


def read_decisions(path, evidence):
    decisions = {}
    if not path.exists():
        return decisions
    rows = load_json(path)
    if not isinstance(rows, list):
        raise ValueError("B5/audit.json must contain an array of final decisions")
    for decision in rows:
        key = decision["evidence_id"]
        if key not in evidence or key in decisions:
            raise ValueError(f"Unknown or duplicate audited evidence ID {key}")
        if decision["evidence_sha256"] != digest(evidence[key]):
            raise ValueError(f"Audited evidence changed: {key}")
        if decision["outcome"] not in ("pass", "fail", "uncertain"):
            raise ValueError(f"Unknown audit outcome for {key}")
        if not all(isinstance(decision.get(f), str) and decision[f].strip() for f in ("reviewer", "reason", "reviewed_at")):
            raise ValueError(f"Incomplete audit decision for {key}")
        stamp = decision["reviewed_at"]
        if not stamp.endswith("Z") or not FORMATS.conforms(stamp, "date-time"):
            raise ValueError(f"Invalid audit timestamp for {key}")
        decisions[key] = decision
    return decisions


def verify_raw_files(input_dir, snapshots, partial):
    mapping_path = input_dir / "raw_paths.json"
    if partial and not mapping_path.exists():
        return []
    paths = load_json(mapping_path)
    verified = []
    for key, row in sorted(snapshots.items()):
        if key not in paths:
            if partial:
                continue
            raise ValueError(f"Missing raw artifact path for {key}")
        checksum = hashlib.sha256()
        with (input_dir / paths[key]).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                checksum.update(chunk)
        if checksum.hexdigest() != row["sha256"]:
            raise ValueError(f"Raw artifact hash mismatch for {key}")
        verified.append(key)
    return verified


def build(input_dir, *, partial=False):
    validator = Draft202012Validator(load_json(SCHEMA), format_checker=FORMATS)
    tables = {table: {} for table in TABLES}
    producers = {}
    audit_queue_targets = set()
    for lane in (*LANES, "B5"):
        path = input_dir / lane / "batch.json"
        if (partial or lane == "B5") and not path.exists():
            continue
        raw = path.read_bytes()
        batch = load_json(path, raw)
        check_envelope(batch, validator)
        if lane == "B5":
            if any(batch[k] for k in TABLES if k != "review_queue"):
                raise ValueError("The independent audit batch may emit only review items")
            audit_queue_targets = {item["evidence_id"] for item in batch["review_queue"] if item["status"] == "open"}
        producers[lane] = hashlib.sha256(raw).hexdigest()
        for table, primary_key in TABLES.items():
            for row in batch[table]:
                key = row[primary_key]
                indexed = tables[table]
                if key in indexed and digest(indexed[key]) != digest(row):
                    raise ValueError(f"Conflicting {table} payload for {key}")
                indexed[key] = row
    if not producers:
        raise ValueError("No B1–B4 producer batches found")
    check_references(tables)
    verified_raw = verify_raw_files(input_dir, tables["source_snapshots"], partial)
    evidence = tables["facility_evidence"]
    audit_path = input_dir / "B5/audit.json"
    decisions = read_decisions(audit_path, evidence)
    if not partial:
        if not audit_path.is_file():
            raise ValueError("Final release requires B5/audit.json")
        eligible = {key for key, row in evidence.items() if row["claim_type"] in ("service", "accreditation")}
        if len(eligible.intersection(decisions)) < min(30, len(eligible)):
            raise ValueError("B5 service and accreditation scope sample is incomplete")

    ledger = []
    original_queue = [row.copy() for row in tables["review_queue"].values()]
    original_counts = Counter(row["claim_type"] for row in evidence.values())
    for key in sorted(evidence):
        row = evidence[key]
        decision = decisions.get(key)
        outcome = decision["outcome"] if decision else "unsampled"
        ledger.append({"claim": row, "outcome": outcome, "decision": decision})
        if outcome in ("fail", "uncertain"):
            # Keep the claim in the local ledger. A queue may reference only exported IDs.
            del evidence[key]
            for queue_id, item in list(tables["review_queue"].items()):
                if item["evidence_id"] == key:
                    del tables["review_queue"][queue_id]
                    # Preserve original issue and action under a new, unlinked ID.
                    replacement = "b5-unlinked:" + digest(item)
                    if replacement in tables["review_queue"]:
                        raise ValueError(f"Reserved audit queue ID collision for {key}")
                    tables["review_queue"][replacement] = dict(
                        item, review_id=replacement, evidence_id=None,
                        next_action=item["next_action"] + f" See local ledger {key}.",
                    )
            if key in audit_queue_targets:
                continue
            queue_key = "b5-review:" + hashlib.sha256(key.encode()).hexdigest()
            if queue_key in tables["review_queue"]:
                raise ValueError(f"Reserved audit queue ID collision for {key}")
            tables["review_queue"][queue_key] = dict(
                review_id=queue_key, external_facility_id=row["external_facility_id"], facility_id=None,
                match_id=None, evidence_id=None, reason_code="b5_" + outcome, severity="high", status="open",
                next_action=f"Resolve {key} using the B5 audit ledger and request re-review.", resolution=None,
            )
    check_references(tables)
    batch = {"contract_version": "1.0.0", **{
        table: [index[k] for k in sorted(index)] for table, index in tables.items()
    }}
    check_envelope(batch, validator)
    report = {
        "stage": "partial" if partial else "audited", "producer_sha256": producers,
        "contract_version": batch["contract_version"], "counts": {k: len(v) for k, v in tables.items()},
        "claim_types_before_audit": dict(original_counts),
        "temporal_status_before_audit": dict(Counter(item["claim"]["temporal_status"] for item in ledger)),
        "review_outcomes": dict(Counter(item["outcome"] for item in ledger)),
        "audited_claim_types": dict(Counter(item["claim"]["claim_type"] for item in ledger if item["decision"])),
        "raw_snapshot_hashes_verified": verified_raw,
        "claims_by_source_family": dict(Counter(
            tables["source_snapshots"][item["claim"]["snapshot_id"]]["source_family"] for item in ledger
        )),
        "verified_against_public_source": sorted(k for k in decisions if decisions[k]["outcome"] == "pass"),
        "snapshots": [{k: row[k] for k in ("snapshot_id", "source_key", "source_family", "sha256", "artifact_uri")}
                      for row in batch["source_snapshots"]],
    }
    return {"batch.json": batch, "claim_ledger.json": ledger, "coverage.json": report,
            "source_review_ledger.json": sorted(original_queue, key=lambda row: row["review_id"])}


def publish(files, output_dir):
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output_dir.parent) as temporary:
        staging = Path(temporary) / "release"
        staging.mkdir()
        for name, value in files.items():
            (staging / name).write_bytes((json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                                      allow_nan=False) + "\n").encode("utf-8"))
        manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(staging.iterdir())}
        (staging / "sha256.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
        if output_dir.exists():
            if {p.name for p in output_dir.iterdir()} == {p.name for p in staging.iterdir()} and all(
                (output_dir / p.name).is_file() and (output_dir / p.name).read_bytes() == p.read_bytes()
                for p in staging.iterdir()
            ):
                return
            raise ValueError("Release directory differs from this run. Choose a new output directory.")
        os.rename(staging, output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--partial", action="store_true", help="Allow pending producer or audit handoffs")
    args = parser.parse_args()
    files = build(args.input_dir, partial=args.partial)
    publish(files, args.output_dir)
    print(json.dumps({"stage": files["coverage.json"]["stage"], "counts": files["coverage.json"]["counts"]}))


if __name__ == "__main__":
    main()
