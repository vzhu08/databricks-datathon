"""Join A's pinned shortlist to physical-site evidence in memory and output only counts."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

import osmium
from shapely import STRtree, from_wkb
from shapely.geometry import Point

from research.acquisition.issuer_campus_geometry.compare import point_distance
from research.acquisition.issuer_campus_geometry.scan import PBF_SHA
from research.acquisition.osm_services.pbf import file_digest
from .compare import evaluate

A_MANIFEST = "9bdb5a057d5bcbd6b967a5896544b74718966a300e51070b741412b64b1b24d7"


def selected_building_shapes(pbf, ids):
    """Recover just the VF-containing buildings for the address shortlist from the original PBF."""
    if file_digest(pbf) != PBF_SHA:
        raise ValueError("Unexpected India PBF edition")
    if not ids:
        return {}
    # libosmium assigns even area IDs to ways, odd ones to relations. Keep only
    # the selected assembled objects while preserving holes and relation members.
    area_ids, relation_ids = set(), set()
    for typed in ids:
        kind, ident = typed.split("/")
        ident = int(ident)
        if kind == "relation":
            relation_ids.add(ident)
        area_ids.add(2 * ident + int(kind == "relation"))
    result = {}
    with TemporaryDirectory() as temp:
        reader = osmium.FileProcessor(pbf).with_locations(f"sparse_file_array,{temp}/nodes")
        reader.with_areas(osmium.filter.IdFilter(relation_ids)).with_filter(osmium.filter.IdFilter(area_ids))
        factory = osmium.geom.WKBFactory()
        for obj in reader:
            if obj.is_area():
                kind = "way" if obj.from_way() else "relation"
                key = f"{kind}/{obj.orig_id()}"
                if key in ids:
                    result[key] = from_wkb(factory.create_multipolygon(obj))
    if result.keys() != ids:
        raise ValueError("Could not recover every shortlisted mapped building")
    return result


def run(method, issuer, vf, directory, pbf):
    if file_digest(method / "manifest.json") != A_MANIFEST:
        raise ValueError("Unexpected A method manifest")
    manifest = json.loads((method / "manifest.json").read_text())
    for name, entry in manifest["files"].items():
        if file_digest(method / name) != entry["sha256"]:
            raise ValueError("Unexpected A method member")
    for path, field in ((issuer, "issuer"), (vf, "vf")):
        if file_digest(path) != manifest["input_sha256"][field]:
            raise ValueError(f"Unexpected A {field} edition")
    sys.path.insert(0, str(method.resolve()))
    from shortlist import iter_shortlist, tied_streets

    shortlist = list(iter_shortlist(issuer, vf, method))
    keys = {x[0] for x in shortlist}
    if len(keys) != len(shortlist) or len(keys) != 16:
        raise ValueError("A shortlist failed its national control")
    clinical_meta = json.loads((directory / "clinical-summary.json").read_text())
    for name, field in (("clinical.jsonl", "candidate_ledger_sha256"), ("outlines.jsonl", "outlines_sha256")):
        if file_digest(directory / name) != clinical_meta[field]:
            raise ValueError(f"Unexpected physical-site edition for {name}")
    building_meta = json.loads((directory / "buildings-summary.json").read_text())
    if file_digest(directory / "buildings.jsonl") != building_meta["ledger_sha256"]:
        raise ValueError("Unexpected building edition")
    with (directory / "clinical.jsonl").open() as stream:
        clinical = {r["occurrence_key"]: r for r in map(json.loads, stream) if r["occurrence_key"] in keys}
    with (directory / "buildings.jsonl").open() as stream:
        buildings = {r["occurrence_key"]: r["buildings"] for r in map(json.loads, stream) if r["occurrence_key"] in keys}
    with gzip.open(vf, "rt") as stream:
        originals = {r["identity"]["facility_id"]: r["original"]["source_row"]
                     for r in map(json.loads, stream) if r["identity"]["facility_id"] in keys}
    with (directory / "outlines.jsonl").open() as stream:
        features = [{**r, "geometry": from_wkb(r["wkb"])} for r in map(json.loads, stream) if r["wkb"]]
    tree = STRtree([r["geometry"] for r in features])
    shortlisted_shapes = selected_building_shapes(pbf, {
        b["id"] for matches in buildings.values() for b in matches if b["interior"]
    })
    counts, tied_counts = Counter(), Counter()
    with sqlite3.connect(issuer.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for key, ids, original, printed in shortlist:
            tied = bool(tied_streets(original) & tied_streets(printed))
            vf_point = originals[key]
            clinical_objects = clinical[key]["candidates"]
            clinical_inside = {c["id"]: c for c in clinical_objects if c["interior"]}
            building_inside = [b for b in buildings[key] if b["interior"]]
            issuer_ids, same_named_building = set(), set()
            points = []
            for listing in ids:
                rows = db.execute("""
                    SELECT l.hco_name, l.address, l.pin_from_address, m.longitude, m.latitude
                    FROM listings l JOIN map_points m ON m.listing_id = l.listing_id
                    WHERE l.listing_id = ? AND m.link_status = 'unique_name_address'
                      AND m.longitude IS NOT NULL AND m.latitude IS NOT NULL
                """, (listing,))
                for name, address, pin, lon, lat in rows:
                    point = Point(lon, lat)
                    points.append(point)
                    source = {"name": name, "address_line1": address, "address_zipOrPostcode": pin}
                    _, candidates = evaluate(source, point, features, tree)
                    for c in candidates:
                        if c["interior"]:
                            issuer_ids.add(c["id"])
                            if c["building"] and c["exact_name"] and not c["pin_conflict"]:
                                same_named_building.add(c["id"])
            vf_has_point = clinical[key]["screen"] != "unusable_original_point"
            vf_geometry = Point(vf_point["longitude"], vf_point["latitude"]) if vf_has_point else None
            same_building = False
            for b in building_inside:
                shape = shortlisted_shapes[b["id"]]
                if vf_geometry is None or not shape.contains(vf_geometry):
                    raise ValueError("Replayed building does not contain the VF point")
                if any(shape.contains(p) for p in points):
                    same_building = True
            distances = ([point_distance(vf_geometry, p) for p in points]
                         if vf_has_point else [])
            checks = {
                "originals": 1, "specific_civic_number_tied_to_street": tied,
                "vf_point": vf_has_point, "linked_issuer_point": bool(points),
                "both_points": bool(distances),
                "any_point_pair_within_1m": any(d <= 1 for d in distances),
                "all_point_pairs_over_300m": bool(distances) and min(distances) > 300,
                "vf_clinical_within_300m": bool(clinical_objects), "vf_inside_clinical": bool(clinical_inside),
                "vf_inside_any_building": bool(building_inside),
                "both_inside_same_any_building": same_building,
                "vf_inside_any_exact_name_building": any(b["exact_name"] for b in building_inside),
                "issuer_inside_clinical": bool(issuer_ids),
                "both_inside_same_clinical_outline": bool(issuer_ids & clinical_inside.keys()),
                "both_inside_same_exact_name_clinical_building_without_postcode_conflict": any(
                    c["id"] in same_named_building and c["exact_name"] and not c["pin_conflict"]
                    for c in clinical_inside.values()),
                "vf_inside_clinical_exact_name_and_address": any(
                    c["exact_name"] and c["address_agrees"] for c in clinical_inside.values()),
            }
            counts.update(checks)
            if tied:
                tied_counts.update(checks)
    return {"a_manifest_sha256": A_MANIFEST, "counts": dict(counts), "tied_subset": dict(tied_counts),
            "clinical_ledger_sha256": clinical_meta["candidate_ledger_sha256"],
            "building_ledger_sha256": building_meta["ledger_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("method", "issuer", "vf", "directory", "pbf"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.method, args.issuer, args.vf, args.directory, args.pbf), sort_keys=True, indent=2))
