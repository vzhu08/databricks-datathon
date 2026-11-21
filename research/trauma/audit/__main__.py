"""Select B5 claims and write the decision, history, and review queue artifacts."""

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .rubric import LIMIT, assess, digest, index_batches, outcome_counts, queue_batch, review_context
from .rubric import select_claims, source_dependence


AUDIT_FIELDS = ("evidence_id", "evidence_sha256", "outcome", "reviewer", "reviewed_at", "reason")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, payload):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_inventory(paths):
    entries = []
    for path in sorted({path.resolve(strict=True) for path in paths}):
        checksum = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
        entries.append({"path": str(path), "sha256": checksum.hexdigest(), "bytes": path.stat().st_size})
    return entries


def adjudicate(selected, tables, observations, prior_history):
    by_claim = defaultdict(list)
    for prior in prior_history:
        by_claim[prior["evidence_id"]].append(prior)

    expected = set(selected)
    extra = set(observations) - expected
    if extra:
        raise ValueError(f"Observations outside the frozen sample: {sorted(extra)}")
    current = []
    for evidence_id in selected:
        history = by_claim[evidence_id]
        if evidence_id in observations:
            context = review_context(tables["facility_evidence"][evidence_id], tables)
            review = assess(context, observations[evidence_id])
            if review not in history:
                timestamp = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
                if history and timestamp <= datetime.fromisoformat(
                    history[-1]["reviewed_at"].replace("Z", "+00:00")
                ):
                    raise ValueError(f"Re-review timestamp must increase for {evidence_id}")
                history.append(review)
        context_hash = digest(review_context(tables["facility_evidence"][evidence_id], tables))
        if history and history[-1]["reviewed_payload_sha256"] == context_hash:
            current.append(history[-1])
    return current, [review for history in by_claim.values() for review in history]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--strata", type=Path)
    parser.add_argument("--freeze-selection", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--prior-history", type=Path)
    parser.add_argument("--lineage", type=Path)
    parser.add_argument("--supporting-input", type=Path, action="append", default=[])
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    args = parser.parse_args()

    tables = index_batches([read_json(path) for path in args.batch])
    labels = read_json(args.strata) if args.strata else {}
    selected, population, lanes = select_claims(tables, labels)
    if args.freeze_selection:
        selected = read_json(args.freeze_selection)["selected"]
        if len(selected) > LIMIT or len(set(selected)) != len(selected):
            parser.error("The frozen sample must contain up to 30 unique IDs.")
    args.out.mkdir(parents=True, exist_ok=True)

    summary = {
        "eligible_population": population,
        "eligible_by_lane": lanes,
        "selected_count": len(selected),
        "selected": selected,
        "context_sha256": {
            eid: digest(review_context(tables["facility_evidence"][eid], tables)) for eid in selected
        },
    }
    if not args.observations:
        write_json(args.out / "selection.json", summary)
        print(f"Selected {len(selected)} of {population} eligible claims.")
        return

    reviews, history = adjudicate(
        selected,
        tables,
        read_json(args.observations),
        read_json(args.prior_history) if args.prior_history else [],
    )
    if len(reviews) != len(selected):
        reviewed = {review["evidence_id"] for review in reviews}
        parser.error(f"Missing current adjudication for: {sorted(set(selected) - reviewed)}")

    lineage = read_json(args.lineage) if args.lineage else {}
    outputs = {
        "selection.json": summary,
        "audit.json": [{field: review[field] for field in AUDIT_FIELDS} for review in reviews],
        "audit-history.json": history,
        "batch.json": queue_batch(tables, reviews),
        "source-dependence.json": {
            "groups": source_dependence(tables["source_snapshots"], lineage.get("snapshots")),
            "comparisons": lineage.get("comparisons", []),
        },
        "review-summary.json": {
            "eligible_population": population,
            "eligible_by_lane": lanes,
            "decision_counts": outcome_counts(reviews),
            "history_rows": len(history),
        },
    }
    for name, payload in outputs.items():
        write_json(args.out / name, payload)
    inputs = [
        path for path in (args.strata, args.freeze_selection, args.observations, args.prior_history, args.lineage)
        if path is not None
    ]
    write_json(args.out / "artifact_inventory.json", {
        "inputs": file_inventory([*args.batch, *inputs, *args.supporting_input]),
        "raw_artifacts": file_inventory(args.artifact),
        "outputs": file_inventory([args.out / name for name in outputs]),
    })
    print(f"Reviewed {len(reviews)} of {population} eligible claims: {outcome_counts(reviews)}")


if __name__ == "__main__":
    main()
