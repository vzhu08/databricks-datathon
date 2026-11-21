"""Deterministic JSON, stable IDs, safe writes and contract checks for ACQ-C01.

Nothing here reads a network, a clock or a workspace. Error messages name a
path and a rule; they never echo source text.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.0.0"
IDS = {
    "source_snapshots": "snapshot_id",
    "external_facilities": "external_facility_id",
    "facility_matches": "match_id",
    "facility_evidence": "evidence_id",
    "review_queue": "review_id",
}
TABLES = tuple(IDS)


class MatchingError(ValueError):
    """Actionable failure that deliberately excludes source text."""


def require(condition, path, message):
    if not condition:
        raise MatchingError(f"{path}: {message}")


def finite(value, path="$"):
    if isinstance(value, float):
        require(math.isfinite(value), path, "non-finite number is forbidden")
    elif isinstance(value, dict):
        for key, item in value.items():
            finite(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            finite(item, f"{path}[{index}]")


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON", "duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise MatchingError("JSON: non-standard numeric constant")


def load(path):
    """Strict JSON: no duplicate keys, no NaN/Infinity."""
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream, object_pairs_hook=_object, parse_constant=_reject_constant)
    finite(value)
    return value


def canonical(value):
    """The same canonical encoding as D's validator (sorted keys, compact, UTF-8)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_id(namespace, *parts):
    """namespace + ':' + SHA-256(canonical JSON array of stable parts). No clock."""
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", namespace) is not None, "namespace", "invalid namespace")
    return f"{namespace}:{digest(list(parts))}"


def empty():
    return {"contract_version": VERSION, **{table: [] for table in TABLES}}


def counts(batch):
    return {table: len(batch[table]) for table in TABLES}


def write_json(path, value, exclusive=False):
    """Atomic canonical write. exclusive=True refuses to replace an existing file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not (exclusive and path.exists()), str(path.name), "refusing to overwrite an existing artifact")
    data = (canonical(value) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return hashlib.sha256(data).hexdigest()


def field_value(row, selector):
    """Dot selector over a preserved row, identical to D's policy selector."""
    if selector in row:
        return row[selector]
    value = row
    for part in selector.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


@lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator, FormatChecker
    schema = load(ROOT / "contracts/enrichment/schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_check(batch, label="batch"):
    """Normative shared schema plus the blank-string rule D enforces."""
    finite(batch, label)
    require(isinstance(batch, dict), label, "expected a contract envelope object")
    require(batch.get("contract_version") == VERSION, f"{label}.contract_version",
            f"supported version is {VERSION}")
    errors = sorted(_validator().iter_errors(batch), key=lambda e: str(list(e.absolute_path)))
    if errors:
        messages = []
        for error in errors[:20]:
            where = ".".join(str(p) for p in error.absolute_path) or "$"
            messages.append(f"{label}.{where}: violates schema {error.validator}")
        raise MatchingError("\n".join(messages))
    for table in TABLES:
        for index, row in enumerate(batch[table]):
            for key, value in row.items():
                if isinstance(value, str):
                    require(bool(value.strip()), f"{label}.{table}[{index}].{key}",
                            "blank strings are not usable values; use null where allowed")
    return batch


def base_check(base):
    """Base input is a JSON array of objects with unique nonempty facility_id."""
    finite(base, "base")
    require(isinstance(base, list), "base", "expected an array of original rows")
    index = {}
    for position, row in enumerate(base):
        path = f"base[{position}].facility_id"
        require(isinstance(row, dict), path, "expected an object")
        fid = row.get("facility_id")
        require(isinstance(fid, str) and bool(fid.strip()), path, "nonempty text ID required")
        require(fid not in index, path, "duplicate base ID; do not collapse original rows")
        index[fid] = row
    return index


def _instant(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def combine_external(batches):
    """Union producer envelopes without overwriting: identical rows deduplicate,
    a different payload under the same ID fails (the contract's replay rule)."""
    tables = {table: {} for table in TABLES}
    for number, batch in enumerate(batches):
        schema_check(batch, f"external[{number}]")
        for table, key in IDS.items():
            for index, row in enumerate(batch[table]):
                old = tables[table].get(row[key])
                if old is not None and canonical(old) != canonical(row):
                    content = lambda r: {k: v for k, v in r.items() if k != "retrieved_at"}
                    same_snapshot = table == "source_snapshots" and canonical(content(old)) == canonical(content(row))
                    require(same_snapshot, f"external[{number}].{table}[{index}].{key}",
                            "conflicting payload under an existing ID")
                    # Keep the earliest retrieval instant, independent of input order.
                    if _instant(row["retrieved_at"]) < _instant(old["retrieved_at"]):
                        tables[table][row[key]] = row
                    continue
                tables[table][row[key]] = row
    return {"contract_version": VERSION,
            **{table: [rows[key] for key in sorted(rows)] for table, rows in tables.items()}}
