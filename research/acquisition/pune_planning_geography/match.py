"""Screen the pinned Pune OSM sites against official NHP locations."""

import argparse
import csv
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from shapely import Point

from .rank_hospitals import DISTRICT_SHA256, PUNE_ID, district_shapes, sha256, verify_sha256

NHP_SHA = "1ddcad9f9b922142a4374c7b89b70fb6cefd8a257448c70a61e1c07d98845134"
ROSTER_SHA = "31a26839d0122ec532cc8c41c261198b3df984c79e405689b27a49700533d439"
NHP_URL = "https://www.data.gov.in/resource/national-hospital-directory-geo-code-and-additional-parameters-updated-till-last-month"
GODL = "https://data.gov.in/Godl"
MAX_METRES = 100
RIVAL_METRES = 300
MIN_ENDPOINT_METRES = 200
GENERIC = set("hospital hospitals clinic medical centre center healthcare health nursing home polyclinic multispeciality multispecialty private limited pvt ltd pune maharashtra india general super speciality specialty care maternity and the of".split())
PLACEHOLDERS = {"", "0", "na", "nil", "none", "unknown", "unnamed", "not available", "not applicable"}


def key(name):
    value = unicodedata.normalize("NFKC", name).casefold()
    # Coalesce dotted initials; other punctuation separates tokens.
    value = re.sub(r"\b(?:[a-z]\.){2,}(?:[a-z]\b)?", lambda m: m[0].replace(".", ""), value)
    value = value.replace("&", " and ")
    words = "".join(c if c.isalnum() or unicodedata.category(c).startswith("M") else " " for c in value).split()
    if words[-2:] in (["pvt", "ltd"], ["private", "limited"]):
        words = words[:-2]
    return " ".join("hospital" if word == "hospitals" else word for word in words)


def distinctive_tokens(name):
    return {t for t in name.split() if len(t) >= 3 and t not in GENERIC}


def distinctive(name):
    return bool(distinctive_tokens(name))


def near_name_rival(name, reference, other_sources, field):
    terms = distinctive_tokens(name)
    for alternate, records in other_sources.items():
        alternate_terms = distinctive_tokens(alternate)
        if alternate == name or not alternate_terms or not (terms <= alternate_terms or alternate_terms <= terms):
            continue
        for record in records:
            if metres(row_point(reference), row_point(record)) <= RIVAL_METRES:
                return record[field]
    return None


def pair(field):
    if not re.fullmatch(r"\s*[-+]?\d+(?:\.\d+)?\s*,\s*[-+]?\d+(?:\.\d+)?\s*", field or ""):
        return None
    lat, lon = map(float, field.split(","))
    return lon, lat


def metres(left, right):
    x, y = left
    a, b = right
    t = math.sin(math.radians(b-y)/2)**2 + math.cos(math.radians(b))*math.cos(math.radians(y))*math.sin(math.radians(a-x)/2)**2
    return 12_742_000 * math.asin(min(1.0, math.sqrt(t)))


def row_point(row):
    return row["longitude"], row["latitude"]


def load_nhp(nhp_path, shapes, district_index):
    count = Counter()
    sources = defaultdict(list)
    min_x, min_y, max_x, max_y = shapes.geometries[district_index].bounds
    with nhp_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            count["official_listings"] += 1
            coords = pair(row["Location_Coordinates"])
            if coords is None or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90):
                continue
            count["official_with_valid_coordinate_pair"] += 1
            if not (min_x <= coords[0] <= max_x and min_y <= coords[1] <= max_y):
                continue
            areas = list(shapes.query(Point(*coords), predicate="covered_by"))
            if district_index not in areas:
                continue
            if len(areas) != 1:
                count["ambiguous_pune_district_boundary"] += 1
                continue
            count["pune_listings"] += 1
            report_name = row["Hospital_Name"].strip()
            normalized = key(report_name)
            if normalized in PLACEHOLDERS or not distinctive(normalized):
                count["pune_unnamed_or_nondistinctive"] += 1
                continue
            state, district = key(row["State"]), key(row["District"])
            concordant = state == "maharashtra" and district == "pune"
            if not concordant:
                count["pune_listings_with_publisher_geography_conflict"] += 1
            sources[(normalized, coords)].append((row["Sr_No"], report_name, concordant))
    by_key = defaultdict(list)
    collision = Counter(coords for _, coords in sources)
    for (normalized, (lon, lat)), records in sorted(sources.items()):
        records.sort()
        if not all(record[2] for record in records):
            count["pune_nhp_name_point_groups_with_publisher_geography_conflict"] += 1
            continue
        by_key[normalized].append({
            "serial_ids": [v[0] for v in records], "label": records[0][1],
            "longitude": lon, "latitude": lat, "point_name_groups": collision[(lon, lat)],
        })
    count["pune_distinct_nhp_name_point_groups_before_collision_screen"] = len(sources)
    count["pune_nhp_name_point_groups_on_shared_coordinate"] = sum(n for n in collision.values() if n > 1)
    count["pune_nhp_concordant_unique_coordinate_name_point_groups"] = sum(
        group["point_name_groups"] == 1 for groups in by_key.values() for group in groups
    )
    return by_key, count


