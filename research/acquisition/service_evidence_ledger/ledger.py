"""Preserve the national baseline; reconcile observations without adjudicating care.

No network, credentials, clock, clinical inference or publication side effects.
Errors deliberately avoid source text and facility identifiers.
"""
from collections import Counter, defaultdict
from datetime import date, datetime
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

VERSION = "service-evidence-ledger-v1"
SERVICES = ("dialysis", "mri", "trauma_care")
EXPECTED_SPANS = {"dialysis": 3038, "mri": 3136, "trauma_care": 2026}
UNKNOWN_STATES = {"(no state label)", "(label is not a state or union territory)"}


def require(ok, rule):
    if not ok:
        raise ValueError(rule)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def key(value):
    return sha(canonical(value))


def pinned(path, expected):
    raw = Path(path).read_bytes()
    require(sha(raw) == expected, "input_hash_mismatch")
    return raw


def lines(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def day(value):
    if value is not None:
        require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value,
                "invalid_date")
    return value


def stamp(value):
    if value is not None:
        require(datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None,
                "retrieval_timezone_required")


def validate_baseline(base, occurrences, decisions, national=True):
    ids = [r["facility_id"] for r in base]
    require(len(ids) == len(set(ids)) and all(ids), "occurrence_keys_not_unique")
    require(ids == [r["facility_id"] for r in occurrences], "original_order_changed")
    upstream = Counter()
    payloads = []
    for position, (original, row) in enumerate(zip(base, occurrences)):
        payload = original["source_row"]
        require(row["input_ordinal_zero_based"] == position, "ordinal_changed")
        require(key(payload) == row["original_payload_sha256"], "original_payload_changed")
        require(payload["unique_id"] == row["original_upstream_id"], "upstream_id_changed")
        upstream[payload["unique_id"]] += 1
        payloads.append(payload)
    pairs = [(r["occurrence_key"], r["service"]) for r in decisions]
    require(len(pairs) == len(set(pairs)) and set(pairs) == {(i, s) for i in ids for s in SERVICES},
            "incomplete_or_duplicate_decision_frame")
    by_id = {r["facility_id"]: r for r in occurrences}
    for row in decisions:
        require(row["status"] in {"yes", "no", "unconfirmed"}, "invalid_baseline_status")
        require(row["state"] == by_id[row["occurrence_key"]]["state"], "decision_geography_changed")
        day(row["as_of"])
    if national:
        require(len(base) == 10088 and len(upstream) == 10077, "national_denominator_changed")
        require(Counter(upstream.values()) == {1: 10066, 2: 11}, "national_twins_changed")
        require(all(r["status"] == "unconfirmed" for r in decisions), "frozen_baseline_status_changed")
    return {"occurrences": len(base), "distinct_upstream_ids": len(upstream),
            "duplicate_id_groups": sum(n > 1 for n in upstream.values()),
            "occurrences_in_duplicate_groups": sum(n for n in upstream.values() if n > 1),
            "decisions": len(decisions),
            "original_payload_multiset_sha256": key(sorted(payloads, key=canonical))}


