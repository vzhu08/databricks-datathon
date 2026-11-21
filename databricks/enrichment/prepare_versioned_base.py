"""Prepare and replay the reviewed VF version-0 base from frozen SQL exports."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from common import canonical, digest, load, require
from export_sql_snapshot import EXPECTED, verify_receipt, write
from occurrence_keys import POLICY, map_occurrences
from prepare_local_export import local_output, parse_rows
from source_inspection import map_base, profile_rows, verify_base_export

MAPPING = {"id": "unique_id", "name": "name", "state": "address_stateOrRegion", "type": "facilityTypeId",
           "pin": "address_zipOrPostcode", "latitude": "latitude", "longitude": "longitude",
           "evidence": ["description", "specialties", "procedure", "equipment", "capability"]}
POSTAL_MAPPING = {"pin": "pincode", "state": "statename", "district": "district"}
OUTPUTS = ("base", "source_metadata", "duplicate_groups", "postal_rows", "postal_metadata", "validation_report")


def frozen_rows(root):
    root = Path(root)
    verify_receipt(root / "source-receipt")
    capture = load(root / "capture_manifest.json")
    require(capture["version"] == "vf-sql-snapshot-1.0.0", "capture", "unknown export version")
    require(set(capture["sources"]) == set(EXPECTED), "capture", "source set changed")
    sources = {}
    for name, (table, key, expected, buckets) in EXPECTED.items():
        metadata = capture["sources"][name]
        require(metadata["original_table"] == table and type(metadata["observed_delta_version"]) is int
                and metadata["observed_delta_version"] == 0, "capture", "source snapshot changed")
        require(len(metadata["parts"]) == buckets, "capture", "partition count changed")
        rows = []
        for i, part in enumerate(metadata["parts"]):
            require(part["bucket"] == i and part["bucket_count"] == buckets and part["truncated"] is False,
                    "capture", "invalid or truncated partition")
            require(part["artifact"] == "raw/" + name + "-" + str(i) + ".jsonl"
                    and part["query"] == "queries/" + name + "-" + str(i) + ".json",
                    "capture", "unexpected artifact path")
            raw = (root / part["artifact"]).read_bytes()
            query = (root / part["query"]).read_bytes()
            require(hashlib.sha256(raw).hexdigest() == part["sha256"] and len(raw) == part["bytes"],
                    "capture", "raw source hash or size mismatch")
            require(hashlib.sha256(query).hexdigest() == part["query_sha256"], "capture", "query hash mismatch")
            parsed = parse_rows(raw, "jsonl") if raw else []
            require(len(parsed) == part["row_count"], "capture", "part row count mismatch")
            require(all(set(row) == {c["name"] for c in metadata["schema"]["columns"]} for row in parsed),
                    "capture", "original field set changed")
            rows.extend(parsed)
        require(len(rows) == metadata["row_count"] == expected, "capture", "source count mismatch")
        require(digest(sorted(rows, key=canonical)) == metadata["source_rows_sha256"],
                "capture", "source multiset hash mismatch")
        sources[name] = rows
    return capture, sources


def prepare_rows(facilities, postal, facilities_metadata, postal_metadata, capture_hash, completed_at):
    """Pure projection; original rows and postal multiplicity remain untouched."""
    source = facilities_metadata
    base = map_base(facilities, MAPPING["id"], source["original_table"], id_policy=POLICY,
                    source_version=source["observed_delta_version"])
    _, groups = map_occurrences(facilities, MAPPING["id"], source["original_table"],
                                source["observed_delta_version"], POLICY)
    metadata = {k: source[k] for k in ("original_table", "observed_delta_version", "schema", "row_count", "source_rows_sha256")}
    metadata.update(mapping=MAPPING, id_policy=POLICY, snapshot_mode="pinned_delta_version_sql_export",
                    inspected_at=completed_at, source_profile=profile_rows(facilities, MAPPING),
                    sql_capture_manifest="capture_manifest.json", sql_capture_manifest_sha256=capture_hash,
                    base_artifact="base.json", base_file_sha256=digest(base),
                    duplicate_groups_artifact="duplicate_groups.json", duplicate_groups_sha256=digest(groups),
                    row_key_decision="https://github.com/vzhu08/databricks-datathon/issues/6#issuecomment-7069026841")
    verify_base_export(base, metadata)
    postal_rows = sorted(postal, key=canonical)
    pmeta = {k: postal_metadata[k] for k in ("original_table", "observed_delta_version", "schema", "row_count", "source_rows_sha256")}
    require(len(postal_rows) == pmeta["row_count"] and digest(postal_rows) == pmeta["source_rows_sha256"],
            "postal", "original postal multiset changed")
    pmeta.update(mapping=POSTAL_MAPPING, snapshot_mode="pinned_delta_version_sql_export", inspected_at=completed_at,
                 sql_capture_manifest="capture_manifest.json", sql_capture_manifest_sha256=capture_hash,
                 artifact="postal_rows.json", file_sha256=digest(postal_rows))
    pins = Counter(str(row["pincode"]) for row in postal_rows if row.get("pincode") is not None)
    exact = lambda value: value.strip() if isinstance(value, str) and re.fullmatch(r"[0-9]{6}", value.strip()) else None
    matches = sum(exact(row["source_row"].get(MAPPING["pin"])) in pins for row in base)
    original_counts = Counter(canonical(row) for row in facilities)
    prepared_counts = Counter(canonical(row["source_row"]) for row in base)
    lost, added = sum((original_counts - prepared_counts).values()), sum((prepared_counts - original_counts).values())
    require(lost == added == 0, "base", "original row multiset changed")
    report = {"base_rows": len(base), "distinct_internal_keys": len({r["facility_id"] for r in base}),
              "distinct_original_ids": len({r["unique_id"] for r in facilities}), "distinct_full_payloads": len(original_counts),
              "duplicate_groups": len(groups), "occurrence_keys": sum(g["multiplicity"] for g in groups),
              "lost_source_rows": lost, "added_source_rows": added, "original_fields_preserved": True,
              "postal_source_rows": len(postal_rows), "distinct_postal_pins": len(pins),
              "max_postal_rows_per_pin": max(pins.values(), default=0),
              "grouped_pin_lookup_rows": len(base), "base_rows_with_postal_context": matches,
              "lookup_rule": "One aggregated PIN entry; only exact six-digit trimmed source postcodes qualify. Original field values stay unchanged.",
              "duplicate_meaning": "Snapshot-scoped interchangeable row occurrences, not separate campuses, independent evidence or cross-version identities.",
              "enrichment_publication": "not_performed", "submission": "not_performed"}
    return dict(base=base, source_metadata=metadata, duplicate_groups=groups, postal_rows=postal_rows,
                postal_metadata=pmeta, validation_report=report)


def derive(root):
    capture, sources = frozen_rows(root)
    result = prepare_rows(sources["facilities"], sources["postal"], capture["sources"]["facilities"],
                          capture["sources"]["postal"], hashlib.sha256((Path(root) / "capture_manifest.json").read_bytes()).hexdigest(),
                          capture["completed_at"])
    report = result["validation_report"]
    for key, expected in {"base_rows": 10088, "distinct_internal_keys": 10088, "distinct_original_ids": 10077,
                          "distinct_full_payloads": 10077, "duplicate_groups": 11, "occurrence_keys": 22,
                          "postal_source_rows": 165627, "distinct_postal_pins": 19586,
                          "base_rows_with_postal_context": 9568}.items():
        require(report[key] == expected, "reviewed_snapshot", "aggregate differs from the approved version-0 decision: " + key)
    require(all(g["multiplicity"] == 2 for g in result["duplicate_groups"]), "reviewed_snapshot", "duplicate multiplicity changed")
    return result


def finalize(root):
    root = local_output(root)
    require(all(not (root / (name + ".json")).exists() for name in OUTPUTS + ("prepared_manifest",)),
            "output", "prepared files already exist")
    result = derive(root)
    for name in OUTPUTS:
        write(root / (name + ".json"), canonical(result[name]).encode("utf-8"))
    files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(root.rglob("*")) if p.is_file()}
    manifest = {"version": "vf-prepared-base-1.0.0", "id_policy": POLICY, "files": files,
                "report": result["validation_report"]}
    write(root / "prepared_manifest.json", canonical(manifest).encode("utf-8"))
    return {"status": "prepared", "manifest_sha256": hashlib.sha256((root / "prepared_manifest.json").read_bytes()).hexdigest(),
            "report": result["validation_report"]}


def replay(root):
    root = local_output(root)
    manifest = load(root / "prepared_manifest.json")
    require(manifest["version"] == "vf-prepared-base-1.0.0" and manifest["id_policy"] == POLICY,
            "manifest", "unknown prepared version or policy")
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p.name != "prepared_manifest.json"}
    require(actual == set(manifest["files"]), "manifest", "prepared file set changed")
    for name, expected in manifest["files"].items():
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, "manifest", "prepared artifact hash mismatch")
    result = derive(root)
    for name in OUTPUTS:
        require((root / (name + ".json")).read_bytes() == canonical(result[name]).encode("utf-8"),
                "replay", "derived bytes changed: " + name)
    require(manifest["report"] == result["validation_report"], "replay", "aggregate report changed")
    return {"status": "byte_identical_replay", "network_requests": 0, "derived_files": len(OUTPUTS),
            "report": result["validation_report"]}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("finalize", "replay"))
    p.add_argument("--run-dir", required=True)
    args = p.parse_args()
    print(json.dumps((finalize if args.command == "finalize" else replay)(args.run_dir), indent=2))
