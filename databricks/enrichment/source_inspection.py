"""Read-only source inspection/export. All field mappings must be observed inputs."""
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

from common import canonical, digest, require, stable_id
from delta_store import identifier, volume_path
from occurrence_keys import map_occurrences
from validation import base_check


def json_value(value):
    # Spark Date/Timestamp/Decimal are represented without rounding or text repair.
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        import base64
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_source_number": str(value)}
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def map_base(rows, id_column, source_identity, allow_surrogate=False, *, id_policy=None, source_version=None):
    """Lossless original rows are nested under source_row; no row drops or joins."""
    if id_policy is not None:
        require(not allow_surrogate, "id_policy", "occurrence policy cannot be combined with generic surrogates")
        base, _ = map_occurrences([json_value(row) for row in rows], id_column, source_identity, source_version, id_policy)
        base_check(base)
        return base
    if id_column is None:
        require(allow_surrogate, "mapping.id", "no ID selected; explicitly approve a raw-row surrogate")
    base = []
    for row in rows:
        raw = json_value(row)
        if id_column is None:
            fid = stable_id("base", source_identity, raw)
        else:
            require(id_column in row and isinstance(row[id_column], (str, int))
                    and not isinstance(row[id_column], bool) and bool(str(row[id_column]).strip()),
                    "mapping.id", "source ID must be non-null text/integer; inspect duplicates/missingness first")
            fid = str(row[id_column])
        base.append({"facility_id": fid, "source_row": raw})
    # Identical rows without source IDs intentionally fail: row index is not a stable ID.
    base_check(base)
    return sorted(base, key=lambda row: row["facility_id"])


def profile_rows(rows, mapping):
    """Aggregate metadata only. Does not return names, IDs or evidence excerpts."""
    require(isinstance(mapping, dict), "mapping", "expected object mapping roles to column names")
    columns = sorted({key for row in rows for key in row})
    require(set(mapping) <= {"id", "name", "state", "type", "pin", "latitude", "longitude", "evidence"},
            "mapping", "unknown mapping role")
    for role, field in mapping.items():
        fields = field if role == "evidence" else [field]
        require(isinstance(fields, list) and all(isinstance(f, str) and f in columns for f in fields),
                f"mapping.{role}", "mapping must name observed columns")
    missing = {column: sum(row.get(column) is None or row.get(column) == "" for row in rows) for column in columns}
    result = {"row_count": len(rows), "columns": columns, "missing_by_column": missing,
              "mapping": mapping, "duplicate_id_rows": None, "coordinate_counts": None}
    if mapping.get("id"):
        ids = [canonical(json_value(row.get(mapping["id"]))) for row in rows if row.get(mapping["id"]) is not None]
        counts = Counter(ids)
        result["duplicate_id_rows"] = sum(n - 1 for n in counts.values() if n > 1)
        result["distinct_nonnull_ids"] = len(counts)
    if mapping.get("pin"):
        pins = Counter(canonical(json_value(row.get(mapping["pin"]))) for row in rows
                       if row.get(mapping["pin"]) is not None)
        result["postal_context"] = {"distinct_nonnull_pins": len(pins),
            "rows_beyond_first_per_pin": sum(n - 1 for n in pins.values()),
            "max_rows_per_pin": max(pins.values(), default=0),
            "join_rule": "Aggregate postal rows to unique PIN before any base join; preserve base cardinality."}
    if mapping.get("latitude") and mapping.get("longitude"):
        coordinates = Counter()
        for row in rows:
            lat, lon = row.get(mapping["latitude"]), row.get(mapping["longitude"])
            if lat is None or lon is None:
                coordinates["missing_or_incomplete"] += 1
            elif not all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)):
                coordinates["invalid_or_nonfinite"] += 1
            elif not (-90 <= lat <= 90 and -180 <= lon <= 180):
                coordinates["outside_wgs84"] += 1
            else:
                coordinates["valid_wgs84"] += 1
                # Bounding box is an anomaly cue, not a political boundary test.
                if not (6 <= lat <= 38 and 68 <= lon <= 98):
                    coordinates["outside_india_bbox_review"] += 1
        result["coordinate_counts"] = dict(coordinates)
    result["evidence_nonempty"] = {field: len(rows) - missing[field] for field in mapping.get("evidence", [])}
    return result


def inspect_table(spark, table, version=None, max_rows=500000):
    quoted = identifier(table, 3)
    require(isinstance(max_rows, int) and 0 < max_rows <= 1000000, "max_rows", "explicit bounded driver export required")
    # History may be unavailable on shared/non-Delta tables. Do not invent a version.
    observed_version = None
    if version is not None:
        require(isinstance(version, int) and version >= 0, "version", "nonnegative Delta version required")
        observed_version = version
    else:
        try:
            observed_version = int(spark.sql(f"DESCRIBE HISTORY {quoted} LIMIT 1").first()["version"])
        except Exception:
            pass
    reader = spark.read
    if observed_version is not None:
        reader = reader.option("versionAsOf", observed_version)
    frame = reader.table(quoted)
    # One action captures a bounded snapshot; do not count and then collect a moving table.
    collected = frame.limit(max_rows + 1).collect()
    require(len(collected) <= max_rows, "source", "export exceeds max_rows; review capacity before raising the bound")
    rows = [r.asDict(recursive=True) for r in collected]
    serial = [json_value(r) for r in rows]
    artifact_hash = digest(sorted(serial, key=canonical))
    return rows, {"original_table": table, "observed_delta_version": observed_version,
                  "inspected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                  "snapshot_mode": "pinned_delta_version" if observed_version is not None else "single_read_export",
                  "schema": frame.schema.jsonValue(), "row_count": len(rows),
                  "source_rows_sha256": artifact_hash,
                  "warning": None if observed_version is not None else "No readable Delta history; downstream runs must use this exact export, not reread a moving source."}


def write_new_json(path, value):
    destination = Path(volume_path(path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value))
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def verify_base_export(base, metadata):
    base_check(base)
    require(len(base) == metadata["row_count"], "base", "export row count differs from inspected source")
    require(all(isinstance(row.get("source_row"), dict) for row in base), "base", "missing preserved source_row")
    raw = sorted((row["source_row"] for row in base), key=canonical)
    require(digest(raw) == metadata["source_rows_sha256"], "base", "original fields/text changed since source inspection")
    if metadata.get("id_policy") is not None:
        require("mapping" in metadata, "id_policy", "reviewed occurrence metadata requires the original mapping")
    if "mapping" in metadata:
        expected = map_base(raw, metadata["mapping"].get("id"), metadata["original_table"],
                            allow_surrogate=metadata["mapping"].get("id") is None,
                            id_policy=metadata.get("id_policy"), source_version=metadata.get("observed_delta_version"))
        require(base == expected, "base", "mapped IDs/order differ from source mapping")
