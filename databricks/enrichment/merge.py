"""Deterministic additive merge with separately audited review transitions."""
from copy import deepcopy
from datetime import datetime
import re

from jsonschema import FormatChecker

from common import IDS, VERSION, canonical, digest, empty, finite, require
from validation import base_check, schema_check, semantic_check

MUTABLE = {
    "facility_matches": {"status", "method", "rationale", "shared_identifier", "reviewer", "reviewed_at"},
    "facility_evidence": {"facility_id", "match_id", "reviewer", "reviewed_at"},
    "review_queue": {"status", "next_action", "resolution"},
}
TRANSITION_KEYS = {"transition_id", "table", "row_id", "prior_payload_sha256",
                   "new_payload_sha256", "actor", "at", "reason", "replacement"}


def transition_check(t):
    require(isinstance(t, dict) and set(t) == TRANSITION_KEYS, "transition", "invalid transition fields")
    finite(t, "transition")
    for key in TRANSITION_KEYS - {"replacement"}:
        require(isinstance(t[key], str) and bool(t[key].strip()), f"transition.{key}", "nonempty string required")
    require(re.fullmatch(r"[A-Za-z0-9_.-]+:.+", t["transition_id"]), "transition.transition_id", "namespaced ID required")
    require(t["table"] in MUTABLE, "transition.table", "immutable source and identity rows cannot transition")
    for key in ("prior_payload_sha256", "new_payload_sha256"):
        require(re.fullmatch(r"[a-f0-9]{64}", t[key]), f"transition.{key}", "SHA-256 required")
    require(FormatChecker().conforms(t["at"], "date-time") and t["at"].endswith("Z"),
            "transition.at", "UTC date-time required")
    require(isinstance(t["replacement"], dict), "transition.replacement", "object required")
    require(digest(t["replacement"]) == t["new_payload_sha256"], "transition.new_payload_sha256", "replacement hash mismatch")
    require(t["replacement"].get(IDS[t["table"]]) == t["row_id"], "transition.row_id", "replacement ID mismatch")
    envelope = empty()
    envelope[t["table"]] = [t["replacement"]]
    schema_check(envelope, "transition.replacement")


def ledger_check(ledger, tables):
    # A supplied historical ledger must terminate at the accepted row, not merely
    # contain a transition ID that lets an unrelated update be skipped as replay.
    groups = {}
    for t in ledger.values():
        groups.setdefault((t["table"], t["row_id"]), []).append(t)
    for (table, row_id), history in groups.items():
        prior_hashes = [t["prior_payload_sha256"] for t in history]
        new_hashes = [t["new_payload_sha256"] for t in history]
        require(len(prior_hashes) == len(set(prior_hashes)) and len(new_hashes) == len(set(new_hashes)),
                "accepted_ledger", "forked or cyclic review history")
        starts = set(prior_hashes) - set(new_hashes)
        ends = set(new_hashes) - set(prior_hashes)
        require(len(starts) == len(ends) == 1, "accepted_ledger", "disconnected or cyclic review history")
        require(row_id in tables[table] and digest(tables[table][row_id]) == next(iter(ends)),
                "accepted_ledger", "ledger tip does not match accepted row")
        edges_by_prior = {t["prior_payload_sha256"]: t["new_payload_sha256"] for t in history}
        cursor, visited = next(iter(starts)), set()
        while cursor in edges_by_prior and cursor not in visited:
            visited.add(cursor)
            cursor = edges_by_prior[cursor]
        require(len(visited) == len(history), "accepted_ledger", "disconnected history")


