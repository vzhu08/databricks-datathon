"""Compare issuer listings with named OSM premises, preserving candidate lineage."""
import argparse
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from shapely import from_geojson, to_geojson
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from research.acquisition.osm_services.core import canonical
from research.acquisition.osm_services.hot import load as load_hot, FROZEN_SHA256
from research.acquisition.osm_services.pbf import file_digest
from .scan import FREEZE_SHA, PBF_SHA, eligible, issuer_rows, names, norm

RADIUS_M = 300
PBF_EXTRACT_SHA = "c62d1841d5fc2133c32f8c5541a44becd54f5337bbaace4e448264a39fcb8920"
POINT_REPEAT_M = 1
NEAR_POINT_M = 10
OUTCOMES = (
    "exact_address_premises_agreement",
    "supported_campus_footprint_entrance_unknown",
    "unresolved_neighboring_or_chain_site",
    "coordinate_only_coincidence",
    "no_labelled_object",
    "missing_input",
)
BASELINE_PINS = {
    "occurrences.jsonl.gz": "a5cdc3effbc923d3ab444db57bf5d5e9b25147446f0de5f9c40c355e20fdcdcf",
    "decisions.jsonl.gz": "51dabdfd56af0d2e97afe6cd157308665b348517291fd8cfcbe2b1e92c3e4f6e",
}


def pin_from(text):
    matches = set(re.findall(r"(?<!\d)[1-9]\d{5}(?!\d)", text or ""))
    return next(iter(matches)) if len(matches) == 1 else None


def address_matches(row, tags):
    if not row["premises_key"] or not row["pin"]:
        return False
    full = tags.get("addr:full")
    mapped_pin = tags.get("addr:postcode") or pin_from(full)
    if mapped_pin != row["pin"]:
        return False
    source = norm(row["premises_address"])
    postal = row["pin"]
    if full and norm(full).removesuffix(" " + postal) == source.removesuffix(" " + postal):
        return True
    if re.search(r"\b(?:floor|suite|unit|wing|block|tower|building)\b", source):
        return False
    house, street = norm(tags.get("addr:housenumber")), norm(tags.get("addr:street"))
    if not house or not street:
        return False
    # Require an explicit numbered street segment. A PIN, city, or landmark alone
    # cannot establish that a directory listing refers to this physical premise.
    for segment in re.split(r"[,;\n]", row["premises_address"]):
        if norm(segment) == f"{house} {street}":
            return True
    return False


def point_distance(point, other):
    x_scale = 111320 * math.cos(math.radians(point.y))
    return math.hypot((point.x - other.x) * x_scale, (point.y - other.y) * 111320)


def geometry_distance(point, geometry):
    from shapely.ops import nearest_points

    if geometry is None or geometry.is_empty:
        return None
    nearest = nearest_points(point, geometry)[1]
    return point_distance(point, nearest)


def way_geometry(refs, coordinates):
    points = [coordinates.get(str(ref)) for ref in refs]
    if len(points) < 2 or None in points:
        return None
    if len(points) >= 4 and refs[0] == refs[-1]:
        polygon = Polygon(points)
        if polygon.is_valid and polygon.area:
            return polygon
    return LineString(points)


def relation_geometry(item, way_refs, coordinates):
    if item["tags"].get("type") not in {"multipolygon", "boundary"}:
        return None
    outer, inner = [], []
    for kind, ref, role in item["members"]:
        if role not in ("", "outer", "inner"):
            continue
        if kind != "w":
            return None
        geometry = way_geometry(way_refs.get(str(ref), []), coordinates)
        if geometry is None:
            return None
        (inner if role == "inner" else outer).append(
            geometry.exterior if geometry.geom_type == "Polygon" else geometry
        )
    if not outer:
        return None
    footprint = unary_union(list(polygonize(outer)))
    holes = unary_union(list(polygonize(inner)))
    if not holes.is_empty:
        footprint = footprint.difference(holes)
    return footprint if footprint.is_valid and not footprint.is_empty else None


def pbf_features(bundle):
    coords = bundle["coordinates"]
    way_refs = {**bundle["member_ways"], **{k: v["nodes"] for k, v in bundle["ways"].items()}}
    for section, kind in (("points", "node"), ("ways", "way"), ("relations", "relation")):
        for ident, item in bundle[section].items():
            if kind == "node":
                geometry = Point(item["point"])
            elif kind == "way":
                geometry = way_geometry(item["nodes"], coords)
            else:
                geometry = relation_geometry(item, way_refs, coords)
            yield {"osm_id": f"{kind}/{ident}", "edition": "geofabrik_2026-11-01",
                   "version": item["version"], "tags": item["tags"], "geometry": geometry}


