#!/usr/bin/env python3
"""Bounded Google Open Buildings comparison extract.

    python -m research.geography.open_buildings --sample sample.json \
        --output google_buildings.ndjson --manifest google_manifest.json [--max-bytes N]

Open Buildings v3 publishes one compressed CSV per level-6 S2 cell. This picks
the cells that hold the most sample points within a download budget, streams
each file once and keeps only the buildings whose published centre lies within
the search radius plus a margin of a sample point. Nothing else is stored.

Sample points in cells left out of the budget are listed as not compared; they
stay unknown. Needs s2sphere to name the cell for a coordinate
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

EXTRACT_VERSION = "open-buildings-extract-1.0.0"
DATASET = "Google Open Buildings"
DATASET_VERSION = "v3"
BUCKET = "open-buildings-data"
OBJECT = "v3/polygons_s2_level_6_gzip_no_header/{token}_buildings.csv.gz"
URL = "https://storage.googleapis.com/" + BUCKET + "/" + OBJECT
META = "https://storage.googleapis.com/storage/v1/b/" + BUCKET + "/o/{name}?fields=name,size,md5Hash,generation,updated"
COLUMNS = ("latitude", "longitude", "area_in_meters", "confidence", "geometry", "full_plus_code")
MAX_BYTES = 1_600_000_000
MARGIN_M = 100.0


def cell_token(lat, lon):
    try:
        import s2sphere
    except ImportError:
        raise MatchingError("s2sphere is required: pip install -r research/geography/requirements.txt")
    return s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(lat, lon)).parent(6).to_token()


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


def choose_cells(cases, tokens, sizes, max_bytes):
    """Cells by descending number of sample points, then size, then token, while they fit.

    `tokens` maps case_id to cell token, `sizes` maps token to bytes (None when
    the cell has no published file). Returns (chosen tokens, skipped {token: reason}).
    """
    members = defaultdict(list)
    for case in cases:
        members[tokens[case["case_id"]]].append(case["case_id"])
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
            token_of=cell_token):
    check_sample(sample)
    cases = sample["cases"]
    tokens = {c["case_id"]: token_of(c["points"][0]["latitude"], c["points"][0]["longitude"]) for c in cases}
    info = {token: metadata(token) for token in sorted(set(tokens.values()))}
    sizes = {token: (int(meta["size"]) if meta else None) for token, meta in info.items()}
    chosen, skipped = choose_cells(cases, tokens, sizes, max_bytes)
    rows, cells = {}, []
    for token in chosen:
        members = [c for c in cases if tokens[c["case_id"]] == token]
        boxes = [bbox(c["points"][0]["latitude"], c["points"][0]["longitude"], radius_m + MARGIN_M) for c in members]
        found, lines = stream(token, boxes)
        for row in found:
            rows.setdefault(row["id"], row)
        cells.append({"token": token, "object": OBJECT.format(token=token), "bytes": sizes[token],
                      "md5": info[token].get("md5Hash"), "generation": info[token].get("generation"),
                      "updated": info[token].get("updated"), "rows_read": lines, "rows_kept": len(found),
                      "sample_points": len(members)})
    compared = sorted(c["case_id"] for c in cases if tokens[c["case_id"]] in chosen)
    manifest = {
        "extract_version": EXTRACT_VERSION, "dataset": DATASET, "dataset_version": DATASET_VERSION,
        "sample_sha256": sample["sample_sha256"], "radius_m": radius_m, "centre_margin_m": MARGIN_M,
        "max_bytes": max_bytes, "bytes_downloaded": sum(c["bytes"] for c in cells), "cells": cells,
        "cells_not_read": [{"token": t, "reason": r, "bytes": sizes.get(t),
                            "sample_points": sum(tokens[c["case_id"]] == t for c in cases)}
                           for t, r in sorted(skipped.items())],
        "compared_case_ids": compared,
        "not_compared_case_ids": sorted(c["case_id"] for c in cases if c["case_id"] not in compared),
        "selection_rule": "Cells ordered by sample points held (most first), then file size, then token; "
                          "each is read while the running total stays within max_bytes.",
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
