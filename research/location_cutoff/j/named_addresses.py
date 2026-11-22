"""Check the structured addresses of exact-name buildings that actually contain VF points."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import osmium

from research.acquisition.issuer_campus_geometry.compare import BASELINE_PINS, address_matches, pin_from
from research.acquisition.issuer_campus_geometry.scan import PBF_SHA
from research.acquisition.osm_services.pbf import file_digest
from .compare import printed_address

BUILDINGS_SHA = "4c0e760645ec4adeef1519c2524bce55124ad86767bba9de80f80d34feb093af"


def check(vf, pbf, buildings):
    for path, pin in ((vf, BASELINE_PINS["occurrences.jsonl.gz"]), (pbf, PBF_SHA), (buildings, BUILDINGS_SHA)):
        if file_digest(path) != pin:
            raise ValueError(f"Unexpected input edition for {path.name}")
    selected = {}
    with buildings.open() as stream:
        for row in map(json.loads, stream):
            matches = [b["id"] for b in row["buildings"] if b["interior"] and b["exact_name"]]
            if matches:
                selected[row["occurrence_key"]] = matches
    wanted = {obj for ids in selected.values() for obj in ids}
    tags = {}
    objects = osmium.FileProcessor(pbf, osmium.osm.WAY | osmium.osm.RELATION)
    objects.with_filter(osmium.filter.IdFilter({int(key.split("/")[1]) for key in wanted}))
    for obj in objects:
        kind = "way" if obj.is_way() else "relation"
        key = f"{kind}/{obj.id}"
        if key in wanted:
            tags[key] = dict(obj.tags)
    if tags.keys() != wanted:
        raise ValueError("Incomplete exact-name building readback")
    counts = Counter()
    with gzip.open(vf, "rt") as stream:
        for row in map(json.loads, stream):
            key = row["identity"]["facility_id"]
            if key not in selected:
                continue
            address = printed_address(row["original"]["source_row"])
            choices = [tags[obj] for obj in selected[key]]
            counts.update({
                "originals": 1,
                "mapped_postcode": any(t.get("addr:postcode") or pin_from(t.get("addr:full")) for t in choices),
                "mapped_full_or_house_and_street": any(t.get("addr:full") or
                    (t.get("addr:housenumber") and t.get("addr:street")) for t in choices),
                "structured_address_agrees": any(address_matches(address, t) for t in choices),
                "mapped_source_tag": any(t.get("source") for t in choices),
            })
    return {"counts": dict(counts), "distinct_typed_outlines": len(wanted), "pbf_sha256": PBF_SHA}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("vf", "pbf", "buildings"):
        parser.add_argument(item, type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.vf, args.pbf, args.buildings), sort_keys=True, indent=2))