def hot_features(records):
    for record in records:
        raw = record["geometry"]
        geometry = from_geojson(json.dumps(raw), on_invalid="ignore") if raw else None
        if geometry is not None and not geometry.is_valid:
            geometry = None
        yield {"osm_id": record["osm_id"], "edition": "hot_2026-10-09",
               "locators": record["locators"], "tags": record["tags"], "geometry": geometry}


def campus_area(feature):
    geometry = feature["geometry"]
    return bool(geometry is not None and geometry.geom_type in {"Polygon", "MultiPolygon"}
                and names(feature["tags"]))


def match_feature(row, feature, point, branch_name, map_names, same_address):
    geometry = feature["geometry"]
    distance = geometry_distance(point, geometry) if point is not None else None
    same_name = branch_name in map_names
    nearby = distance is not None and distance <= RADIUS_M
    if not (same_name or same_address or nearby):
        return None
    contains = campus_area(feature) and point is not None and geometry.covers(point)
    repeats = (geometry is not None and geometry.geom_type == "Point" and
               distance is not None and distance <= POINT_REPEAT_M)
    tags = feature["tags"]
    mapped_pin = tags.get("addr:postcode") or pin_from(tags.get("addr:full"))
    postal_conflict = bool(row["pin"] and mapped_pin and row["pin"] != mapped_pin)
    house = norm(tags.get("addr:housenumber"))
    street = norm(tags.get("addr:street"))
    source_segments = [norm(segment) for segment in re.split(r"[,;\n]", row["premises_address"] or "")]
    house_conflict = bool(house and street and any(
        segment.endswith(" " + street) and segment.split()[0].isdigit() and
        segment != f"{house} {street}" for segment in source_segments
    ))
    selected_keys = {"name", "name:en", "alt_name", "official_name", "amenity", "healthcare",
                     "building", "entrance", "landuse", "office", "shop", "source", "source:date",
                     "addr:full", "addr:housenumber", "addr:street", "addr:postcode", "addr:city"}
    return {
        **feature, "tags": {key: value for key, value in tags.items() if key in selected_keys},
        "geometry": json.loads(to_geojson(geometry)) if geometry is not None else None,
        "same_name": same_name, "same_address": same_address, "distance_m": distance,
        "address_conflict": postal_conflict or house_conflict,
        "named_footprint_contains_point": bool(contains), "point_repeats_osm_node": repeats,
        "same_numeric_coordinates_6dp": bool(repeats and
            (round(point.x, 6), round(point.y, 6)) == (round(geometry.x, 6), round(geometry.y, 6))),
        "is_named": bool(map_names), "is_entrance": bool(tags.get("entrance")),
        "site_geometry": geometry is not None and geometry.geom_type in {"Point", "Polygon", "MultiPolygon"},
        "medical": bool(tags.get("healthcare") or tags.get("amenity") in {"hospital", "clinic", "doctors"}),
        "source_lineage": tags.get("source"), "evidence_origin": "osm",
    }


def premises_groups(candidates):
    """Cluster overlapping same-name footprints and their interior documented POIs."""
    groups = []
    for candidate in sorted(candidates, key=lambda c: c["osm_id"]):
        geometry = from_geojson(json.dumps(candidate["geometry"])) if candidate["geometry"] else None
        hits = []
        for group in groups:
            for other, other_geometry in group:
                same_id = candidate["osm_id"] == other["osm_id"]
                intersects = (geometry is not None and other_geometry is not None and
                              geometry.intersects(other_geometry) and
                              (geometry.area > 0 or other_geometry.area > 0))
                if same_id or intersects:
                    hits.append(group)
                    break
        merged = [(candidate, geometry)]
        for group in hits:
            groups.remove(group)
            merged.extend(group)
        groups.append(merged)
    return [[c for c, _ in group] for group in groups]


