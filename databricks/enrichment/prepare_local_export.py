#!/usr/bin/env python3
"""Prepare preserved base rows from an authorized operator's JSON/JSONL export."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

from jsonschema import FormatChecker

from common import ROOT, Invalid, canonical, digest, finite, load, require
from delta_store import identifier
from source_inspection import map_base, profile_rows, verify_base_export

MAX_BYTES = 512 * 1024 * 1024
MAX_ROWS = 500000


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "input", "duplicate JSON object key; export again without ambiguous columns")
        result[key] = value
    return result


def _number(token):
    value = float(token)
    require(math.isfinite(value) and Decimal(str(value)) == Decimal(token), "input.number",
            "fractional number cannot round-trip losslessly; export precise decimals as strings with source type metadata")
    return value


def _constant(_):
    raise Invalid("input.number: non-finite JSON numbers are forbidden")


def parse_rows(raw, input_format, max_rows=MAX_ROWS):
    require(input_format in ("json", "jsonl"), "format", "choose json or jsonl explicitly")
    require(type(max_rows) is int and 0 < max_rows <= MAX_ROWS, "max_rows", f"must be 1..{MAX_ROWS}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise Invalid("input: UTF-8 required; no replacement of invalid source bytes") from error

    def parse(value, location):
        try:
            return json.loads(value, object_pairs_hook=_object, parse_float=_number, parse_constant=_constant)
        except json.JSONDecodeError as error:
            raise Invalid(f"{location}: malformed/truncated JSON at line {error.lineno}, column {error.colno}") from error

    if input_format == "json":
        rows = parse(text, "input")
        require(isinstance(rows, list), "input", "JSON input must be an array of row objects")
    else:
        lines = text.split("\n")  # Do not split U+2028 inside a valid JSON string.
        if lines and lines[-1] == "":
            lines.pop()
        require(len(lines) <= max_rows, "input", "export exceeds max_rows; split into explicitly scoped exports")
        rows = []
        for index, line in enumerate(lines, 1):
            require(bool(line.strip()), f"input.line[{index}]", "blank JSONL rows are forbidden")
            rows.append(parse(line, f"input.line[{index}]"))
    require(bool(rows) and len(rows) <= max_rows, "input", "expected a nonempty bounded export")
    for index, row in enumerate(rows):
        require(isinstance(row, dict), f"input.rows[{index}]", "each exported row must be an object")
    finite(rows, "input")
    # Encoding rejects lone surrogate escapes, without replacing source text.
    try:
        canonical(rows).encode("utf-8")
    except UnicodeEncodeError as error:
        raise Invalid("input: invalid Unicode surrogate in row text") from error
    return rows


def observed_types(rows):
    types = {}
    for row in rows:
        for field, value in row.items():
            kind = ("null" if value is None else "boolean" if isinstance(value, bool) else
                    "integer" if isinstance(value, int) else "number" if isinstance(value, float) else
                    "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object")
            types.setdefault(field, set()).add(kind)
    return {field: sorted(kinds) for field, kinds in sorted(types.items())}


def _write_bytes(path, content):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_directory(output_dir, files, metadata):
    """Publish a fully verified local directory, never an incomplete final path.

    A sibling exclusive lock serializes adapters using the same destination.
    A process crash can leave hidden staging/lock files; it cannot label them final.
    """
    output = Path(output_dir).absolute()
    require(not output.exists() and not output.is_symlink(), "output_dir", "destination already exists; choose a new run directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / ("." + output.name + ".lock")
    try:
        lock_fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise Invalid("output_dir: another adapter or interrupted attempt holds the destination lock") from error
    os.close(lock_fd)
    staging = None
    try:
        require(not output.exists() and not output.is_symlink(), "output_dir", "destination already exists")
        staging = Path(tempfile.mkdtemp(prefix="." + output.name + ".staging-", dir=output.parent))
        for filename, content in files.items():
            _write_bytes(staging / filename, content)
        _write_bytes(staging / "source_metadata.json", canonical(metadata).encode("utf-8"))
        readback = load(staging / "base.json")
        saved_metadata = load(staging / "source_metadata.json")
        require(saved_metadata == metadata, "output", "metadata readback differs")
        require(hashlib.sha256((staging / "base.json").read_bytes()).hexdigest() == metadata["base_file_sha256"],
                "output.base", "base readback hash mismatch")
        require(hashlib.sha256((staging / metadata["operator_export"]["artifact"]).read_bytes()).hexdigest() ==
                metadata["operator_export"]["sha256"], "output.input", "raw export readback hash mismatch")
        verify_base_export(readback, saved_metadata)
        require(not output.exists() and not output.is_symlink(), "output_dir", "destination appeared during preparation")
        os.rename(staging, output)  # Same parent/filesystem; final path appears after verification.
        staging = None
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        lock.unlink()


def prepare_export(input_path, input_format, source_table, mapping, output_dir, *,
                   operator, exported_at, completeness, scope, expected_row_count=None,
                   reported_delta_version=None, max_rows=MAX_ROWS, max_bytes=MAX_BYTES):
    identifier(source_table, 3)
    require(isinstance(mapping, dict) and isinstance(mapping.get("id"), str) and mapping["id"].strip(),
            "mapping.id", "explicit observed source ID column required; no automatic surrogate")
    for field, value in (("operator", operator), ("scope", scope)):
        require(isinstance(value, str) and bool(value.strip()), field, "nonempty operator-supplied value required")
    require(isinstance(exported_at, str) and exported_at.endswith("Z") and
            FormatChecker().conforms(exported_at, "date-time"), "exported_at", "operator's UTC export time required")
    require(completeness in ("complete", "partial", "unknown"), "completeness", "choose complete, partial or unknown explicitly")
    require(expected_row_count is None or (type(expected_row_count) is int and expected_row_count >= 0),
            "expected_row_count", "must be a nonnegative integer or unknown")
    require(completeness != "complete" or expected_row_count is not None, "expected_row_count",
            "complete export requires an independent count for the stated selection")
    require(reported_delta_version is None or (type(reported_delta_version) is int and reported_delta_version >= 0),
            "reported_delta_version", "must be nonnegative or unknown")
    require(type(max_bytes) is int and 0 < max_bytes <= MAX_BYTES, "max_bytes", f"must be 1..{MAX_BYTES}")
    source = Path(input_path)
    require(source.is_file(), "input", "regular export file required")
    # Hash and parse the same bounded bytes; never reread a changing input at copy time.
    with source.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    require(len(raw) <= max_bytes, "input", "file exceeds byte limit; use a bounded scoped export")
    rows = parse_rows(raw, input_format, max_rows)
    if expected_row_count is not None:
        require(len(rows) <= expected_row_count, "expected_row_count", "export exceeds the operator's stated selection count")
        if completeness == "complete":
            require(len(rows) == expected_row_count, "completeness", "export row count is incomplete; re-export or explicitly label partial")
        elif completeness == "partial":
            require(len(rows) < expected_row_count, "completeness", "partial label disagrees with expected count; clarify selection/count")
    profile = profile_rows(rows, mapping)
    base = map_base(rows, mapping["id"], source_table)
    base_bytes = canonical(base).encode("utf-8")
    input_name = "source_export." + input_format
    metadata = {
        "original_table": source_table, "observed_delta_version": None,
        "inspected_at": None, "prepared_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshot_mode": "operator_supplied_export", "schema": None,
        "observed_json_types": observed_types(rows), "row_count": len(rows),
        "source_rows_sha256": digest(sorted(rows, key=canonical)),
        "mapping": mapping, "source_profile": profile, "base_artifact": "base.json",
        "base_file_sha256": hashlib.sha256(base_bytes).hexdigest(),
        "operator_export": {"operator": operator, "exported_at": exported_at, "format": input_format,
            "artifact": input_name, "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
            "ordered_rows_sha256": digest(rows), "reported_delta_version": reported_delta_version,
            "scope": scope, "completeness": completeness, "expected_row_count": expected_row_count,
            "missing_row_count": expected_row_count - len(rows) if expected_row_count is not None else None,
            "provenance_status": "operator_reported; not independently queried in Databricks"},
        "warning": "Counts cover this supplied export only. Completeness/source/version are operator assertions; live Databricks access is unverified.",
    }
    verify_base_export(base, metadata)
    _publish_directory(output_dir, {input_name: raw, "base.json": base_bytes}, metadata)
    return metadata


def local_output(path):
    """CLI artifacts stay in this checkout's ignored data/local subtree."""
    output = Path(path).absolute()
    allowed = (ROOT / "data/local").resolve()
    require(output.resolve() != allowed and output.resolve().is_relative_to(allowed), "output_dir",
            "choose a new subdirectory of this checkout's ignored data/local/")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--format", required=True, choices=("json", "jsonl"))
    parser.add_argument("--source-table", required=True, help="Observed catalog.schema.table; never inferred")
    parser.add_argument("--mapping", required=True, help="JSON mapping using observed column names, including id")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--exported-at", required=True, help="Actual operator export time, UTC ...Z")
    parser.add_argument("--completeness", required=True, choices=("complete", "partial", "unknown"))
    parser.add_argument("--scope", required=True, help="Actual full-table or filtered selection; descriptive text only")
    parser.add_argument("--expected-row-count", type=int)
    parser.add_argument("--reported-delta-version", type=int)
    parser.add_argument("--max-rows", type=int, default=MAX_ROWS)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = parser.parse_args(argv)
    try:
        metadata = prepare_export(args.input, args.format, args.source_table, load(args.mapping),
            local_output(args.output_dir), operator=args.operator, exported_at=args.exported_at,
            completeness=args.completeness, scope=args.scope, expected_row_count=args.expected_row_count,
            reported_delta_version=args.reported_delta_version, max_rows=args.max_rows, max_bytes=args.max_bytes)
        # Aggregate operational output only; source text and mapping values stay in artifacts.
        print(json.dumps({"status": "prepared", "snapshot_mode": metadata["snapshot_mode"],
            "base_rows": metadata["row_count"], "input_sha256": metadata["operator_export"]["sha256"],
            "base_file_sha256": metadata["base_file_sha256"], "completeness": args.completeness,
            "expected_row_count": args.expected_row_count, "live_databricks_verified": False}, indent=2))
        return 0
    except (Invalid, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
