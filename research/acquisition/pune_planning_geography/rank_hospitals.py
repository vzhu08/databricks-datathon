"""Rank Indian districts and extract Pune geography from the pinned OSM export."""

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from shapely import STRtree, box, make_valid
from shapely.geometry import shape


OSM_URL = ("https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/"
           "hotosm_ind_health_facilities_osm_geojson.zip")
OSM_REPORT = ("https://production-raw-data-api.s3.amazonaws.com/ISO3/IND/health_facilities/"
              "hotosm_ind_health_facilities_report.html")
DISTRICT_URL = ("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/"
                "releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2.geojson")
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
PUNE_ID = "76128533B71380851181380"
OSM_SHA256 = "5b2c036798554a5842b66dbbd88f98d4561269a5e05de377513fd6454f6deff3"
DISTRICT_SHA256 = "8bef6929fd65432e7dc775e7c44473e84efff064ebddbfd6b834e6291546db40"
PLACEHOLDERS = {"hospital", "hospitals", "unnamed", "unknown", "no name", "अस्पताल", "হাসপাতাল", "மருத்துவமனை"}
NAME_FIELDS = ("name_en", "name", "name_latin", "name_hi")
ATTRIBUTION = "© OpenStreetMap contributors (via Geofabrik and oex); geoBoundaries, Pathways Data Pvt. Ltd. and Local Government Directory."


def key(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(c if c.isalnum() or unicodedata.category(c).startswith("M") else " "
                            for c in text).split())


def normalized_names(props):
    named = {}
    for field in NAME_FIELDS:
        value = props.get(field)
        if isinstance(value, str):
            name_key = key(value)
            if name_key and name_key not in PLACEHOLDERS and any(c.isalpha() for c in name_key):
                named.setdefault(name_key, value.strip())
    return named


def district_shapes(boundaries):
    features = json.loads(boundaries.read_bytes())["features"]
    records, geoms = [], []
    repaired = 0
    for feature in features:
        props = feature["properties"]
        geometry = shape(feature["geometry"])
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            repaired += 1
        if geometry.is_empty:
            raise ValueError(f"Empty district geometry: {props['shapeID']}")
        records.append((props["shapeID"], props["shapeName"]))
        geoms.append(geometry)
    if len({district[0] for district in records}) != len(records):
        raise ValueError("District identifiers are not unique")
    return records, STRtree(geoms), repaired


def hospital_geometry(feature):
    raw = feature.get("geometry")
    if not raw or raw.get("type") not in {"Point", "Polygon", "MultiPolygon"}:
        return None, None, "unsupported_geometry"
    geometry = shape(raw)
    if not geometry.is_valid:
        geometry = make_valid(geometry)
    if geometry.is_empty or geometry.geom_type not in {"Point", "Polygon", "MultiPolygon"}:
        return None, None, "invalid_or_empty_geometry"
    point = geometry if geometry.geom_type == "Point" else geometry.representative_point()
    if not (math.isfinite(point.x) and math.isfinite(point.y) and -180 <= point.x <= 180 and -90 <= point.y <= 90):
        return None, None, "invalid_coordinates"
    precision = "OSM mapped point" if geometry.geom_type == "Point" else "OSM mapped outline interior point"
    return geometry, point, precision


def eligible_hospitals(osm, district_index):
    with zipfile.ZipFile(osm) as archive:
        with archive.open("health_facilities.geojson") as stream:
            features = json.load(stream)["features"]
    counts = Counter(export_features=len(features))
    rows = []
    seen = set()
    for ordinal, feature in enumerate(features):
        props = feature["properties"]
        if props.get("amenity") != "hospital" and props.get("healthcare") != "hospital":
            continue
        counts["hospital_tagged_features"] += 1
        names = normalized_names(props)
        if not names:
            counts["unnamed_or_placeholder_hospital_features"] += 1
            continue
        counts["named_hospital_features"] += 1
        source_id = str(props["id"]) if props.get("id") is not None else f"export-row-{ordinal}"
        if source_id in seen:
            counts["repeated_osm_object_ids"] += 1
            continue
        seen.add(source_id)
        geometry, point, precision = hospital_geometry(feature)
        if point is None:
            counts[precision] += 1
            continue
        hits = district_index.query(point, predicate="covered_by")
        district = int(hits[0]) if len(hits) == 1 else None
        if district is None:
            counts["no_district_polygon" if len(hits) == 0 else "overlapping_district_polygons"] += 1
        rows.append({"source_id": source_id, "name": next(iter(names.values())), "aliases": set(names),
                     "point": point, "geometry": geometry, "precision": precision, "district": district,
                     "tags": {k: props[k] for k in ("amenity", "healthcare") if props.get(k) == "hospital"}})
    counts["named_objects_with_usable_geometry"] = len(rows)
    return rows, counts