def classify(row, candidates):
    # Prefer the November edition per typed ID while retaining October evidence.
    latest = {c["osm_id"]: c for c in sorted(candidates, key=lambda c: c["edition"], reverse=True)}
    # Reverse lexical sorting puts HOT first, so the later Geofabrik entry wins.
    matched = [c for c in latest.values() if c["same_name"] and not c["is_entrance"]]
    active = [c for c in matched if c["distance_m"] is None or c["distance_m"] <= RADIUS_M]
    decisive = [c for c in active if c["same_address"] and c["site_geometry"] and not c["address_conflict"]]
    footprint = [c for c in active if c["named_footprint_contains_point"] and not c["address_conflict"]]
    # A nearby distinct same-name mapped premise leaves the choice unresolved
    # unless its differing full addressed premise can be ruled out explicitly.
    pool = active if row["points"] else matched
    clusters = premises_groups(pool)
    plausible = [g for g in clusters if any(c in decisive or c in footprint for c in g)]
    if len(clusters) == 1 and len(plausible) == 1 and not any(c["address_conflict"] for c in active):
        return OUTCOMES[0] if decisive else OUTCOMES[1]
    if matched or any(c["same_address"] for c in candidates):
        return OUTCOMES[2]
    if any(c["named_footprint_contains_point"] or c["point_repeats_osm_node"] or
           (c["is_named"] and c["distance_m"] is not None and c["distance_m"] <= NEAR_POINT_M)
           for c in latest.values()):
        return OUTCOMES[3]
    if not row["points"] and not row["premises_key"]:
        return OUTCOMES[5]
    return OUTCOMES[2] if any(c["is_named"] for c in latest.values()) else OUTCOMES[4]


def baseline(input_dir):
    for name, pin in BASELINE_PINS.items():
        if file_digest(input_dir / name) != pin:
            raise ValueError(f"Unexpected national baseline digest: {name}")
    with gzip.open(input_dir / "occurrences.jsonl.gz", "rt") as stream:
        occurrences = [json.loads(line)["identity"] for line in stream]
    count = len(occurrences)
    upstream_ids = len({r["original_upstream_id"] for r in occurrences})
    repeat_sizes = Counter(Counter(r["original_payload_sha256"] for r in occurrences).values())
    with gzip.open(input_dir / "decisions.jsonl.gz", "rt") as stream:
        decisions = Counter((r["service"], r["status"]) for r in map(json.loads, stream))
    decision_count = sum(decisions.values())
    if ((count, upstream_ids, repeat_sizes[2], decision_count) != (10088, 10077, 11, 30264)
            or len(decisions) != 3 or any(status != "unconfirmed" or n != 10088
                                         for (_, status), n in decisions.items())):
        raise ValueError("National baseline counts differ")
    return {"occurrence_count": count, "upstream_ids": upstream_ids, "identical_pairs": repeat_sizes[2],
            "unconfirmed_decisions": decision_count,
            "input_sha256": BASELINE_PINS, "mutations": 0, "new_vf_links_computed": False}


def load_pinned_extract(path):
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PBF_EXTRACT_SHA:
        raise ValueError("Unexpected frozen India PBF extraction digest")
    return json.loads(raw)


