"""Run the pinned national baseline and produce private rows and eligible aggregates."""

import argparse
from collections import Counter
import json
from itertools import combinations
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

from research.matching.common import canonical, file_digest
from research.matching.national import NO_STATE, NOT_A_STATE, STATES

from . import inputs, model, peer_methods
from .judges import pin, write

ISSUE = f"{inputs.ISSUES}/239"
EDITION = "issue-239-national-facility-baseline-v1"
AUDIENCE = "Four named Datathon research readers in the private intake"
METHOD_RECEIPTS = {
    "operator_source_first": f"{inputs.ISSUES}/232#issuecomment-7076268874",
    "equipment_source_first": f"{inputs.ISSUES}/233#issuecomment-7076273611",
    "campus_geometry": f"{inputs.ISSUES}/234",
    "address_method": f"{inputs.ISSUES}/235#issuecomment-7076286644",
    "branch_website": f"{inputs.ISSUES}/241",
}
AREA_CONTEXT = {"compatible_label_and_postal_area", "postal_area_only"}


def write_rows(path, rows):
    count = 0
    with path.open("wb") as stream:
        for row in rows:
            stream.write((canonical(row) + "\n").encode("utf-8"))
            count += 1
    return {**pin(path), "records": count}


def combined_status(forward, key):
    candidates = [candidate for outcome in forward for candidate in outcome[key]["candidates"]]
    premises = {row["premises_id"] for row in candidates}
    if not premises:
        return "unmatched"
    if len(premises) == 1 and any(o[key]["status"] == "exact" for o in forward):
        if not any(row["conflicts"] for row in candidates):
            return "exact"
    return "ambiguous"


def method_summary(batch, forward, reverse):
    result = {
        "inventory": batch.inventory, "evidence": model.source_counts([batch]),
        "occurrence_dispositions": model.disposition_counts(forward.values()),
        "source_premises_dispositions": model.disposition_counts(reverse.values()),
        "candidate_associations": len(batch.links),
        "conflict_associations": sum(bool(r["conflicts"]) for r in batch.links),
        "source_only_comparable_premises": sum(r["status"] == "unmatched" for r in reverse.values()),
    }
    return result


