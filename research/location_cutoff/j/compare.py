"""Measure overlap between VF source points and mapped clinical premises in private custody."""
import argparse
from collections import Counter
import gzip
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from shapely import STRtree, from_wkb
from shapely.affinity import scale
from shapely.geometry import Point, box

from research.acquisition.issuer_campus_geometry.compare import address_matches, baseline, pin_from
from research.acquisition.issuer_campus_geometry.scan import names, norm, PBF_SHA
from research.acquisition.osm_services.pbf import file_digest

OUTLINES_SHA = "aa6ea4142666696c3f3f6eacd1bab50873dad7542825e23b2de218a5e57b3239"
RADIUS_M = 300
INACTIVE_BUILDINGS = {"no", "construction", "proposed", "demolished", "ruins"}


def building(tags):
    return bool(tags.get("building") and tags["building"] not in INACTIVE_BUILDINGS)


def printed_address(source):
    fields = ("address_line1", "address_line2", "address_line3", "address_zipOrPostcode")
    printed = ", ".join(source[k] for k in fields if source.get(k))
    return {"premises_key": bool(printed), "premises_address": printed, "pin": pin_from(printed)}


def evaluate(source, point, features, tree):
    """Return evidence flags and private candidate details; no point is adjudicated here."""
    x_scale = 111320 * math.cos(math.radians(point.y))
    y_scale = 111320
    bounds = box(point.x - RADIUS_M / x_scale, point.y - RADIUS_M / y_scale,
                 point.x + RADIUS_M / x_scale, point.y + RADIUS_M / y_scale)
    name = norm(source["name"])
    address = printed_address(source)
    pin = address["pin"]
    candidates = []
    for idx in tree.query(bounds):
        record = features[idx]
        geom = record["geometry"]
        tags = record["tags"]
        inside = geom.contains(point)
        boundary = not inside and geom.covers(point)
        distance = 0 if inside or boundary else scale(
            geom, xfact=x_scale, yfact=y_scale, origin=(point.x, point.y)).distance(point)
        if distance > RADIUS_M:
            continue
        osm_pin = tags.get("addr:postcode") or pin_from(tags.get("addr:full"))
        candidates.append({
            "index": int(idx), "id": record["id"], "version": record["version"],
            "interior": inside, "boundary": boundary, "building": building(tags),
            "named": bool(names(tags)), "exact_name": bool(name and name in names(tags)),
            "address_agrees": address_matches(address, tags),
            "pin_conflict": bool(pin and osm_pin and pin != osm_pin),
            "distance_m": round(distance, 3),
        })
    candidates.sort(key=lambda item: item["id"])
    interior = [c for c in candidates if c["interior"]]
    buildings = [c for c in interior if c["building"]]
    grounds = [c for c in interior if not c["building"]]
    adjacent_names = [c for c in candidates if c["exact_name"] and not c["interior"] and not c["boundary"]]
    overlap = any(features[g["index"]]["geometry"].covers(features[b["index"]]["geometry"])
                  for g in grounds for b in buildings)
    rival = any(features[inside["index"]]["geometry"].disjoint(features[other["index"]]["geometry"])
                for inside in interior for other in adjacent_names)
    flags = {
        "within_300m": bool(candidates), "interior": bool(interior),
        "boundary": any(c["boundary"] for c in candidates),
        "inside_mapped_building": bool(buildings), "inside_site_without_building_tag": bool(grounds),
        "inside_both_types": bool(buildings and grounds), "building_nested_in_site": overlap,
        "multiple_containing_objects": len(interior) > 1,
        "inside_named_nonmatching_without_exact_name": bool(any(c["named"] for c in interior)
                                                            and not any(c["exact_name"] for c in interior)),
        "inside_exact_name": any(c["exact_name"] for c in interior),
        "inside_exact_name_building": any(c["exact_name"] for c in buildings),
        "inside_exact_name_and_address": any(c["exact_name"] and c["address_agrees"] for c in interior),
        "inside_building_exact_name_and_address": any(c["exact_name"] and c["address_agrees"] for c in buildings),
        "inside_conflicting_postcode": any(c["pin_conflict"] for c in interior),
        "nearby_exact_name_outside": bool(adjacent_names),
        "inside_one_outline_with_disjoint_exact_name_nearby": rival,
    }
    for c in candidates:
        del c["index"]
    return flags, candidates


def _compare(vf, outlines, ledger):
    frame = baseline(vf)
    if file_digest(outlines) != OUTLINES_SHA:
        raise ValueError("Unexpected clinical outline cache")
    features = []
    skipped = 0
    with outlines.open() as stream:
        for item in map(json.loads, stream):
            if not item["wkb"]:
                skipped += 1
                continue
            geometry = from_wkb(item.pop("wkb"))
            if geometry.is_empty:
                skipped += 1
                continue
            features.append({**item, "geometry": geometry})
    if len({r["id"] for r in features}) != len(features):
        raise ValueError("Repeated typed OSM outline")
    tree = STRtree([r["geometry"] for r in features])
    counts = Counter()
    classes = Counter()
    seen = set()
    with gzip.open(vf / "occurrences.jsonl.gz", "rt") as stream, ledger.open("x") as output:
        for row in map(json.loads, stream):
            identity, source = row["identity"], row["original"]["source_row"]
            key = identity["facility_id"]
            if key in seen:
                raise ValueError("Repeated original occurrence key")
            seen.add(key)
            screen = identity["original_point"]["screen_class"]
            flags, candidates = {}, []
            if screen != "unusable_original_point":
                point = Point(source["longitude"], source["latitude"])
                flags, candidates = evaluate(source, point, features, tree)
                counts.update(flags)
            classes[screen] += 1
            output.write(json.dumps({"occurrence_key": key, "screen": screen, "flags": flags,
                                     "candidates": candidates}, separators=(",", ":")) + "\n")
    if len(seen) != frame["occurrence_count"]:
        raise ValueError("Incomplete national comparison")
    return {"baseline": frame, "pbf_sha256": PBF_SHA, "outlines_sha256": OUTLINES_SHA,
            "outline_objects": len(features), "emitted_unusable_geometries": skipped,
            "point_classes": dict(classes), "occurrences": dict(sorted(counts.items())),
            "candidate_ledger_sha256": file_digest(ledger), "radius_m": RADIUS_M}


def compare(vf, outlines, ledger):
    with TemporaryDirectory(dir=ledger.parent) as temp:
        staged = Path(temp) / "clinical.jsonl"
        summary = _compare(vf, outlines, staged)
        staged.replace(ledger)
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for item in ("vf", "outlines", "ledger", "summary"):
        parser.add_argument(item, type=Path)
    args = parser.parse_args()
    summary = compare(args.vf, args.outlines, args.ledger)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
