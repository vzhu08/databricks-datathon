"""Compare the November collector ledger and L's prior candidate edition by exact decision key."""
import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import SERVICES, canonical, require
from .collectors import HOT_SAMPLE, PIN as EARLIER_LEDGER, VOLUME, frozen_inputs, reconcile
from .hot import verified

NOVEMBER = "5c088cf8dcac51265c808b9b585bc3dee7eb62861d3b3d72753d440aac52b08a"
PRIOR = "243dcfb005e0fa8891914abebf9192d6994e1199ffc45df357df8a7109e97437"
NEW_LANE = "J_OSM_20261101"


def key(row):
    return row["occurrence_key"], row["service"]


def prior_rows(directory):
    raw = (directory / "manifest.json").read_bytes()
    require(sha256(raw).hexdigest() == PRIOR, "prior edition mismatch")
    manifest = json.loads(raw)
    require(manifest["collector_sha256"] == EARLIER_LEDGER and manifest["frozen_sample_sha256"] == HOT_SAMPLE,
            "prior inputs changed")
    for name, spec in manifest["files"].items():
        raw = (directory / name).read_bytes()
        require(len(raw) == spec["bytes"] and sha256(raw).hexdigest() == spec["sha256"], "prior member changed")
        if name == "candidate-decisions.jsonl":
            rows = [json.loads(line) for line in raw.splitlines()]
            require(len(rows) == spec["records"], "prior table count mismatch")
    return rows


def compare(prior, current):
    previous = {key(r): r for r in prior}
    require(len(previous) == len(prior) == len(current) and set(previous) == {key(r) for r in current},
            "decision frame changed")
    mixed, october, november, candidates = set(), set(), set(), set()
    for row in current:
        pair = key(row)
        old = previous[pair]
        earlier = [h for h in row["candidates"] if h["lane"] != NEW_LANE]
        require(earlier == old["candidates"], "earlier candidate evidence changed")
        require(all(row[k] == old[k] for k in ("status", "frozen_sample", "state")), "status, sample or state changed")
        if earlier:
            mixed.add(pair)
        if any(h["family"] == "osm" for h in earlier):
            october.add(pair)
        if any(h["lane"] == NEW_LANE for h in row["candidates"]):
            november.add(pair)
        if row["candidates"]:
            candidates.add(pair)
    delta = november - october
    union = mixed | delta
    require(union == candidates, "union differs from full collector reconstruction")
    sets = {"prior_mixed": mixed, "october_map": october, "november_map": november,
            "combined_map": october | november, "new_vs_october": delta,
            "new_vs_october_already_in_mixed": delta & mixed, "gain_vs_mixed": delta - mixed,
            "mixed_intersect_combined_map": mixed & (october | november), "union": union}
    return {name: {"total": len(pairs),
                   "by_service": {s: sum(service == s for _, service in pairs) for s in sorted(SERVICES)}}
            for name, pairs in sets.items()}


def run(ledger, previous, frozen, output):
    manifest, data = verified(ledger, NOVEMBER)
    old = prior_rows(previous)
    frame, plan = frozen_inputs(frozen)
    for name in ("occurrences.jsonl.gz", "decisions.jsonl.gz"):
        require(manifest["files"][name]["sha256"] == frame["input_hashes"][name], "base file changed")
    rows, summary = reconcile(data, data["decisions"], plan["sample"])
    partitions = compare(old, rows)
    by_service = {}
    for service in sorted(SERVICES):
        group = [r for r in rows if r["service"] == service]
        by_service[service] = {
            "decisions": len(group), "no_external_lead": sum(not r["candidates"] for r in group),
            "repeated_family": sum(len(r["candidates"]) > len({h["family"] for h in r["candidates"]}) for r in group),
            "multiple_families": sum(len({h["family"] for h in r["candidates"]}) > 1 for r in group),
            "status": dict(Counter(r["status"] for r in group))}
    geo = defaultdict(Counter)
    for row in rows:
        bucket = geo[row["state"], row["service"]]
        bucket["decisions"] += 1
        bucket["candidates"] += bool(row["candidates"])
        bucket["confirmed_yes_or_no"] += row["status"] in {"yes", "no"}
        bucket["unconfirmed"] += row["status"] == "unconfirmed"
    summary["state_service"] = [dict(state=state, service=service, **counts)
                                for (state, service), counts in sorted(geo.items())]
    summary.update(key_comparison=partitions, by_service=by_service, observations=len(data["observations"]),
                   population=manifest["population"], sampled=sum(r["frozen_sample"] for r in rows),
                   unknown_geography_occurrences=len({r["occurrence_key"] for r in rows if r["state"].startswith("(")}),
                   vf_wording_overlap_for_this_union=None, completed_human_reviews=0, adjudicated=0)
    require(not output.exists(), "destination exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / "edition"
        stage.mkdir()
        files = {}
        for name, raw, count in (("coverage.json", canonical(summary) + b"\n", 1),
                                 ("candidate-decisions.jsonl", b"".join(canonical(r) + b"\n" for r in rows), len(rows))):
            (stage / name).write_bytes(raw)
            files[name] = dict(records=count, bytes=len(raw), sha256=sha256(raw).hexdigest())
        receipt = dict(edition="service-l-final-union-v1", files=files, publisher="Datathon Developer L",
                       inputs={"november": VOLUME+"service-ledger-163-november-osm-v1-"+NOVEMBER+"/manifest.json",
                               "prior": VOLUME+"service-l-collectors-v1-"+PRIOR+"/manifest.json",
                               "frozen_sample": VOLUME+"service-l-hot-partial-v1-"+HOT_SAMPLE+"/manifest.json"},
                       rights="Private four-reader team. Restricted VF derivative. OpenStreetMap contributors, HOT/Geofabrik, ODbL. See linked inputs for source terms.",
                       grain="original occurrence and service", join_fields=["occurrence_key","service","ledger_id"])
        (stage / "manifest.json").write_bytes(canonical(receipt) + b"\n")
        stage.rename(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("ledger", "previous", "frozen", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    run(args.ledger, args.previous, args.frozen, args.output)
