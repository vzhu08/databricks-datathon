"""Extract local and nationally exact-named objects from the pinned India PBF."""
import json
import math
import re
import unicodedata

import osmium

from research.acquisition.osm_services.pbf import file_digest

PBF_SHA = "c0a4a9382e67c8afc8427ab865358dcf42226ab3876f8477667585eaab6731b7"
FREEZE_SHA = "6a687d9b4fad7956e5144f8c4677beeb48d45f239604efe5ddfb4694281680e7"
CELL = 0.02
MEDICAL = {"hospital", "clinic", "doctors", "health_centre", "dialysis"}


def norm(value):
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.findall(r"[^\W_]+", value))


def names(tags):
    return {norm(tags.get(key)) for key in ("name", "name:en", "official_name", "alt_name")} - {""}


def eligible(tags):
    return bool(tags.get("entrance") or tags.get("addr:housenumber") or (
        names(tags) and (
            tags.get("amenity") in MEDICAL or tags.get("healthcare") or
            tags.get("building") not in (None, "no") or tags.get("landuse") or
            tags.get("office") or tags.get("shop")
        )
    ))


def issuer_rows(freeze):
    if file_digest(freeze / "freeze.json") != FREEZE_SHA:
        raise ValueError("Unexpected issuer freeze digest")
    pins = json.loads((freeze / "freeze.json").read_text())["files"]
    for name, pin in pins.items():
        if file_digest(freeze / name) != pin:
            raise ValueError(f"Unexpected issuer freeze member: {name}")
    with (freeze / "source-ledger.jsonl").open() as stream:
        rows = [json.loads(line) for line in stream]
    if len(rows) != 49 or len({row["listing_id"] for row in rows}) != 49:
        raise ValueError("Invalid issuer cohort")
    return rows


def cells(rows):
    result = set()
    for row in rows:
        for point in row["points"]:
            x = math.floor(point["longitude"] / CELL)
            y = math.floor(point["latitude"] / CELL)
            for a in range(x - 2, x + 3):
                for b in range(y - 2, y + 3):
                    result.add((a, b))
    return result


def extract(path, rows):
    if file_digest(path) != PBF_SHA:
        raise ValueError("Unexpected India PBF digest")
    grid = cells(rows)
    y_cells = {y for _, y in grid}
    wanted_names = {norm(row["name"]) for row in rows} - {""}
    coordinates = {}
    nodes = {}
    ways = {}
    relations = {}
    nearby_way_ids = set()

    class Local(osmium.SimpleHandler):
        def node(self, obj):
            if not obj.location.valid():
                return
            y = obj.location.lat
            bin_y = math.floor(y / CELL)
            x = obj.location.lon
            near = bin_y in y_cells and (math.floor(x / CELL), bin_y) in grid
            if near:
                coordinates[obj.id] = [x, y]
            if not obj.tags:
                return
            tags = dict(obj.tags)
            if (near and eligible(tags)) or (names(tags) & wanted_names):
                nodes[obj.id] = {"tags": tags, "point": [x, y], "version": obj.version}

        def way(self, obj):
            refs = [node.ref for node in obj.nodes]
            near = any(ref in coordinates for ref in refs)
            if near:
                nearby_way_ids.add(obj.id)
            if obj.tags:
                tags = dict(obj.tags)
                if (near and eligible(tags)) or names(tags) & wanted_names:
                    ways[obj.id] = {"tags": tags, "nodes": refs, "version": obj.version}

        def relation(self, obj):
            tags = dict(obj.tags)
            if not (eligible(tags) or names(tags) & wanted_names):
                return
            members = [[m.type, m.ref, m.role] for m in obj.members]
            near = any((kind == "w" and ref in nearby_way_ids) or
                       (kind == "n" and ref in coordinates) for kind, ref, _ in members)
            if near or names(tags) & wanted_names:
                relations[obj.id] = {"tags": tags, "members": members, "version": obj.version}

    Local().apply_file(str(path))
    print(f"Local pass complete: {len(coordinates)} nodes, {len(ways)} ways, {len(relations)} relations", flush=True)
    missing_ways = {ref for row in relations.values() for kind, ref, _ in row["members"]
                    if kind == "w" and ref not in ways}
    members = {}

    class MemberWays(osmium.SimpleHandler):
        def way(self, obj):
            if obj.id in missing_ways:
                members[obj.id] = [node.ref for node in obj.nodes]

    if missing_ways:
        MemberWays().apply_file(str(path), filters=[osmium.filter.IdFilter(missing_ways)])
    needed = {ref for row in ways.values() for ref in row["nodes"]}
    for refs in members.values():
        needed.update(refs)
    unresolved = needed.difference(coordinates)

    class MemberNodes(osmium.SimpleHandler):
        def node(self, obj):
            if obj.id in unresolved and obj.location.valid():
                coordinates[obj.id] = [obj.location.lon, obj.location.lat]

    if unresolved:
        MemberNodes().apply_file(str(path), filters=[osmium.filter.IdFilter(unresolved)])
    return {"points": nodes, "ways": ways, "relations": relations, "member_ways": members,
            "coordinates": {ref: coordinates[ref] for ref in sorted(needed & coordinates.keys())},
            "extraction": {"local_grid_cells": len(grid), "unresolved_node_refs": len(needed - coordinates.keys()),
                           "unresolved_member_ways": len(missing_ways - members.keys())}}


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("freeze", type=Path)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    result = extract(args.pbf, issuer_rows(args.freeze))
    with args.out.open("x") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
