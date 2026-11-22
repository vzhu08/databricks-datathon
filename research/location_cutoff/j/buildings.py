"""Check each original VF point against all assembled OSM building-tagged areas."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import osmium
from shapely import STRtree, contains, from_wkb, is_valid, points

from research.acquisition.issuer_campus_geometry.compare import baseline
from research.acquisition.issuer_campus_geometry.scan import PBF_SHA, names, norm
from research.acquisition.osm_services.pbf import file_digest
from .compare import building


def scan(vf, pbf, output):
    frame = baseline(vf)
    if file_digest(pbf) != PBF_SHA:
        raise ValueError("Unexpected India PBF edition")
    records, coordinates, indexed = [], [], []
    with gzip.open(vf / "occurrences.jsonl.gz", "rt") as stream:
        for row in map(json.loads, stream):
            identity, source = row["identity"], row["original"]["source_row"]
            key = identity["facility_id"]
            records.append(key)
            if identity["original_point"]["screen_class"] != "unusable_original_point":
                indexed.append((key, norm(source["name"])))
                coordinates.append((source["longitude"], source["latitude"]))
    if len(set(records)) != frame["occurrence_count"]:
        raise ValueError("Incomplete occurrence frame")
    query_points = points(coordinates)
    tree = STRtree(query_points)
    hits = defaultdict(list)
    counts = Counter()
    factory = osmium.geom.WKBFactory()
    batch = []

    def flush():
        if not batch:
            return
        geometries = from_wkb([item[0] for item in batch])
        valid = is_valid(geometries)
        counts["invalid"] += int((~valid).sum())
        geometries[~valid] = None
        polygons, targets = tree.query(geometries, predicate="covers")
        strict = contains(geometries[polygons], query_points[targets])
        for index, target, interior in zip(polygons, targets, strict):
            _, osm_id, version, labels = batch[index]
            key, wanted = indexed[target]
            hits[key].append({"id": osm_id, "version": version, "interior": bool(interior),
                              "named": bool(labels), "exact_name": bool(wanted and wanted in labels)})
        batch.clear()

    with TemporaryDirectory(dir=output.parent) as directory:
        temp = Path(directory)
        reader = osmium.FileProcessor(pbf).with_locations(f"sparse_file_array,{temp / 'nodes'}")
        reader.with_areas(osmium.filter.KeyFilter("building")).with_filter(osmium.filter.KeyFilter("building"))
        for obj in reader:
            if not obj.is_area() or not building(obj.tags):
                continue
            counts["emitted_active_buildings"] += 1
            try:
                geometry = factory.create_multipolygon(obj)
            except RuntimeError:
                counts["unavailable_wkb"] += 1
                continue
            kind = "way" if obj.from_way() else "relation"
            batch.append((geometry, f"{kind}/{obj.orig_id()}", obj.version, names(obj.tags)))
            if len(batch) >= 4096:
                flush()
        flush()
        result = temp / "buildings.jsonl"
        with result.open("w") as stream:
            for key in records:
                buildings = sorted(hits[key], key=lambda item: item["id"])
                stream.write(json.dumps({"occurrence_key": key, "buildings": buildings},
                                        separators=(",", ":")) + "\n")
        result.replace(output)
    return {"counts": dict(counts), "pbf_sha256": PBF_SHA, "ledger_sha256": file_digest(output),
            "baseline": frame, "indexed_occurrence_points": len(indexed)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for param in ("vf", "pbf", "ledger", "summary"):
        parser.add_argument(param, type=Path)
    args = parser.parse_args()
    result = scan(args.vf, args.pbf, args.ledger)
    args.summary.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
