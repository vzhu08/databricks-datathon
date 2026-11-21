"""Bind an accepted, separate service-status artifact to a completed v1 run.

These checks establish input lineage and complete coverage, not clinical accuracy
or release approval. The caller supplies independently accepted file hashes.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from common import _object, canonical, digest, finite, require
from delta_store import volume_path
from source_inspection import verify_base_export

SERVICES = ("dialysis", "mri", "trauma_care")
STATUSES = ("yes", "no", "unconfirmed")


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def bind_status_artifact(spec, base, as_of):
    """Read once, verify pins and every occurrence/service, return reference/data."""
    path = volume_path(spec["path"])
    require(_hash(spec["sha256"]), "service_status.sha256", "independently accepted hash required")
    identity_hash = spec.get("identity_rows_sha256")
    require(identity_hash is None or _hash(identity_hash), "service_status.identity", "invalid identity hash")
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == spec["sha256"], "service_status", "artifact file hash mismatch")
    artifact = json.loads(raw, object_pairs_hook=_object)
    finite(artifact)
    metadata = spec["input_metadata"]
    verify_base_export(base, metadata)
    require(artifact.get("policy") == "onsite-service-review-v1", "service_status", "unsupported policy")
    for field, expected in {
        "base_file_sha256": metadata["base_file_sha256"], "metadata_sha256": digest(metadata),
        "original_table": metadata["original_table"], "delta_version": metadata["observed_delta_version"],
        "as_of": as_of, "identity_rows_file_sha256": identity_hash,
        "occurrences": len(base), "decision_count": len(base) * len(SERVICES),
    }.items():
        require(canonical(artifact.get(field)) == canonical(expected),
                "service_status." + field, "artifact does not match accepted inputs")
    require(_hash(artifact.get("batch_sha256")), "service_status.batch", "missing batch hash")
    facilities = artifact.get("facilities")
    require(isinstance(facilities, dict) and set(facilities) == {r["facility_id"] for r in base},
            "service_status.facilities", "must cover exactly the original occurrence keys")
    coverage = {s: Counter() for s in SERVICES}
    states = {}
    for row in base:
        entry = facilities[row["facility_id"]]
        require(canonical(entry.get("source_id")) == canonical(row["source_row"][metadata["mapping"]["id"]]),
                "service_status.source_id", "original source ID changed")
        services = entry.get("services")
        require(isinstance(services, dict) and set(services) == set(SERVICES),
                "service_status.services", "exactly three services required per occurrence")
        state = entry.get("state")
        require(isinstance(state, str) and bool(state.strip()), "service_status.state", "missing state bucket")
        counts = states.setdefault(state, {s: Counter() for s in SERVICES})
        for service, decision in services.items():
            status = decision.get("status")
            require(status in STATUSES, "service_status.status", "unknown status")
            coverage[service][status] += 1
            counts[service][status] += 1
    expected_coverage = {s: {v: coverage[s][v] for v in STATUSES} for s in SERVICES}
    require(artifact.get("coverage") == expected_coverage, "service_status.coverage", "totals do not reconcile")
    require(artifact.get("coverage_by_state") == states, "service_status.coverage_by_state", "state totals do not reconcile")
    reference = {"artifact": path, "sha256": spec["sha256"], "policy": artifact["policy"],
                 "base_file_sha256": artifact["base_file_sha256"],
                 "input_metadata_sha256": artifact["metadata_sha256"],
                 "identity_rows_file_sha256": identity_hash, "batch_sha256": artifact["batch_sha256"],
                 "as_of": as_of, "decision_count": artifact["decision_count"]}
    return reference, artifact


def read_status_artifact(manifest, base, input_metadata):
    """Read the artifact named by one captured completed manifest, never latest."""
    reference = manifest["source_metadata"]["service_status_artifact"]
    require(manifest["base_sha256"] == digest(base) and manifest["base_rows"] == len(base),
            "service_status.base", "consumer base differs from completed run")
    checked, artifact = bind_status_artifact({"path": reference["artifact"], "sha256": reference["sha256"],
        "identity_rows_sha256": reference["identity_rows_file_sha256"], "input_metadata": input_metadata},
        base, reference["as_of"])
    require(checked == reference and reference["batch_sha256"] == manifest["batch_sha256"]
            and reference["as_of"] == manifest["coverage"]["as_of"],
            "service_status", "artifact reference differs from completed run")
    return artifact
