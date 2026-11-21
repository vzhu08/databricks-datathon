"""Deterministic serialization, safe writes, and producer contract checks."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("source_snapshots", "external_facilities", "facility_matches", "facility_evidence", "review_queue")


class AcquisitionError(Exception):
    """A safe machine-readable reason (never source response text)."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_json(path, data):
    atomic_bytes(path, canonical(data) + b"\n")


def publish_json_directory(output, payloads, conflict_reason):
    """Publish a complete reference or verify a previous identical release."""
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        with tempfile.TemporaryDirectory(prefix=".reference-", dir=output.parent) as temp:
            stage = Path(temp) / "reference"
            for name, data in payloads.items():
                write_json(stage / name, data)
            try:
                stage.rename(output)
                return
            except OSError:
                if not output.is_dir():
                    raise
    if (not output.is_dir() or set(p.name for p in output.iterdir()) != set(payloads)
            or any((output / name).read_bytes() != canonical(data) + b"\n" for name, data in payloads.items())):
        raise AcquisitionError(conflict_reason)


def safe_url(url):
    """Logs never include userinfo, query strings, or fragments."""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.hostname or "", p.path, "", ""))


def public_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise AcquisitionError("nonpublic_or_credentialed_url")
    return url


def envelope():
    return {"contract_version": "1.0.0", **{table: [] for table in TABLES}}


def review(reason, key, external_id=None, action=None):
    return {
        "review_id": "acq-review:" + digest(canonical([reason, key])),
        "facility_id": None, "external_facility_id": external_id,
        "evidence_id": None, "match_id": None, "reason_code": reason,
        "severity": "medium", "status": "open", "resolution": None,
        "next_action": action or "Inspect the original record at its locator before using it for matching.",
    }


def validate(batch):
    schema = read_json(ROOT / "contracts/enrichment/schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(batch)
    for table in TABLES:
        key = {"source_snapshots": "snapshot_id", "external_facilities": "external_facility_id",
               "facility_matches": "match_id", "facility_evidence": "evidence_id", "review_queue": "review_id"}[table]
        ids = [row[key] for row in batch[table]]
        if len(ids) != len(set(ids)):
            raise AcquisitionError("duplicate_contract_id")
    snapshots = {row["snapshot_id"] for row in batch["source_snapshots"]}
    external = {row["external_facility_id"] for row in batch["external_facilities"]}
    for row in batch["external_facilities"]:
        if row["snapshot_id"] not in snapshots or not row["record_locator"]:
            raise AcquisitionError("unresolved_source_reference")
    for row in batch["review_queue"]:
        if row["external_facility_id"] is not None and row["external_facility_id"] not in external:
            raise AcquisitionError("unresolved_review_reference")
    if batch["facility_matches"] or batch["facility_evidence"]:
        raise AcquisitionError("unowned_table_not_empty")
