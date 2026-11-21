"""Reconcile printed national programme rows with the frozen Rajasthan release."""

from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory


KNOWN_SHA256 = "fb0deb83f24ee85612a10cdcb491a14b6d667e02874e8800f341d3ba33236586"
KNOWN_COUNTS = {"completed": 105, "under_construction": 7, "construction_not_started": 4, "supported": 80}


def publish_national(output_dir, outputs):
    """Expose the complete directory only after every frozen file has been written."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir.parent) as temporary:
        stage = Path(temporary) / "release"
        stage.mkdir()
        for name, data in outputs.items():
            (stage / name).write_bytes(data)
        # Windows cannot rename onto an empty existing directory. A concurrently
        # published non-empty directory is never removed and is checked below.
        try:
            output_dir.rmdir()
        except OSError:
            pass
        try:
            stage.rename(output_dir)
        except OSError:
            if not output_dir.is_dir():
                raise
            for name, data in outputs.items():
                path = output_dir / name
                if not path.is_file() or path.read_bytes() != data:
                    raise ValueError(f"National output {name} differs; choose a new output directory")


def _index(rows, field):
    index = {row[field]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"Duplicate {field} in national release inputs")
    return index


def preserve_rajasthan(batch, ledger, prior_batch, prior_ledger):
    """Retain original row payloads and audit holds when the national batch is imported alone."""
    previous = _index([s for s in prior_batch["source_snapshots"] if s["source_key"] == "mohfw_trauma_program"],
                      "snapshot_id")
    snapshots = _index(batch["source_snapshots"], "snapshot_id")
    if not previous or previous.keys() - snapshots.keys():
        raise ValueError("Prior MoHFW snapshot is missing from one of the releases")
    for key, saved in previous.items():
        current = snapshots[key]
        # A verified local copy can reside at a different path. The contract snapshot
        # retains the first accepted artifact URI; the new inventory lists the actual copy.
        if {**current, "artifact_uri": saved["artifact_uri"]} != saved:
            raise ValueError("Existing MoHFW snapshot metadata changed")
        current["artifact_uri"] = saved["artifact_uri"]

    old_facilities = {r["external_facility_id"]: r for r in prior_batch["external_facilities"]
                      if r["snapshot_id"] in previous and r["state"].casefold() == "rajasthan"}
    current_facilities = {r["external_facility_id"]: r for r in batch["external_facilities"]
                          if r["snapshot_id"] in previous and r["state"].casefold() == "rajasthan"}
    if not old_facilities or old_facilities != current_facilities:
        raise ValueError("Rajasthan facility IDs or payloads changed")
    old_claims = _index([item["claim"] for item in prior_ledger
                         if item["claim"]["external_facility_id"] in old_facilities], "evidence_id")
    current_claims = {r["evidence_id"]: r for r in batch["facility_evidence"]
                      if r["external_facility_id"] in old_facilities}
    if not old_claims or current_claims != old_claims:
        raise ValueError("Rajasthan evidence differs from the frozen producer claim ledger")
    decisions = {item["claim"]["evidence_id"]: item["outcome"] for item in prior_ledger
                 if item["claim"]["evidence_id"] in old_claims}
    held = {key for key, outcome in decisions.items() if outcome in {"fail", "uncertain"}}
    accepted = {r["evidence_id"]: r for r in prior_batch["facility_evidence"]
                if r["external_facility_id"] in old_facilities}
    if (set(decisions.values()) - {"pass", "unsampled", "fail", "uncertain"}
            or accepted != {key: row for key, row in old_claims.items() if key not in held}):
        raise ValueError("Rajasthan audit outcomes disagree with prior released evidence")
    batch["facility_evidence"] = [r for r in batch["facility_evidence"] if r["evidence_id"] not in held]
    for row in ledger:
        if row["external_facility_id"] in old_facilities:
            row["prior_audit_outcomes"] = {kind: decisions[eid] for kind, eid in row["evidence_ids"].items()}
    queues = _index(batch["review_queue"], "review_id")
    for row in prior_batch["review_queue"]:
        if row["external_facility_id"] in old_facilities:
            key = row["review_id"]
            if key in queues and queues[key] != row:
                raise ValueError("Rajasthan review item changed")
            queues[key] = row
    batch["review_queue"] = list(queues.values())
    return {"identical_facility_payloads": len(old_facilities), "identical_producer_claim_payloads": len(old_claims),
            "identical_released_claim_payloads": len(accepted), "retained_holds": len(held),
            "prior_outcomes": dict(sorted(Counter(decisions.values()).items()))}


def national_receipt(batch, ledger, acquired, prior_release):
    primary = acquired["primary"]
    printed = Counter(row.section.key for row in primary["document"].rows)
    if primary["sha256"] == KNOWN_SHA256 and (len(primary["document"].pages) != 14 or printed != KNOWN_COUNTS):
        raise ValueError("Known Ministry PDF must reconcile 105 + 7 + 4 + 80 printed rows")
    prior_batch, prior_ledger = (json.loads((prior_release / name).read_text(encoding="utf-8"))
                                 for name in ("batch.json", "claim_ledger.json"))
    compatibility = preserve_rajasthan(batch, ledger, prior_batch, prior_ledger)
    unique_sources = {entry["sha256"]: entry for entry in acquired.values()}
    expected_rows = sum(len(unique_sources[s["sha256"]]["document"].rows) for s in batch["source_snapshots"])
    if len(batch["external_facilities"]) != expected_rows or len(ledger) != expected_rows:
        raise ValueError("National ledger must contain one row per emitted programme listing")
    evidence = {row["evidence_id"] for row in batch["facility_evidence"]}
    return {
        "primary_printed_rows_before_deduplication": sum(printed.values()),
        "primary_section_counts": dict(sorted(printed.items())),
        "raw_files": len(acquired), "distinct_raw_hashes": len(unique_sources),
        "emitted_programme_rows": len(ledger), "campus_deduplication": "none",
        "emitted_claims_by_kind": dict(sorted(Counter(kind for row in ledger
                                                      for kind, eid in row["evidence_ids"].items()
                                                      if eid in evidence).items())),
        "rejected_printed_rows": 0, "reject_policy": "Abort on unrecognized grid structure or section count disagreement.",
        "emitted_rows_by_normalized_source_label": dict(sorted(Counter(
            " ".join(row["state_as_printed"].split()).casefold() for row in ledger).items())),
        "prior_rajasthan": compatibility,
    }