def summarize(originals, contexts, batches, by_method, postal_profile):
    upstream = Counter(r["upstream_id"] for r in originals.values())
    duplicates = Counter(upstream.values())
    model.need(len(upstream) == 10077 and duplicates == {1: 10066, 2: 11}, "upstream duplicates changed")
    payloads_by_id = {}
    for row in originals.values():
        key, payload = row["upstream_id"], row["payload_sha256"]
        model.need(payloads_by_id.setdefault(key, payload) == payload, "duplicate upstream ID payload differs")
    methods = {b.method: method_summary(b, *by_method[b.method]) for b in batches}
    for b in batches:
        forward, reverse = by_method[b.method]
        model.need(sum(methods[b.method]["occurrence_dispositions"].values()) == 10088, "forward margin changed")
        model.need(sum(methods[b.method]["source_premises_dispositions"].values()) == len(reverse), "reverse margin changed")
        model.need(sum(len(r["candidates"]) for r in forward.values()) == len(b.links)
                   == sum(len(r["candidates"]) for r in reverse.values()), "candidate cardinality changed")
    pilot = methods["nabh_strict_printed_premises"]
    model.need(pilot["occurrence_dispositions"] == dict(exact=0, ambiguous=0, unmatched=10088, unresolved_before_comparison=0)
               and pilot["source_premises_dispositions"] == dict(exact=0, ambiguous=0, unmatched=47, unresolved_before_comparison=2),
               "#221 margins did not reproduce")

    forward = [values[0] for values in by_method.values()]
    reverse = [values[1] for values in by_method.values()]
    seen_source_sites = {site for method in reverse for site in method}
    source_only = {site for site in seen_source_sites if all(
        site not in table or table[site]["status"] == "unmatched" for table in reverse)}
    unresolved_sites = {site for table in reverse for site, row in table.items()
                        if row["status"] == "unresolved_before_comparison"}
    union = {key: combined_status(forward, key) for key in originals}
    areas = {key for key, r in contexts.items() if r["status"] in AREA_CONTEXT}
    reached = {name: {key for key, r in table.items() if r["candidates"]}
               for name, (table, _) in by_method.items()}
    active = set().union(*reached.values())
    geography = {state: [] for state in sorted(STATES | {NO_STATE, NOT_A_STATE})}
    for key, row in originals.items():
        geography[row["state"]].append(key)
    by_state = []
    for state, keys in geography.items():
        by_state.append({
            "state_or_unknown": state,
            "original_occurrences": len(keys),
            "baseline_decisions_unconfirmed_by_service": dict.fromkeys(model.SERVICES, len(keys)),
            "combined_premises_dispositions": dict(Counter(union[key] for key in keys)),
            "source_or_method_candidate_occurrences": {name: sum(key in found for key in keys) for name, found in reached.items()},
            "postal_context_dispositions": dict(Counter(contexts[key]["status"] for key in keys)),
        })
    model.need(sum(len(geography[s]) for s in (NO_STATE, NOT_A_STATE)) == 448, "unknown geography margin changed")
    model.need(len(by_state) == 38 and sum(r["original_occurrences"] for r in by_state) == 10088,
               "state/UT rollup changed")

    for method, keys in reached.items():
        others = set().union(*(value for name, value in reached.items() if name != method))
        sites = {link["premises_id"] for b in batches if b.method == method for link in b.links}
        other_sites = {link["premises_id"] for b in batches if b.method != method for link in b.links}
        methods[method]["coverage"] = {
            "occurrences_reached": len(keys), "occurrences_reached_only_by_this_method": len(keys - others),
            "occurrences_also_reached_by_another_premises_method": len(keys & others),
            "occurrences_also_with_postal_area_context": len(keys & areas),
            "premises_hypotheses_reached": len(sites),
            "same_premises_identifier_elsewhere": len(sites & other_sites),
        }

    aggregate = {
        "edition": EDITION,
        "population": {"original_occurrences": len(originals), "distinct_upstream_ids": len(upstream),
                       "identical_upstream_pairs": duplicates[2], "unknown_geography_occurrences": 448,
                       "state_ut_buckets": 36, "unknown_buckets": 2,
                       "baseline_unconfirmed_by_service": dict.fromkeys(model.SERVICES, len(originals)),
                       "frozen_decisions": len(originals) * len(model.SERVICES), "decision_transitions": 0},
        "postal_geography_only": {"source_inventory": postal_profile,
                                  "occurrence_dispositions": dict(Counter(r["status"] for r in contexts.values())),
                                  "with_usable_area_context": len(areas),
                                  "area_context_without_premises_candidate": len(areas - active)},
        "methods": methods,
        "combined": {
            "occurrence_dispositions": model.disposition_counts({"status": status} for status in union.values()),
            "evidence": model.source_counts(batches),
            "source_premises_hypotheses_linked_at_any_method": len({r["premises_id"] for b in batches for r in b.links}),
            "source_only_comparable_premises": len(source_only),
            "source_hypotheses_need_comparable_fields": len(unresolved_sites),
            "candidate_overlap": [{"methods": [a, b], "occurrences": len(reached[a] & reached[b])}
                                  for a, b in combinations(reached, 2)],
            "premises_without_cross_source_entity_merge": True,
        },
        "by_original_state_ut_unknown": by_state,
        "other_method_receipts": METHOD_RECEIPTS,
        "evaluation": {
            "natural_ground_truth_pairs": 0, "national_physical_premises_accuracy": None,
            "national_service_accuracy": None, "sealed_audit_inputs": 0,
            "source_only_definition": "A comparable source premise with no VF edge under the included rules. Actual national overlap is unmeasured.",
            "independent_site_definition": "Reviewed identity with distinct civic or surveyed source families. Map display roles and area matches do not count.",
            "method_receipts_definition": "Separate operational receipts. Only an included, verified row packet contributes to this run's measured union.",
        },
    }
    model.need(sum(aggregate["combined"]["occurrence_dispositions"].values()) == 10088, "combined occurrence margin changed")
    return aggregate, union


