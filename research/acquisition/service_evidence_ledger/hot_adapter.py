"""Read Developer J's pinned HOT packet and exact-ID frozen candidate trace.

This adapter performs no new matching, campus confirmation or service inference.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

from .ledger import canonical, lines, pinned, require, sha


def adapt_hot(manifest, source_rows, joint_rows, candidates):
    source = manifest["source_edition"]
    require(manifest["permitted_audience"] ==
            "four-person private research team; OSM-derived ledger remains ODbL-1.0", "unrecognized_hot_audience")
    require(len(source_rows) == manifest["ledger_observations"], "hot_observation_count_changed")
    by_representative = defaultdict(list)
    for row in joint_rows:
        by_representative[row["representative"]].append(row["facility_id"])
    object_ids = {r["osm_id"] for r in source_rows}
    candidate_links = defaultdict(dict)
    snapshot = "hot_osm_health:" + source["sha256"]
    for candidate in candidates:
        if (candidate["source_key"] != "hot_osm_health" or candidate["snapshot_id"] != snapshot or
                candidate["source_record_id"] not in object_ids or not candidate["runs"].get("joint")):
            continue
        representative = candidate["representative"]
        require(representative in by_representative, "candidate_representative_missing")
        for fid in by_representative[representative]:
            link = {"occurrence_key": fid, "campus_id": None, "quality": "candidate", "review_reference": None,
                    "frozen_candidate": candidate}
            previous = candidate_links[candidate["source_record_id"]].get(fid)
            require(previous is None or previous == link, "multiple_frozen_links_for_same_object")
            candidate_links[candidate["source_record_id"]][fid] = link
    edition_id = "hot-osm:" + source["sha256"]
    edition = {"edition_id": edition_id, "content_sha256": source["sha256"],
               "publisher": source["publisher"], "source_url": source["source_url"],
               "reuse_terms": manifest["attribution"] + "; ODbL-1.0; " + manifest["license_url"],
               "sharing_scope": "private_datathon_four_readers", "geographic_scope": "India national HOT/Geofabrik extract",
               "source_family": "osm", "origin_status": "known", "published_date": source["publication_date"],
               "retrieved_at": source["first_retrieved_at"], "source_manifest": manifest}
    observations = []
    for row in source_rows:
        require(row["edition_sha256"] == source["sha256"] and row["source_family"] == "osm" and
                row["independence"] == "shared_origin" and row["patient_status"] == "unconfirmed" and
                row["campus_id"] is None and row["facility_id"] is None, "hot_source_scope_changed")
        require(isinstance(row["locators"], list) and row["locators"], "hot_locators_missing")
        # Capture/extract/edit dates are deliberately not service-effective dates.
        require(row["service_observation_date"] is None and row["service_observed_date"] is None,
                "dated_hot_observation_needs_new_adapter")
        observations.append({"observation_id": row["observation_id"], "edition_id": edition_id,
                             "source_facility_id": row["osm_id"], "modality": row["service"],
                             "claim_type": "map_" + row["category"], "claim_scope": row["source_key"],
                             "claim_value": row["raw_value"], "units": None, "raw_text": row["raw_value"],
                             "locator": {"source_key": row["source_key"], "all_original_locators": row["locators"],
                                         "payload_sha256": row["payload_sha256"]},
                             "original_occurrence_key": None, "source_date": None,
                             "effective_from": None, "effective_until": None,
                             "polarity": "inconclusive", "independence_status": "shared_origin",
                             "multi_campus": False, "mirror_of": [], "supersedes": [],
                             "target_links": [v for _, v in sorted(candidate_links[row["osm_id"]].items())],
                             "source_record": row})
    return {"schema_version": "service-evidence-lane-v1", "lane": "J_HOT_20261009_v2",
            "editions": [edition], "observations": observations}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--packet", type=Path, required=True)
    cli.add_argument("--packet-sha256", required=True)
    cli.add_argument("--intake-manifest", type=Path, required=True)
    cli.add_argument("--intake-sha256", required=True)
    cli.add_argument("--joint-dir", type=Path, required=True)
    cli.add_argument("--out", type=Path, required=True)
    args = cli.parse_args()
    manifest = json.loads(pinned(args.packet / "manifest.json", args.packet_sha256))
    for name, meta in manifest["files"].items():
        require(Path(name).name == name, "unsafe_input_member")
        require(len(pinned(args.packet / name, meta["sha256"])) == meta["bytes"], "input_size_mismatch")
    intake = json.loads(pinned(args.intake_manifest, args.intake_sha256))
    joint_source = next(d for d in intake["datasets"] if d["id"] == "vf-joint-matching")
    for name in ("candidate-delta.jsonl.gz", "occurrence-delta.jsonl.gz"):
        meta = joint_source["file"]["members"][name]
        require(len(pinned(args.joint_dir / name, meta["sha256"])) == meta["bytes"], "input_size_mismatch")
    with gzip.open(args.joint_dir / "candidate-delta.jsonl.gz", "rt", encoding="utf-8") as stream:
        package = adapt_hot(manifest, lines(args.packet / "ledger.jsonl"),
                            lines(args.joint_dir / "occurrence-delta.jsonl.gz"), (json.loads(s) for s in stream))
    if args.packet_sha256 == "77039f8135e104fa22d56fa90de155678bc2c83e0e776404ac88a35d219eae1f":
        package["lane"] = "J_HOT_20261009_v3"
    elif args.packet_sha256 != "f8b21b0396a06417178f45ba1381b64767766a4a4eb920dbb6676b9aae8a68a4":
        raise ValueError("unrecognized_hot_packet")
    package["editions"][0]["adapter_inputs"] = {
        "packet_manifest_sha256": args.packet_sha256, "intake_manifest_sha256": args.intake_sha256,
        "joint_archive": joint_source["file"], "adapter_code_sha256": sha(Path(__file__).read_bytes())}
    data = canonical(package) + b"\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        require(args.out.read_bytes() == data, "adapter_output_already_exists_changed_bytes")
    else:
        args.out.write_bytes(data)
    print(json.dumps({"sha256": sha(data), "observations": len(package["observations"]),
                      "retained_locators": sum(len(o["source_record"]["locators"]) for o in package["observations"]),
                      "linked_observations": sum(bool(o["target_links"]) for o in package["observations"])}))


if __name__ == "__main__":
    main()
