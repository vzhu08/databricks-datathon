#!/usr/bin/env python3
"""Building-footprint location checks.

    python -m research.geography.footprints --cases cases.json --buildings buildings.ndjson \
        --snapshot snapshot.json --matches reviewed_batch.json --external a.json \
        --reviewer <name> --reviewed-at <UTC> --output-dir <path>

For each case point this measures the distance in metres to the nearest mapped
building within the search radius and whether the point is inside one. The
result is location evidence only. It says nothing about services or quality,
and a missing footprint is recorded as unknown, never as a negative finding.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from research.matching.common import (MatchingError, canonical, combine_external, empty, file_digest, load,
                                      require, schema_check, stable_id, write_json)
from .checks import number
from .distance import haversine_m, point_to_polygons_m, polygons_of

FOOTPRINT_VERSION = "footprints-1.0.0"
EVIDENCE_NS, REVIEW_NS = "acq-c-spatial", "acq-c-spatial-review"
RADIUS_M = 500.0
OSM_NAMES = ("openstreetmap", "osm")
METHOD = ("Planar point-to-polygon distance in a local equirectangular frame centred on the checked point; "
          "0 when the point lies inside the footprint")


def load_buildings(path):
    """GeoJSON FeatureCollection, or the newline-delimited JSON written by the
    DuckDB script in research.geography.overture."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict) and document.get("type") == "FeatureCollection":
        require(isinstance(document.get("features"), list), "buildings", "FeatureCollection without features")
        rows = [{"id": f.get("id", (f.get("properties") or {}).get("id")), "geometry": f.get("geometry"),
                 **{k: v for k, v in (f.get("properties") or {}).items() if k != "id"}}
                for f in document["features"] if isinstance(f, dict)]
    else:
        try:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError:
            raise MatchingError("buildings: expected a GeoJSON FeatureCollection or newline-delimited JSON")
        require(all(isinstance(r, dict) for r in rows), "buildings", "each line must be a JSON object")
    buildings, skipped = [], Counter()
    for row in rows:
        geometry, sources = row.get("geometry"), row.get("sources")
        if isinstance(geometry, str):
            try:
                geometry = json.loads(geometry)
            except json.JSONDecodeError:
                geometry = None
        if isinstance(sources, str):
            try:
                sources = json.loads(sources)
            except json.JSONDecodeError:
                sources = None
        polygons = polygons_of(geometry)
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            skipped["missing_feature_id"] += 1
            continue
        if polygons is None:
            skipped["unsupported_or_invalid_geometry"] += 1
            continue
        lons = [lon for polygon in polygons for ring in polygon for lon, _ in ring]
        lats = [lat for polygon in polygons for ring in polygon for _, lat in ring]
        buildings.append({"id": identifier, "polygons": polygons,
                          "bounds": (min(lats), min(lons), max(lats), max(lons)),
                          "sources": sources if isinstance(sources, list) else None,
                          "capture_date": row.get("capture_date")})
    ids = Counter(b["id"] for b in buildings)
    require(all(n == 1 for n in ids.values()), "buildings", "repeated feature ID; deduplicate the extract first")
    return sorted(buildings, key=lambda b: b["id"]), dict(skipped)


def lineage(building):
    """Upstream datasets named by the feature, lower-cased; None when unstated."""
    if building["sources"] is None:
        return None
    names = sorted({str(s.get("dataset")).strip() for s in building["sources"]
                    if isinstance(s, dict) and s.get("dataset")})
    return names or None


def building_snapshot(extract_path, release, retrieved_at, artifact_uri, url, license_text=None):
    """Contract snapshot row for one extract. Identity is the extract's bytes."""
    sha = file_digest(extract_path)
    return {
        "snapshot_id": f"overture_buildings:{sha}", "source_key": "overture_buildings",
        "publisher": "Overture Maps Foundation / upstream contributors",
        "source_family": "overture_buildings", "url": url, "retrieved_at": retrieved_at,
        "published_date": None, "license": license_text,
        "attribution": f"Overture Maps Foundation buildings, release {release}; per-feature upstream "
                       "contributors as listed in each feature's sources",
        "sha256": sha, "artifact_uri": artifact_uri, "parser_version": FOOTPRINT_VERSION,
        # Overture buildings reuse OSM and other inputs, so they are never counted as independent.
        "independence_status": "shared_origin",
    }


