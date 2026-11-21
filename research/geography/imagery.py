#!/usr/bin/env python3
"""Dated public imagery metadata for sample points (optional).

    python -m research.geography.imagery --sample sample.json --output imagery.json

For each point this finds the newest Sentinel-2 L2A scenes in the public COG
archive and reads one value of the scene classification layer at the point. It
records the acquisition time, pixel size, scene cloud cover, whether the point
was clear in that scene, and the licence link the scene itself carries.

Sentinel-2 pixels are 10 m (the classification layer 20 m). That shows whether
a recent cloud-free observation exists; it cannot outline a building, so
`can_resolve_building` is always false here. Obstructed or missing imagery is
unknown. Needs mgrs and rasterio (research/geography/requirements.txt).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

from research.matching.common import MatchingError, canonical, load, write_json
from .coverage import check_sample
from .overture_read import fetch

IMAGERY_VERSION = "imagery-metadata-1.0.0"
HOST = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
ROOT = "sentinel-s2-l2a-cogs"
SOURCE = "Sentinel-2 L2A, public cloud-optimised archive (sentinel-cogs)"
SCL = {0: "no_data", 1: "saturated_or_defective", 2: "dark_area", 3: "cloud_shadow", 4: "vegetation",
       5: "not_vegetated", 6: "water", 7: "unclassified", 8: "cloud_medium_probability",
       9: "cloud_high_probability", 10: "thin_cirrus", 11: "snow_or_ice"}
OBSTRUCTED = {3, 8, 9, 10}
UNUSABLE = {0, 1}
MAX_SCENES = 6


def visibility(value):
    """clear, obstructed or no_observation for one classification value."""
    if value in UNUSABLE or value not in SCL:
        return "no_observation"
    return "obstructed" if value in OBSTRUCTED else "clear"


def tile_of(lat, lon):
    try:
        import mgrs
    except ImportError:
        raise MatchingError("mgrs is required: pip install -r research/geography/requirements.txt")
    text = mgrs.MGRS().toMGRS(lat, lon, MGRSPrecision=0)
    return f"{int(text[:-3])}/{text[-3]}/{text[-2:]}"


def tile_candidates(tile):
    """The tile itself, then the same 100 km square under the neighbouring latitude
    bands: a square that straddles a band edge is published under one band only."""
    bands = "CDEFGHJKLMNPQRSTUVWX"
    zone, band, square = tile.split("/")
    index = bands.index(band)
    others = [bands[i] for i in (index - 1, index + 1) if 0 <= i < len(bands)]
    return [tile] + [f"{zone}/{other}/{square}" for other in others]


def list_prefixes(prefix, get=fetch):
    root = ET.fromstring(get(f"{HOST}/?list-type=2&prefix={urllib.request.quote(prefix)}&delimiter=/")[0])
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    return [node.findtext(f"{ns}Prefix") for node in root.findall(f"{ns}CommonPrefixes")]


def newest_scenes(tile, limit=MAX_SCENES, lister=list_prefixes):
    """Scene prefixes for one tile, newest first, at most `limit`."""
    def number(prefix):
        return int(prefix.rstrip("/").rsplit("/", 1)[1])

    scenes = []
    for year in sorted(lister(f"{ROOT}/{tile}/"), key=number, reverse=True):
        for month in sorted(lister(year), key=number, reverse=True):
            found = [s for s in lister(month) if re.search(r"_(\d{8})_\d+_L2A/$", s)]
            scenes += sorted(found, key=lambda s: re.search(r"_(\d{8})_(\d+)_L2A/$", s).groups(), reverse=True)
            if len(scenes) >= limit:
                return scenes[:limit]
    return scenes


def scene_item(scene, get=fetch):
    name = scene.rstrip("/").rsplit("/", 1)[1]
    return json.loads(get(f"{HOST}/{scene}{name}.json")[0])


def classification_at(scene, lat, lon):
    try:
        import rasterio
        from rasterio.warp import transform
    except ImportError:
        raise MatchingError("rasterio is required: pip install -r research/geography/requirements.txt")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
                      GDAL_HTTP_TIMEOUT="120"):
        with rasterio.open(f"{HOST}/{scene}SCL.tif") as dataset:
            xs, ys = transform("EPSG:4326", dataset.crs, [lon], [lat])
            return int(next(dataset.sample([(xs[0], ys[0])]))[0]), float(dataset.res[0])


def describe(case_id, scenes_checked):
    """One imagery record from [(scene, item, class value, layer pixel size)], newest first."""
    record = {"case_id": case_id, "source": SOURCE, "scenes_checked": len(scenes_checked),
              "can_resolve_building": False,
              "resolution_reason": "10 m pixels (20 m for the classification layer) cannot outline a single "
                                   "building; this only shows whether a recent clear observation exists",
              "acquired_at": None, "scene_id": None, "resolution_m": None, "classification_resolution_m": None,
              "scene_cloud_cover_percent": None, "class_at_point": None, "visibility_at_point": "unknown",
              "license": None, "newest_scene_acquired_at": None, "newest_scene_visibility_at_point": None}
    if not scenes_checked:
        record["unknown_reason"] = "No scene listed for this tile; imagery coverage is unknown"
        return record
    first = scenes_checked[0]
    record["newest_scene_acquired_at"] = first[1]["properties"].get("datetime")
    record["newest_scene_visibility_at_point"] = visibility(first[2])
    for scene, item, value, pixel in scenes_checked:
        if visibility(value) != "clear":
            continue
        links = [link.get("href") for link in item.get("links", []) if link.get("rel") == "license"]
        record.update({"acquired_at": item["properties"].get("datetime"),
                       "scene_id": item.get("id") or scene.rstrip("/").rsplit("/", 1)[1],
                       "resolution_m": 10.0, "classification_resolution_m": pixel,
                       "scene_cloud_cover_percent": item["properties"].get("eo:cloud_cover"),
                       "class_at_point": SCL[value], "visibility_at_point": "clear",
                       "license": links[0] if links else None})
        return record
    record["unknown_reason"] = (f"The point was cloud, shadow or outside the swath in the {len(scenes_checked)} "
                                "newest scenes; visibility is unknown, not a negative finding")
    return record


def collect(sample, limit=MAX_SCENES, lister=list_prefixes, item_of=scene_item, classify=classification_at,
            tile=tile_of):
    check_sample(sample)
    records, listed = [], {}
    for case in sorted(sample["cases"], key=lambda c: c["case_id"]):
        point = case["points"][0]
        name = tile(point["latitude"], point["longitude"])
        if name not in listed:
            listed[name] = []
            for candidate in tile_candidates(name):
                listed[name] = newest_scenes(candidate, limit, lister)
                if listed[name]:
                    break
        checked = []
        for scene in listed[name]:
            value, pixel = classify(scene, point["latitude"], point["longitude"])
            checked.append((scene, item_of(scene), value, pixel))
            if visibility(value) == "clear":
                break
        records.append(describe(case["case_id"], checked))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.imagery", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-scenes", type=int, default=MAX_SCENES)
    args = parser.parse_args(argv)
    try:
        records = collect(load(args.sample), args.max_scenes)
        digest = write_json(args.output, records)
        print(canonical({"status": "ok", "points": len(records), "sha256": digest, "imagery_version": IMAGERY_VERSION,
                         "clear": sum(r["visibility_at_point"] == "clear" for r in records)}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