def build(root, pilot, private_target, release_target, extensions=(), method_receipts=None):
    if private_target.exists() or release_target.exists():
        raise FileExistsError("Use new private and release directories for a new run")
    private_target.parent.mkdir(parents=True, exist_ok=True)
    release_target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=private_target.parent) as tmp, TemporaryDirectory(dir=release_target.parent) as stage:
        private = Path(tmp) / "rows"
        release = Path(stage) / "aggregate"
        private.mkdir()
        release.mkdir()
        inputs.replay_issuer(root, pilot, private / "replay-221")
        originals, decisions, frame_pin = inputs.frozen_frame(root)
        postal, contexts, postal_profile = inputs.postal_context(root, originals)
        issuer = inputs.issuer_batch(pilot, private / "replay-221", postal)
        batches = [issuer, inputs.operator_batch(root), inputs.equipment_batch(root, originals)]
        comparators = {}
        if method_receipts is not None:
            batches.append(peer_methods.address_comparison(root, pilot, method_receipts, private / "replay-a0", issuer))
            comparators = peer_methods.equipment_comparators(method_receipts)
        batches.extend(inputs.extension_batch(Path(path), digest) for path, digest in extensions)
        model.need(len({b.method for b in batches}) == len(batches), "duplicate method identifiers")
        by_method = {b.method: model.link_outcomes(b, originals) for b in batches}
        report, combined = summarize(originals, contexts, batches, by_method, postal_profile)
        report["aggregate_only_comparators"] = comparators

        payload_files = {
            name: write_rows(private / name, rows)
            for name, rows in {
                "vf-occurrences.jsonl": originals.values(),
                "postal-context.jsonl": contexts.values(),
                "source-records.jsonl": model.shared_index(batches, "records", "record_id").values(),
                "premises.jsonl": model.shared_index(batches, "premises", "premises_id").values(),
                "service-claims.jsonl": model.shared_index(batches, "claims", "claim_id").values(),
                "occurrence-links.jsonl": (
                    {"occurrence_key": key, "combined_status": combined[key],
                     "methods": {name: method[0][key] for name, method in by_method.items()}} for key in originals),
                "source-premises-links.jsonl": (
                    {"premises_id": key, "method": name, **r}
                    for name, (_, reverse) in by_method.items() for key, r in reverse.items()),
            }.items()
        }
        baseline = private / "baseline-decisions.jsonl.gz"
        shutil.copyfile(decisions, baseline)
        model.need(file_digest(baseline) == file_digest(decisions), "decisions must remain byte-identical")
        payload_files[baseline.name] = {**pin(baseline), "records": report["population"]["frozen_decisions"]}
        write(release / "aggregate.json", report)
        write(release / "manifest.json", {
            "edition": EDITION, "issue": ISSUE, "sharing_scope": AUDIENCE,
            "publisher": "Vincent, Datathon national evidence reconciliation",
            "grain": "National occurrence coverage, per-method source premises, source claims, geography and service margins",
            "join_fields_private": {"vf": ["occurrence_key", "original payload hash"],
                                    "source": ["source record ID", "premises ID", "claim ID", "producer locator"]},
            "inputs": {"frozen_vf": frame_pin, "postal": postal_profile,
                       "methods": {b.method: b.inventory for b in batches}, "aggregate_only_comparators": comparators},
            "custody": {
                "copied_to_this_edition": "Aggregate report and manifest. Owner readback is appended by the Volume writer.",
                "reused_team_rows": "Exact authorized VF/India Post Delta v0 and input editions referenced under inputs.",
                "producer_replay": "#221 method packet references are methods and aggregates. Private artifacts are regenerated and hash-checked.",
                "private_generated_files": payload_files,
                "private_disposition": "Working rows preserve upstream scope. New joined outputs remain private; this receipt does not stage or expand access to them.",
            },
            "checks": report["population"],
            "builder_files": {p.name: pin(p) for p in (Path(__file__), Path(inputs.__file__), Path(model.__file__), Path(peer_methods.__file__))},
            "files": {"aggregate.json": {**pin(release / "aggregate.json"), "records": 1}},
        })
        private.rename(private_target)
        release.rename(release_target)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="directory with the pinned local private prepared inputs")
    parser.add_argument("--pilot", type=Path, required=True, help="verified #221 method and aggregate package")
    parser.add_argument("--private-out", type=Path, required=True)
    parser.add_argument("--release-out", type=Path, required=True)
    parser.add_argument("--method-receipts", type=Path, help="directory with the verified A0 and K peer editions")
    parser.add_argument("--packet", nargs=2, action="append", default=[], metavar=("MANIFEST", "SHA256"))
    args = parser.parse_args()
    report = build(args.data_root.resolve(), args.pilot.resolve(),
                   args.private_out.resolve(), args.release_out.resolve(), args.packet, args.method_receipts)
    print(json.dumps({"population": report["population"], "combined": report["combined"],
                      "methods": {name: row["coverage"] for name, row in report["methods"].items()},
                      "postal": report["postal_geography_only"]["occurrence_dispositions"]}, sort_keys=True))


if __name__ == "__main__":
    main()