def normalize_lanes(packages, base):
    """Validate a deliberately narrow collector input; keep every submitted row."""
    originals = {r["facility_id"]: r["source_row"] for r in base}
    editions, observations, lane_names = {}, [], set()
    for package in packages:
        require(package["schema_version"] == "service-evidence-lane-v1", "unknown_lane_schema")
        lane = package["lane"]
        require(isinstance(lane, str) and lane and lane not in lane_names, "duplicate_or_empty_lane")
        lane_names.add(lane)
        local_editions = {}
        for edition in package["editions"]:
            for field in ("edition_id", "publisher", "source_url", "reuse_terms", "sharing_scope", "geographic_scope"):
                require(isinstance(edition.get(field), str) and edition[field].strip(), "edition_provenance_required")
            require(len(edition["content_sha256"]) == 64 and
                    all(c in "0123456789abcdef" for c in edition["content_sha256"]), "invalid_edition_digest")
            require(edition["sharing_scope"] == "private_datathon_four_readers", "edition_not_cleared_for_team")
            day(edition["published_date"])
            stamp(edition["retrieved_at"])
            require(edition["origin_status"] in {"known", "unknown"}, "invalid_origin_status")
            require(edition["source_family"] is None or
                    isinstance(edition["source_family"], str) and edition["source_family"].strip(), "invalid_family")
            require(edition["origin_status"] != "known" or edition["source_family"], "known_origin_requires_family")
            eid = edition["edition_id"]
            require(eid not in local_editions, "duplicate_edition_in_lane")
            require(eid not in editions or editions[eid] == edition, "edition_id_collision")
            editions[eid] = local_editions[eid] = edition
        local_ids = set()
        for raw in package["observations"]:
            oid = raw["observation_id"]
            require(isinstance(oid, str) and oid and oid not in local_ids, "duplicate_or_empty_observation")
            local_ids.add(oid)
            require(raw["edition_id"] in local_editions, "unknown_edition")
            for field in ("source_facility_id", "modality", "claim_type", "claim_scope"):
                require(isinstance(raw[field], str) and raw[field].strip(), "observation_field_required")
            if raw.get("raw_text_withheld") is True:
                require(raw["raw_text"] is None and raw["original_occurrence_key"] is None, "invalid_withheld_text")
            else:
                require(isinstance(raw["raw_text"], str) and raw["raw_text"].strip(), "raw_text_required")
            require(raw["polarity"] in {"supports", "contradicts", "inconclusive"}, "invalid_polarity")
            require(raw["independence_status"] in {"unassessed", "shared_origin", "reviewed_independent"},
                    "invalid_independence_status")
            require(type(raw["multi_campus"]) is bool, "multi_campus_required")
            require(isinstance(raw["locator"], dict) and raw["locator"], "locator_required")
            require("claim_value" in raw and "units" in raw, "claim_value_and_units_required")
            for field in ("source_date", "effective_from", "effective_until"):
                day(raw[field])
            require(not (raw["effective_from"] and raw["effective_until"] and
                         raw["effective_from"] > raw["effective_until"]), "reversed_interval")
            origin = raw["original_occurrence_key"]
            if origin is not None:
                require(origin in originals, "unknown_original_occurrence")
                loc = raw["locator"]
                value = originals[origin].get(loc.get("field"))
                start, end = loc.get("start"), loc.get("end")
                require(isinstance(value, str) and type(start) is int and type(end) is int and
                        0 <= start < end <= len(value), "invalid_original_locator")
                require(value[start:end] == raw["raw_text"], "original_excerpt_changed")
            seen_links = set()
            for link in raw["target_links"]:
                fid = link["occurrence_key"]
                require(fid in originals and fid not in seen_links, "unknown_or_duplicate_target")
                seen_links.add(fid)
                require(link["quality"] in {"unresolved", "candidate", "confirmed"}, "invalid_link_quality")
                if link["quality"] == "confirmed":
                    require(bool(link["campus_id"]) and bool(link["review_reference"]), "confirmed_link_requires_review")
            edition = editions[raw["edition_id"]]
            if raw["independence_status"] == "reviewed_independent":
                require(edition["origin_status"] == "known" and bool(raw.get("independence_review")),
                        "independence_review_required")
            for field in ("mirror_of", "supersedes"):
                require(isinstance(raw[field], list) and all(isinstance(v, str) and v for v in raw[field]),
                        "invalid_relationships")
            observations.append({"ledger_id": key([lane, oid]), "lane": lane,
                                 "source_family": edition["source_family"],
                                 "origin_status": edition["origin_status"], "raw": raw})
    by_id = {r["ledger_id"]: r for r in observations}
    for row in observations:
        for field in ("mirror_of", "supersedes"):
            for target in row["raw"][field]:
                require(target in by_id and target != row["ledger_id"], "unresolved_relationship")
    return sorted(editions.values(), key=lambda e: e["edition_id"]), sorted(observations, key=lambda r: r["ledger_id"])


