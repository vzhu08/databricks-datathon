"""Build the scoped B3 fallback and national overlap receipt for #270."""

import argparse
from datetime import datetime
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from . import audit, core, feeds, random_audit, targeted

EDITION = "issue-270-b3-fallback-and-rollup-v1"


def publishable_receipts(file, sha256):
    if file is None:
        return None
    content = core.read(file, sha256)
    core.need(set(content) == {"directory_v4_local_sha256", "occurrences", "as_of_utc", "inputs"}
              and content["directory_v4_local_sha256"] == core.V4 and content["occurrences"] == 10088,
              "aggregate citation file uses a different original frame or schema")
    cut = datetime.fromisoformat(content["as_of_utc"])
    core.need(cut.tzinfo is not None, "aggregate citation file needs an observation timezone")
    fields = {"method", "receipt", "unit", "exact_cohort_overlap_measured", "counts"}
    labels = {"B1_I", "C", "A_J", "H", "K", "L", "F", "D", "C_chain_stratum"}
    seen = set()
    for entry in content["inputs"]:
        name = entry["method"]
        core.need(set(entry) == fields and name in labels and name not in seen and
                  type(entry["exact_cohort_overlap_measured"]) is bool, "unsupported receipt shape")
        core.need(re.fullmatch(r"https://github\.com/vzhu08/databricks-datathon/issues/[0-9]+#issuecomment-[0-9]+",
                              entry["receipt"]) and entry["unit"] in
                  {"original_occurrences", "proxy_originals", "purposive_controls", "method_slots", "synthetic_cases"},
                  "unsupported receipt source or unit")
        core.need(all(re.fullmatch("[a-z][a-z0-9_]*", k) and (n is None or type(n) is int and n >= 0)
                      for k, n in entry["counts"].items()), "only aggregate counts are shareable")
        seen.add(name)
    return {**content, "receipt_file_sha256": sha256}


def random_receipt(arguments):
    if not arguments:
        return None
    path, digest = arguments
    value = core.read(Path(path), digest)
    expected = {"seed": random_audit.SEED, "frame_sha256": random_audit.FRAME_SHA,
                "directory_v4_local_sha256": core.V4,
                "prior_stratified_commitment_sha256": random_audit.STRATIFIED_SHA}
    core.need(all(value[k] == v for k, v in expected.items()) and
              value["eligible_original_occurrences"] == 7418 and value["selected_original_occurrences"] == 60 and
              len(value["commitment_sha256"]) == 64 and sum(value["review_dispositions"].values()) == 60,
              "separate random audit receipt does not match the precommitted design")
    return {k: value[k] for k in (*expected, "selection_rule", "commitment_sha256", "eligible_original_occurrences",
                                  "selected_original_occurrences", "distinct_selected_payloads",
                                  "complete_selected_identical_pairs", "reference_material", "review_dispositions")}