def nearest(lat, lon, buildings, radius_m):
    best = None
    for b in buildings:
        south, west, north, east = b["bounds"]
        # Cheap reject: the footprint's box is further away than the radius.
        clat, clon = min(max(lat, south), north), min(max(lon, west), east)
        if haversine_m(lat, lon, clat, clon) > radius_m:
            continue
        distance, contained = point_to_polygons_m(lat, lon, b["polygons"])
        if distance is None or distance > radius_m:
            continue
        key = (distance, b["id"])
        if best is None or key < best[0]:
            best = (key, b, contained)
    return (best[1], best[0][0], best[2]) if best else (None, None, False)


def check_cases(cases, known_external):
    require(isinstance(cases, list) and cases, "cases", "expected a non-empty array")
    seen = set()
    for index, case in enumerate(cases):
        path = f"cases[{index}]"
        require(isinstance(case, dict), path, "expected an object")
        require(isinstance(case.get("case_id"), str) and case["case_id"].strip() and case["case_id"] not in seen,
                path + ".case_id", "unique nonempty case_id required")
        seen.add(case["case_id"])
        require(case.get("kind") in ("disputed", "control"), path + ".kind", "must be disputed or control")
        require(case.get("external_facility_id") in known_external, path + ".external_facility_id",
                "must be an external record in the supplied batches")
        require(isinstance(case.get("points"), list) and case["points"], path + ".points", "at least one point")
        labels = set()
        for point in case["points"]:
            require(isinstance(point, dict) and point.get("label") in ("claimed", "corroborated")
                    and point["label"] not in labels, path + ".points", "labels are claimed and/or corroborated, once each")
            labels.add(point["label"])
            lat, lon = number(point.get("latitude")), number(point.get("longitude"))
            require(lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180,
                    path + ".points", "finite WGS84 coordinates required")
            require(isinstance(point.get("coordinate_basis"), str) and point["coordinate_basis"].strip(),
                    path + ".points", "state where each coordinate came from")
    return cases


