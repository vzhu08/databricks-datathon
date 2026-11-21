"""Contract utilities. No workspace access or mutations at import time."""
import hashlib
import json
import math
from pathlib import Path

VERSION = "1.0.0"
IDS = {
    "source_snapshots": "snapshot_id",
    "external_facilities": "external_facility_id",
    "facility_matches": "match_id",
    "facility_evidence": "evidence_id",
    "review_queue": "review_id",
}
ROOT = Path(__file__).resolve().parents[2]


class Invalid(ValueError):
    """Actionable validation failure, deliberately excluding source text."""


def require(condition, path, message):
    if not condition:
        raise Invalid(f"{path}: {message}")


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


def load(path):
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream, object_pairs_hook=_object)
    finite(value)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def stable_id(namespace, *parts):
    """New IDs: namespace + SHA256(canonical JSON array of stable source parts)."""
    import re
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", namespace), "namespace", "invalid namespace")
    return f"{namespace}:{digest(list(parts))}"


def empty():
    return {"contract_version": VERSION, **{table: [] for table in IDS}}


def counts(batch):
    return {table: len(batch[table]) for table in IDS}
