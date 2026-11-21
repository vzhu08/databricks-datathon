#!/usr/bin/env python3
"""Run the bounded Overture building extract without DuckDB.

    python -m research.geography.overture_read --cases cases.json --release <release> \
        --index data/local/geography/overture/index-<release>.json \
        --output data/local/geography/overture/buildings.ndjson

This applies the same predicate as the script written by
research.geography.overture (a building's bbox touches the box around a listed
point) and selects the same columns. It reads the public release files over
HTTPS range requests: every file's footer once (cached in --index), then only
the row groups whose bbox statistics touch a requested box. Use it where the
DuckDB httpfs and spatial extensions cannot be installed.

Needs pyarrow (research/geography/requirements.txt). Output stays under
ignored data/local/ or an authorized Volume.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from research.matching.common import MatchingError, canonical, file_digest, load, require, write_json
from .overture import MAX_POINTS, MAX_RADIUS_M, bbox, case_points

READER_VERSION = "overture-read-1.0.0"
HOST = "https://overturemaps-us-west-2.s3.amazonaws.com"
PREFIX = "release/{release}/theme=buildings/type=building/"
COLUMNS = ("id", "sources", "subtype", "class", "geometry")
BLOCK = 1 << 20
TIMEOUT_S = 120
ATTEMPTS = 3


def fetch(url, headers=None):
    """GET with a bounded retry on transport errors and 5xx. Returns (bytes, headers)."""
    last = None
    for _ in range(ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as error:
            if error.code < 500:
                raise MatchingError(f"fetch: HTTP {error.code} for {url.split('?')[0]}")
            last = error
        except (urllib.error.URLError, OSError) as error:
            last = error
    raise MatchingError(f"fetch: {type(last).__name__} after {ATTEMPTS} attempts for {url.split('?')[0]}")


class RangeFile:
    """Read-only seekable file over HTTP range requests, cached in fixed blocks."""

    def __init__(self, url, size, get=fetch, block=BLOCK):
        self.url, self.length, self.get, self.block = url, size, get, block
        self.position, self.blocks, self.requests, self.bytes_fetched = 0, {}, 0, 0
        self.closed = False

    def readable(self):
        return True

    def seekable(self):
        return True

    def writable(self):
        return False

    def tell(self):
        return self.position

    def size(self):
        return self.length

    def seek(self, offset, whence=0):
        base = 0 if whence == 0 else self.position if whence == 1 else self.length
        self.position = max(0, min(self.length, base + offset))
        return self.position

    def close(self):
        self.closed = True
        self.blocks.clear()

    def _load(self, first, last):
        start, end = first * self.block, min(self.length, (last + 1) * self.block) - 1
        data, _ = self.get(self.url, {"Range": f"bytes={start}-{end}"})
        require(len(data) == end - start + 1, "range", "server returned a different byte count than requested")
        self.requests += 1
        self.bytes_fetched += len(data)
        for index in range(first, last + 1):
            offset = (index - first) * self.block
            self.blocks[index] = data[offset:offset + self.block]

    def read(self, count=-1):
        if count is None or count < 0:
            count = self.length - self.position
        count = min(count, self.length - self.position)
        if count <= 0:
            return b""
        first, last = self.position // self.block, (self.position + count - 1) // self.block
        run = None
        for index in range(first, last + 2):
            missing = index <= last and index not in self.blocks
            if missing and run is None:
                run = index
            if not missing and run is not None:
                self._load(run, index - 1)
                run = None
        data = b"".join(self.blocks[i] for i in range(first, last + 1))
        offset = self.position - first * self.block
        self.position += count
        if last - first > 8:  # a column chunk was read: do not keep it in memory
            for index in range(first, last + 1):
                self.blocks.pop(index, None)
        return data[offset:offset + count]


def list_release(release, get=fetch):
    """[{'key', 'size', 'etag'}] for every building file of one release."""
    require(isinstance(release, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release) is not None,
            "release", "pin an inspected release such as 2026-11-18.0")
    files, token = [], None
    while True:
        url = f"{HOST}/?list-type=2&prefix={PREFIX.format(release=release)}"
        if token:
            url += "&continuation-token=" + urllib.request.quote(token, safe="")
        root = ET.fromstring(get(url)[0])
        ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        for item in root.findall(f"{ns}Contents"):
            key = item.findtext(f"{ns}Key")
            if key.endswith(".parquet"):
                files.append({"key": key, "size": int(item.findtext(f"{ns}Size")),
                              "etag": (item.findtext(f"{ns}ETag") or "").strip('"')})
        if root.findtext(f"{ns}IsTruncated") != "true":
            break
        token = root.findtext(f"{ns}NextContinuationToken")
    require(files, "release", f"no building files found for release {release}")
    return sorted(files, key=lambda f: f["key"])


def _parquet():
    try:
        import pyarrow
        import pyarrow.parquet
    except ImportError:
        raise MatchingError("pyarrow is required: pip install -r research/geography/requirements.txt")
    return pyarrow, pyarrow.parquet


def row_group_boxes(metadata):
    """[(xmin, ymin, xmax, ymax, rows)] per row group from bbox column statistics;
    None for a group without usable statistics (it must then be read)."""
    boxes = []
    for index in range(metadata.num_row_groups):
        group, found = metadata.row_group(index), {}
        for column in range(group.num_columns):
            chunk = group.column(column)
            if chunk.path_in_schema in ("bbox.xmin", "bbox.xmax", "bbox.ymin", "bbox.ymax"):
                stats = chunk.statistics
                if stats is not None and stats.has_min_max:
                    found[chunk.path_in_schema] = (float(stats.min), float(stats.max))
        if len(found) == 4:
            boxes.append([found["bbox.xmin"][0], found["bbox.ymin"][0], found["bbox.xmax"][1],
                          found["bbox.ymax"][1], group.num_rows])
        else:
            boxes.append(None)
    return boxes


def build_index(release, files, get=fetch, workers=8):
    """Footer statistics for every file: which row groups can touch which area."""
    _, pq = _parquet()
    import pyarrow

    def one(item):
        handle = RangeFile(f"{HOST}/{item['key']}", item["size"], get)
        metadata = pq.ParquetFile(pyarrow.PythonFile(handle, mode="r")).metadata
        return {"key": item["key"], "size": item["size"], "etag": item["etag"], "rows": metadata.num_rows,
                "row_groups": row_group_boxes(metadata), "footer_bytes": handle.bytes_fetched}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        entries = list(pool.map(one, files))
    return {"reader_version": READER_VERSION, "release": release, "files": entries}


def touches(box, other):
    return box[2] >= other[0] and box[0] <= other[2] and box[3] >= other[1] and box[1] <= other[3]


def plan(index, boxes):
    """Row groups to read: [(key, size, [row_group, ...])]."""
    work = []
    for entry in index["files"]:
        groups = [i for i, stats in enumerate(entry["row_groups"])
                  if stats is None or any(touches(stats, box) for box in boxes)]
        if groups:
            work.append((entry["key"], entry["size"], groups))
    return work


def wkb_geojson(data):
    """Two-dimensional Polygon or MultiPolygon WKB as a GeoJSON geometry, else None."""
    try:
        geometry, end = _wkb(memoryview(data), 0)
        return geometry if end == len(data) else None
    except (struct.error, ValueError, IndexError):
        return None


def _wkb(view, offset):
    order = "<" if view[offset] == 1 else ">"
    kind, = struct.unpack_from(order + "I", view, offset + 1)
    offset += 5
    if kind == 3:
        rings, offset = _rings(view, offset, order)
        return {"type": "Polygon", "coordinates": rings}, offset
    if kind == 6:
        count, = struct.unpack_from(order + "I", view, offset)
        offset += 4
        polygons = []
        for _ in range(count):
            part, offset = _wkb(view, offset)
            if part["type"] != "Polygon":
                raise ValueError("unexpected member")
            polygons.append(part["coordinates"])
        return {"type": "MultiPolygon", "coordinates": polygons}, offset
    raise ValueError("unsupported geometry type")


def _rings(view, offset, order):
    count, = struct.unpack_from(order + "I", view, offset)
    offset += 4
    rings = []
    for _ in range(count):
        points, = struct.unpack_from(order + "I", view, offset)
        offset += 4
        values = struct.unpack_from(f"{order}{points * 2}d", view, offset)
        offset += points * 16
        rings.append([[values[i], values[i + 1]] for i in range(0, len(values), 2)])
    return rings, offset


def rows_in_boxes(table, boxes):
    """Rows of a pyarrow table whose bbox touches any requested box, as extract rows."""
    columns = table.to_pydict()
    rows = []
    for i, feature_box in enumerate(columns["bbox"]):
        if feature_box is None or any(feature_box.get(k) is None for k in ("xmin", "ymin", "xmax", "ymax")):
            continue
        feature = (feature_box["xmin"], feature_box["ymin"], feature_box["xmax"], feature_box["ymax"])
        if not any(touches(feature, box) for box in boxes):
            continue
        rows.append({"id": columns["id"][i], "sources": columns["sources"][i], "subtype": columns["subtype"][i],
                     "class": columns["class"][i], "geometry": wkb_geojson(columns["geometry"][i])})
    return rows


def extract(index, cases, radius_m=MAX_RADIUS_M, get=fetch):
    """Return (rows sorted by id, read statistics)."""
    require(isinstance(radius_m, (int, float)) and 0 < radius_m <= MAX_RADIUS_M, "radius_m",
            f"bounded neighbourhood only (at most {MAX_RADIUS_M:g} m)")
    points = case_points(cases)
    require(0 < len(points) <= MAX_POINTS, "cases", f"between 1 and {MAX_POINTS} distinct points")
    boxes = [bbox(lat, lon, radius_m) for lat, lon in points]
    _, pq = _parquet()
    import pyarrow
    rows, stats = {}, {"files_in_release": len(index["files"]), "files_read": 0, "row_groups_read": 0,
                       "rows_scanned": 0, "bytes_fetched": 0, "requests": 0}
    for key, size, groups in plan(index, boxes):
        handle = RangeFile(f"{HOST}/{key}", size, get)
        parquet = pq.ParquetFile(pyarrow.PythonFile(handle, mode="r"))
        stats["files_read"] += 1
        for group in groups:
            # Coordinates first: skip the heavy columns when no row in the group qualifies.
            boxes_only = parquet.read_row_group(group, columns=["bbox"])
            stats["row_groups_read"] += 1
            stats["rows_scanned"] += boxes_only.num_rows
            if not rows_in_boxes_any(boxes_only, boxes):
                continue
            table = parquet.read_row_group(group, columns=["bbox", *COLUMNS])
            for row in rows_in_boxes(table, boxes):
                require(row["id"] not in rows, "extract", "one feature ID appeared twice in the release")
                rows[row["id"]] = row
        stats["bytes_fetched"] += handle.bytes_fetched
        stats["requests"] += handle.requests
        handle.close()
    stats.update({"points": len(points), "radius_m": radius_m, "features": len(rows)})
    return [rows[key] for key in sorted(rows)], stats


def rows_in_boxes_any(table, boxes):
    for feature_box in table.column("bbox").to_pylist():
        if feature_box is None or any(feature_box.get(k) is None for k in ("xmin", "ymin", "xmax", "ymax")):
            continue
        if any(touches((feature_box["xmin"], feature_box["ymin"], feature_box["xmax"], feature_box["ymax"]), box)
               for box in boxes):
            return True
    return False


def write_ndjson(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(canonical(row) + "\n" for row in rows)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return file_digest(path)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.overture_read", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", required=True, help="Cases or sample file with a points list per entry")
    parser.add_argument("--release", required=True)
    parser.add_argument("--index", required=True, help="Footer statistics cache; created when missing")
    parser.add_argument("--output", required=True)
    parser.add_argument("--radius-m", type=float, default=MAX_RADIUS_M)
    args = parser.parse_args(argv)
    try:
        cases = load(args.cases)
        if isinstance(cases, dict):
            cases = cases.get("cases")
        if Path(args.index).exists():
            index = load(args.index)
            require(index.get("release") == args.release and index.get("reader_version") == READER_VERSION,
                    "index", "index belongs to another release or reader version")
        else:
            index = build_index(args.release, list_release(args.release))
            write_json(args.index, index)
        rows, stats = extract(index, cases, args.radius_m)
        stats["sha256"] = write_ndjson(args.output, rows)
        stats["release"] = args.release
        print(json.dumps(stats, sort_keys=True))
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
