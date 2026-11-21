"""Distances in metres. Pure stdlib; planar maths is only used inside a few
hundred metres of a reference point, where the equirectangular error is small
compared with coordinate uncertainty."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def local_xy(lat, lon, lat0, lon0):
    """Equirectangular metres east/north of (lat0, lon0)."""
    x = math.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH_RADIUS_M
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def _segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside_ring(px, py, ring):
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > py) != (by > py) and px < (bx - ax) * (py - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def polygons_of(geometry):
    """GeoJSON Polygon/MultiPolygon -> list of polygons (each a list of rings).
    Any other geometry type returns None: it is unsupported, not empty."""
    if not isinstance(geometry, dict):
        return None
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon":
        polygons = [coords]
    elif kind == "MultiPolygon":
        polygons = coords
    else:
        return None
    try:
        checked = []
        for polygon in polygons:
            rings = []
            for ring in polygon:
                points = [(float(lon), float(lat)) for lon, lat, *_ in ring]
                if len(points) < 4 or not all(math.isfinite(v) for p in points for v in p):
                    return None
                if not all(-180 <= lon <= 180 and -90 <= lat <= 90 for lon, lat in points):
                    return None
                rings.append(points)
            if not rings:
                return None
            checked.append(rings)
        return checked or None
    except (TypeError, ValueError):
        return None


def point_to_polygons_m(lat, lon, polygons):
    """(distance_m, contained). Distance is 0.0 when the point is inside a
    polygon (holes respected); otherwise metres to the nearest boundary."""
    best, contained = None, False
    for polygon in polygons:
        rings = [[local_xy(la, lo, lat, lon) for lo, la in ring] for ring in polygon]
        inside = _inside_ring(0.0, 0.0, rings[0]) and not any(_inside_ring(0.0, 0.0, hole) for hole in rings[1:])
        if inside:
            return 0.0, True
        for ring in rings:
            for (ax, ay), (bx, by) in zip(ring, ring[1:]):
                d = _segment_distance(0.0, 0.0, ax, ay, bx, by)
                if best is None or d < best:
                    best = d
    return best, contained
