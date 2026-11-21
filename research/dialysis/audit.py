"""Verify the complete independent review against the exact released evidence and sources."""
import argparse
import json
from pathlib import Path

from .release import digest


def verify(batch, decisions):
    evidence = {row["evidence_id"]: row for row in batch["facility_evidence"]}
    snapshots = {row["snapshot_id"]: row["sha256"] for row in batch["source_snapshots"]}
    if len(evidence) != len(batch["facility_evidence"]):
        raise ValueError("Duplicate evidence ID in release")
    checked = set()
    for decision in decisions:
        eid = decision["evidence_id"]
        if eid not in evidence or eid in checked:
            raise ValueError("Unexpected or duplicate audit decision")
        row = evidence[eid]
        encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if digest(encoded) != decision["evidence_sha256"]:
            raise ValueError("Audit decision belongs to an earlier claim payload")
        if snapshots[row["snapshot_id"]] != decision["source_snapshot_sha256"]:
            raise ValueError("Audit source differs from released snapshot")
        if not (decision["outcome"] == "pass" and decision["exact_excerpt_at_locator"] is True
                and decision["reviewer"] and decision["reviewed_at"]):
            raise ValueError("A claim requires correction or withholding before acceptance")
        checked.add(eid)
    if checked != evidence.keys():
        raise ValueError("Audit coverage is incomplete")
    return len(checked)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", required=True, type=Path)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--summary", required=True, type=Path)
    a = p.parse_args()
    raw = a.batch.read_bytes()
    summary = json.loads(a.summary.read_bytes())
    if digest(raw) != summary["final_batch_sha256"]:
        raise ValueError("Summary is bound to a different batch")
    n = verify(json.loads(raw), json.loads(a.decisions.read_bytes()))
    print(json.dumps({"documentary_claims_checked": n, "batch_sha256": digest(raw)}))


if __name__ == "__main__":
    main()
