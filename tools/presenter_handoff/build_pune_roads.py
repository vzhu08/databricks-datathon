"""Build clipped, offline ODbL cartography from the pinned public Geofabrik extract."""

import argparse
from collections import Counter, defaultdict
from hashlib import file_digest, sha256
import gzip
import json
from pathlib import Path
import osmium
import shapely
from shapely.geometry import LineString, box


BBOX = [73.753, 18.424, 73.958, 18.615]
ATTRIBUTION = "© OpenStreetMap contributors"
COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
SOURCE_URL = "https://download.geofabrik.de/asia/india/india-261101.osm.pbf"
SOURCE_SHA256 = "c0a4a9382e67c8afc8427ab865358dcf42226ab3876f8477667585eaab6731b7"
ROAD_ZOOM = {
    **dict.fromkeys(("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"), 9),
    **dict.fromkeys(("secondary", "secondary_link"), 10),
    **dict.fromkeys(("tertiary", "tertiary_link"), 11),
    **dict.fromkeys(("unclassified", "residential", "living_street"), 12),
    "service": 13,
}
PLACES = {"city", "town", "suburb"}
LABEL_KEYS = ("name", "name:en", "ref")
PRECISION = 5
MAX_GROUP_SIZE = 200


def sha256_file(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def put_json(root, filename, value, *, compressed=False):
    payload = json_bytes(value)
    (root / filename).write_bytes(payload)
    stats = {"file": filename, "bytes": len(payload), "sha256": sha256(payload).hexdigest()}
    if compressed:
        packed = gzip.compress(payload, compresslevel=9, mtime=0)
        gzip_name = filename + ".gz"
        (root / gzip_name).write_bytes(packed)
        stats.update(gzip_file=gzip_name, gzip_bytes=len(packed), gzip_sha256=sha256(packed).hexdigest())
    return stats


def lines(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "LineString":
        yield geometry
    elif geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        for component in geometry.geoms:
            yield from lines(component)


def clipped_parts(raw, cutoff, tolerance):
    for line in lines(LineString(raw).intersection(cutoff)):
        simplified = line.simplify(tolerance, preserve_topology=True)
        rounded = []
        for point in simplified.coords:
            pair = tuple(round(axis, PRECISION) for axis in point)
            if not rounded or rounded[-1] != pair:
                rounded.append(pair)
        if len(rounded) > 1:
            yield rounded


def clean_labels(tags):
    # Keep display tags only. Preserve Marathi and other UTF-8 scripts.
    return {key: value for key in LABEL_KEYS if (value := " ".join(tags.get(key, "").split()))}


def features(groups):
    result = []
    for attrs, parts in sorted(groups.items()):
        for start in range(0, len(parts), MAX_GROUP_SIZE):
            chunk = parts[start:start + MAX_GROUP_SIZE]
            geometry = (
                {"type": "LineString", "coordinates": chunk[0]}
                if len(chunk) == 1
                else {"type": "MultiLineString", "coordinates": chunk}
            )
            result.append({"type": "Feature", "geometry": geometry, "properties": dict(attrs)})
    return result


def collection(rows):
    return {"type": "FeatureCollection", "bbox": BBOX, "attribution": ATTRIBUTION,
            "license": "ODbL-1.0", "license_url": LICENSE_URL, "features": rows}


def road_and_context(pbf):
    roads, water = defaultdict(list), defaultdict(list)
    places = []
    ways, segments, dropped = Counter(), Counter(), Counter()
    cutoff = box(*BBOX)
    processor = osmium.FileProcessor(str(pbf)).with_locations()
    processor.with_filter(osmium.filter.KeyFilter("highway", "waterway", "place"))
    for obj in processor:
        tags = obj.tags
        if obj.is_node():
            place = tags.get("place")
            if place in PLACES and tags.get("name"):
                lon, lat = obj.location.lon, obj.location.lat
                if BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]:
                    places.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, PRECISION), round(lat, PRECISION)]},
                                   "properties": {"place": place, **clean_labels(tags)}})
            continue
        if not obj.is_way():
            continue
        highway = tags.get("highway")
        waterway = tags.get("waterway")
        if highway not in ROAD_ZOOM and waterway not in {"river", "canal"}:
            continue
        labels = clean_labels(tags)
        if highway == "service" and not (labels.get("name") or labels.get("name:en")):
            continue
        raw = [(node.location.lon, node.location.lat) for node in obj.nodes if node.location.valid()]
        if len(raw) != len(obj.nodes):
            dropped["missing_way_node"] += 1
            continue
        if len(set(raw)) < 2:
            dropped["degenerate_way"] += 1
            continue
        if highway in ROAD_ZOOM:
            zoom = ROAD_ZOOM[highway]
            props = {"highway": highway, "min_zoom": zoom, **labels}
            parts = list(clipped_parts(raw, cutoff, 0.000035 if zoom <= 11 else 0.000060))
            if parts:
                roads[tuple(sorted(props.items()))].extend(parts)
                ways[highway] += 1
                segments[highway] += len(parts)
        if waterway in {"river", "canal"}:
            props = {"waterway": waterway, **labels}
            parts = list(clipped_parts(raw, cutoff, 0.000045))
            if parts:
                water[tuple(sorted(props.items()))].extend(parts)
                ways[waterway] += 1
                segments[waterway] += len(parts)
    place_sort = lambda row: (row["properties"]["place"], row["properties"]["name"], row["geometry"]["coordinates"])
    return features(roads), features(water) + sorted(places, key=place_sort), dict(ways), dict(segments), dict(dropped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, required=True, help="Osmium complete_ways bounding-box extract")
    parser.add_argument("--output", type=Path, required=True, help="Untracked output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    roads, context, ways, segments, dropped = road_and_context(args.pbf)
    if not roads or not ways.get("primary") or not ways.get("residential"):
        raise RuntimeError("The clipped source failed expected road coverage checks")
    overview = [row for row in roads if row["properties"]["min_zoom"] <= 11]
    files = [put_json(args.output, "pune-roads-v1.geojson", collection(roads), compressed=True),
             put_json(args.output, "pune-roads-overview-v1.geojson", collection(overview), compressed=True),
             put_json(args.output, "pune-map-context-v1.geojson", collection(context), compressed=True)]
    report = {
        "version": "pune-openstreetmap-road-display-v1", "bbox_wgs84": BBOX,
        "format": "RFC 7946 GeoJSON, longitude latitude, optional min_zoom advisory",
        "scope": "2026-11-01 mapped road centerlines and context; display only",
        "attribution": ATTRIBUTION, "attribution_url": COPYRIGHT_URL,
        "license": "ODbL-1.0", "license_url": LICENSE_URL,
        "source": {"publisher": "OpenStreetMap contributors, distributed by Geofabrik",
                   "snapshot": "2026-11-01", "url": SOURCE_URL, "sha256": SOURCE_SHA256,
                   "bbox_pbf_sha256": sha256_file(args.pbf)},
        "extraction": {"strategy": "osmium extract --strategy=complete_ways",
                       "osmium_tool": "1.19.1", "pyosmium": "4.2.0", "shapely": shapely.__version__,
                       "simplify_degrees": {"arterial": 0.000035, "local": 0.000060, "water": 0.000045},
                       "coordinate_decimals": PRECISION, "local_service_filter": "named ways only"},
        "original_ways_per_class": ways, "clipped_segments_per_class": segments,
        "dropped_way_reasons": dropped, "road_features": len(roads),
        "overview_features": len(overview), "context_features": len(context),
        "files": files,
    }
    manifest = put_json(args.output, "pune-roads-v1.manifest.json", report)
    print(json.dumps({"manifest": manifest, "report": report}, ensure_ascii=True))


if __name__ == "__main__":
    main()
