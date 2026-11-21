"""Append isolated attempts; publish one completed manifest only after readback.

The store provides atomic compare-and-swap of ONE operational state row. The
five data writes are sequential and are not a multi-table transaction.
"""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from common import IDS, VERSION, counts, digest, require
from coverage import coverage
from merge import plan_merge, transition_check


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def publish(store, batches, base, run_id, as_of, transitions=None, identity_policy=None,
            source_metadata=None, expected_revision=None, after_write=None, status_artifact=None):
    require(isinstance(run_id, str) and bool(run_id.strip()) and len(run_id) <= 200,
            "run_id", "nonempty run ID up to 200 characters required")
    revision, state = store.read_state()
    status_reference = None
    if status_artifact is not None:
        from status_artifact import bind_status_artifact
        status_reference, _ = bind_status_artifact(status_artifact, base, as_of)
        source_metadata = deepcopy(source_metadata or {})
        require(all(k in source_metadata and source_metadata[k] == v
                    for k, v in status_artifact["input_metadata"].items()),
                "service_status.metadata", "operational metadata changed the original input metadata")
        source_metadata["service_status_artifact"] = status_reference
    for t in transitions or []:
        transition_check(t)
    request_sha = digest({"batches": sorted((digest(b) for b in batches)),
                          "base": base, "transitions": sorted((transitions or []), key=lambda t: t["transition_id"]),
                          "identity_policy": identity_policy or {}, "as_of": as_of,
                          "source_metadata": source_metadata or {}})
    if run_id in state["runs"]:
        existing = state["runs"][run_id]
        require(status_reference is None or status_reference["batch_sha256"] == existing["batch_sha256"],
                "service_status.batch", "artifact differs from completed batch")
        require(existing["request_sha256"] == request_sha, "run_id", "completed run ID cannot be reused for different inputs")
        # Verify the retained version can still be read; never silently republish an old run.
        store.read_completed(existing)
        return existing
    if expected_revision is not None:
        require(revision == expected_revision, "publication", "state changed since input preparation; reload and revalidate")
    previous = state["runs"].get(state["current_run"])
    accepted = store.read_completed(previous) if previous else None
    if previous:
        require(previous["base_sha256"] == digest(base), "base", "original base rows/text/order changed; use a separately reviewed source revision/output schema")
    plan = plan_merge(batches, base, accepted, transitions,
                      previous["ledger"] if previous else None, identity_policy)
    require(status_reference is None or status_reference["batch_sha256"] == digest(plan["batch"]),
            "service_status.batch", "artifact must bind the entire merged batch before staging")
    report = coverage(plan["batch"], base, as_of)
    attempt = uuid.uuid4().hex
    versions = {}
    for index, table in enumerate(IDS, 1):
        versions[table] = store.write_stage(table, attempt, plan["batch"][table])
        if after_write:
            after_write(index)  # test-only failure injection; notebooks never set this
    descriptor = {"attempt_id": attempt, "table_versions": versions}
    readback = store.read_completed(descriptor)
    require(readback == plan["batch"], "staging", "readback differs from validated plan; previous completed run retained")
    manifest = {
        "run_id": run_id, "attempt_id": attempt, "status": "completed",
        "contract_version": VERSION, "completed_at": utc_now(), "parent_run": state["current_run"],
        "revision": revision + 1, "request_sha256": request_sha,
        "batch_sha256": digest(plan["batch"]), "base_sha256": plan["base_sha256"],
        "base_rows": len(base), "counts": counts(readback), "table_versions": versions,
        "ledger": plan["ledger"], "identity_policy": plan["identity_policy"],
        "coverage": report, "source_metadata": deepcopy(source_metadata or {}),
    }
    updated = deepcopy(state)
    updated["runs"][run_id] = manifest
    updated["current_run"] = run_id
    require(store.compare_and_swap(revision, updated), "publication",
            "concurrent publication won; staged attempt remains unpublished, rerun against latest state")
    return manifest


def current(store):
    """Capture pointer ONCE, then read all five pinned table versions for that run."""
    _, state = store.read_state()
    manifest = state["runs"].get(state["current_run"])
    return (manifest, store.read_completed(manifest)) if manifest else (None, None)
