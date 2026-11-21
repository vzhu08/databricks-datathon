"""Build a portable, hash-pinned matching packet without changing accepted rows."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

from jsonschema.exceptions import ValidationError

from .common import (AcquisitionError, TABLES, canonical, file_digest,
                     read_json, validate, write_json)
from .parsers import load_features, normalize, present
from .rajasthan import combine_inputs, extract
from .run import verify_saved

PINS = Path(__file__).with_name("matching_inputs.json")
DISTRICT_FIELDS = {"osm": ("adm2_name", "adm2_pcode"), "nhp": ("District", "District_ID")}
CONTACT_FIELDS = ("Telephone", "Mobile_Number", "Nodal_Person_Info", "Nodal_Person_Tele",
                  "Nodal_Person_Email_Id", "Ambulance_Phone_No", "Bloodbank_Phone_No")
BATCH_NAMES = ("national.json", "explicit.json", "additional_review.json")


def district_rows(features, member, snapshot, source, batch):
    """Resolve each accepted row to its first raw feature, without source-ID joins."""
    name_field, code_field = DISTRICT_FIELDS[source]
    prefix = ("zip:" + member if member else "raw") + "#/features/"
    result = []
    for row in batch["external_facilities"]:
        locator = row["record_locator"]
        if not locator.startswith(prefix) or not re.fullmatch(r"0|[1-9][0-9]*", locator[len(prefix):]):
            raise AcquisitionError("unresolvable_district_locator")
        index = int(locator[len(prefix):])
        if index >= len(features):
            raise AcquisitionError("unresolvable_district_locator")
        feature = features[index]
        if normalize(feature, snapshot["snapshot_id"], source, locator)["external_facility_id"] != row["external_facility_id"]:
            raise AcquisitionError("district_feature_identity_mismatch")
        properties = feature["properties"]
        values = {key: properties.get(key) if present(properties.get(key), nhp=source == "nhp") is not None else None
                  for key in (name_field, code_field)}
        result.append({"external_facility_id": row["external_facility_id"],
                       "snapshot_id": snapshot["snapshot_id"], "raw_sha256": snapshot["sha256"],
                       "record_locator": locator, "district_original": values[name_field],
                       "district_code_original": values[code_field],
                       "district_field": name_field, "district_code_field": code_field})
    return result


def check_pinned(path, expected):
    if file_digest(path) != expected["sha256"]:
        raise AcquisitionError("accepted_input_hash_mismatch")
    batch = read_json(path)
    validate(batch)
    for table in ("external_facilities", "source_snapshots", "review_queue"):
        if len(batch[table]) != expected[table]:
            raise AcquisitionError("accepted_input_count_mismatch")
    return batch


def check_subsets(batches):
    generated, _, _, _ = extract([batches["national.json"]])
    for name in ("explicit", "additional_review"):
        if canonical(generated[name]) != canonical(batches[name + ".json"]):
            raise AcquisitionError("regional_batch_does_not_replay")


def coverage(rows, batches):
    indexed = {r["external_facility_id"]: r for r in rows}
    result = {}
    for name, batch in batches.items():
        groups = {}
        for snapshot in batch["source_snapshots"]:
            selected = [indexed[r["external_facility_id"]] for r in batch["external_facilities"]
                        if r["snapshot_id"] == snapshot["snapshot_id"]]
            groups[snapshot["source_key"]] = {
                "rows": len(selected),
                "district_populated": sum(r["district_original"] is not None for r in selected),
                "district_missing": sum(r["district_original"] is None for r in selected),
                "district_code_populated": sum(r["district_code_original"] is not None for r in selected),
                "explicit_institutional_switchboards": 0}
        result[name] = groups
    return result


def build(snapshot_dirs, national_path, regional_dir, output, pins_path=PINS):
    pins = read_json(pins_path)
    paths = {"national.json": Path(national_path),
             **{name: Path(regional_dir) / name for name in BATCH_NAMES[1:]}}
    batches = {name: check_pinned(path, pins[name]) for name, path in paths.items()}
    check_subsets(batches)
    rows, originals, snapshots, raw_counts = [], [], [], {}
    seen = set()
    for directory in sorted(map(Path, snapshot_dirs)):
        source = read_json(directory / "manifest.json")["source"]
        manifest, batch, _ = verify_saved(directory, source)
        snapshot = manifest["snapshot"]
        if snapshot["snapshot_id"] in seen:
            raise AcquisitionError("duplicate_input_snapshot")
        seen.add(snapshot["snapshot_id"])
        snapshots.append(batch)
        features, member, _ = load_features(directory / manifest["raw_file"], source)
        rows.extend(district_rows(features, member, snapshot, source, batch))
        fields = (*DISTRICT_FIELDS[source], *CONTACT_FIELDS)
        raw_counts[snapshot["source_key"]] = {
            "raw_features": len(features),
            "populated_fields": dict(sorted(Counter({key: sum(present(f["properties"].get(key), nhp=source == "nhp") is not None
                                                                 for f in features) for key in fields}).items()))}
        originals.append({"snapshot": snapshot, "provenance": manifest["provenance"],
                          "raw_included": False,
                          "replay_requirement": "Use the original raw snapshot at this SHA-256; artifact_uri is historical and unchanged."})
    combined, _ = combine_inputs(snapshots)
    national, _ = combine_inputs([batches["national.json"]])
    if canonical(combined) != canonical(national):
        raise AcquisitionError("national_batch_does_not_match_snapshot_union")
    rows.sort(key=lambda r: r["external_facility_id"])
    report = {"version": "matching-handoff-1.0.0", "coverage": coverage(rows, batches),
              "raw_input_field_coverage": raw_counts,
              "phone_policy": "No observed field explicitly identifies an institutional switchboard. Generic Telephone, mobile, nodal and service-specific contacts are excluded. No contact values are copied.",
              "district_policy": "Original district labels/codes are source observations, not validated current administrative boundaries or a campus match. Null and NHP zero placeholders remain unknown.",
              "raw_snapshots_included": False, "transfer_status": "local_only_pending_authorized_destination",
              "dhis_status": "blocked_source_pdf_unavailable", "live_databricks": "not_attempted", "submission": "not_attempted"}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".matching-packet-", dir=output.parent) as temp:
        stage = Path(temp)
        for name, path in paths.items():
            shutil.copyfile(path, stage / name)
        write_json(stage / "districts.json", {"version": report["version"], "rows": rows})
        write_json(stage / "coverage.json", report)
        write_json(stage / "provenance.json", sorted(originals, key=lambda x: x["snapshot"]["snapshot_id"]))
        manifest = {"version": report["version"], "accepted_inputs": pins,
                    "files": {p.name: file_digest(p) for p in sorted(stage.iterdir())}}
        write_json(stage / "manifest.json", manifest)
        manifest_hash = file_digest(stage / "manifest.json")
        if output.exists():
            verify(output, manifest_hash)
        else:
            os.rename(stage, output)
    return {"manifest_sha256": manifest_hash, **report}


def verify(directory, expected_manifest_hash):
    directory = Path(directory)
    if file_digest(directory / "manifest.json") != expected_manifest_hash:
        raise AcquisitionError("portable_manifest_hash_mismatch")
    manifest = read_json(directory / "manifest.json")
    expected_files = set(BATCH_NAMES) | {"districts.json", "coverage.json", "provenance.json"}
    if set(manifest["files"]) != expected_files or {p.name for p in directory.iterdir()} != expected_files | {"manifest.json"}:
        raise AcquisitionError("portable_file_set_mismatch")
    for name, expected in manifest["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or file_digest(path) != expected:
            raise AcquisitionError("portable_file_hash_mismatch")
    batches = {name: check_pinned(directory / name, manifest["accepted_inputs"][name]) for name in BATCH_NAMES}
    check_subsets(batches)
    rows = read_json(directory / "districts.json")["rows"]
    national = {r["external_facility_id"]: r for r in batches["national.json"]["external_facilities"]}
    snapshots = {r["snapshot_id"]: r for r in batches["national.json"]["source_snapshots"]}
    if len(rows) != len(national) or {r["external_facility_id"] for r in rows} != set(national):
        raise AcquisitionError("district_sidecar_key_mismatch")
    for row in rows:
        original = national[row["external_facility_id"]]
        if (row["snapshot_id"] != original["snapshot_id"] or row["record_locator"] != original["record_locator"]
                or row["raw_sha256"] != snapshots[original["snapshot_id"]]["sha256"]):
            raise AcquisitionError("district_sidecar_provenance_mismatch")
    if coverage(rows, batches) != read_json(directory / "coverage.json")["coverage"]:
        raise AcquisitionError("district_coverage_mismatch")
    return {name: {table: len(batch[table]) for table in TABLES} for name, batch in batches.items()}


def archive(directory, destination, manifest_hash):
    """Fixed metadata and ordering make archive bytes reproducible on this runtime."""
    directory, destination = Path(directory), Path(destination)
    if directory.resolve() in destination.resolve().parents:
        raise AcquisitionError("archive_overlaps_packet")
    verify(directory, manifest_hash)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".packet-archive-", dir=destination.parent) as temp:
        temporary = Path(temp) / "packet.zip"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
            for path in sorted(directory.iterdir()):
                info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                with path.open("rb") as source, stream.open(info, "w") as target:
                    shutil.copyfileobj(source, target)
        checksum = file_digest(temporary)
        if destination.exists():
            if file_digest(destination) != checksum:
                raise AcquisitionError("existing_archive_not_identical")
        else:
            os.rename(temporary, destination)
    return checksum


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("build")
    create.add_argument("--snapshot", action="append", type=Path, required=True)
    create.add_argument("--national-batch", type=Path, required=True)
    create.add_argument("--regional-dir", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--directory", type=Path, required=True)
    check.add_argument("--manifest-sha256", required=True)
    pack = commands.add_parser("archive")
    pack.add_argument("--directory", type=Path, required=True)
    pack.add_argument("--manifest-sha256", required=True)
    pack.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.snapshot, args.national_batch, args.regional_dir, args.output_dir)
        elif args.command == "verify":
            result = verify(args.directory, args.manifest_sha256)
        else:
            result = {"archive_sha256": archive(args.directory, args.output, args.manifest_sha256)}
    except (AcquisitionError, OSError, ValueError, KeyError, ValidationError) as error:
        reason = str(error) if isinstance(error, AcquisitionError) else "invalid_input_or_io_error"
        print(json.dumps({"status": "failed", "reason": reason}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "verified", "result": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