def build(args):
    targets = (args.private, args.aggregate)
    core.need(not any(t.exists() for t in targets), "run output already exists")
    core.need(args.measure_sample_coverage is None or not args.measure_sample_coverage.exists(),
              "the coverage check already has a committed aggregate")
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
    receipts = publishable_receipts(
        Path(args.receipts[0]) if args.receipts else None, args.receipts[1] if args.receipts else None)
    frame, input_pins = core.load(args.nationwide)
    summary = core.aggregate(frame)

    with TemporaryDirectory(dir=args.private.parent) as working, TemporaryDirectory(dir=args.aggregate.parent) as release:
        private = Path(working) / "rows"
        share = Path(release) / "edition"
        private.mkdir()
        share.mkdir()

        lock = audit.lock(frame, args.secret, private, args.strata)
        j_signals, j_report = feeds.geometry(frame, args.clinical, args.buildings)
        g_leads, g_report = feeds.rural(frame, args.rural)
        a_leads, a_report = targeted.address(frame, args.nationwide, args.address)
        h_leads, h_report = targeted.arrival(frame, args.nationwide, args.arrival)
        linked, candidate_union = feeds.overlap(frame, j_signals, g_leads, {
            "a_nabh_address_shortlist": a_leads, "h_nhp_name_pin_lead": h_leads,
        })
        random_summary = random_receipt(args.random_receipt)
        if args.measure_sample_coverage or args.sample_coverage:
            core.need(random_summary is not None, "sample coverage requires the frozen random receipt")
            commitment = random_summary["commitment_sha256"]
            union_count = linked["unique_originals_with_at_least_one_of_these_flags"]
            core.need(union_count == 2490, "locked coverage must use the exact five-flag 2,490 union")
            if args.measure_sample_coverage:
                choice = Path(args.random_receipt[0]).with_name("private-random-selection.json")
                coverage = audit.coverage(frame, args.secret, choice, commitment, candidate_union, linked["across_keyed_feeds"])
                coverage["random_commitment_sha256"] = commitment
                coverage["union_originals"] = union_count
                with args.measure_sample_coverage.open("xb") as file:
                    file.write(core.encode(coverage) + b"\n")
            else:
                path, sha = args.sample_coverage
                coverage = core.read(Path(path), sha)
            core.need(coverage["random_commitment_sha256"] == commitment and coverage["union_originals"] == union_count
                      and coverage["with_any_of_five_frozen_flags"] + coverage["with_none_of_five_frozen_flags"] == 60,
                      "verified coverage receipt differs from the locked draw or union")
            random_summary["candidate_flag_coverage"] = coverage
        edition = EDITION
        summary.update(edition=edition,
                       scope="National area evidence and duplicate-safe candidate overlap in existing Windows custody",
                       candidate_inputs={"j_geometry": j_report, "g_b2_rural": g_report,
                                         "a_address": a_report, "h_arrival": h_report},
                       candidate_overlap=linked, blinded_sampling=lock, separate_random_audit=random_summary,
                       exact_site_gate={
                           "new_independently_reviewed_buildings_in_admitted_rows": 0,
                           "new_independently_reviewed_entrances_in_admitted_rows": 0,
                           "independently_reviewed_truth_on_full_area_cohort": None,
                           "wrong_branch_rate": None,
                           "area_rows_remain_area_only_under_admitted_feeds": 7418,
                           "notes": "The original area fields cannot supply a building or entrance. D owns independently adjudicated results.",
                       },
                       receipt_only_feeds=receipts)
        files = {
            "area-fallback.jsonl": core.write_rows(private / "area-fallback.jsonl", frame.values()),
            "blinded-area-frame.jsonl": {**core.pin(private / "blinded-area-frame.jsonl"), "records": 7418},
            "private-selection.json": {**core.pin(private / "private-selection.json"), "records": 1},
        }
        core.write_json(share / "aggregate.json", summary)
        core.write_json(share / "manifest.json", {
            "edition": edition, "issue": core.ISSUE,
            "share_scope": "Aggregate report and manifest for Vincent, Oliver, Andrew and Ayush in existing private intake.",
            "inputs": input_pins,
            "candidate_input_manifests": {"J clinical": feeds.CLINICAL_PIN,
                                          "J all buildings": feeds.BUILDINGS_PIN, "G/B2 rural": feeds.RURAL_PIN,
                                          "A address": targeted.ADDRESS_PIN, "H arrival": targeted.ARRIVAL_PIN},
            "sampling_commitment": lock["commitment_sha256"],
            "random_audit_aggregate_sha256": args.random_receipt[1] if random_summary else None,
            "random_sample_coverage_sha256": (core.pin(args.measure_sample_coverage)["sha256"]
                                              if args.measure_sample_coverage else
                                              args.sample_coverage[1] if args.sample_coverage else None),
            "working_member_pins": files,
            "workspace_only": "Directory labels and keys, keyed candidate joins, opaque frame, selection and secret stay with the Windows custodian.",
            "source_grains": {"national": "original occurrence and frozen occurrence/service decisions",
                             "fallback": "original occurrence and smallest supported retained area evidence",
                             "sampling": "area-only original occurrence, with selection by unique payload group",
                             "candidate_union": "original occurrence present in expressly keyed research screens"},
            "builder_files": {p.name: core.pin(p) for p in (Path(__file__), Path(core.__file__),
                                                             Path(audit.__file__), Path(feeds.__file__),
                                                             Path(targeted.__file__), Path(random_audit.__file__))},
            "files": {"aggregate.json": {**core.pin(share / "aggregate.json"), "records": 1}},
        })
        private.rename(args.private)
        share.rename(args.aggregate)
    return {"fallback": summary["fallback"]["by_precision"], "overlap": linked, "blinded_sampling": lock,
            "sample_coverage": random_summary.get("candidate_flag_coverage") if random_summary else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("nationwide", "clinical", "buildings", "rural", "address", "arrival", "secret", "private", "aggregate"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--random-receipt", nargs=2, metavar=("AGGREGATE_COMMITMENT", "SHA256"))
    coverage = parser.add_mutually_exclusive_group()
    coverage.add_argument("--measure-sample-coverage", type=Path)
    coverage.add_argument("--sample-coverage", nargs=2, metavar=("AGGREGATE_COVERAGE", "SHA256"))
    parser.add_argument("--strata", nargs=2, metavar=("AUTHORIZED_INPUT", "SHA256"))
    parser.add_argument("--receipts", nargs=2, metavar=("AGGREGATE_CITATIONS", "SHA256"))
    args = parser.parse_args()
    if args.strata:
        args.strata = Path(args.strata[0]), args.strata[1]
    print(build(args))


if __name__ == "__main__":
    main()