def observe(cases, buildings, snapshot, matches_batch, external_batch, reviewer=None, reviewed_at=None,
            radius_m=RADIUS_M, stale_before=None):
    """Return {'batch', 'ledger', 'summary'}.

    Evidence rows are written only with review metadata: the claim comes from
    a different source than the identity record, which the contract requires a
    reviewer to check. Without it, observations stay in the ledger and queue.
    """
    require((reviewer is None) == (reviewed_at is None), "reviewer", "reviewer and reviewed_at go together")
    require(0 < radius_m <= RADIUS_M, "radius_m", "bounded neighbourhood only (at most 500 m)")
    stale = date.fromisoformat(stale_before) if stale_before else None
    externals = {e["external_facility_id"]: e for e in external_batch["external_facilities"]}
    families = {s["snapshot_id"]: s["source_family"] for s in external_batch["source_snapshots"]}
    check_cases(cases, externals)
    confirmed = {m["external_facility_id"]: m for m in matches_batch["facility_matches"] if m["status"] == "confirmed"}
    batch, ledger = empty(), []
    batch["source_snapshots"] = [snapshot]
    for case in sorted(cases, key=lambda c: c["case_id"]):
        external_id = case["external_facility_id"]
        match = confirmed.get(external_id)
        identity_family = families.get(externals[external_id]["snapshot_id"])
        for point in sorted(case["points"], key=lambda p: p["label"]):
            lat, lon = float(point["latitude"]), float(point["longitude"])
            building, distance, contained = nearest(lat, lon, buildings, radius_m)
            entry = {"case_id": case["case_id"], "kind": case["kind"], "external_facility_id": external_id,
                     "point_label": point["label"], "latitude": lat, "longitude": lon,
                     "coordinate_basis": point["coordinate_basis"], "search_radius_m": radius_m,
                     "footprint_found": building is not None, "source_feature_id": None, "distance_m": None,
                     "contained": False, "upstream_datasets": None, "shares_origin_with_identity_source": None,
                     "capture_date": None, "evidence_id": None, "linked_to_confirmed_match": False}
            if building is None:
                batch["review_queue"].append(_review(
                    "footprint_not_found", case, point, external_id, match,
                    f"No mapped building within {radius_m:g} m. This is unknown, not evidence against the facility. "
                    "Check the coordinates against the address or another map source."))
                ledger.append(entry)
                continue
            datasets = lineage(building)
            shared = None if datasets is None else (
                identity_family == "osm" and any(d.casefold() in OSM_NAMES for d in datasets))
            capture = building["capture_date"] if isinstance(building["capture_date"], str) else None
            if capture is not None:
                date.fromisoformat(capture)
            limitations = ["A footprint shows a mapped building, not healthcare activity, services or quality",
                           "Footprint datasets are incomplete; a point outside a footprint is not a negative finding"]
            limitations.append("Capture date unknown; the footprint may predate or postdate the facility"
                               if capture is None else f"Footprint capture date {capture}; later changes are not reflected")
            limitations.append("Upstream lineage not stated for this feature" if datasets is None
                               else "Upstream datasets: " + ", ".join(datasets))
            if shared:
                limitations.append("Shares OpenStreetMap origin with the identity record; not independent corroboration")
            is_stale = capture is not None and stale is not None and date.fromisoformat(capture) < stale
            if is_stale:
                limitations.append(f"Footprint captured before {stale.isoformat()}; treated as historical")
            polarity = "supports" if contained and not shared and not is_stale else "inconclusive"
            where = "inside" if contained else f"{round(distance, 1)} m from"
            evidence_id = stable_id(EVIDENCE_NS, external_id, snapshot["snapshot_id"], building["id"],
                                    point["label"], lat, lon)
            entry.update({"source_feature_id": building["id"], "distance_m": round(distance, 1),
                          "contained": contained, "upstream_datasets": datasets,
                          "shares_origin_with_identity_source": shared, "capture_date": capture,
                          "polarity": polarity})
            if shared or is_stale:
                batch["review_queue"].append(_review(
                    "footprint_shared_origin" if shared else "footprint_stale", case, point, external_id, match,
                    "The footprint cannot corroborate this location independently. Look for a second, unrelated source."
                    if shared else "The footprint is old. Check a newer source before relying on it."))
            if reviewer is not None:
                batch["facility_evidence"].append({
                    "evidence_id": evidence_id, "external_facility_id": external_id,
                    "snapshot_id": snapshot["snapshot_id"],
                    "facility_id": match["facility_id"] if match else None,
                    "match_id": match["match_id"] if match else None,
                    "claim_type": "location", "service": None, "polarity": polarity,
                    "assertion": f"The {point['label']} coordinate is {where} building footprint {building['id']}. "
                                 "Location plausibility only; no clinical interpretation.",
                    "excerpt": None,
                    "observation": {"method": METHOD, "source_feature_id": building["id"],
                                    "distance_m": round(distance, 1), "units": "metres",
                                    "latitude": lat, "longitude": lon,
                                    "coordinate_basis": point["coordinate_basis"],
                                    "capture_date": capture, "limitations": limitations},
                    "locator": f"building feature {building['id']}", "source_url": snapshot["url"],
                    "effective_date": capture, "valid_until": None,
                    "temporal_status": "undated" if capture is None else "historical" if is_stale else "dated",
                    "reviewer": reviewer, "reviewed_at": reviewed_at})
                entry["evidence_id"] = evidence_id
                entry["linked_to_confirmed_match"] = match is not None
            ledger.append(entry)
    batch["facility_evidence"].sort(key=lambda r: r["evidence_id"])
    batch["review_queue"].sort(key=lambda r: r["review_id"])
    schema_check(batch, "footprints")
    kinds = Counter(c["kind"] for c in cases)
    summary = {
        "cases": len(cases), "disputed": kinds.get("disputed", 0), "controls": kinds.get("control", 0),
        "points_checked": len(ledger), "search_radius_m": radius_m, "units": "metres",
        "footprint_found": sum(e["footprint_found"] for e in ledger),
        "footprint_not_found_unknown": sum(not e["footprint_found"] for e in ledger),
        "point_inside_footprint": sum(e["contained"] for e in ledger),
        "shares_origin_with_identity_source": sum(bool(e["shares_origin_with_identity_source"]) for e in ledger),
        "capture_date_unknown": sum(e["footprint_found"] and e["capture_date"] is None for e in ledger),
        "evidence_rows_emitted": len(batch["facility_evidence"]),
        "evidence_rows_held_back_without_reviewer": 0 if reviewer else sum(e["footprint_found"] for e in ledger),
        "building_snapshot_id": snapshot["snapshot_id"],
        "interpretation": "Coverage of the selected cases only. Footprints are a location plausibility cue; "
                          "they are not a clinical or fraud signal, and absence is unknown.",
    }
    return {"batch": batch, "ledger": ledger, "summary": summary}