def reconcile(observations):
    """Compare only reviewed single-campus links with equal claim scope and units.

    An overlapping explicitly bounded interval is required to flag opposing
    polarities. Different/unknown time scopes remain separate, without conflicts
    or independence being inferred from the absence of an assessment.
    """
    groups, wording = defaultdict(list), defaultdict(list)
    for row in observations:
        raw = row["raw"]
        if raw["raw_text"] is not None:
            wording[key([raw["modality"], raw["raw_text"]])].append(row["ledger_id"])
        campuses = {link["campus_id"] for link in raw["target_links"] if link["quality"] == "confirmed"}
        if raw["multi_campus"] or len(campuses) != 1:
            continue
        campus = next(iter(campuses))
        gkey = (campus, raw["modality"], raw["claim_type"], raw["claim_scope"],
                canonical(raw["units"]).decode(), canonical(raw["claim_value"]).decode())
        groups[gkey].append(row)
    reconciled = []
    for group_key, rows in sorted(groups.items()):
        conflicts = []
        for index, left in enumerate(rows):
            a = left["raw"]
            for right in rows[index + 1:]:
                b = right["raw"]
                dates = [a["effective_from"], a["effective_until"], b["effective_from"], b["effective_until"]]
                if (all(dates) and max(dates[0], dates[2]) <= min(dates[1], dates[3]) and
                        {a["polarity"], b["polarity"]} == {"supports", "contradicts"}):
                    conflicts.append([left["ledger_id"], right["ledger_id"]])
        known = Counter(r["source_family"] for r in rows if r["origin_status"] == "known")
        independent = sorted({r["source_family"] for r in rows if
                              r["raw"]["independence_status"] == "reviewed_independent"})
        reconciled.append({"group_id": key(group_key), "campus_id": group_key[0],
                           "modality": group_key[1], "claim_type": group_key[2], "claim_scope": group_key[3],
                           "units": json.loads(group_key[4]), "claim_value": json.loads(group_key[5]),
                           "observation_ids": [r["ledger_id"] for r in rows],
                           "known_families": dict(sorted(known.items())),
                           "reviewed_independent_families": independent,
                           "unknown_origin_observations": sum(r["origin_status"] == "unknown" for r in rows),
                           "comparable_polarity_conflicts": conflicts})
    repeats = [{"wording_sha256": h, "observation_ids": ids, "origin_relationship": "unassessed"}
               for h, ids in sorted(wording.items()) if len(ids) > 1]
    return reconciled, repeats


