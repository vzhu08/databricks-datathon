#!/usr/bin/env python3
"""Bounded Overture building extract for footprint checks.

    python -m research.geography.overture --cases cases.json --release <release> --output extract.sql

Writes a DuckDB script that reads only the bounding boxes around the listed
points from one pinned release and saves newline-delimited JSON. It downloads
nothing itself. No area, height or roof measure is selected: footprints here
answer "is a building mapped at this point", nothing clinical.

The release must be one the operator has checked exists. The source registry
lists a release prefix as an entry point, not a verified artifact.
"""
from __future__ import annotations

import argparse
import math
import re
import sys

from research.matching.common import MatchingError, load, require
from .checks import number
from .distance import EARTH_RADIUS_M

MAX_POINTS = 40          # 10 disputed + 10 controls, two points each
MAX_RADIUS_M = 500.0
BUCKET = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*"


def bbox(lat, lon, radius_m):
    dlat = math.degrees(radius_m / EARTH_RADIUS_M)
    dlon = math.degrees(radius_m / (EARTH_RADIUS_M * max(math.cos(math.radians(lat)), 1e-6)))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def case_points(cases):
    require(isinstance(cases, list), "cases", "expected an array")
    points = []
    for index, case in enumerate(cases):
        require(isinstance(case, dict) and isinstance(case.get("points"), list) and case["points"],
                f"cases[{index}]", "each case needs a non-empty points list")
        for point in case["points"]:
            lat, lon = number(point.get("latitude")), number(point.get("longitude"))
            require(lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180,
                    f"cases[{index}].points", "finite WGS84 coordinates required")
            points.append((lat, lon))
    return sorted(set(points))


def extract_sql(cases, release, output_file, radius_m=MAX_RADIUS_M):
    require(isinstance(release, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release) is not None,
            "release", "pin an inspected release such as 2026-11-18.0")
    require(isinstance(output_file, str) and re.fullmatch(r"[A-Za-z0-9_./-]+", output_file) is not None
            and ".." not in output_file, "output_file", "plain relative or absolute path without quotes required")
    require(isinstance(radius_m, (int, float)) and 0 < radius_m <= MAX_RADIUS_M, "radius_m",
            f"bounded neighbourhood only (at most {MAX_RADIUS_M:g} m)")
    points = case_points(cases)
    require(0 < len(points) <= MAX_POINTS, "cases", f"between 1 and {MAX_POINTS} distinct points")
    clauses = []
    for lat, lon in points:
        xmin, ymin, xmax, ymax = bbox(lat, lon, radius_m)
        clauses.append(f"(bbox.xmax >= {xmin:.7f} AND bbox.xmin <= {xmax:.7f} "
                       f"AND bbox.ymax >= {ymin:.7f} AND bbox.ymin <= {ymax:.7f})")
    source = BUCKET.format(release=release)
    return "\n".join([
        f"-- ACQ-C01 bounded building extract. Release {release}; {len(points)} point(s); {radius_m:g} m boxes.",
        "-- Keep the output under ignored data/local/ or an authorized Volume. Never commit it.",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "SET s3_region='us-west-2';",
        "COPY (",
        "  SELECT id, to_json(sources) AS sources, subtype, class, ST_AsGeoJSON(geometry) AS geometry",
        f"  FROM read_parquet('{source}', filename=true, hive_partitioning=1)",
        "  WHERE " + "\n     OR ".join(clauses),
        "  ORDER BY id",
        f") TO '{output_file}' (FORMAT JSON);",
        "",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m research.geography.overture", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--output", required=True, help="Where to write the DuckDB script")
    parser.add_argument("--extract-file", default="data/local/matching/footprints/buildings.ndjson")
    parser.add_argument("--radius-m", type=float, default=MAX_RADIUS_M)
    args = parser.parse_args(argv)
    try:
        sql = extract_sql(load(args.cases), args.release, args.extract_file, args.radius_m)
        with open(args.output, "x", encoding="utf-8") as stream:
            stream.write(sql)
        print(f"wrote {args.output}; run it with DuckDB, then pass {args.extract_file} to research.geography.footprints")
        return 0
    except (MatchingError, OSError, ValueError) as error:
        print(f"INVALID: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