def report(freeze, hot, pbf_path, baseline_dir, out):
    pbf = load_pinned_extract(pbf_path)
    rows = issuer_rows(freeze)
    # Bucket issuer points, so a nationwide archive scan tests each feature against
    # all names but only runs exact distances for plausible local bounding boxes.
    cohort_names = defaultdict(list)
    by_id = {}
    for index, row in enumerate(rows):
        branch = norm(row["name"])
        cohort_names[branch].append(index)
        p = row["points"]
        point = Point(p[0]["longitude"], p[0]["latitude"]) if p else None
        by_id[index] = row, branch, point
    hot_rows, _, _, _, _ = load_hot(hot)
    candidates = defaultdict(list)
    scanned = Counter()
    for features in (hot_features(hot_rows), pbf_features(pbf)):
        for item in features:
            scanned[item["edition"]] += 1
            tags, geometry = item["tags"], item["geometry"]
            map_names = names(tags)
            if not eligible(tags) and not (map_names & cohort_names.keys()):
                continue
            indices = {i for name in map_names for i in cohort_names[name]}
            mapped_pin = tags.get("addr:postcode") or pin_from(tags.get("addr:full"))
            bounds = geometry.bounds if geometry is not None and not geometry.is_empty else None
            for index, (row, _, point) in by_id.items():
                if mapped_pin and mapped_pin == row["pin"] and address_matches(row, tags):
                    indices.add(index)
                if point is None or bounds is None:
                    continue
                margin_lat = RADIUS_M / 111320
                margin_lon = margin_lat / math.cos(math.radians(point.y))
                if (bounds[0] - margin_lon <= point.x <= bounds[2] + margin_lon and
                        bounds[1] - margin_lat <= point.y <= bounds[3] + margin_lat):
                    indices.add(index)
            for index in sorted(indices):
                row, branch, point = by_id[index]
                match = match_feature(row, item, point, branch, map_names, address_matches(row, tags))
                if match:
                    candidates[index].append(match)
    ledger = []
    counts = Counter()
    for index, row in enumerate(rows):
        records = sorted(candidates[index], key=lambda c: (c["osm_id"], c["edition"], canonical(c)))
        outcome = classify(row, records)
        counts[outcome] += 1
        ledger.append({"listing_id": row["listing_id"], "payload_sha256": row["listing_payload_sha256"],
                       "capture_locator": [row["page"], row["position"]], "has_address_key": bool(row["premises_key"]),
                       "has_numeric_point": bool(row["points"]), "outcome": outcome,
                       "entrance_confirmed": None, "independent_premises_origin": None,
                       "candidate_objects": records})
    by_edition = defaultdict(set)
    for row in ledger:
        for candidate in row["candidate_objects"]:
            by_edition[candidate["edition"]].add(candidate["osm_id"])
    shared = by_edition["hot_2026-10-09"] & by_edition["geofabrik_2026-11-01"]
    availability_groups = defaultdict(Counter)
    for row in ledger:
        availability = f"address_{int(row['has_address_key'])}_point_{int(row['has_numeric_point'])}"
        availability_groups[availability][row["outcome"]] += 1
    summary = {
        "source_pins": {"issuer_freeze": FREEZE_SHA, "hot_zip": FROZEN_SHA256,
                        "pbf": PBF_SHA, "pbf_extract": PBF_EXTRACT_SHA},
        "issuer_listings": len(rows),
        "with_eligible_address": sum(bool(r["premises_key"]) for r in rows),
        "with_numeric_point": sum(bool(r["points"]) for r in rows),
        "with_both": sum(bool(r["premises_key"] and r["points"]) for r in rows),
        "source_objects_screened_or_extracted": dict(scanned),
        "pbf_extract_diagnostics": pbf["extraction"],
        "outcomes": {outcome: counts[outcome] for outcome in OUTCOMES},
        "outcomes_by_input_availability": dict(availability_groups),
        "eligible_osm_candidates_by_edition": dict(Counter(c["edition"] for r in ledger for c in r["candidate_objects"])),
        "within_one_metre_of_osm_point_listings": sum(any(c["point_repeats_osm_node"] for c in r["candidate_objects"]) for r in ledger),
        "same_numeric_coordinates_6dp_listings": sum(any(c["same_numeric_coordinates_6dp"] for c in r["candidate_objects"]) for r in ledger),
        "listings_with_mapped_entrance_candidates": sum(any(c["is_entrance"] for c in r["candidate_objects"]) for r in ledger),
        "listings_with_declared_map_source_candidates": sum(any(c["source_lineage"] for c in r["candidate_objects"]) for r in ledger),
        "shared_candidate_typed_osm_ids_between_editions": len(shared),
        "footprint_coincidence_listings_any_candidate": sum(any(c["named_footprint_contains_point"] for c in r["candidate_objects"]) for r in ledger),
        "exact_branch_name_listings": sum(any(c["same_name"] for c in r["candidate_objects"]) for r in ledger),
        "exact_structured_address_listings": sum(any(c["same_address"] for c in r["candidate_objects"]) for r in ledger),
        "distinct_candidate_typed_osm_ids": len({c["osm_id"] for r in ledger for c in r["candidate_objects"]}),
        "confirmed_entrances": 0, "independently_verified_campuses": 0, "service_status_transitions": 0,
        "national_frozen_frame": baseline(baseline_dir),
    }
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_bytes(canonical(summary))
    with (out / "candidates.jsonl").open("wb") as stream:
        for row in ledger:
            stream.write(canonical(row))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("freeze", "hot", "pbf_extract", "baseline", "out"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    report(args.freeze, args.hot, args.pbf_extract, args.baseline, args.out)