def build(base, occurrences, decisions, packages=(), national=True, statements_complete=False,
          geography_buckets=()):
    population = validate_baseline(base, occurrences, decisions, national)
    editions, observations = normalize_lanes(packages, base)
    groups, repeats = reconcile(observations)
    states = {r["facility_id"]: r["state"] for r in occurrences}
    base_pairs = set()
    spans = defaultdict(set)
    lane_pairs = defaultdict(set)
    family_pairs = defaultdict(set)
    for package in packages:
        lane_pairs[package["lane"]]  # An empty attempted lane still has a zero-gain receipt.
    for row in observations:
        raw = row["raw"]
        origin = raw["original_occurrence_key"]
        if origin is not None:
            loc = raw["locator"]
            spans[raw["modality"]].add((origin, loc["field"], loc["start"], loc["end"]))
            base_pairs.add((origin, raw["modality"]))
        for link in raw["target_links"]:
            pair = (link["occurrence_key"], raw["modality"])
            lane_pairs[row["lane"]].add(pair)
            family_pairs[row["source_family"]].add(pair)
    measured_spans = {s: len(spans[s]) for s in SERVICES}
    if statements_complete and national:
        require(measured_spans == EXPECTED_SPANS, "frozen_span_totals_changed")
    count_by_state = Counter(states.values())
    if geography_buckets:
        require(set(count_by_state) <= set(geography_buckets), "unrecognized_baseline_geography")
        for state in geography_buckets:
            count_by_state.setdefault(state, 0)
    if national:
        require(len(count_by_state) == 38 and UNKNOWN_STATES <= set(count_by_state), "national_geography_buckets_missing")
    decision_counts = Counter((r["state"], r["service"], r["status"]) for r in decisions)
    state_service = []
    conflicted_ids = {oid for g in groups for pair in g["comparable_polarity_conflicts"] for oid in pair}
    conflicted_pairs = {(link["occurrence_key"], r["raw"]["modality"]) for r in observations
                        if r["ledger_id"] in conflicted_ids for link in r["raw"]["target_links"]
                        if link["quality"] == "confirmed"}
    for state, count in sorted(count_by_state.items()):
        for service in SERVICES:
            state_service.append({"state": state, "service": service, "original_occurrences": count,
                                  **{s: decision_counts[state, service, s] for s in ("yes", "no", "unconfirmed")},
                                  "comparable_conflicted_occurrence_pairs": sum(states[f] == state and s == service for f, s in conflicted_pairs),
                                  "original_mention_occurrences": (sum(states[f] == state and s == service for f, s in base_pairs)
                                                                   if statements_complete else None)})
    # These are occurrence-level leads, never distinct physical campuses or care confirmations.
    marginal = [{"lane": lane, "linked_occurrence_modality_pairs": len(pairs),
                 "new_leads_over_original_text": len(pairs - base_pairs) if statements_complete else None,
                 "decision_transitions": 0} for lane, pairs in sorted(lane_pairs.items())]
    facility_counts = []
    by_occurrence = defaultdict(list)
    for row in observations:
        targets = {link["occurrence_key"] for link in row["raw"]["target_links"]}
        if row["raw"]["original_occurrence_key"]:
            targets.add(row["raw"]["original_occurrence_key"])
        for fid in targets:
            by_occurrence[fid].append(row)
    for row in occurrences:
        obs = by_occurrence[row["facility_id"]]
        families = sorted({r["source_family"] for r in obs if r["origin_status"] == "known"})
        facility_counts.append({"occurrence_key": row["facility_id"], "state": row["state"],
                                "observations_loaded": len(obs), "known_families": families,
                                "unknown_origin_observations": sum(r["origin_status"] == "unknown" for r in obs),
                                "single_known_origin": len(families) == 1,
                                "comparable_conflicted_services": sorted(s for f, s in conflicted_pairs if f == row["facility_id"]),
                                "mixed_campus": row["branch_evidence"]["mixed_campus"],
                                "identity_conflict_count": len(row["conflicts"])})
    report = {"population": population, "baseline_as_of": sorted({r["as_of"] for r in decisions}),
              "original_statement_coverage": "complete" if statements_complete else "missing_packet",
              "expected_original_field_spans": EXPECTED_SPANS,
              "verified_original_field_spans": measured_spans if statements_complete else None,
              "loaded_observations": len(observations), "source_editions": len(editions),
              "loaded_observations_by_modality": dict(sorted(Counter(r["raw"]["modality"] for r in observations).items())),
              "source_object_editions": len({(r["raw"]["edition_id"], r["raw"]["source_facility_id"]) for r in observations}),
              "unlinked_observations": sum(not r["raw"]["target_links"] for r in observations),
              "confirmed_campus_modality_claim_groups": len(groups),
              "comparable_conflicted_groups": sum(bool(g["comparable_polarity_conflicts"]) for g in groups),
              "shared_wording_groups": len(repeats), "independent_accuracy": None,
              "unknown_geography_occurrences": sum(count_by_state[s] for s in UNKNOWN_STATES),
              "baseline_decision_transitions": 0, "state_service": state_service,
              "marginal_by_lane": marginal,
              "combined_linked_occurrence_modality_pairs": len(set().union(*lane_pairs.values())),
              "family_coverage": [{"family": family, "state": state, "service": service,
                                   "linked_occurrence_modality_pairs": sum(states[f] == state and s == service for f, s in pairs)}
                                  for family, pairs in sorted(family_pairs.items(), key=lambda item: str(item[0]))
                                  for state in sorted(count_by_state)
                                  for service in sorted(set(SERVICES) | {r["raw"]["modality"] for r in observations})],
              "limitations": ["Read-only baseline decisions; observations do not authorize service transitions.",
                              "Distinct families do not establish independence without a review.",
                              "Different or unknown date scopes are retained without automatic conflict resolution."]}
    return {"occurrences": [{"original": original, "identity": occurrence} for original, occurrence in zip(base, occurrences)],
            "decisions": decisions, "editions": editions, "observations": observations,
            "reconciliation": groups, "shared_wording": repeats, "facility_counts": facility_counts,
            "report": report}


