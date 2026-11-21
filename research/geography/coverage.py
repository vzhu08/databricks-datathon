#!/usr/bin/env python3
"""Building-footprint coverage on a frozen public sample (ACQ-C02).

    python -m research.geography.coverage freeze --frame explicit.json --output-dir <dir>
    python -m research.geography.coverage measure --sample <dir>/sample.json \
        --overture buildings.ndjson --release <release> [--google google.ndjson] \
        [--imagery imagery.json] --output-dir <dir>
    python -m research.geography.coverage manifest --dir <dir>

`freeze` draws a deterministic sample of public reference coordinates from one
external batch. `measure` records, for every sampled point, which mapped
buildings lie within the search radius, how far the nearest one is in metres,
whether the point is inside one, and which upstream dataset each came from.

Nothing here links a point to an original facility row or says anything about
services. A footprint supports building-location plausibility only when its
origin differs from the reference point's origin. Missing coverage is unknown.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from research.matching.common import MatchingError, canonical, digest, file_digest, load, require, write_json
from .checks import decimals, number
from .distance import haversine_m, point_to_polygons_m
from .footprints import lineage, load_buildings

SAMPLE_VERSION = "rajasthan-footprint-sample-1.0.0"
COVERAGE_VERSION = "footprint-coverage-1.1.0"
# A's screening rectangle for Rajasthan (rajasthan-candidates-1.0.0): not a state polygon.
RECTANGLE = {"lon_min": 69.4, "lon_max": 78.35, "lat_min": 23.0, "lat_max": 30.25}
STRATA = ("isolated_point_control", "mapped_area_control", "ambiguous_neighbour", "coarse_coordinate")
ROLE = {"isolated_point_control": "control", "mapped_area_control": "control",
        "ambiguous_neighbour": "challenge", "coarse_coordinate": "challenge"}
MAX_CASES = 20
RADIUS_M = 500.0
NEAR_M = 150.0
ISOLATED_M = 500.0
COARSE_DECIMALS = 4
FINE_DECIMALS = 6
BANDS_M = (25.0, 100.0, 500.0)
RULE = (
    "Frame: every external record in the supplied batch. Eligible: facility_type 'hospital', a source name, "
    "finite coordinates inside the Rajasthan screening rectangle. Each eligible record gets the first stratum "
    "that applies: mapped_area_control (coordinate is the interior point of a mapped area); coarse_coordinate "
    f"(a source point with at most {COARSE_DECIMALS} decimals on either axis); ambiguous_neighbour (a source "
    f"point with another frame record of a different name within {NEAR_M:g} m); isolated_point_control (a source "
    f"point with at least {FINE_DECIMALS} decimals on both axes, a name used once in the frame and no other frame "
    f"record within {ISOLATED_M:g} m). Other eligible records are not sampled. Within a stratum, records are "
    "ordered by SHA-256 of [sample version, external_facility_id] and the first N are taken."
)


def origin_family(dataset):
    """Collapse an upstream dataset name to its origin, so reuse counts once."""
    text = str(dataset or "").casefold().strip()
    if text in {"", "none", "unknown", "unassessed", "unstated", "unspecified"}:
        return "unstated"
    if "openstreetmap" in text or text.strip() == "osm":
        return "osm"
    if "google" in text:
        return "google_open_buildings"
    if "microsoft" in text:
        return "microsoft_ml_buildings"
    if "esri" in text:
        return "esri_community_maps"
    slug = "".join(c if c.isalnum() else "_" for c in text).strip("_")
    return slug or "unstated"


def families_of(building):
    sources = building["sources"] or []
    return sorted({origin_family(s.get("dataset") if isinstance(s, dict) else None) for s in sources}
                  or {"unstated"})


def _grid(rows, cell=0.01):
    grid = defaultdict(list)
    for row in rows:
        grid[(math.floor(row["latitude"] / cell), math.floor(row["longitude"] / cell))].append(row)
    return grid, cell


def _neighbours(row, grid, cell, radius_m):
    lat, lon = row["latitude"], row["longitude"]
    reach_lat = int(math.ceil(radius_m / 111000.0 / cell))
    reach_lon = int(math.ceil(radius_m / (111000.0 * max(math.cos(math.radians(lat)), 0.1)) / cell))
    found = []
    for i in range(-reach_lat, reach_lat + 1):
        for j in range(-reach_lon, reach_lon + 1):
            for other in grid.get((math.floor(lat / cell) + i, math.floor(lon / cell) + j), ()):
                if other is not row and haversine_m(lat, lon, other["latitude"], other["longitude"]) <= radius_m:
                    found.append(other)
    return found


def freeze(batch, per_stratum=5, frame_file_sha256=None):
    """Return the frozen sample document for one external batch."""
    require(isinstance(per_stratum, int) and 1 <= per_stratum and per_stratum * len(STRATA) <= MAX_CASES,
            "per_stratum", f"at most {MAX_CASES} cases in total")
    require(isinstance(batch, dict) and isinstance(batch.get("external_facilities"), list)
            and isinstance(batch.get("source_snapshots"), list), "frame", "expected a contract batch")
    snapshots = {s["snapshot_id"]: s for s in batch["source_snapshots"]}
    rows = batch["external_facilities"]
    ids = Counter(r["external_facility_id"] for r in rows)
    require(all(n == 1 for n in ids.values()), "frame", "repeated external_facility_id")
    located = []
    for row in rows:
        lat, lon = number(row.get("latitude")), number(row.get("longitude"))
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            located.append({**row, "latitude": lat, "longitude": lon})
    grid, cell = _grid(located)
    name_uses = Counter(r.get("name_normalized") for r in rows if r.get("name_normalized"))
    exclusions, pools, unsampled = Counter(), {s: [] for s in STRATA}, 0
    located_ids = {r["external_facility_id"]: r for r in located}
    for row in rows:
        if row.get("facility_type") != "hospital":
            exclusions["not_hospital_type"] += 1
            continue
        if not row.get("name_original") or not row.get("name_normalized"):
            exclusions["name_missing"] += 1
            continue
        point = located_ids.get(row["external_facility_id"])
        if point is None:
            exclusions["coordinates_unusable"] += 1
            continue
        if not (RECTANGLE["lat_min"] <= point["latitude"] <= RECTANGLE["lat_max"]
                and RECTANGLE["lon_min"] <= point["longitude"] <= RECTANGLE["lon_max"]):
            exclusions["outside_rajasthan_rectangle"] += 1
            continue
        near = _neighbours(point, grid, cell, NEAR_M)
        wide = _neighbours(point, grid, cell, ISOLATED_M)
        places = min(decimals(point["latitude"]) or 0, decimals(point["longitude"]) or 0)
        method = row.get("coordinate_method")
        entry = {"row": point, "places": places, "near": len(near), "wide": len(wide)}
        if method == "polygon_representative_point":
            pools["mapped_area_control"].append(entry)
        elif method != "source_point":
            exclusions["coordinate_method_other"] += 1
        elif places <= COARSE_DECIMALS:
            pools["coarse_coordinate"].append(entry)
        elif any(o.get("name_normalized") != row["name_normalized"] for o in near):
            pools["ambiguous_neighbour"].append(entry)
        elif places >= FINE_DECIMALS and not wide and name_uses[row["name_normalized"]] == 1:
            pools["isolated_point_control"].append(entry)
        else:
            unsampled += 1
    cases = []
    for stratum in STRATA:
        ordered = sorted(pools[stratum], key=lambda e: digest([SAMPLE_VERSION, e["row"]["external_facility_id"]]))
        for entry in ordered[:per_stratum]:
            row, mapped = entry["row"], stratum == "mapped_area_control"
            snapshot = snapshots.get(row["snapshot_id"], {})
            cases.append({
                "case_id": f"{stratum}:{row['external_facility_id']}", "stratum": stratum, "role": ROLE[stratum],
                "external_facility_id": row["external_facility_id"], "snapshot_id": row["snapshot_id"],
                "reference_origin": origin_family(snapshot.get("source_family", "unstated")),
                "frame_neighbours_within_150_m": entry["near"], "frame_neighbours_within_500_m": entry["wide"],
                "points": [{
                    "label": "reference", "latitude": row["latitude"], "longitude": row["longitude"],
                    "coordinate_method": row["coordinate_method"],
                    "coordinate_basis": ("Interior point computed by the producer from the source's mapped area; "
                                         "not an entrance" if mapped else
                                         "Point coordinates as published by the source, unmodified"),
                    "coordinate_decimals": None if mapped else entry["places"],
                    "coordinate_resolution_m": None if mapped else round(111320.0 * 10 ** -entry["places"], 3),
                }]})
    frame = {
        "snapshots": [{"snapshot_id": s["snapshot_id"], "source_key": s.get("source_key"),
                       "source_family": s.get("source_family"), "sha256": s.get("sha256"),
                       "license": s.get("license")}
                      for s in sorted(batch["source_snapshots"], key=lambda s: s["snapshot_id"])],
        "geography": "Records the producer's rule marks as explicitly in Rajasthan, screened to the rectangle "
                     "below. The rectangle is not a state boundary.",
        "rectangle": RECTANGLE, "frame_rows": len(rows), "eligible_rows": sum(len(p) for p in pools.values()) + unsampled,
        "exclusions": dict(sorted(exclusions.items())), "eligible_but_in_no_stratum": unsampled,
        "frame_file_sha256": frame_file_sha256,
    }
    body = {"sample_version": SAMPLE_VERSION, "rule": RULE, "frame": frame,
            "strata": {s: {"eligible": len(pools[s]), "selected": sum(c["stratum"] == s for c in cases),
                           "role": ROLE[s]} for s in STRATA},
            "cases": cases}
    require(len(cases) <= MAX_CASES, "sample", "too many cases")
    body["sample_sha256"] = digest(body)
    return body


def check_sample(sample):
    require(isinstance(sample, dict) and sample.get("sample_version") == SAMPLE_VERSION
            and isinstance(sample.get("cases"), list) and sample["cases"], "sample", "not a frozen sample")
    body = {k: v for k, v in sample.items() if k != "sample_sha256"}
    require(digest(body) == sample.get("sample_sha256"), "sample", "content does not match its recorded hash")
    require(len(sample["cases"]) <= MAX_CASES, "sample", "too many cases")
    return sample


def _near(lat, lon, buildings, radius_m):
    """Every building within the radius as (distance_m, contained, building), nearest first."""
    found = []
    for b in buildings:
        south, west, north, east = b["bounds"]
        clat, clon = min(max(lat, south), north), min(max(lon, west), east)
        if haversine_m(lat, lon, clat, clon) > radius_m:
            continue
        distance, contained = point_to_polygons_m(lat, lon, b["polygons"])
        if distance is not None and distance <= radius_m:
            found.append((distance, contained, b))
    return sorted(found, key=lambda item: (item[0], item[2]["id"]))


def _update_time(building):
    times = sorted(str(s["update_time"]) for s in (building["sources"] or [])
                   if isinstance(s, dict) and s.get("update_time"))
    return times[-1] if times else None


def _versions(building):
    return {str(s["dataset"]): str(s["version"]) for s in (building["sources"] or [])
            if isinstance(s, dict) and s.get("dataset") and s.get("version")} or None


def _describe(item, reference_origin):
    if item is None:
        return None
    distance, contained, b = item
    families = families_of(b)
    return {"feature_id": b["id"], "distance_m": round(distance, 1), "contained": contained,
            "upstream_datasets": lineage(b), "origins": families,
            "shares_origin_with_reference": reference_origin in families,
            "origin_stated": "unstated" not in families,
            "upstream_dataset_versions": _versions(b),
            "upstream_record_update_time": _update_time(b)}


def _independent(building, reference_origin):
    families = families_of(building)
    reference = origin_family(reference_origin)
    return reference != "unstated" and "unstated" not in families and reference not in families


def _source_view(found, reference_origin):
    by_origin = Counter()
    for _, _, b in found:
        for family in families_of(b):
            by_origin[family] += 1
    independent = [item for item in found if _independent(item[2], reference_origin)]
    return {"features_within_radius": len(found), "features_by_origin": dict(sorted(by_origin.items())),
            "features_within_band_m": {f"{band:g}": sum(d <= band for d, _, _ in found) for band in BANDS_M},
            "nearest": _describe(found[0] if found else None, reference_origin),
            "nearest_other_origin": _describe(independent[0] if independent else None, reference_origin)}


def measure(sample, overture, google=None, imagery=None, radius_m=RADIUS_M, release=None):
    """Per-point observations and coverage by stratum. Returns {'observations', 'summary'}."""
    check_sample(sample)
    require(isinstance(radius_m, (int, float)) and 0 < radius_m <= RADIUS_M, "radius_m", "at most 500 m")
    imagery = imagery or {}
    google_cases = None if google is None else set(google["compared_case_ids"])
    observations = []
    seen = {"overture_google": {}, "direct_google": set(), "overture": set()}
    for case in sorted(sample["cases"], key=lambda c: c["case_id"]):
        point, origin = case["points"][0], case["reference_origin"]
        lat, lon = point["latitude"], point["longitude"]
        over = _near(lat, lon, overture, radius_m)
        compared = google_cases is not None and case["case_id"] in google_cases
        goog = _near(lat, lon, google["buildings"], radius_m) if compared else []
        if compared:
            for _, _, b in over:
                seen["overture"].add(b["id"])
                for source in b["sources"] or []:
                    if isinstance(source, dict) and origin_family(source.get("dataset")) == "google_open_buildings":
                        seen["overture_google"][b["id"]] = source.get("record_id")
            seen["direct_google"].update(b["id"].split(":", 1)[-1] for _, _, b in goog)
        containing = [item for item in over + goog if item[1]]
        origins_containing = sorted({f for _, _, b in containing for f in families_of(b)})
        other_origins = sorted({f for _, _, b in containing if _independent(b, origin) for f in families_of(b)
                                if f not in (origin, "unstated")})
        limitations = ["A footprint shows a mapped building, not healthcare activity, services or quality",
                       "No capture date is published per feature; an upstream record update time is not an image date"]
        resolution = point.get("coordinate_resolution_m")
        if point["coordinate_method"] == "polygon_representative_point":
            limitations.append("The reference point was computed from a mapped area of the same origin as the "
                               "reference record, so containment by that area's own building is expected")
        elif resolution is not None and resolution >= 10:
            limitations.append(f"Coordinate published to about {resolution:g} m; containment within that margin "
                               "is not established")
        if not over and not goog:
            finding, reason = "no_footprint_within_radius", (
                f"No mapped building within {radius_m:g} m in the sources compared. Coverage is unknown, "
                "not evidence against the location.")
        elif not containing:
            nearest = min(item[0] for item in over + goog)
            finding, reason = "footprint_nearby_point_outside", (
                f"Nearest mapped building is {round(nearest, 1)} m away and none contains the point. A point "
                "can mark an entrance, a campus centre or a street address.")
        elif origin_family(origin) == "unstated":
            finding, reason = "inside_footprint_reference_origin_unknown", (
                "The source of the reference coordinate is unknown, so independence cannot be assessed.")
        elif not other_origins:
            finding, reason = "inside_footprint_of_reference_origin_only", (
                "Every footprint containing the point has the reference record's own origin or an unstated one, "
                "so it adds no independent support.")
        else:
            finding, reason = "inside_footprint_of_other_origin", None
        observation = {
            "case_id": case["case_id"], "stratum": case["stratum"], "role": case["role"],
            "external_facility_id": case["external_facility_id"], "reference_origin": origin,
            "latitude": lat, "longitude": lon, "coordinate_method": point["coordinate_method"],
            "coordinate_basis": point["coordinate_basis"], "coordinate_decimals": point.get("coordinate_decimals"),
            "coordinate_resolution_m": resolution, "search_radius_m": radius_m, "units": "metres",
            "overture": _source_view(over, origin),
            "google_open_buildings": ({"compared": True, **_source_view(goog, origin)} if compared else
                                      {"compared": False, "reason": "outside the bounded comparison subset"
                                       if google is not None else "comparison not run"}),
            "origins_containing_point": origins_containing,
            "other_origins_containing_point": other_origins,
            "finding": finding,
            "supports_building_location_plausibility": finding == "inside_footprint_of_other_origin",
            "inconclusive_reason": reason, "capture_date": None, "limitations": limitations,
            "imagery": imagery.get(case["case_id"]),
        }
        observations.append(observation)
    summary = _summary(sample, observations, google, radius_m, release)
    if google is not None:
        reused = {code for code in seen["overture_google"].values() if code in seen["direct_google"]}
        summary["source_overlap"] = {
            "scope": "Buildings within the search radius of the compared points",
            "overture_features": len(seen["overture"]),
            "overture_features_from_google": len(seen["overture_google"]),
            "of_which_same_record_in_google_files": len(reused),
            "google_file_features": len(seen["direct_google"]),
            "google_file_features_not_carried_by_overture": len(seen["direct_google"] - reused),
            "note": "A Google record carried by Overture and found again in Google's own files is one origin. "
                    "Records are matched on the published building code; versions of the Google dataset can differ.",
        }
    return {"observations": observations, "summary": summary}


def _summary(sample, observations, google, radius_m, release):
    def block(rows):
        distances = [o["overture"]["nearest"]["distance_m"] for o in rows if o["overture"]["nearest"]]
        compared = [o for o in rows if o["google_open_buildings"]["compared"]]
        return {
            "points": len(rows),
            "finding": dict(sorted(Counter(o["finding"] for o in rows).items())),
            "overture_any_footprint_within_m": {
                f"{band:g}": sum(o["overture"]["features_within_band_m"][f"{band:g}"] > 0 for o in rows)
                for band in BANDS_M if band <= radius_m},
            "overture_point_inside_any_footprint": sum(bool(o["overture"]["nearest"] and o["overture"]["nearest"]["contained"])
                                                       for o in rows),
            "overture_nearest_shares_reference_origin": sum(bool(o["overture"]["nearest"]
                                                                 and o["overture"]["nearest"]["shares_origin_with_reference"])
                                                            for o in rows),
            "overture_nearest_distance_m_median": round(statistics.median(distances), 1) if distances else None,
            "google_compared_points": len(compared),
            "google_any_footprint_within_radius": sum(o["google_open_buildings"]["features_within_radius"] > 0
                                                      for o in compared),
            "google_point_inside_footprint": sum(bool(o["google_open_buildings"]["nearest"]
                                                      and o["google_open_buildings"]["nearest"]["contained"])
                                                 for o in compared),
            "supports_building_location_plausibility": sum(o["supports_building_location_plausibility"] for o in rows),
            "imagery_recorded": sum(o["imagery"] is not None for o in rows),
        }
    origins = Counter()
    for o in observations:
        origins.update(o["overture"]["features_by_origin"])
    return {
        "coverage_version": COVERAGE_VERSION, "sample_sha256": sample["sample_sha256"],
        "sample_version": sample["sample_version"], "overture_release": release,
        "search_radius_m": radius_m, "units": "metres", "denominator_points": len(observations),
        "all": block(observations),
        "by_stratum": {s: block([o for o in observations if o["stratum"] == s]) for s in STRATA
                       if any(o["stratum"] == s for o in observations)},
        "overture_features_near_sample_by_origin": dict(sorted(origins.items())),
        "google_comparison": None if google is None else {
            "cells": google.get("cells"), "compared_case_ids": len(google["compared_case_ids"]),
            "features_loaded": len(google["buildings"])},
        "interpretation": "Coverage of the frozen sample only; no population rate. A footprint is a location "
                          "plausibility cue. Reuse of one upstream dataset counts as one origin, and a footprint "
                          "sharing the reference record's origin adds no independent support. Absence is unknown.",
    }


def _cmd_freeze(args):
    sample = freeze(load(args.frame), args.per_stratum, file_digest(args.frame))
    out = Path(args.output_dir)
    hashes = {"sample.json": write_json(out / "sample.json", sample, exclusive=True)}
    print(canonical({"status": "ok", "sample_sha256": sample["sample_sha256"], "strata": sample["strata"],
                     "frame": {k: sample["frame"][k] for k in ("frame_rows", "eligible_rows", "exclusions",
                                                                 "eligible_but_in_no_stratum")},
                     "files": hashes}))


def _cmd_measure(args):
    sample = check_sample(load(args.sample))
    overture, skipped = load_buildings(args.overture)
    google = None
    if args.google:
        from .open_buildings import EXTRACT_VERSION
        document = load(args.google_manifest)
        require(document.get("extract_version") == EXTRACT_VERSION, "google", "rebuild with boundary-aware extraction")
        require(document.get("sample_sha256") == sample["sample_sha256"], "google", "sample hash mismatch")
        require(document.get("extract_sha256") == file_digest(args.google), "google", "extract hash mismatch")
        radius = number(document.get("radius_m"))
        require(radius is not None and args.radius_m <= radius <= RADIUS_M, "google", "insufficient extract radius")
        required = document.get("required_cells")
        case_ids = {c["case_id"] for c in sample["cases"]}
        require(isinstance(required, dict) and set(required) == case_ids, "google", "cell coverage missing for sample")
        read = {c["token"] for c in document["cells"]}
        for tokens in required.values():
            require(isinstance(tokens, list) and tokens and all(isinstance(t, str) and t for t in tokens),
                    "google", "invalid required cell list")
        complete = sorted(c for c, tokens in required.items() if set(tokens).issubset(read))
        require(document.get("compared_case_ids") == complete, "google", "inconsistent comparison denominator")
        require(document.get("not_compared_case_ids") == sorted(case_ids - set(complete)),
                "google", "inconsistent excluded cases")
        buildings, google_skipped = load_buildings(args.google)
        google = {"buildings": buildings, "compared_case_ids": document["compared_case_ids"],
                  "cells": document.get("cells"), "skipped": google_skipped}
    imagery = None
    if args.imagery:
        rows = load(args.imagery)
        require(isinstance(rows, list), "imagery", "expected an array")
        imagery = {r["case_id"]: {k: v for k, v in r.items() if k != "case_id"} for r in rows}
    result = measure(sample, overture, google, imagery, args.radius_m, args.release)
    result["summary"]["overture_extract_sha256"] = file_digest(args.overture)
    result["summary"]["overture_features_loaded"] = len(overture)
    result["summary"]["overture_features_skipped"] = skipped
    if google is not None:
        result["summary"]["google_extract_sha256"] = file_digest(args.google)
    out = Path(args.output_dir)
    hashes = {f"{name}.json": write_json(out / f"{name}.json", result[name]) for name in ("observations", "summary")}
    print(canonical({"status": "ok", "summary": result["summary"], "files": hashes}))


ARTIFACTS = {
    "sample.json": "Frozen public sample: frame, rule, strata, points and sample hash",
    "overture_buildings.ndjson": "Bounded building extract from the pinned Overture release",
    "google_buildings.ndjson": "Bounded Google Open Buildings comparison extract",
    "google_manifest.json": "Cells read for the Google comparison, with object hashes and row counts",
    "imagery.json": "Per-point Sentinel-2 scene details",
    "observations.json": "Per-point observations, all sources",
    "summary.json": "Coverage by stratum with denominators, all sources",
}


def manifest(folder):
    """Hashes and sizes of the run's files, for handing to other owners. Paths are relative."""
    folder = Path(folder)
    sample = check_sample(load(folder / "sample.json"))
    files = []
    for name, purpose in ARTIFACTS.items():
        path = folder / name
        if path.is_file():
            files.append({"path": name, "sha256": file_digest(path), "bytes": path.stat().st_size, "purpose": purpose})
    summary = load(folder / "summary.json") if (folder / "summary.json").is_file() else {}
    return {"coverage_version": COVERAGE_VERSION, "sample_version": sample["sample_version"],
            "sample_sha256": sample["sample_sha256"],
            # The points alone: equal for any batch that holds the same frame rows, whatever else it carries.
            "cases_sha256": digest(sample["cases"]),
            "overture_release": summary.get("overture_release"),
            "frame_snapshots": sample["frame"]["snapshots"], "files": files,
            "storage": "Ignored local storage or an authorized Volume only. Never commit these files.",
            "terms": "Building and reference data derive from OpenStreetMap (ODbL 1.0), Overture Maps and Google "
                     "Open Buildings; imagery details derive from Copernicus Sentinel data. "
                     "Confirm each source's terms before moving a file to another environment."}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.coverage", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("freeze")
    one.add_argument("--frame", required=True, help="External batch that defines the sampling frame")
    one.add_argument("--per-stratum", type=int, default=5)
    one.add_argument("--output-dir", required=True)
    two = commands.add_parser("measure")
    two.add_argument("--sample", required=True)
    two.add_argument("--overture", required=True, help="Bounded building extract (NDJSON), outside Git")
    two.add_argument("--release", required=True)
    two.add_argument("--google", help="Bounded Google Open Buildings extract (NDJSON)")
    two.add_argument("--google-manifest", help="Manifest written with the Google extract")
    two.add_argument("--imagery", help="Optional per-case imagery metadata")
    two.add_argument("--radius-m", type=float, default=RADIUS_M)
    two.add_argument("--output-dir", required=True)
    three = commands.add_parser("manifest")
    three.add_argument("--dir", required=True, help="Folder holding sample.json and the run's outputs")
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            document = manifest(args.dir)
            print(canonical({"status": "ok", "files": len(document["files"]),
                             "manifest_sha256": write_json(Path(args.dir) / "manifest.json", document)}))
            return 0
        if args.command == "measure":
            require(bool(args.google) == bool(args.google_manifest), "google", "--google needs --google-manifest")
        (_cmd_freeze if args.command == "freeze" else _cmd_measure)(args)
        return 0
    except (MatchingError, OSError, ValueError, KeyError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
