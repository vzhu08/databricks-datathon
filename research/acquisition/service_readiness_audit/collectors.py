"""Reconcile D's pinned collector ledger with the frozen HOT sample, without labels."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import SERVICES, canonical, require
from .hot import verified

PIN = "191fbfae50f42c32e14faacf064d7b72bcc67b83b62b7f61f850d4e477cc2fa8"
HOT_SAMPLE = "e87f1dc3d46e7e1cf4a47d19112e8811016782824ccbb8bdc3acb6ab858e9d71"
VOLUME = "dbfs:/Volumes/workspace/datathon_acquisition/matching_inputs/"
LEXICAL = {"dialysis": "dialysis", "mri": "mri", "trauma": "trauma_care"}


def frozen_inputs(directory):
    raw = (directory / "manifest.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == HOT_SAMPLE, "wrong HOT sample edition")
    member = json.loads(raw)["files"]
    # Read only the two design artifacts. Reviewer files are never inputs.
    def read(name):
        data = (directory / name).read_bytes()
        require(hashlib.sha256(data).hexdigest() == member[name]["sha256"], "frozen member changed")
        return json.loads(data)
    return read("partial-frame.json"), read("plan.json")


def services(raw, lane):
    if lane == "NHP_181":
        require(raw["modality"] == "directory_field", "unexpected NHP modality")
        record = raw["source_record"]
        if record["withheld_for_contact_pattern"]:
            return {}
        return {LEXICAL[t]: "directory_term" for t in record["term_leads"] if t in LEXICAL}
    if raw["modality"] in SERVICES:
        return {raw["modality"]: raw["claim_type"]}
    return {}


def reconcile(data, decisions, sample):
    selected = {(r["occurrence_key"], r["service"]) for r in sample}
    by_key = {(r["occurrence_key"], r["service"]): r for r in decisions}
    require(len(by_key) == len(decisions) and selected <= by_key.keys(), "invalid frame keys")
    all_occ = {k for k, _ in by_key}
    observations = data["observations"]
    require(len({r["ledger_id"] for r in observations}) == len(observations), "duplicate ledger ID")
    lanes = {}
    hits = defaultdict(list)
    occ_lanes = defaultdict(set)
    for lane in sorted({r["lane"] for r in observations}):
        rows = [r for r in observations if r["lane"] == lane]
        linked, target, linked_target, sampled, campus_refs = set(), set(), set(), set(), set()
        applied = set()
        for r in rows:
            raw, mid = r["raw"], r["ledger_id"]
            mapped = services(raw, lane)
            if mapped:
                target.add(mid)
            for link in raw["target_links"]:
                occ = link["occurrence_key"]
                require(occ in all_occ and link["quality"] == "candidate" and link["campus_id"] is None,
                        "unexpected candidate relation in pinned edition")
                linked.add(mid)
                occ_lanes[occ].add(lane)
                for service, scope in sorted(mapped.items()):
                    pair = (occ, service)
                    require(pair in by_key, "missing decision")
                    linked_target.add(mid)
                    applied.add(pair)
                    if pair in selected:
                        sampled.add(mid)
                    hits[pair].append(dict(ledger_id=mid, lane=lane, family=r["source_family"],
                                           scope=scope, campus_quality=link["quality"]))
            if any(link["campus_id"] and link.get("review_reference") for link in raw["target_links"]):
                campus_refs.add(mid)
        lanes[lane] = dict(observations=len(rows), source_objects=len({r["raw"]["source_facility_id"] for r in rows}),
                           linked_observations=len(linked), unlinked_observations=len(rows)-len(linked),
                           candidate_occurrences=sum(lane in group for group in occ_lanes.values()),
                           target_service_observations=len(target), target_observations_with_candidate=len(linked_target),
                           target_candidate_decisions=len(applied), sample_candidate_decisions=len(applied & selected),
                           observations_represented_in_sample=len(sampled), observations_outside_sample=len(rows)-len(sampled),
                           origin_flags=dict(Counter(r["raw"]["independence_status"] for r in rows)),
                           reviewed_campus_observations=len(campus_refs))
    rows = []
    for pair, decision in sorted(by_key.items()):
        rows.append(dict(occurrence_key=pair[0], service=pair[1], state=decision["state"], status=decision["status"],
                         frozen_sample=pair in selected, candidates=sorted(hits.get(pair, []), key=lambda x:x["ledger_id"])))
    overlap = Counter(tuple(sorted(v)) for v in occ_lanes.values())
    families = defaultdict(set)
    for r in observations:
        families[r["source_family"]].add(r["lane"])
    shared = {family for family, names in families.items() if len(names)>1}
    summary = dict(lanes=lanes, source_families={k: sorted(v) for k,v in families.items()},
                   observations_in_families_shared_between_lanes=sum(r["source_family"] in shared for r in observations),
                   occurrence_overlap=[dict(lanes=list(k), occurrences=v) for k,v in sorted(overlap.items())],
                   candidate_occurrences_any_modality=len(occ_lanes), candidate_decisions=len(hits),
                   no_candidate_decisions=len(rows)-len(hits), sample_candidate_decisions=len(selected & hits.keys()),
                   multiple_mention_same_family_decisions=sum(len(v)>len({h["family"] for h in v}) for v in hits.values()),
                   multiple_family_candidate_decisions=sum(len({h["family"] for h in v})>1 for v in hits.values()),
                   target_decisions_by_service=dict(Counter(k[1] for k in hits)),
                   decisions_by_status=dict(Counter(r["status"] for r in rows)), exact_duplicate_claim_rate=None,
                   independently_reviewed_onsite_decisions=0, supported_decision_transitions=0,
                   validated_accuracy=None, uncertain_cases=None, unreachable_cases=None)
    return rows, summary


def run(directory, frozen, output):
    manifest, data = verified(directory, PIN)
    old, plan = frozen_inputs(frozen)
    for name in ("occurrences.jsonl.gz", "decisions.jsonl.gz"):
        require(manifest["files"][name]["sha256"] == old["input_hashes"][name], "HOT population changed")
    keys = {r["original"]["facility_id"] for r in data["occurrences"]}
    require(len(keys) == 10088 and len(data["decisions"]) == 30264, "wrong population")
    rows, summary = reconcile(data, data["decisions"], plan["sample"])
    require({(r["occurrence_key"],r["service"]) for r in rows} == {(k,s) for k in keys for s in SERVICES}, "incomplete decisions")
    # Compare occurrence/service keys, retaining geography and the original HOT assignment.
    hot_keys = {(r["occurrence_key"], r["service"]) for r in old["decisions"] if r["mentions"]}
    current = {(r["occurrence_key"], r["service"]) for r in rows if r["candidates"]}
    require(hot_keys == {(r["occurrence_key"], r["service"]) for r in rows
                         if any(h["family"] == "osm" for h in r["candidates"])}, "HOT candidate set changed")
    summary["added_candidate_decisions"] = len(current - hot_keys)
    additional = current - hot_keys
    geographic = defaultdict(Counter)
    for row in rows:
        bucket = geographic[row["state"], row["service"]]
        bucket["total"] += 1
        bucket["candidate"] += bool(row["candidates"])
        bucket["additional_vs_hot"] += (row["occurrence_key"], row["service"]) in additional
    summary["state_service"] = [dict(state=k[0], service=k[1], **v) for k,v in sorted(geographic.items())]
    require(sum(r["frozen_sample"] for r in rows)==30, "wrong sample")
    summary.update(population=manifest["population"], total_observations=len(data["observations"]),
                   frozen_sample=30, completed_human_reviews=0, adjudicated=0,
                   source_register=[{k:r[k] for k in ("issue","disposition","manifest_sha256","admitted_decision_transitions")}
                                    for r in data["source_register"]],
                   referenced_equipment_tables=next(r["verified_counts"] for r in data["source_register"] if r["issue"]==110))
    require(not output.exists(), "destination exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        dest=Path(tmp)/"edition"
        dest.mkdir()
        files={}
        for name, content, count in (("candidate-decisions.jsonl", b"".join(canonical(r)+b"\n" for r in rows),len(rows)),
                                     ("coverage.json",canonical(summary)+b"\n",1)):
            (dest/name).write_bytes(content)
            files[name]=dict(bytes=len(content),records=count,sha256=hashlib.sha256(content).hexdigest())
        record=dict(edition="service-l-collector-comparison-v1", publisher="Datathon Developer L", sharing_scope="private four-reader team",
                    source_manifest=VOLUME+"service-ledger-163-collectors-v1-"+PIN+"/manifest.json",
                    frozen_sample_manifest=VOLUME+"service-l-hot-partial-v1-"+HOT_SAMPLE+"/manifest.json",
                    collector_sha256=PIN,frozen_sample_sha256=HOT_SAMPLE,files=files,grain="original occurrence and service",
                    join_fields=["occurrence_key","service","ledger_id"],rights="Restricted VF derivative; source-specific terms in input editions; OpenStreetMap contributors, HOT/Geofabrik ODbL.")
        (dest/"manifest.json").write_bytes(canonical(record)+b"\n")
        dest.rename(output)
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("directory","frozen","output"):
        parser.add_argument(arg,type=Path)
    args=parser.parse_args()
    run(args.directory,args.frozen,args.output)
