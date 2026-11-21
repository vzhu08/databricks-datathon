#!/usr/bin/env python3
"""Bounded Google Open Buildings comparison extract.

    python -m research.geography.open_buildings --sample sample.json \
        --output google_buildings.ndjson --manifest google_manifest.json [--max-bytes N]

Open Buildings v3 publishes one compressed CSV per level-6 S2 cell. This picks
the cells intersecting the most sample search areas within a download budget, streams
each file once and keeps only the buildings whose published centre lies within
the search radius plus a margin of a sample point. Nothing else is stored.

Sample points with incomplete cell coverage are listed as not compared.
Needs s2sphere to cover each padded search area
(research/geography/requirements.txt).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from research.matching.common import MatchingError, canonical, load, require, write_json
from .coverage import RADIUS_M, check_sample
from .overture import bbox
from .overture_read import ATTEMPTS, TIMEOUT_S, write_ndjson

EXTRACT_VERSION = "open-buildings-extract-1.1.0"
DATASET = "Google Open Buildings"
DATASET_VERSION = "v3"
BUCKET = "open-buildings-data"
OBJECT = "v3/polygons_s2_level_6_gzip_no_header/{token}_buildings.csv.gz"
URL = "https://storage.googleapis.com/" + BUCKET + "/" + OBJECT
META = "https://storage.googleapis.com/storage/v1/b/" + BUCKET + "/o/{name}?fields=name,size,md5Hash,generation,updated"
COLUMNS = ("latitude", "longitude", "area_in_meters", "confidence", "geometry", "full_plus_code")
MAX_BYTES = 1_600_000_000
MARGIN_M = 100.0


def covering_tokens(box):
    """All level-6 S2 cells intersecting the padded centre-selection rectangle."""
    try:
        import s2sphere
    except ImportError:
        raise MatchingError("s2sphere is required: pip install -r research/geography/requirements.txt")
    west, south, east, north = box
    region = s2sphere.LatLngRect.from_point_pair(s2sphere.LatLng.from_degrees(south, west),
                                                 s2sphere.LatLng.from_degrees(north, east))
    coverer = s2sphere.RegionCoverer()
    coverer.min_level = coverer.max_level = 6
    return sorted(cell.to_token() for cell in coverer.get_covering(region))


def object_metadata(token):
    name = urllib.request.quote(OBJECT.format(token=token), safe="")
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(META.format(name=name), timeout=TIMEOUT_S) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code < 500:
                raise MatchingError(f"open buildings: HTTP {error.code} for cell {token}")
        except (urllib.error.URLError, OSError):
            continue
    raise MatchingError(f"open buildings: could not read metadata for cell {token}")


def choose_cells(members, sizes, max_bytes):
    """Prioritize cells covering the most cases, then smaller files within budget."""
    chosen, skipped, used = [], {}, 0
    for token in sorted(members, key=lambda t: (-len(members[t]), sizes.get(t) or 0, t)):
        size = sizes.get(token)
        if size is None:
            skipped[token] = "no_published_file_for_cell"
        elif used + size > max_bytes:
            skipped[token] = "outside_download_budget"
        else:
            chosen.append(token)
            used += size
    return chosen, skipped


def wkt_geojson(text):
    """POLYGON or MULTIPOLYGON well-known text as GeoJSON, else None."""
    text = text.strip()
    try:
        upper = text.upper()
        if upper.startswith("MULTIPOLYGON"):
            body = text[text.index("(") + 1:text.rindex(")")].strip()
            parts = _split(body)
            return {"type": "MultiPolygon", "coordinates": [_polygon(p) for p in parts]}
        if upper.startswith("POLYGON"):
            return {"type": "Polygon", "coordinates": _polygon(text[text.index("("):])}
    except (ValueError, IndexError):
        return None
    return None


def _split(body):
    """Top-level parenthesised groups of a comma-separated list."""
    parts, depth, start = [], 0, None
    for index, char in enumerate(body):
        if char == "(":
            if depth == 0:
                start = index
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                parts.append(body[start:index + 1])
            if depth < 0:
                raise ValueError("unbalanced")
    if depth != 0 or not parts:
        raise ValueError("unbalanced")
    return parts


def _polygon(text):
    text = text.strip()
    if not (text.startswith("(") and text.endswith(")")):
        raise ValueError("not a polygon body")
    rings = []
    for ring in _split(text[1:-1]):
        points = []
        for pair in ring[1:-1].split(","):
            x, y = pair.split()[:2]
            points.append([float(x), float(y)])
        if len(points) < 4:
            raise ValueError("short ring")
        rings.append(points)
    return rings


def filter_rows(lines, boxes):
    """Extract rows for CSV lines whose centre lies in any box. Returns (rows, lines_read)."""
    xmin = min(b[0] for b in boxes)
    xmax = max(b[2] for b in boxes)
    ymin = min(b[1] for b in boxes)
    ymax = max(b[3] for b in boxes)
    rows, count = [], 0
    for line in lines:
        count += 1
        head = line.split(",", 2)
        try:
            lat, lon = float(head[0]), float(head[1])
        except (ValueError, IndexError):
            continue
        if not (ymin <= lat <= ymax and xmin <= lon <= xmax):
            continue
        if not any(b[0] <= lon <= b[2] and b[1] <= lat <= b[3] for b in boxes):
            continue
        record = next(csv.reader([line]))
        if len(record) != len(COLUMNS):
            continue
        code = record[5].strip()
        rows.append({"id": f"google_open_buildings_{DATASET_VERSION}:{code}",
                     "sources": [{"dataset": DATASET, "record_id": code, "version": DATASET_VERSION,
                                  "confidence": float(record[3])}],
                     "subtype": None, "class": None, "geometry": wkt_geojson(record[4])})
    return rows, count


def stream_cell(token, boxes):
    last = None
    for _ in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(URL.format(token=token), timeout=TIMEOUT_S) as response:
                text = io.TextIOWrapper(gzip.GzipFile(fileobj=response), encoding="utf-8", newline="")
                return filter_rows(text, boxes)
        except (urllib.error.URLError, OSError, EOFError) as error:
            last = error
    raise MatchingError(f"open buildings: {type(last).__name__} while reading cell {token}")


def extract(sample, max_bytes=MAX_BYTES, radius_m=RADIUS_M, metadata=object_metadata, stream=stream_cell,
            tokens_for=covering_tokens):
    check_sample(sample)
    require(0 < radius_m <= RADIUS_M and max_bytes >= 0, "extract", "invalid radius or byte budget")
    boxes, required_cells, members = {}, {}, defaultdict(list)
    for case in sample["cases"]:
        case_id, point = case["case_id"], case["points"][0]
        boxes[case_id] = bbox(point["latitude"], point["longitude"], radius_m + MARGIN_M)
        required_cells[case_id] = sorted(set(tokens_for(boxes[case_id])))
        require(required_cells[case_id], "cells", "no cells cover the search area")
        for token in required_cells[case_id]:
            members[token].append(case_id)
    info = {token: metadata(token) for token in sorted(members)}
    sizes = {token: (int(meta["size"]) if meta else None) for token, meta in info.items()}
    chosen, skipped = choose_cells(members, sizes, max_bytes)
    rows, cells = {}, []
    for token in chosen:
        found, lines = stream(token, [boxes[c] for c in members[token]])
        for row in found:
            rows.setdefault(row["id"], row)
        cells.append({"token": token, "object": OBJECT.format(token=token), "bytes": sizes[token],
                      "md5": info[token].get("md5Hash"), "generation": info[token].get("generation"),
                      "updated": info[token].get("updated"), "rows_read": lines, "rows_kept": len(found),
                      "sample_points": len(members[token])})
    compared = sorted(case_id for case_id, needed in required_cells.items() if set(needed).issubset(chosen))
    manifest = {
        "extract_version": EXTRACT_VERSION, "dataset": DATASET, "dataset_version": DATASET_VERSION,
        "sample_sha256": sample["sample_sha256"], "radius_m": radius_m, "centre_margin_m": MARGIN_M,
        "max_bytes": max_bytes, "bytes_downloaded": sum(c["bytes"] for c in cells), "cells": cells,
        "cells_not_read": [{"token": t, "reason": r, "bytes": sizes.get(t),
                            "sample_points": len(members[t])}
                           for t, r in sorted(skipped.items())],
        "compared_case_ids": compared,
        "required_cells": required_cells, "not_compared_case_ids": sorted(set(required_cells) - set(compared)),
        "selection_rule": "Read cells intersecting padded search rectangles in order of number of cases, "
                          "then size and token. Compare a case only if every required cell was read.",
        "license_note": "Check the Open Buildings dataset page for its current terms before redistribution.",
    }
    return [rows[key] for key in sorted(rows)], manifest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.open_buildings", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--radius-m", type=float, default=RADIUS_M)
    args = parser.parse_args(argv)
    try:
        require(0 < args.radius_m <= RADIUS_M, "radius_m", "at most 500 m")
        rows, manifest = extract(load(args.sample), args.max_bytes, args.radius_m)
        manifest["extract_sha256"] = write_ndjson(args.output, rows)
        manifest["features"] = len(rows)
        write_json(Path(args.manifest), manifest)
        print(canonical({k: manifest[k] for k in ("features", "bytes_downloaded", "extract_sha256")}
                        | {"cells": [c["token"] for c in manifest["cells"]],
                           "compared": len(manifest["compared_case_ids"])}))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