def write_release(output, artifact, provenance):
    output = Path(output)
    files = {}
    for name, value in artifact.items():
        if name == "report":
            raw, filename = canonical(value) + b"\n", "report.json"
        else:
            raw = gzip.compress(b"".join(canonical(row) + b"\n" for row in value), mtime=0)
            filename = name + ".jsonl.gz"
        files[filename] = raw
    manifest = {"schema_version": VERSION, "publisher": "Datathon Developer D",
                "purpose": "Private read-only national service evidence reconciliation",
                "geographic_scope": "India; all original occurrences including unknown geography",
                "sharing_scope": "private_datathon_four_readers",
                "reuse_terms": "Restricted VF derivative; retain source-specific rights in editions and input manifests.",
                "join_fields": ["occurrence_key / original.facility_id", "ledger_id", "edition_id", "campus_id"],
                "inputs": provenance, "population": artifact["report"]["population"],
                "files": {name: {"sha256": sha(raw), "bytes": len(raw),
                                 "records": None if name == "report.json" else len(artifact[name.split('.')[0]])}
                          for name, raw in sorted(files.items())}}
    files["manifest.json"] = canonical(manifest) + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        require(set(p.name for p in output.iterdir()) == set(files), "release_already_exists_different_files")
        require(all((output / name).read_bytes() == raw for name, raw in files.items()), "release_already_exists_changed_bytes")
    else:
        with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
            staged = Path(tmp) / "release"
            staged.mkdir()
            for name, raw in files.items():
                (staged / name).write_bytes(raw)
            staged.rename(output)
    return sha(files["manifest.json"])


def attach_joint_trace(artifact, joint_rows):
    """Retain the newer matching trace alongside, without changing service scope."""
    occurrences = artifact["occurrences"]
    require([r["original"]["facility_id"] for r in occurrences] == [r["facility_id"] for r in joint_rows],
            "joint_occurrence_frame_changed")
    counts = Counter()
    for position, (row, joint) in enumerate(zip(occurrences, joint_rows), start=1):
        require(joint["input_ordinal"] == position and
                joint["original_payload_sha256"] == row["identity"]["original_payload_sha256"] and
                joint["state"] == row["identity"]["state"], "joint_original_or_geography_changed")
        require(joint["baseline_service_context"] == dict.fromkeys(SERVICES, "unconfirmed"),
                "joint_baseline_service_context_changed")
        outcome = joint["outcomes"]["joint"]
        require(outcome in {"unmatched", "candidate_only", "ambiguous", "confirmed"}, "unknown_joint_outcome")
        counts[outcome] += 1
        row["joint_identity"] = joint
    artifact["report"]["joint_identity_outcomes"] = dict(sorted(counts.items()))
    artifact["report"]["identity_frames"] = {"identity": "LOC-04 v3", "joint_identity": "frozen LOC-03 joint comparison in #147"}