def metres(left, right):
    dy = math.radians(right.y - left.y)
    dx = math.radians(right.x - left.x)
    a = math.sin(dy / 2) ** 2 + math.cos(math.radians(left.y)) * math.cos(math.radians(right.y)) * math.sin(dx / 2) ** 2
    return 12_742_000 * math.asin(min(1.0, math.sqrt(a)))


def duplicate_candidates(rows):
    points = STRtree([row["point"] for row in rows])
    geometry = STRtree([row["geometry"] for row in rows])
    candidates = []
    for i, original in enumerate(rows):
        point = original["point"]
        nearby = points.query(box(point.x - 0.004, point.y - 0.004, point.x + 0.004, point.y + 0.004))
        overlapping = geometry.query(original["geometry"], predicate="intersects")
        for j in sorted(set(nearby.tolist()) | set(overlapping.tolist())):
            if j <= i:
                continue
            other = rows[j]
            if original["district"] != other["district"] or not (original["aliases"] & other["aliases"]):
                continue
            overlap = original["geometry"].intersects(other["geometry"])
            distance = metres(point, other["point"])
            if overlap or distance <= 250:
                candidates.append((overlap, distance, i, j))
    return sorted(candidates, key=lambda match: (not match[0], match[1], match[2], match[3]))


def group_sites(rows, candidates, radius):
    groups = {i: [i] for i in range(len(rows))}
    group_for = list(range(len(rows)))
    aliases = [row["aliases"].copy() for row in rows]
    for overlap, distance, i, j in candidates:
        if not overlap and distance > radius:
            continue
        a, b = group_for[i], group_for[j]
        if a == b or not (aliases[a] & aliases[b]):
            continue
        # A chain of close objects does not merge separate faraway premises.
        if any(metres(rows[x]["point"], rows[y]["point"]) > radius
               and not rows[x]["geometry"].intersects(rows[y]["geometry"])
               for x in groups[a] for y in groups[b]):
            continue
        aliases[a].intersection_update(aliases[b])
        for pos in groups[b]:
            group_for[pos] = a
        groups[a].extend(groups.pop(b))
    return list(groups.values())


def representatives(rows, groups):
    for group in groups:
        best = min(group, key=lambda i: (rows[i]["geometry"].geom_type == "Point", rows[i]["source_id"]))
        yield rows[best], len(group)


def ranking(rows, groups, districts):
    assigned = Counter(row["district"] for row, _ in representatives(rows, groups))
    order = sorted(range(len(districts)), key=lambda d: (-assigned[d], districts[d][1], districts[d][0]))
    return assigned, [{"district_id": districts[d][0], "district": districts[d][1], "sites": assigned[d], "index": d}
                      for d in order]


def write_csv(path, fields, records):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def verify_sha256(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"{path.name}: expected SHA-256 {expected}, got {actual}")


def write_json(path, data):
    # The frozen OSM intermediate was serialized with CRLF.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\r\n")


def pune_facility(row, cluster_size):
    id_parts = re.fullmatch(r"(node|way|relation)[/_]?(\d+)", row["source_id"])
    if not id_parts:
        raise ValueError("An OSM source object has no typed identity")
    kind, ref = id_parts.groups()
    polygon = row["geometry"].geom_type != "Point"
    return {"id": f"osm-{kind}-{ref}", "label": row["name"],
            "longitude": round(row["point"].x, 7), "latitude": round(row["point"].y, 7),
            "precision": "point", "location_class": "campus simulation anchor" if polygon else "mapped facility point",
            "source_geometry": row["geometry"].geom_type, "facility_class": "hospital (OSM tag)",
            "osm_hospital_tags": row["tags"], "source_id": row["source_id"],
            "source_url": f"https://www.openstreetmap.org/{kind}/{ref}", "publisher": "OpenStreetMap contributors",
            "snapshot": "2026-10-09", "license": "ODbL-1.0", "license_url": ODBL_URL,
            "duplicate_objects_collapsed": cluster_size - 1}


