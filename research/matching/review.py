"""Review sampling, the review ledger, and audited application of decisions.

A decision is a named reviewer's judgement about one candidate pair. Applying
decisions never edits an input file: it writes a reviewed batch for a first
submission, and D-compatible transitions for rows D has already accepted.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime

from .candidates import LEVEL
from .common import IDS, canonical, digest, empty, require, schema_check, stable_id

TRANSITION_NS = "acq-c-transition"
STRATA = ("easy", "alias", "ambiguous_name", "conflicting_geography", "missing_geography",
          "non_hospital_type", "shared_identifier", "proximity_only", "other")
DECISIONS = ("confirmed", "rejected", "conflict")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def stratum(candidate):
    flags = set(candidate["flags"])
    if candidate.get("auto_confirmed"):
        return "shared_identifier"
    if flags & {"state_conflict", "place_conflict", "pin_conflict", "coordinates_far_apart", "identifier_disagrees"}:
        return "conflicting_geography"
    if "ambiguous_campus" in flags:
        return "ambiguous_name"
    if flags & {"matched_via_alias", "acronym_only"}:
        return "alias"
    if "non_hospital_type" in flags:
        return "non_hospital_type"
    if "proximity_only" in flags:
        return "proximity_only"
    if flags & {"geography_unknown", "name_only", "distance_unavailable"}:
        return "missing_geography"
    if LEVEL[candidate["signals"]["name_level"]] == 3 and candidate["rank"] == 1:
        return "easy"
    return "other"


def sample(candidates, limit=50):
    """Up to `limit` candidates, round-robin across strata. Order inside a stratum
    is the SHA-256 of the match ID: arbitrary, repeatable, and not ranked by score."""
    require(isinstance(limit, int) and limit >= 0, "sample_size", "non-negative integer required")
    groups = defaultdict(list)
    for c in candidates:
        groups[stratum(c)].append(c)
    for members in groups.values():
        members.sort(key=lambda c: digest(c["match_id"]))
    chosen, depth = [], 0
    while len(chosen) < limit and any(depth < len(groups[s]) for s in STRATA):
        for s in STRATA:
            if depth < len(groups[s]) and len(chosen) < limit:
                chosen.append(groups[s][depth])
        depth += 1
    sizes = {s: len(groups[s]) for s in STRATA}
    taken = Counter(stratum(c) for c in chosen)
    return chosen, {"population": len(candidates), "sample_size": len(chosen), "limit": limit,
                    "rule": "Round-robin across strata; within a stratum ordered by SHA-256 of match_id. "
                            "All candidates are sampled when there are no more than the limit.",
                    "strata": {s: {"population": sizes[s], "sampled": taken.get(s, 0)} for s in STRATA}}


def worksheet(chosen, bases, externals):
    """Rows a reviewer fills in. Contains source text, so it stays outside Git."""
    base_rows = {b["id"]: b["row"] for b in bases}
    external_rows = {e["id"]: e["row"] for e in externals}
    rows = []
    for c in chosen:
        rows.append({
            "match_id": c["match_id"], "stratum": stratum(c), "rank": c["rank"],
            "facility_id": c["facility_id"], "external_facility_id": c["external_facility_id"],
            "base_row": base_rows[c["facility_id"]],
            "external_row": external_rows[c["external_facility_id"]],
            "signals": c["signals"], "flags": sorted(c["flags"]),
            "auto_confirmed": c["auto_confirmed"], "review_reason": c["review_reason"],
            "decision": None, "reviewer": None, "reviewed_at": None, "rationale": None,
        })
    return rows


def check_decisions(decisions, matches):
    require(isinstance(decisions, list), "decisions", "expected an array")
    seen = {}
    for index, d in enumerate(decisions):
        path = f"decisions[{index}]"
        require(isinstance(d, dict), path, "expected an object")
        require({"match_id", "decision", "reviewer", "reviewed_at", "rationale"} <= set(d), path,
                "needs match_id, decision, reviewer, reviewed_at, rationale")
        require(d["match_id"] in matches, path + ".match_id", "unknown match")
        require(d["match_id"] not in seen, path + ".match_id", "more than one decision for a match")
        require(d["decision"] in DECISIONS, path + ".decision", "must be confirmed, rejected or conflict")
        for key in ("reviewer", "rationale"):
            require(isinstance(d[key], str) and bool(d[key].strip()), f"{path}.{key}", "nonempty text required")
        require(isinstance(d["reviewed_at"], str) and UTC.match(d["reviewed_at"]) is not None,
                path + ".reviewed_at", "UTC timestamp ending in Z required")
        _instant(d["reviewed_at"])
        seen[d["match_id"]] = d
    return seen


def _instant(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _transition(table, old, new, actor, at, reason):
    key = IDS[table]
    return {"transition_id": stable_id(TRANSITION_NS, table, old[key], digest(old), digest(new)),
            "table": table, "row_id": old[key], "prior_payload_sha256": digest(old),
            "new_payload_sha256": digest(new), "actor": actor, "at": at, "reason": reason,
            "replacement": new}


def apply(matches_batch, decisions, external_batch=None):
    """Apply reviewer decisions.

    Returns a dict with:
      reviewed_batch  C's envelope with final match rows and resolved queue items
      transitions     D-format transitions: match and queue changes, plus evidence
                      links/unlinks for evidence rows in `external_batch`. Use
                      with the ORIGINAL candidate batch when D already holds it.
      evidence_transitions  the evidence links/unlinks alone. Use with
                      reviewed_batch on a first submission. Never send both sets.
      ledger          one line per decision, including whether it was a false match
      summary         counts with denominators
    Evidence is linked only to a match a reviewer confirmed. A rejected or
    conflicting match unlinks any evidence that pointed at it.
    """
    schema_check(matches_batch, "matches")
    external_batch = external_batch or empty()
    schema_check(external_batch, "external")
    matches = {m["match_id"]: m for m in matches_batch["facility_matches"]}
    decided = check_decisions(decisions, matches)
    reviewed, transitions, ledger = deepcopy(matches_batch), [], []

    final = {}
    for row in reviewed["facility_matches"]:
        d = decided.get(row["match_id"])
        if d is None:
            final[row["match_id"]] = row
            continue
        old = deepcopy(row)
        endorsement = d["decision"] == "confirmed" and old["status"] == "confirmed"
        if not endorsement:
            if old["reviewed_at"] is not None:
                require(_instant(d["reviewed_at"]) >= _instant(old["reviewed_at"]),
                        "decisions.reviewed_at", "review time cannot go backwards")
            row.update({"status": d["decision"], "method": "manual_review", "shared_identifier": None,
                        "rationale": f"Review decision ({d['decision']}): {d['rationale'].strip()} "
                                     f"Retrieval context: {old['rationale']}",
                        "reviewer": d["reviewer"], "reviewed_at": d["reviewed_at"]})
            transitions.append(_transition("facility_matches", old, deepcopy(row), d["reviewer"],
                                           d["reviewed_at"], d["rationale"].strip()))
        final[row["match_id"]] = row
        ledger.append({"match_id": row["match_id"], "facility_id": row["facility_id"],
                       "external_facility_id": row["external_facility_id"],
                       "prior_status": old["status"], "prior_method": old["method"],
                       "decision": d["decision"], "endorsed_automatic_confirmation": endorsement,
                       "reviewer": d["reviewer"], "reviewed_at": d["reviewed_at"],
                       "rationale": d["rationale"].strip(),
                       "observed_false_match": d["decision"] == "rejected"})

    confirmed = defaultdict(set)
    for row in final.values():
        if row["status"] == "confirmed":
            confirmed[row["external_facility_id"]].add(row["facility_id"])
    for external_id in sorted(confirmed):
        require(len(confirmed[external_id]) <= 1, "decisions",
                "one external record cannot be confirmed for more than one base row")

    for row in reviewed["review_queue"]:
        d = decided.get(row["match_id"]) if row["match_id"] else None
        if d is None or row["status"] == "resolved":
            continue
        old = deepcopy(row)
        row.update({"status": "resolved", "resolution": f"{d['decision']} by review: {d['rationale'].strip()}"})
        transitions.append(_transition("review_queue", old, deepcopy(row), d["reviewer"], d["reviewed_at"],
                                       d["rationale"].strip()))

    confirmed_by_external = {m["external_facility_id"]: m for m in final.values() if m["status"] == "confirmed"}
    linked = unlinked = waiting = 0
    for evidence in external_batch["facility_evidence"]:
        old = deepcopy(evidence)
        if evidence["match_id"] is not None:
            match = final.get(evidence["match_id"])
            d = decided.get(evidence["match_id"])
            if match is not None and match["status"] != "confirmed" and d is not None:
                new = dict(old, facility_id=None, match_id=None, reviewer=d["reviewer"], reviewed_at=d["reviewed_at"])
                _forward(old, d)
                transitions.append(_transition("facility_evidence", old, new, d["reviewer"], d["reviewed_at"],
                                               "Unlinked: the match this evidence pointed at is no longer confirmed."))
                unlinked += 1
            continue
        match = confirmed_by_external.get(evidence["external_facility_id"])
        d = decided.get(match["match_id"]) if match else None
        if match is None or d is None:
            waiting += 1
            continue
        new = dict(old, facility_id=match["facility_id"], match_id=match["match_id"],
                   reviewer=d["reviewer"], reviewed_at=d["reviewed_at"])
        _forward(old, d)
        transitions.append(_transition("facility_evidence", old, new, d["reviewer"], d["reviewed_at"],
                                       "Linked to the base row of a reviewer-confirmed match."))
        linked += 1

    reviewed["facility_matches"].sort(key=lambda r: r["match_id"])
    schema_check(reviewed, "reviewed")
    transitions.sort(key=lambda t: t["transition_id"])
    ledger.sort(key=lambda r: r["match_id"])
    outcomes = Counter(row["decision"] for row in ledger)
    summary = {
        "decisions": len(ledger), "denominator_note": "Rates below use reviewed decisions as the denominator, "
        "not all candidates. They describe this sample only and are not a precision estimate for unreviewed rows.",
        "confirmed": outcomes.get("confirmed", 0), "rejected": outcomes.get("rejected", 0),
        "conflict": outcomes.get("conflict", 0),
        "observed_false_matches": [row["match_id"] for row in ledger if row["observed_false_match"]],
        "matches_total": len(final),
        "matches_by_final_status": dict(sorted(Counter(m["status"] for m in final.values()).items())),
        "evidence_rows_seen": len(external_batch["facility_evidence"]), "evidence_linked": linked,
        "evidence_unlinked": unlinked, "evidence_left_unlinked": waiting,
        "transitions": len(transitions),
    }
    return {"reviewed_batch": reviewed, "transitions": transitions,
            "evidence_transitions": [t for t in transitions if t["table"] == "facility_evidence"],
            "ledger": ledger, "summary": summary}


def _forward(evidence, decision):
    if evidence["reviewed_at"] is not None:
        require(_instant(decision["reviewed_at"]) >= _instant(evidence["reviewed_at"]),
                "decisions.reviewed_at", "link time precedes the evidence review time")


def main(argv=None):
    import argparse
    import sys
    from pathlib import Path

    from .common import MatchingError, combine_external, load, write_json

    parser = argparse.ArgumentParser(prog="python -m research.matching.review",
                                     description="Apply reviewer decisions to a matching run.")
    parser.add_argument("--matches", required=True, help="batch.json written by research.matching.run")
    parser.add_argument("--decisions", required=True, help="JSON array of reviewer decisions")
    parser.add_argument("--external", action="append", default=[],
                        help="Producer envelope(s) holding evidence to link; repeatable")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        external = combine_external([load(p) for p in args.external]) if args.external else None
        result = apply(load(args.matches), load(args.decisions), external)
        out = Path(args.output_dir)
        hashes = {name: write_json(out / f"{name}.json", result[key]) for name, key in (
            ("reviewed_batch", "reviewed_batch"), ("transitions", "transitions"),
            ("evidence_transitions", "evidence_transitions"),
            ("review_ledger", "ledger"), ("review_summary", "summary"))}
        print(canonical({"status": "ok", "summary": result["summary"], "sha256": hashes}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
