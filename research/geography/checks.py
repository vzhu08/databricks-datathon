"""Coordinate screening. Flags and *proposed* corrections only.

Nothing here replaces an original coordinate. The India envelope is the same
broad anomaly cue used by A and D (latitude 6-38, longitude 68-98); it is not a
political boundary test.
"""
from __future__ import annotations

import math
from collections import defaultdict

INDIA_LAT = (6.0, 38.0)
INDIA_LON = (68.0, 98.0)


def number(value):
    """A finite real number or None. Booleans and numeric text are not numbers:
    text coordinates stay unrepaired and are reported as invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def in_envelope(lat, lon):
    return INDIA_LAT[0] <= lat <= INDIA_LAT[1] and INDIA_LON[0] <= lon <= INDIA_LON[1]


def coordinate_status(lat_raw, lon_raw):
    """Classify one coordinate pair.

    Returns {'usable', 'lat', 'lon', 'flags', 'proposed'}. `usable` means a
    finite WGS84 pair, so distance can be computed from the ORIGINAL values.
    `proposed` is a suggested correction with its reason, or None.
    """
    flags, proposed = [], None
    if lat_raw is None and lon_raw is None:
        return {"usable": False, "lat": None, "lon": None, "flags": ["coordinates_missing"], "proposed": None}
    if lat_raw is None or lon_raw is None:
        return {"usable": False, "lat": None, "lon": None, "flags": ["coordinates_incomplete"], "proposed": None}
    lat, lon = number(lat_raw), number(lon_raw)
    if lat is None or lon is None:
        return {"usable": False, "lat": None, "lon": None, "flags": ["coordinates_not_finite_numbers"], "proposed": None}
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        flags.append("coordinates_outside_wgs84")
        if -90 <= lon <= 90 and -180 <= lat <= 180 and in_envelope(lon, lat):
            proposed = {"latitude": lon, "longitude": lat, "reason": "possible_swapped_axes",
                        "basis": "Swapping the two values gives a point inside the India envelope."}
            flags.append("possible_swapped_axes")
        return {"usable": False, "lat": None, "lon": None, "flags": flags, "proposed": proposed}
    if lat == 0 and lon == 0:
        flags.append("null_island")
    if not in_envelope(lat, lon):
        flags.append("outside_india_envelope")
        if in_envelope(lon, lat):
            proposed = {"latitude": lon, "longitude": lat, "reason": "possible_swapped_axes",
                        "basis": "Swapping the two values gives a point inside the India envelope."}
            flags.append("possible_swapped_axes")
    return {"usable": True, "lat": lat, "lon": lon, "flags": flags, "proposed": proposed}


def decimals(value):
    text = repr(float(value))
    if "e" in text or "E" in text:
        return None
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def duplicate_clusters(points, minimum=3, precision=5):
    """Groups of records sharing one coordinate (rounded to ~1 m).

    `points` yields (record_id, lat, lon, distinct_key). A cluster is reported
    when at least `minimum` records with at least two different distinct_key
    values (for example different names) sit on the same point: a cue for a
    city centroid or geocoder fallback, never proof of an error.
    """
    groups = defaultdict(list)
    for record_id, lat, lon, key in points:
        groups[(round(lat, precision), round(lon, precision))].append((record_id, key))
    clusters = []
    for (lat, lon), members in sorted(groups.items()):
        if len(members) >= minimum and len({key for _, key in members}) >= 2:
            clusters.append({"latitude": lat, "longitude": lon, "record_count": len(members),
                             "record_ids": sorted(record_id for record_id, _ in members)})
    return clusters


def low_precision(lat, lon, limit=2):
    """Both values carry at most `limit` decimals (~1 km or coarser)."""
    a, b = decimals(lat), decimals(lon)
    return a is not None and b is not None and a <= limit and b <= limit
