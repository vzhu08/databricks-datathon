"""Full occurrence-frame source screen; output is NOT an adjudicated status ledger."""
from __future__ import annotations

from collections import Counter, defaultdict
import re

from .extract import canonical, digest, require
from research.matching.national import NO_STATE, NOT_A_STATE, STATES, state_bucket
from research.matching.normalize import state_key

SERVICES = ("mri", "dialysis", "trauma_care")


def name_key(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold())) if isinstance(value, str) else ""


def compare(base, observations, mapping, *, expected_rows, expected_upstream_ids):
    require(len(base) == expected_rows, "full occurrence denominator required")
    require(len({r['facility_id'] for r in base}) == len(base), "occurrence keys must be unique")
    ids = {canonical(r["source_row"].get(mapping["id"])) for r in base}
    require(len(ids) == expected_upstream_ids, "upstream ID denominator changed")
    require(all(o["current_service_eligible"] is False and o["vf_link_status"] == "unreviewed"
                for o in observations), "use reviewed shared projection for accepted evidence")
    by_name = defaultdict(list)
    for obs in observations:
        key = name_key(obs["campus_raw"])
        # No expansion of abbreviated station/campus names and no city-only joins.
        if len(key.split()) >= 2:
            by_name[key].append(obs)
    frame, leads = [], []
    states = Counter({s: 0 for s in STATES | {NO_STATE, NOT_A_STATE}})
    for row in base:
        source = row["source_row"]
        state = source.get(mapping["state"])
        bucket = state_bucket(state_key(state if isinstance(state, str) else None))
        states[bucket] += 1
        related = by_name.get(name_key(source.get(mapping["name"])), [])
        source_keys = sorted({o["source_campus_key"] for o in related})
        if related:
            leads.append({"facility_id": row["facility_id"], "source_campus_keys": source_keys,
                          "observation_ids": sorted(o["observation_id"] for o in related),
                          "method": "literal_normalized_name_only", "link_status": "unreviewed"})
        for service in SERVICES:
            frame.append({"facility_id": row["facility_id"], "upstream_id": source.get(mapping["id"]),
                          "original_payload_sha256": digest(canonical(source)), "service": service,
                          "state_label_raw": state, "screening_result": "no_eligible_current_evidence_in_packet",
                          "status_delta": "none", "baseline_status": None,
                          "candidate_observation_ids": sorted(o["observation_id"] for o in related
                                                              if o["clinical_service"] == service),
                          "adjudication": "not_performed", "current_service_upgrade": False})
    summary = {"occurrences": len(base), "distinct_upstream_ids": len(ids),
               "occurrence_service_screens": len(frame), "screens_per_service": len(base),
               "state_ut_unknown_counts": dict(sorted(states.items())),
               "literal_name_candidate_occurrences": len(leads), "accepted_campus_links": 0,
               "new_current_service_decisions": 0, "new_current_service_occurrences": 0,
               "source_overlap_after_review": None, "baseline_candidate_overlap": None,
               "unmeasured_reason": "campus aliases and source linkage require Vincent review",
               "meaning": "Source exclusion and literal-name screen over every occurrence; not clinical adjudication"}
    return frame, leads, summary