def plan_merge(batches, base, accepted=None, transitions=None, accepted_ledger=None, identity_policy=None):
    """Ordinary conflicting rows never overwrite, even if a transition is supplied.

    Transitions are applied after combining ordinary rows, ordered by their hash
    dependencies, and retained in a separate ledger. Replays use accepted_ledger.
    """
    base_check(base)
    before_base = digest(base)
    accepted = deepcopy(accepted) if accepted is not None else empty()
    schema_check(accepted, "accepted")
    tables = {table: {} for table in IDS}
    for table, key in IDS.items():
        for row in accepted[table]:
            require(row[key] not in tables[table], f"accepted.{table}", "duplicate accepted ID")
            tables[table][row[key]] = row
    persisted = {table: set(rows) for table, rows in tables.items()}
    for batch_index, batch in enumerate(batches):
        schema_check(batch, f"batch[{batch_index}]")
        for table, key in IDS.items():
            for index, original in enumerate(batch[table]):
                row = deepcopy(original)
                old = tables[table].get(row[key])
                if old is not None and canonical(old) != canonical(row):
                    # Retrieval attempts do not version immutable source content.
                    old_content = {k: v for k, v in old.items() if k != "retrieved_at"}
                    new_content = {k: v for k, v in row.items() if k != "retrieved_at"}
                    if table == "source_snapshots" and canonical(old_content) == canonical(new_content):
                        if row[key] not in persisted[table]:
                            tables[table][row[key]] = min((old, row), key=lambda r: (datetime.fromisoformat(r["retrieved_at"].replace("Z", "+00:00")), canonical(r)))
                        continue
                    require(False, f"batch[{batch_index}].{table}[{index}].{key}",
                            "conflicting payload under existing ID; version content or use a separate audited transition")
                tables[table][row[key]] = row

    ledger = {}
    for t in accepted_ledger or []:
        transition_check(t)
        prior = ledger.get(t["transition_id"])
        require(prior is None or prior == t, "accepted_ledger", "conflicting transition ID")
        ledger[t["transition_id"]] = deepcopy(t)
    ledger_check(ledger, tables)
    pending = {}
    for t in transitions or []:
        transition_check(t)
        tid = t["transition_id"]
        prior = ledger.get(tid, pending.get(tid))
        require(prior is None or prior == t, "transition.transition_id", "conflicting transition replay")
        if tid not in ledger:
            pending[tid] = deepcopy(t)
    # A fork cannot become order-dependent just because one transition sorts first.
    edges = [(t["table"], t["row_id"], t["prior_payload_sha256"]) for t in pending.values()]
    require(len(edges) == len(set(edges)), "transitions", "multiple transitions from the same prior hash")
    while pending:
        ready = []
        for tid, t in sorted(pending.items()):
            row = tables[t["table"]].get(t["row_id"])
            if row is not None and digest(row) == t["prior_payload_sha256"]:
                ready.append(tid)
        require(bool(ready), "transitions", "missing row, stale prior hash, or cyclic transition chain")
        for tid in ready:
            t = pending.pop(tid)
            old = tables[t["table"]][t["row_id"]]
            new = t["replacement"]
            changed = {key for key in old if canonical(old[key]) != canonical(new[key])}
            require(bool(changed) and changed <= MUTABLE[t["table"]], "transition.replacement",
                    "only review/link decisions may change; immutable facts require a new ID")
            if "reviewer" in new:
                require(new["reviewer"] == t["actor"] and new["reviewed_at"] == t["at"], "transition",
                        "replacement reviewer/time must equal ledger actor/time")
                if old["reviewed_at"]:
                    require(datetime.fromisoformat(new["reviewed_at"].replace("Z", "+00:00")) >=
                            datetime.fromisoformat(old["reviewed_at"].replace("Z", "+00:00")),
                            "transition.at", "review time cannot go backwards")
            tables[t["table"]][t["row_id"]] = deepcopy(new)
            ledger[tid] = t

    ledger_check(ledger, tables)
    output = {"contract_version": VERSION, **{
        table: [rows[key] for key in sorted(rows)] for table, rows in tables.items()}}
    semantic_check(output, base, identity_policy)
    require(before_base == digest(base), "base", "base changed during validation")
    return {"batch": output, "base": deepcopy(base), "base_sha256": before_base,
            "ledger": [ledger[key] for key in sorted(ledger)],
            "identity_policy": deepcopy(identity_policy or {}), "contract_version": VERSION}
