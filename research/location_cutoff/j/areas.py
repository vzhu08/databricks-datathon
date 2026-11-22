"""Extract closed clinical site and medical-building outlines from the pinned India PBF."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import osmium
from shapely import from_wkb

from research.acquisition.issuer_campus_geometry.scan import PBF_SHA
from research.acquisition.osm_services.pbf import file_digest

CLINICAL = ("hospital", "clinic", "doctors", "health_centre", "health_center")
TAGS = tuple((key, value) for key in ("amenity", "healthcare") for value in CLINICAL) + (
    ("building", "hospital"), ("building", "clinic"), ("building", "healthcare"),
)
FIELDS = {
    "building", "amenity", "healthcare", "name", "name:en", "official_name", "alt_name",
    "addr:postcode", "addr:housenumber", "addr:street", "addr:full", "source", "source:date",
}


def extract(pbf, output):
    if file_digest(pbf) != PBF_SHA:
        raise ValueError("Unexpected India PBF edition")
    factory = osmium.geom.WKBFactory()
    with TemporaryDirectory(dir=output.parent) as temp:
        cache = Path(temp) / "node-locations"
        reader = osmium.FileProcessor(pbf).with_locations(f"sparse_file_array,{cache}")
        reader.with_areas(osmium.filter.TagFilter(*TAGS)).with_filter(osmium.filter.TagFilter(*TAGS))
        result = Path(temp) / "outlines.jsonl"
        with result.open("w") as stream:
            for obj in reader:
                if not obj.is_area():
                    continue
                try:
                    geometry = factory.create_multipolygon(obj)
                except RuntimeError:
                    geometry = None
                if geometry and not from_wkb(geometry).is_valid:
                    geometry = None
                kind = "way" if obj.from_way() else "relation"
                row = {"id": f"{kind}/{obj.orig_id()}", "version": obj.version,
                       "tags": {k: v for k, v in obj.tags if k in FIELDS}, "wkb": geometry}
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        result.replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    extract(args.pbf, args.output)