def _review(reason, case, point, external_id, match, action):
    return {"review_id": stable_id(REVIEW_NS, reason, case["case_id"], point["label"]),
            "facility_id": match["facility_id"] if match else None, "external_facility_id": external_id,
            "evidence_id": None, "match_id": match["match_id"] if match else None, "reason_code": reason,
            "severity": "low", "status": "open", "next_action": action, "resolution": None}


def select_cases(candidates, externals, bases, disputed=10, controls=10, dispute_m=1000.0, control_m=150.0):
    """Pick footprint cases from a matching run's candidate ledger.

    Disputed: serious name candidates whose two coordinates are more than
    `dispute_m` apart. Controls: strong-name candidates within `control_m` and
    with no geography conflict. Order is the SHA-256 of the match ID. Fewer
    eligible cases than requested returns all of them.
    """
    from research.matching.common import digest
    base_coord = {b["id"]: b["coord"] for b in bases}
    ext_coord = {e["id"]: e["coord"] for e in externals}
    pools = {"disputed": [], "control": []}
    for c in candidates:
        s, flags = c["signals"], set(c["flags"])
        if s["distance_m"] is None or s["name_level"] not in ("strong", "moderate"):
            continue
        if s["distance_m"] > dispute_m:
            pools["disputed"].append(c)
        elif (s["distance_m"] <= control_m and s["name_level"] == "strong"
              and not flags & {"state_conflict", "place_conflict", "pin_conflict", "ambiguous_campus"}):
            pools["control"].append(c)
    cases = []
    for kind, limit in (("disputed", disputed), ("control", controls)):
        for c in sorted(pools[kind], key=lambda c: digest(c["match_id"]))[:limit]:
            b, e = base_coord[c["facility_id"]], ext_coord[c["external_facility_id"]]
            points = [{"label": "claimed", "latitude": b["lat"], "longitude": b["lon"],
                       "coordinate_basis": "Base row coordinates as supplied (original, unmodified)"}]
            if (b["lat"], b["lon"]) != (e["lat"], e["lon"]):
                points.append({"label": "corroborated", "latitude": e["lat"], "longitude": e["lon"],
                               "coordinate_basis": "External record coordinates as normalised by its producer"})
            cases.append({"case_id": f"{kind}:{c['match_id']}", "kind": kind, "match_id": c["match_id"],
                          "facility_id": c["facility_id"], "external_facility_id": c["external_facility_id"],
                          "points": points})
    eligible = {kind: len(pool) for kind, pool in pools.items()}
    return cases, {"eligible": eligible, "selected": dict(Counter(c["kind"] for c in cases)),
                   "rule": f"disputed: name strong/moderate and coordinates > {dispute_m:g} m apart; "
                           f"control: name strong, <= {control_m:g} m, no geography conflict or campus ambiguity; "
                           "ordered by SHA-256 of match_id"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.footprints", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--buildings", required=True, help="Bounded extract (NDJSON or GeoJSON), outside Git")
    parser.add_argument("--snapshot", required=True, help="source_snapshots row for the extract (see README)")
    parser.add_argument("--matches", required=True, help="C's batch: links are attached only to confirmed matches")
    parser.add_argument("--external", required=True, action="append")
    parser.add_argument("--reviewer")
    parser.add_argument("--reviewed-at")
    parser.add_argument("--radius-m", type=float, default=RADIUS_M)
    parser.add_argument("--stale-before", help="ISO date; footprints captured earlier are historical")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        snapshot = load(args.snapshot)
        require(isinstance(snapshot, dict) and snapshot.get("sha256") == file_digest(args.buildings), "snapshot",
                "snapshot sha256 does not match the buildings file")
        buildings, skipped = load_buildings(args.buildings)
        result = observe(load(args.cases), buildings, snapshot, load(args.matches),
                         combine_external([load(p) for p in args.external]), args.reviewer, args.reviewed_at,
                         args.radius_m, args.stale_before)
        result["summary"]["buildings_loaded"] = len(buildings)
        result["summary"]["buildings_skipped"] = skipped
        out = Path(args.output_dir)
        hashes = {name: write_json(out / f"footprint_{name}.json", result[name]) for name in ("batch", "ledger", "summary")}
        print(canonical({"status": "ok", "summary": result["summary"], "sha256": hashes}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