def write_pune_roster(path, rows, groups, districts, report):
    district = next(i for i, record in enumerate(districts) if record[0] == PUNE_ID)
    facilities = sorted((pune_facility(row, n) for row, n in representatives(rows, groups)
                         if row["district"] == district), key=lambda row: row["id"])
    if len({row["id"] for row in facilities}) != len(facilities):
        raise ValueError("Pune roster has repeated facility IDs")
    geography = {"name": "Pune, Maharashtra, India", "selection": "Vincent selected Pune using B's national VF district comparison. This roster is extracted separately from public OSM locations.",
                 "selection_receipt": "https://github.com/vzhu08/databricks-datathon/issues/323#issuecomment-7081734925",
                 "verification": "Mapped hospital points and outline anchors from the pinned OSM extract. The roster makes no claim about entrances, operating status, current services, or capacity.",
                 "source": "Health Facilities of India, HOT/Geofabrik/oex OpenStreetMap snapshot 2026-10-09",
                 "district_boundary": {"name": "Pune", "feature_id": PUNE_ID, "edition": report["boundary_edition"],
                                       "feature_id_field": "shapeID", "url": DISTRICT_URL,
                                       "sha256": report["boundaries_sha256"], "license": "ODbL-1.0"},
                 "attribution": [{"text": "© OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright"},
                                 {"text": "Humanitarian OpenStreetMap Team, via Geofabrik and oex", "url": OSM_REPORT},
                                 {"text": "geoBoundaries / Pathways Data Pvt. Ltd. / Local Government Directory",
                                  "url": report["district_metadata"]},
                                 {"text": "Open Database License 1.0", "url": ODBL_URL}]}
    source = {"name": "Health Facilities of India", "extract_url": OSM_URL, "catalog_url": OSM_REPORT,
              "snapshot": "2026-10-09", "zip_sha256": report["osm_export_sha256"],
              "archive_member": "health_facilities.geojson", "filter": report["filter"],
              "deduplication": report["deduplication"], "license": "ODbL-1.0", "license_url": ODBL_URL}
    common = {"schema_version": "storm-roster-v1", "geography": geography, "source": source,
              "coordinate_reference_system": {"name": "WGS 84", "authority_code": "EPSG:4326",
                                              "longitude_field": "longitude", "latitude_field": "latitude"},
              "publication": {"export_license": "ODbL-1.0", "license_url": ODBL_URL,
                              "intended_venue": "Separate attributed Storm planning geography, subject to project release approval. Source rows stay out of Git and the standalone notebook."},
              "distinct_district_site_count": len(facilities)}
    write_json(path, dict(common, roster_kind="district", facility_count=len(facilities), facilities=facilities))


def run(osm, boundaries, output_dir):
    verify_sha256(osm, OSM_SHA256)
    verify_sha256(boundaries, DISTRICT_SHA256)
    districts, district_index, repaired = district_shapes(boundaries)
    rows, counts = eligible_hospitals(osm, district_index)
    candidates = duplicate_candidates(rows)
    sensitivity = {}
    for radius in (50, 150, 250):
        groups = group_sites(rows, candidates, radius)
        assigned, order = ranking(rows, groups, districts)
        sensitivity[str(radius)] = {"distinct_locatable_sites": len(groups), "unassigned_sites": assigned[None],
                                    "top_five": [{k: v for k, v in entry.items() if k != "index"}
                                                 for entry in order[:5]]}
        if radius == 150:
            default_groups, default_counts, default_order = groups, assigned, order
    counts["named_unique_objects_without_geometry"] = (counts["named_hospital_features"]
        - counts["repeated_osm_object_ids"] - len(rows))
    counts["named_sites_with_unique_district"] = len(default_groups) - default_counts[None]
    counts["mapped_sites_without_unique_district"] = default_counts[None]
    counts["districts_with_mapped_sites"] = sum(default_counts[d] > 0 for d in range(len(districts)))
    counts["same_name_geometry_duplicates_collapsed"] = len(rows) - len(default_groups)
    ranking_rows = [{k: v for k, v in row.items() if k != "index"} for row in default_order]
    if sum(entry["sites"] for entry in ranking_rows) != counts["named_sites_with_unique_district"]:
        raise ValueError("Assigned sites did not reconcile to the district ranking")
    output_dir.mkdir(parents=True, exist_ok=True)
    ranking_path = output_dir / "district-ranking.csv"
    write_csv(ranking_path, ("district_id", "district", "sites"), ranking_rows)
    report = {"scope": "Independent public map objects; no VF rows or joins", "snapshot": "2026-10-09",
              "osm_export_sha256": OSM_SHA256, "boundaries_sha256": DISTRICT_SHA256,
              "boundary_edition": "geoBoundaries IND-ADM2-76128533, 2021 districts, published revision 9469f09",
              "boundary_features": len(districts), "boundary_invalid_repaired": repaired,
              "filter": "amenity=hospital or healthcare=hospital with a usable non-placeholder published name",
              "deduplication": "Unique typed OSM IDs, then same normalized published name and same district with overlapping feature geometries or a bounded 150 m pairwise distance",
              "precision": "Unique district containing a mapped point or an interior point of a mapped outline. Locations are map features, not reviewed hospitals or entrances.",
              "counts": dict(counts), "top_ten": ranking_rows[:10],
              "radius_sensitivity": sensitivity, "attribution": ATTRIBUTION,
              "licenses": ["https://www.openstreetmap.org/copyright", "https://opendatacommons.org/licenses/odbl/1-0/"],
              "district_metadata": "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/",
              "ranking_sha256": sha256(ranking_path)}
    roster_path = output_dir / "pune-full.storm-roster-v1.json"
    write_pune_roster(roster_path, rows, default_groups, districts, report)
    report["pune_roster_sha256"] = sha256(roster_path)
    write_json(output_dir / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm", type=Path, required=True, help="Pinned HOT India health-facilities ZIP")
    parser.add_argument("--boundaries", type=Path, required=True, help="Pinned India 2021 ADM2 GeoJSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated files")
    args = parser.parse_args(argv)
    try:
        report = run(args.osm, args.boundaries, args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
