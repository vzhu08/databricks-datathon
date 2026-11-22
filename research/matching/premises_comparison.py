"""Compare a private national premises replay with verified LOC-01 controls."""
from __future__ import annotations

import argparse
import gzip
import io
import json
from itertools import zip_longest
from collections import Counter, defaultdict
from pathlib import Path

from .common import MatchingError, canonical, digest, file_digest, load, require, write_json
from .national import NOT_A_STATE, NO_STATE, OUTCOMES, STATES, _outcome, duplicate_groups

CONTROLS = ("frozen", "corrected")
SERVICES = ("dialysis", "mri", "trauma_care")
STATES_WITH_UNKNOWN = sorted([*STATES, NO_STATE, NOT_A_STATE])
EXPECTED_OUTCOMES = {"frozen": (0, 3358, 4038, 2692), "corrected": (0, 3555, 3929, 2604)}
EXPECTED_PAIR_COUNTS = {"frozen": 20713, "corrected": 21339}


def _verified(path, expected):
    require(file_digest(path) == expected, path.name, "SHA-256 differs from the verified receipt")
    return path


def _json_lines(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        yield from map(json.loads, stream)


def _gzip_lines(path):
    return io.TextIOWrapper(gzip.GzipFile(filename="", mode="wb", fileobj=path, mtime=0), encoding="utf-8")


def _write(stream, row):
    stream.write(canonical(row) + "\n")


def _states_summary():
    return {state: Counter({outcome: 0 for outcome in OUTCOMES}) for state in STATES_WITH_UNKNOWN}


def _stage(pair, exclusion, variant):
    if pair is None:
        return {"stage": "scoring_rejection" if exclusion else "outside_index_blocks",
                "loss_reason": exclusion or "no_index_block_admitted_pair"}
    rank = pair.get("rank" if variant else "retained_rank")
    return {"stage": "retained" if rank is not None else "rank_cut", "retained_rank": rank,
            "loss_reason": "outside_top_k" if rank is None else None, "pre_cut_rank": pair["pre_cut_rank"],
            "serious": pair["serious" if variant else "serious_for_competition"],
            "admission_reason": pair["retrieval_reason"], "flags": pair["flags"],
            "review_reason": pair.get("review_reason"), "block_stages": pair.get("block_stages"),
            "geography": {k: pair["signals"][k] for k in ("state", "place", "pin", "address", "distance_band")}}


def _by_rep(candidates):
    indexed = defaultdict(dict)
    for candidate in candidates:
        rid, eid = candidate["facility_id"], candidate["external_facility_id"]
        require(eid not in indexed[rid], "candidates", "duplicate admitted pair")
        indexed[rid][eid] = candidate
    return indexed


def _rejections(row):
    return {i: reason for reason, indexes in row["scoring_rejections"].items() for i in indexes}


def _control_observations(root, receipt, reference_ids):
    frames, external_indexes, retained = {}, {}, {}
    for scenario in CONTROLS:
        control = receipt["scenarios"][scenario]
        require(tuple(control["outcomes"][o] for o in OUTCOMES) == EXPECTED_OUTCOMES[scenario]
                and control["retained_pairs"] == EXPECTED_PAIR_COUNTS[scenario]
                and control["original_rows"] == 10088 and control["reference_rows"] == 146847,
                scenario, "reproduced control counts differ from the frozen pins")
        pins = control["private_artifact_sha256"]
        path = "observations/external-index.jsonl.gz"
        refs = list(_json_lines(_verified(root / scenario / path, pins[path])))
        index = {ref["external_facility_id"]: ref for ref in refs}
        require(set(index) == reference_ids and len(refs) == len(index)
                and all(ref["index"] == i for i, ref in enumerate(refs)), scenario, "reference index does not reconcile")
        external_indexes[scenario] = index
        path = "observations/retrieval-stages.jsonl.gz"
        frames[scenario] = _json_lines(_verified(root / scenario / path, pins[path]))
        kept = load(_verified(root / scenario / "exact/candidates.json", control["outputs_sha256"]["candidates"]))
        retained[scenario] = _by_rep(kept)
    return frames, external_indexes, retained


def _compare_pairs(trace, indexed, ids, control_trace, external_indexes, control_retained, path):
    # Pair counts here use representative/reference pairs. Occurrence counts are
    # expanded in the next pass, including both members of each identical pair.
    changes = {scenario: defaultdict(Counter) for scenario in CONTROLS}
    moves = {scenario: Counter() for scenario in CONTROLS}
    pair_summary = {scenario: defaultdict(Counter) for scenario in CONTROLS}
    coverage = Counter()
    with path.open("xb") as raw, _gzip_lines(raw) as output:
        streams = [control_trace[scenario] for scenario in CONTROLS]
        for rid, *controls in zip_longest(sorted(trace), *streams):
            require(rid is not None and all(c is not None for c in controls), "controls", "trace length differs")
            variant = trace[rid]
            pairs = _by_rep(variant["pre_cut"])[rid]
            retained = indexed.get(rid, {})
            rejected = _rejections(variant)
            require(variant["scored"] == len(pairs) + len(rejected), "variant", "scoring flow does not reconcile")
            require(all(pair["pre_cut_rank"] == rank and pair["facility_id"] == rid
                        for rank, pair in enumerate(pairs.values(), 1))
                    and set(retained) == {eid for eid, pair in pairs.items() if "rank" in pair}
                    and sorted(p["rank"] for p in retained.values()) == list(range(1, len(retained) + 1))
                    and all(retained[eid]["rank"] == pairs[eid]["pre_cut_rank"] for eid in retained)
                    and len(retained) <= 5, "variant", "retained positions do not reconcile with trace")
            for key, count in (
                ("scored", variant["scored"]), ("scoring_rejections", len(rejected)), ("pre_cut", len(pairs)),
                ("retained", len(retained)), ("rank_cut", len(pairs) - len(retained)),
                ("serious_pre_cut", sum(p["serious"] for p in pairs.values())),
                ("serious_rank_cut", sum(p["serious"] for eid, p in pairs.items() if eid not in retained)),
                ("representatives_with_rank_cut", int(len(pairs) > len(retained))),
                ("representatives_with_no_blocked_pair", int(variant["scored"] == 0)),
                ("representatives_scored_without_admission", int(variant["scored"] > 0 and not pairs)),
            ):
                coverage[key] += count
            previous, exclusions = {}, {}
            for scenario, control in zip(CONTROLS, controls):
                require(control["representative"] == rid, scenario, "trace order differs from representatives")
                previous[scenario] = _by_rep(control["pre_cut"])[rid]
                exclusions[scenario] = _rejections(control)
                kept = control_retained[scenario].get(rid, {})
                require(set(kept) == {eid for eid, pair in previous[scenario].items() if pair["retained_rank"] is not None},
                        scenario, "control trace and retained candidate ledger disagree")
            for eid in sorted(set(pairs).union(*(set(rows) for rows in previous.values()))):
                now = _stage(pairs.get(eid), rejected.get(ids[eid]), variant=True)
                ref = external_indexes["corrected"][eid]
                row = {"matched_as": rid, "external_facility_id": eid, "source_key": ref["source_key"],
                       "source_record_id": ref["source_record_id"], "snapshot_id": ref["snapshot_id"],
                       "reference_geography": ref["geography"], "variant": now}
                for scenario in CONTROLS:
                    ref_before = external_indexes[scenario][eid]
                    prior = _stage(previous[scenario].get(eid), exclusions[scenario].get(ref_before["index"]),
                                   variant=False)
                    kept = control_retained[scenario].get(rid, {}).get(eid)
                    if kept:
                        prior["review_reason"] = kept["review_reason"]
                        prior["flags"] = kept["flags"]
                    row[scenario] = prior
                    move = f"{prior['stage']} -> {now['stage']}"
                    moves[scenario][move] += 1
                    pair_summary[scenario][ref["source_key"]][move] += 1
                    delta = changes[scenario][rid]
                    if prior["stage"] != "retained" and now["stage"] == "retained":
                        delta["retained_added"] += 1
                    if prior["stage"] == "retained" and now["stage"] != "retained":
                        delta["retained_lost"] += 1
                        delta[f"retained_lost_to_{now['stage']}"] += 1
                    if prior["stage"] == now["stage"] == "retained" and prior["retained_rank"] != now["retained_rank"]:
                        delta["retained_rank_changed"] += 1
                    if prior["stage"] in ("scoring_rejection", "outside_index_blocks") and eid in pairs:
                        delta["pre_cut_added"] += 1
                    if eid in previous[scenario] and eid not in pairs:
                        delta["pre_cut_lost"] += 1
                _write(output, row)
    return changes, moves, pair_summary, coverage


def _compare_occurrences(base, variant, control_frames, service, changes, retained, path):
    outcomes, unknown, by_state, by_service = {}, {}, {}, {}
    pair_delta_by_state, pair_delta_by_outcome = {}, {}
    variant_state = _states_summary()
    for scenario in CONTROLS:
        outcomes[scenario] = Counter()
        unknown[scenario] = Counter()
        by_state[scenario] = {state: Counter() for state in STATES_WITH_UNKNOWN}
        by_service[scenario] = {name: Counter() for name in SERVICES}
        pair_delta_by_state[scenario] = {state: Counter() for state in STATES_WITH_UNKNOWN}
        pair_delta_by_outcome[scenario] = {outcome: Counter() for outcome in OUTCOMES}
    with path.open("xb") as raw, _gzip_lines(raw) as output:
        for ordinal, (original, row, controls) in enumerate(zip_longest(base, variant, control_frames), 1):
            require(all(record is not None for record in (original, row, controls)), "occurrences", "frame length differs")
            fid, rid = row["facility_id"], row["matched_as"]
            require(original["facility_id"] == controls["facility_id"] == fid
                    and controls["matched_as"] == rid and controls["input_ordinal"] == ordinal,
                    "occurrences", "input sequence or representative differs from controls")
            payload = digest(original["source_row"])
            require(payload == controls["original_payload_sha256"], "occurrences", "original payload differs")
            candidates = list(retained.get(rid, {}).values())
            require(row["candidate_count"] == len(candidates) and row["outcome"] == _outcome(candidates),
                    "occurrences", "variant outcome disagrees with retained candidates")
            state = row["state"]
            variant_state[state][row["outcome"]] += 1
            require(set(service[fid]["services"]) == set(SERVICES), "service", "incomplete occurrence/service row")
            statuses = {name: service[fid]["services"][name]["status"] for name in SERVICES}
            require(set(statuses.values()) <= {"yes", "no", "unconfirmed"}, "service", "unknown status")
            record = {"input_ordinal": ordinal, "facility_id": fid, "matched_as": rid, "original_payload_sha256": payload,
                      "variant": row, "identity_review_priority": sorted(set(row["conflicts"]) | set(row["input_problems"])),
                      "baseline_service_status": statuses}
            for scenario in CONTROLS:
                old = controls[scenario]
                require(old["duplicate_group"] == row["duplicate_group"] and old["state"] == state
                        and old["duplicate_multiplicity"] == row["duplicate_multiplicity"],
                        scenario, "original geography bucket or group context changed")
                move = f"{old['outcome']} -> {row['outcome']}"
                old_found = old["outcome"] != "unmatched"
                new_found = row["outcome"] != "unmatched"
                reach = "gained" if new_found and not old_found else "lost" if old_found and not new_found else "unchanged"
                delta = changes[scenario].get(rid, Counter())
                outcomes[scenario][move] += 1
                by_state[scenario][state][move] += 1
                if state in (NO_STATE, NOT_A_STATE):
                    unknown[scenario][move] += 1
                for change, count in delta.items():
                    pair_delta_by_state[scenario][state][change] += count
                    pair_delta_by_state[scenario][state][f"rows_with_{change}"] += bool(count)
                    pair_delta_by_outcome[scenario][old["outcome"]][change] += count
                    pair_delta_by_outcome[scenario][old["outcome"]][f"rows_with_{change}"] += bool(count)
                for name in SERVICES:
                    by_service[scenario][name][f"{statuses[name]} / retrieval {reach}"] += 1
                record[scenario] = {"control": old, "pair_delta": delta}
            _write(output, record)
    return outcomes, unknown, by_state, by_service, variant_state, pair_delta_by_state, pair_delta_by_outcome


def compare(base_path, control_root, control_pin, variant_root, service_path, service_pin, out):
    receipt_path = _verified(control_root / "aggregate-receipt.json", control_pin)
    receipt = load(receipt_path)
    manifest_path = variant_root / "manifest.json"
    manifest = load(manifest_path)
    input_hashes = manifest["inputs_sha256"]
    inputs = receipt["input_sha256"]
    for role, filename in (("base", "base.json"), ("source_metadata", "source_metadata.json"),
                           ("duplicate_groups", "duplicate_groups.json"), ("postal", "postal_rows.json"),
                           ("base_mapping", "base-mapping-extra.json")):
        require(inputs[filename] == input_hashes[role], role, "variant used different frozen input data")
    require(input_hashes["external"] == [inputs["national.json"]] and input_hashes["identity_policy"] is None
            and manifest["state"] is None, "variant", "expected an unfiltered candidate-only run")
    base = load(_verified(base_path, inputs["base.json"]))
    orig_ids = {row["source_row"]["unique_id"] for row in base}
    keys = [row["facility_id"] for row in base]
    payload_sha = digest(sorted((row["source_row"] for row in base), key=canonical))
    require(len(base) == len(set(keys)) == 10088 and len(orig_ids) == 10077
            and digest(keys) == receipt["ordered_occurrence_keys_sha256"]
            and payload_sha == receipt["original_payload_multiset_sha256"], "base", "original population differs")
    groups = duplicate_groups(base)
    require(len(groups) == 11 and all(g["multiplicity"] == 2 for g in groups), "base", "eleven identical pairs required")

    def artifact(name):
        return load(_verified(variant_root / (name + ".json"), manifest["outputs_sha256"][name]))

    variant = artifact("base_rows")
    require([row["facility_id"] for row in variant] == keys and artifact("duplicate_groups") == groups,
            "variant", "occurrence sequence or groups differ")
    candidates = artifact("candidates")
    batch = artifact("batch")
    require(all(m["status"] == "candidate" and m["shared_identifier"] is None for m in batch["facility_matches"])
            and not batch["facility_evidence"] and not any(c["auto_confirmed"] for c in candidates)
            and {m["match_id"] for m in batch["facility_matches"]} == {c["match_id"] for c in candidates}
            and len(batch["facility_matches"]) == len(candidates), "variant", "candidate-only contract rows expected")

    ids = {eid: i for i, eid in enumerate(artifact("stage_reference_ids"))}
    require(len(ids) == 146847, "variant", "frozen reference population differs")
    trace = artifact("candidate_stages")
    require(set(trace) == {row["matched_as"] for row in variant}, "variant", "trace misses a representative")
    service = load(_verified(service_path, service_pin))
    require(service["base_file_sha256"] == inputs["base.json"] and set(service["facilities"]) == set(keys)
            and service["decision_count"] == 30264, "service", "lookup does not cover the same pinned population")
    indexes, refs, control_retained = _control_observations(control_root, receipt, set(ids))
    occurrence_file = "occurrence-comparison.jsonl.gz"
    control_occurrences = _verified(control_root / occurrence_file, receipt["private_artifact_sha256"][occurrence_file])
    out.mkdir(parents=True, exist_ok=False)
    pair_file = out / "candidate-comparison.jsonl.gz"
    occurrence_output = out / occurrence_file
    retained = _by_rep(candidates)
    pair_deltas, stages, source_stages, stage_counts = _compare_pairs(trace, retained, ids, indexes, refs,
                                                                    control_retained, pair_file)
    results = _compare_occurrences(base, variant, _json_lines(control_occurrences), service["facilities"],
                                  pair_deltas, retained, occurrence_output)
    outcome, unknown, state, services, variant_state, state_deltas, outcome_deltas = results
    variant_outcomes = Counter(row["outcome"] for row in variant)
    summary = {
        "data": {"original_occurrences": len(base), "original_upstream_ids": len(orig_ids), "duplicate_pairs": len(groups),
                 "duplicate_occurrences": sum(group["multiplicity"] for group in groups), "references": len(ids),
                 "ordered_occurrence_keys_sha256": digest(keys), "original_payload_multiset_sha256": payload_sha},
        "replay_pins": {"control_receipt_sha256": control_pin, "variant_manifest_sha256": file_digest(manifest_path),
                        "variant_input_sha256": input_hashes, "variant_outputs_sha256": manifest["outputs_sha256"],
                        "service_lookup_sha256": service_pin},
        "variant": {"outcomes": {o: variant_outcomes[o] for o in OUTCOMES},
                    "by_state": variant_state, "by_source": artifact("national_report")["by_source"],
                    "candidate_stages": stage_counts, "review_items": len(batch["review_queue"])},
        "versus_controls": {
            scenario: {"outcome_transitions": outcome[scenario], "unknown_geography_transitions": unknown[scenario],
                       "outcome_transitions_by_state": state[scenario], "pair_delta_by_state": state_deltas[scenario],
                       "pair_delta_by_control_outcome": outcome_deltas[scenario],
                       "candidate_stage_transitions": stages[scenario], "candidate_stages_by_source": source_stages[scenario],
                       "service_context_by_retrieval_change": services[scenario]}
            for scenario in CONTROLS
        },
        "service_context": {"baseline_coverage": service["coverage"], "by_state": service["coverage_by_state"],
                            "decisions": service["decision_count"], "new_decisions": 0},
        "comparisons_sha256": {p.name: file_digest(p) for p in (pair_file, occurrence_output)},
    }
    write_json(out / "aggregate.json", summary, exclusive=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "control-dir", "variant-dir", "service", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--control-receipt-sha256", required=True)
    parser.add_argument("--service-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = compare(args.base, args.control_dir, args.control_receipt_sha256, args.variant_dir,
                         args.service, args.service_sha256, args.output_dir)
        print(canonical({"outcomes": result["variant"]["outcomes"], "data": result["data"],
                         "aggregate_sha256": file_digest(args.output_dir / "aggregate.json")}))
    except (MatchingError, OSError, ValueError) as error:
        parser.exit(1, f"INVALID: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