def select(accepted, limit=12):
    if not accepted:
        return []
    # A Pune city-scale set avoids distant district outliers in a short drive scenario.
    nearby = [[j for j, b in enumerate(accepted) if metres(row_point(a["osm"]), row_point(b["osm"])) <= 12_000]
              for a in accepted]
    center = min(range(len(accepted)), key=lambda i: (-len(nearby[i]), accepted[i]["osm"]["id"]))
    pool = set(nearby[center]) - {center}
    chosen = [center]
    while pool and len(chosen) < limit:
        best = min(pool, key=lambda i: (-min(metres(row_point(accepted[i]["osm"]), row_point(accepted[j]["osm"])) for j in chosen),
                                         accepted[i]["osm"]["id"]))
        chosen.append(best)
        if min(metres(row_point(accepted[best]["osm"]), row_point(accepted[j]["osm"])) for j in chosen[:-1]) < MIN_ENDPOINT_METRES:
            chosen.pop()
            break
        pool.remove(best)
    return [dict(accepted[i], planning_id=f"C{k:02d}") for k, i in enumerate(chosen, 1)]


def write_json(output_dir, name, data):
    path = output_dir / name
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"file": name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def run(osm_roster, boundaries, nhp_path, output_dir):
    verify_sha256(nhp_path, NHP_SHA)
    verify_sha256(boundaries, DISTRICT_SHA256)
    verify_sha256(osm_roster, ROSTER_SHA)

    source = json.loads(osm_roster.read_bytes())
    if (source["facility_count"] != len(source["facilities"])
            or source["roster_kind"] != "district"
            or source["geography"]["district_boundary"]["feature_id"] != PUNE_ID):
        raise ValueError("Expected the complete Pune district roster from the OSM stage")
    districts, shapes, _ = district_shapes(boundaries)
    district_index, = (i for i, record in enumerate(districts) if record[0] == PUNE_ID)
    nhp, counts = load_nhp(nhp_path, shapes, district_index)
    osm = defaultdict(list)
    collisions = Counter(row_point(row) for row in source["facilities"])
    for row in source["facilities"]:
        osm[key(row["label"])].append(row)

    accepted = []
    rejected = []
    counts["pune_osm_distinct_sites"] = source["facility_count"]
    counts["cross_source_normalized_name_keys"] = len(nhp.keys() & osm.keys())
    for name in sorted(nhp.keys() & osm.keys()):
        public = osm[name]
        authority = nhp[name]
        if len(public) != 1 or len(authority) != 1:
            possible = [(site, record, metres(row_point(site), row_point(record)))
                        for site in public for record in authority]
            viable = [(site, record, dist) for site, record, dist in possible if dist <= MAX_METRES]
            # Multiple exact-name sites anywhere in Pune are possible same-name branches.
            reason = "non_unique_name_in_district" if viable else "non_unique_name_no_close_pair"
            counts[reason] += 1
            rejected.append({"name_key": name, "status": reason, "osm_ids": [row["source_id"] for row in public],
                             "nhp_serial_groups": [row["serial_ids"] for row in authority], "pairs_within_radius": len(viable)})
            continue
        site, record = public[0], authority[0]
        distance = metres(row_point(site), row_point(record))
        if collisions[row_point(site)] != 1 or record["point_name_groups"] != 1:
            reason = "shared_source_coordinate"
        elif not re.fullmatch(r"(?:node|way|relation)/\d+", site["source_id"]):
            reason = "missing_typed_osm_id"
        elif distance > MAX_METRES:
            reason = "point_difference_exceeds_threshold"
        elif near_name_rival(name, site, osm, "source_id") or near_name_rival(name, record, nhp, "serial_ids"):
            reason = "nearby_variant_name_rival"
        else:
            reason = "matched"
        counts[reason] += 1
        if reason == "matched":
            matched_nhp = {k: record[k] for k in ("serial_ids", "label", "longitude", "latitude")}
            matched_nhp.update({"publisher": "National Health Portal, Ministry of Health and Family Welfare, Government of India",
                                "source_url": NHP_URL, "source_license": "GODL-India", "license_url": GODL,
                                "point_precision": "publisher-reported point", "observation_date": None})
            accepted.append({"normalized_name": name, "point_separation_metres": round(distance, 1),
                             "osm": site, "nhp": matched_nhp,
                             "finding": "Two-public-source name and position agreement. Upstream independence and entrance unverified."})
        else:
            rejected.append({"name_key": name, "status": reason, "osm_ids": [site["source_id"]],
                             "nhp_serial_groups": [record["serial_ids"]], "point_separation_metres": round(distance, 1)})
    accepted.sort(key=lambda result: result["osm"]["id"])
    picked = select(accepted)
    attributes = {
        "district": "Pune, Maharashtra, India", "district_shape_id": PUNE_ID,
        "boundary_sha256": DISTRICT_SHA256, "osm_input_roster_sha256": ROSTER_SHA,
        "osm_upstream_sha256": source["source"]["zip_sha256"],
        "nhp_sha256": NHP_SHA, "nhp_source_url": NHP_URL, "max_point_separation_m": MAX_METRES,
        "method": "Require an exact normalized cross-source name with a distinctive token, unique site group in each source across the district, unique coordinates in each source, and at most 100 m between points, with no possible variant-name rival within 300 m. All NHP rows in an admitted group must say Maharashtra and Pune after normalization; no spelling aliases are used. Site grouping comes from the OSM roster and exact NHP name/point pairs. Keep branch and locality words.",
        "scope": "This comparison uses public inputs only. No VF matching, site membership, private geocodes, current clinical evidence or patient data were used.",
        "lineage_limit": "OSM could have imported or copied NHP or a common source. This test measures source-listing agreement and does not establish independent verification, inspection, current operation, service, a verified entrance, or a clinical routing endpoint.",
        "selection_method": "Among accepted sites, start at the site with the most accepted neighbours within 12 km, breaking ties by OSM ID. Within that radius, select up to twelve by greedy maximum minimum separation of at least 200 m, breaking ties by OSM ID. Use the existing OSM point or interior campus anchor only for modeled travel.",
        "counts": dict(counts),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    package = [
        write_json(output_dir, "pune-all-agreements.json", {"metadata": attributes, "facilities": accepted}),
        write_json(output_dir, "pune-screened-out-name-agreements.json", {"metadata": attributes, "facilities": rejected}),
        write_json(output_dir, "pune-planning-agreement-sites.json", {"metadata": attributes, "facilities": picked}),
    ]
    anchor_distances = [metres(row_point(a["osm"]), row_point(b["osm"]))
                        for i, a in enumerate(picked) for b in picked[i + 1:]]
    selected_agreement = [row["point_separation_metres"] for row in picked]
    distribution = {
        "location_classes": dict(Counter(row["osm"]["location_class"] for row in picked)),
        "cross_source_point_separation_m": [min(selected_agreement), max(selected_agreement)] if picked else [],
        "between_selected_osm_anchors_m": [round(min(anchor_distances), 1), round(max(anchor_distances), 1)] if anchor_distances else [],
        "exact_or_near_exact_cross_source_pairs_at_1_m": sum(m <= 1 for m in selected_agreement),
    }
    flat_geo = dict(source["geography"], verification=(
        "Matched public OSM and official NHP names and mapped positions. Possible shared upstream lineage. "
        "These locations supply simulation anchors only and establish neither entrance nor current operation."
    ))
    flat = {key: source[key] for key in ("schema_version", "source", "coordinate_reference_system", "publication", "distinct_district_site_count")}
    flat.update(
        geography=flat_geo, roster_kind="planning_subset",
        facility_count=len(picked), selection_method=attributes["selection_method"],
        location_agreement_method=attributes["method"], selection_distribution=distribution,
        location_agreement_audit_sha256=package[-1]["sha256"],
        facilities=[dict(row["osm"], planning_id=row["planning_id"]) for row in picked],
    )
    package.append(write_json(output_dir, "pune-planning-agreement-roster.storm-roster-v1.json", flat))
    report = dict(attributes, selected_sites=len(picked), selected_distribution=distribution, results=package)
    write_json(output_dir, "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--osm-roster", type=Path, required=True, help="Pune district JSON from the OSM stage")
    parser.add_argument("--boundaries", type=Path, required=True, help="Pinned India 2021 ADM2 GeoJSON")
    parser.add_argument("--nhp", type=Path, required=True, help="Pinned official NHP hospital-directory CSV")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated files")
    args = parser.parse_args(argv)
    try:
        report = run(args.osm_roster, args.boundaries, args.nhp, args.output_dir)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
