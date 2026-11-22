"""Prepare a partial national audit from D's immutable November HOT release."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import SERVICES, SCHEMA, build_plan, canonical, digest, require

PIN = "fb36db50b2685e58a7b98f1e0c4d3859153b56df817ca9d578a608c40fafcb08"
VOLUME = "dbfs:/Volumes/workspace/datathon_acquisition/matching_inputs/service-ledger-163-hot-v1-" + PIN
# Analytic grouping for this audit. Retain both original unknown-state categories.
REGIONS = {
    "north": "chandigarh|delhi|haryana|himachal pradesh|jammu and kashmir|ladakh|punjab|rajasthan|uttar pradesh|uttarakhand",
    "central": "chhattisgarh|madhya pradesh",
    "west": "dadra and nagar haveli and daman and diu|goa|gujarat|maharashtra",
    "east": "bihar|jharkhand|odisha|west bengal",
    "northeast": "arunachal pradesh|assam|manipur|meghalaya|mizoram|nagaland|sikkim|tripura",
    "south": "andaman and nicobar islands|andhra pradesh|karnataka|kerala|lakshadweep|puducherry|tamil nadu|telangana",
}
REGION = {s: region for region, states in REGIONS.items() for s in states.split("|")}


def verified(directory, expected_pin=PIN):
    raw = (directory / "manifest.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected_pin, "unexpected ledger release")
    manifest = json.loads(raw)
    data = {}
    for name, spec in manifest["files"].items():
        raw = (directory / name).read_bytes()
        require(len(raw) == spec["bytes"] and hashlib.sha256(raw).hexdigest() == spec["sha256"], f"invalid {name}")
        if name.endswith(".gz"):
            rows = [json.loads(line) for line in gzip.decompress(raw).splitlines()]
            require(len(rows) == spec["records"], f"row count mismatch in {name}")
            data[name.split(".")[0]] = rows
    return manifest, data


def adapt(manifest, data):
    identity, payloads = {}, []
    for i, row in enumerate(data["occurrences"]):
        ident, original = row["identity"], row["original"]
        key = original["facility_id"]
        payload = original["source_row"]
        require(key == ident["facility_id"] and key not in identity and i == ident["input_ordinal_zero_based"], "occurrence mismatch")
        require(payload["unique_id"] == ident["original_upstream_id"] and digest(payload) == ident["original_payload_sha256"], "payload changed")
        identity[key] = ident
        payloads.append(payload)
    multiset = digest(sorted(payloads, key=canonical))
    require(multiset == manifest["population"]["original_payload_multiset_sha256"], "multiset mismatch")
    decisions = {}
    for source in data["decisions"]:
        key, service = source["occurrence_key"], source["service"]
        ident = identity[key]
        state = ident["state"]
        require(source["state"] == state and (key, service) not in decisions, "decision identity mismatch")
        decisions[key, service] = dict(occurrence_key=key, service=service, source_id=ident["original_upstream_id"],
                                       state=state, region=REGION.get(state), status=source["status"], mentions=[],
                                       conflict=None, independent_origin_ids=None)
    counts = Counter()
    targets = set()
    all_links = set()
    ids = set()
    for obs in data["observations"]:
        raw = obs["raw"]
        mid = obs["ledger_id"]
        require(mid not in ids and obs["source_family"] == "osm" and raw["independence_status"] == "shared_origin", "unsupported origin or duplicate")
        ids.add(mid)
        counts["original_locators"] += len(raw["locator"]["all_original_locators"])
        counts["linked_observations" if raw["target_links"] else "unlinked_observations"] += 1
        for link in raw["target_links"]:
            key, service = link["occurrence_key"], raw["modality"]
            require(key in identity and link["quality"] == "candidate" and link["campus_id"] is None, "unsupported campus link")
            all_links.add((key, service))
            if service in SERVICES:
                # ledger_id resolves all raw attributes, original locators and links in the pinned input.
                decisions[key, service]["mentions"].append(dict(mention_id=mid, origin_id="osm", claimant_id=None,
                    campus_id=None, observation_id=raw["observation_id"], observed_on=raw["source_date"],
                    claim_type=raw["claim_type"], campus_quality=link["quality"]))
                if raw["claim_type"] == "map_explicit_service_tag":
                    targets.add((key, service))
    counts.update(source_observations=len(ids), all_modality_candidate_pairs=len(all_links))
    frame = dict(schema=SCHEMA, freeze_sha256=PIN, original_payload_multiset_sha256=multiset,
                 input_hashes={k: v["sha256"] for k, v in manifest["files"].items()}, decisions=list(decisions.values()))
    return frame, dict(counts), {s: sum(service == s for _, service in targets) for s in sorted(SERVICES)}


def run(directory, output):
    manifest, data = verified(directory)
    frame, inventory, exact = adapt(manifest, data)
    plan, forms = build_plan(frame, as_of="2026-11-21", hot_partial=True)
    summary = dict(denominator=plan["denominator"], coverage=plan["coverage"], inventory=inventory,
                   exact_tag_candidate_pairs=exact, sample_size=len(forms), strata=plan["strata"],
                   unavailable=["independent corroboration", "comparable conflicts", "service-effective dates",
                                "verified claimant multiplicity", "approved campus matches", "original statement spans"],
                   completed_reviews=0, adjudicated=0, uncertain=None, unreachable=None, validated_accuracy=None)
    files = {"partial-frame.json": frame, "plan.json": plan, "reviewer-1.json": forms, "reviewer-2.json": forms, "summary.json": summary}
    output.parent.mkdir(parents=True, exist_ok=True)
    require(not output.exists(), "destination exists")
    with TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / "edition"
        stage.mkdir()
        specs = {}
        for name, value in files.items():
            raw = canonical(value) + b"\n"
            (stage / name).write_bytes(raw)
            specs[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        receipt = dict(edition="service-l-hot-partial-v1", publisher="Datathon Developer L", files=specs,
                       source_manifest=VOLUME + "/manifest.json", freeze_sha256=PIN, sharing_scope="private four-reader team",
                       rights="Restricted VF derivative. OpenStreetMap contributors, HOT/Geofabrik, ODbL-1.0.",
                       join_fields=["occurrence_key", "service", "mention_id -> ledger_id"], population=plan["denominator"],
                       observation_count=inventory["source_observations"], sample_count=len(forms), assessed_for=plan["as_of"])
        (stage / "manifest.json").write_bytes(canonical(receipt) + b"\n")
        stage.rename(output)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.ledger, args.output), sort_keys=True))
