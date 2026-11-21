"""Public acquisition and byte-verifiable offline replay.

python -m research.acquisition.run --source all --output-dir data/local/acquisition/public
"""
from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import fcntl
import json
import os
import tempfile
import uuid
from datetime import date
from pathlib import Path

from jsonschema.exceptions import ValidationError

from . import PARSER_VERSION
from .common import (AcquisitionError, ROOT, TABLES, canonical, digest, envelope,
                     file_digest, read_json, review, utc_now, validate, write_json)
from .fetch import Fetcher
from .parsers import load_features, make_batch, resolve_nhp_landing, strict_json

SOURCE_KEYS = {"osm": "hot_osm_health", "nhp": "nhp_hospitals_mirror"}


def iso_date(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise AcquisitionError("invalid_publication_date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise AcquisitionError("invalid_publication_date") from exc


def provenance(source, entry, raw_hash, retrieved_at, url, raw_path, metadata, embedded):
    details = {"publication_date_basis": "No explicit source publication date observed; unknown.",
               "independence_basis": "Shared upstream family; independence from VF has not been assessed."}
    if source == "osm":
        if not isinstance(metadata, dict) or not isinstance(embedded, dict):
            raise AcquisitionError("osm_metadata_missing")
        props, inside = metadata.get("properties", {}), embedded.get("properties", {})
        asset = metadata.get("assets", {}).get("geojson", {})
        if (metadata.get("id") != "hotosm_ind_health_facilities-osm"
                or embedded.get("id") != metadata.get("id")
                or props.get("oex:source") != "osm"
                or inside.get("oex:source") != "osm"
                or props.get("license") != inside.get("license")
                or props.get("oex:snapshot") != inside.get("oex:snapshot")
                or props.get("table:row_count") != inside.get("table:row_count")
                or asset.get("href") != url
                or asset.get("file:size") != raw_path.stat().st_size):
            raise AcquisitionError("osm_metadata_lineage_mismatch")
        license_value = props.get("license")
        if not license_value:
            raise AcquisitionError("osm_license_unverified")
        published = None  # STAC created/updated and OSM snapshot dates are not publication dates.
        publisher = "OpenStreetMap contributors / HOT (Geofabrik extract; oex export)"
        attribution = "© OpenStreetMap contributors; HOT/Geofabrik/oex distribution. " + license_value + "; https://www.openstreetmap.org/copyright"
        details.update(source_capture_date=props.get("oex:snapshot"),
                       artifact_created_at=props.get("created"), metadata_updated_at=props.get("updated"),
                       expected_input_rows=props.get("table:row_count"),
                       expected_distinct_ids=next((c.get("oex:distinct_count") for c in props.get("table:columns", []) if c.get("name") == "id"), None))
    else:
        if not isinstance(metadata, dict) or not isinstance(metadata.get("creator"), dict):
            raise AcquisitionError("nhp_upstream_metadata_missing")
        publisher = metadata["creator"].get("name")
        attribution = metadata.get("creditText")
        license_value = metadata.get("license")
        if not publisher or "National Health Portal" not in publisher or not attribution or not license_value:
            raise AcquisitionError("nhp_license_or_lineage_unverified")
        publisher += " / Bharatlas mirror"
        published = iso_date(metadata.get("datePublished"))
        if published:
            details["publication_date_basis"] = "Explicit datePublished on the mirror's Dataset metadata; not verified upstream freshness."
        details.update(mirror_modified_date=metadata.get("dateModified"),
                       upstream_date=None, upstream_date_note="No verified upstream as-of date; filename year is not a date.")
    return {
        "snapshot_id": entry["source_key"] + ":" + raw_hash,
        "source_key": entry["source_key"], "publisher": publisher,
        "source_family": entry["source_family_hint"], "url": url, "retrieved_at": retrieved_at,
        "published_date": published, "license": license_value, "attribution": attribution,
        "sha256": raw_hash, "artifact_uri": raw_path.as_uri(),
        "parser_version": PARSER_VERSION, "independence_status": "shared_origin",
    }, details


def verify_saved(directory, source):
    directory = Path(directory).resolve()
    manifest = read_json(directory / "manifest.json")
    if manifest.get("source") != source or manifest.get("parser_version") != PARSER_VERSION:
        raise AcquisitionError("replay_source_or_parser_mismatch")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or file_digest(directory / name) != expected:
            raise AcquisitionError("persisted_artifact_hash_mismatch")
    snapshot = manifest["snapshot"]
    raw = directory / manifest["raw_file"]
    if file_digest(raw) != snapshot["sha256"] or snapshot["snapshot_id"] != SOURCE_KEYS[source] + ":" + snapshot["sha256"]:
        raise AcquisitionError("snapshot_identity_mismatch")
    features, member, _ = load_features(raw, source)
    batch, coverage = make_batch(features, member, snapshot, source)
    if canonical(batch) != canonical(read_json(directory / "batch.json")) or canonical(coverage) != canonical(read_json(directory / "coverage.json")):
        raise AcquisitionError("replay_content_mismatch")
    validate(batch)
    return manifest, batch, coverage


def acquire(source, output, entry, fetcher, replay=None):
    raw_name = "raw.zip" if source == "osm" else "raw.geojson"
    if replay:
        manifest, batch, coverage = verify_saved(replay, source)
        fetcher.log({"source": source, "attempted_at": fetcher.clock(), "outcome": "replayed",
                     "snapshot_id": manifest["snapshot"]["snapshot_id"]})
        return batch, coverage, str(Path(replay).resolve()), manifest["provenance"]
    staging_root = output / ".staging"
    staging_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging_root) as temp:
        stage = Path(temp)
        raw = stage / raw_name
        support_name = "source_metadata.json" if source == "osm" else "landing.html"
        support_url = entry["related_urls"]["metadata"] if source == "osm" else entry["entry_url"]
        fetcher.download(support_url, stage / support_name, "json" if source == "osm" else "html", source)
        if source == "osm":
            metadata = strict_json((stage / support_name).read_bytes())
            download_url = entry["related_urls"]["download"]
        else:
            download_url, metadata = resolve_nhp_landing((stage / support_name).read_bytes(), entry["entry_url"])
        event = fetcher.download(download_url, raw, "zip" if source == "osm" else "json", source)
        raw_hash = file_digest(raw)
        dest = output / "snapshots" / entry["source_key"] / raw_hash
        if dest.exists():
            manifest, batch, coverage = verify_saved(dest, source)
            return batch, coverage, str(dest), manifest["provenance"]
        features, member, embedded = load_features(raw, source)
        # Provenance names the final raw artifact. Its size is checked against the staged file.
        snapshot, details = provenance(source, entry, raw_hash, event["retrieved_at"], download_url,
                                       raw, metadata, embedded)
        snapshot["artifact_uri"] = (dest / raw_name).as_uri()
        batch, coverage = make_batch(features, member, snapshot, source)
        expected = details.get("expected_input_rows")
        if expected is not None and expected != coverage["input"]["rows"]:
            raise AcquisitionError("metadata_row_count_mismatch")
        validate(batch)
        write_json(stage / "batch.json", batch)
        write_json(stage / "coverage.json", coverage)
        manifest = {"manifest_version": "1.0.0", "source": source, "parser_version": PARSER_VERSION,
                    "raw_file": raw_name, "snapshot": snapshot, "provenance": details,
                    "files": {p.name: file_digest(p) for p in stage.iterdir() if p.is_file()}}
        write_json(stage / "manifest.json", manifest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # The directory becomes visible only after validation and all writes succeed.
        os.rename(stage, dest)
        return batch, coverage, str(dest), details


def coverage_for_report(coverage, batch):
    """Add per-type dedup/conflict metrics without mutating accepted sidecars."""
    coverage = copy.deepcopy(coverage)
    conflicts = defaultdict(list)
    for row in batch["external_facilities"]:
        if "conflicting_source_identifier" in row["quality_flags"]:
            conflicts[row["facility_type"]].append(row)
    for kind, metrics in coverage["by_facility_type"].items():
        metrics["exact_duplicates_removed"] = metrics["input"]["rows"] - metrics["output"]["rows"]
        metrics["conflicting_variants"] = len(conflicts[kind])
        metrics["conflicting_source_identifiers"] = len({row["source_record_id"] for row in conflicts[kind]})
    return coverage


def run(sources, output_dir, replay=None, fetcher=None):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    registry = read_json(ROOT / "contracts/enrichment/source_registry.json")
    entries = {s["source_key"]: s for s in registry["sources"]}
    fetcher = fetcher or Fetcher(output / "attempts.jsonl")
    run_id = uuid.uuid4().hex
    result = envelope()
    report = {"run_id": run_id, "started_at": fetcher.clock(), "contract_version": "1.0.0", "sources": {},
              "live_databricks": "not attempted by this collector", "submission": "not attempted"}
    with (output / ".writer.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AcquisitionError("output_directory_busy") from exc
        for source in sources:
            try:
                batch, coverage, directory, details = acquire(source, output, entries[SOURCE_KEYS[source]], fetcher, replay)
                for table in TABLES:
                    result[table].extend(batch[table])
                report["sources"][source] = {"status": "replayed" if replay else "accepted", "snapshot_directory": directory,
                                              "snapshot_id": batch["source_snapshots"][0]["snapshot_id"],
                                              "coverage": coverage_for_report(coverage, batch), "provenance": details}
                write_json(output / (source + "-latest.json"), {"snapshot_directory": directory,
                                                            "snapshot_id": batch["source_snapshots"][0]["snapshot_id"]})
            except (AcquisitionError, OSError, ValueError, KeyError, ValidationError) as exc:
                # Exception strings, response bodies, and raw records are never logged.
                reason = str(exc) if isinstance(exc, AcquisitionError) else "local_or_metadata_error"
                report["sources"][source] = {"status": "failed", "reason": reason}
                result["review_queue"].append(review("acquisition_failed", [source, reason, run_id], action=
                    "Inspect acquisition report for " + source + "; retry after resolving " + reason + ". Prior accepted snapshots are unchanged."))
                fetcher.log({"source": source, "attempted_at": fetcher.clock(), "outcome": "failed", "reason": reason})
        validate(result)
        report["finished_at"] = fetcher.clock()
        report["status"] = "complete" if all(s["status"] != "failed" for s in report["sources"].values()) else "partial_or_failed"
        run_dir = output / "runs" / run_id
        write_json(run_dir / "batch.json", result)
        write_json(run_dir / "report.json", report)
        write_json(output / "latest-run.json", {"run_id": run_id, "report": str(run_dir / "report.json"),
                                               "batch": str(run_dir / "batch.json"), "status": report["status"]})
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["osm", "nhp", "all"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay", type=Path, help="Accepted snapshot directory containing manifest.json and original raw bytes; offline")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args(argv)
    if args.replay and args.source == "all":
        parser.error("--replay requires a single source")
    fetcher = Fetcher(args.output_dir / "attempts.jsonl", timeout=args.timeout, attempts=args.attempts)
    report = run(["osm", "nhp"] if args.source == "all" else [args.source], args.output_dir, args.replay, fetcher)
    print(json.dumps({"status": report["status"], "run_id": report["run_id"],
                      "sources": {k: {"status": v["status"], "snapshot_id": v.get("snapshot_id"),
                                       "reason": v.get("reason"), "output_rows": v.get("coverage", {}).get("output", {}).get("rows")}
                                  for k, v in report["sources"].items()}}, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
