"""Prepare a v1 identity envelope and aliases for the existing national matcher.

This does not admit the source to the approved registry, establish permission,
create service evidence, or confirm any campus. Rights-held inputs stay local.
"""
import argparse
import json
from pathlib import Path
from .extract import VERSION, dump


def prepare(records, config, artifact_uri):
    snapshot_id = f"esic:{config['sha256']}"
    batch = {"contract_version": "1.0.0", "source_snapshots": [{
        "snapshot_id": snapshot_id, "source_key": config["edition_id"],
        "publisher": config["publisher"], "source_family": config["source_family"],
        "url": config["url"], "retrieved_at": config["retrieved_at"],
        "published_date": config["publication_date"], "license": config["reuse_status"],
        "attribution": config["publisher"], "sha256": config["sha256"],
        "artifact_uri": artifact_uri, "parser_version": VERSION,
        "independence_status": "shared_origin"}], "external_facilities": [],
        "facility_matches": [], "facility_evidence": [], "review_queue": []}
    aliases = {}
    for row in records:
        batch["external_facilities"].append({
            "external_facility_id": row["record_id"], "snapshot_id": snapshot_id,
            "source_record_id": str(row["serial"]),
            "record_locator": json.dumps(row["locator"], sort_keys=True),
            "name_original": row["name_original"], "name_normalized": row["name_normalized"],
            "address_original": None, "facility_type": "hospital", "city": None,
            "state": row["state_normalized"], "pin": None, "latitude": None, "longitude": None,
            "coordinate_method": None,
            "quality_flags": ["campus_review_required", "address_not_printed", "pin_missing",
                              "coordinates_missing", "rights_hold", "historical_return"]})
        # ESIC is printed in the column header, while cells contain locality
        # names. The context-derived alias is kept apart from source wording.
        aliases[row["record_id"]] = {"aliases": [row["name_normalized"],
                                      "ESIC Hospital " + row["name_normalized"]]}
    return batch, aliases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--edition-dir", type=Path, required=True)
    p.add_argument("--artifact-uri", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):
        raise ValueError("Refusing to overwrite identity inputs")
    batch, aliases = prepare(json.loads((a.edition_dir / "records.json").read_text()),
                             json.loads((a.edition_dir / "edition.json").read_text()), a.artifact_uri)
    a.output.mkdir(parents=True, exist_ok=True)
    dump(a.output / "batch.json", batch)
    dump(a.output / "attributes.json", aliases)


if __name__ == "__main__":
    main()
