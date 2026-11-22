"""Optional data-quality overlay for the facility search. Off unless an overlay is supplied.

The overlay is a CSV keyed by `facility_id`, built outside Git from the record-integrity, pin-repair,
duplicate and evidence-ladder research outputs (`research/quality_overlay/build_overlay.py`). With no
overlay, `search_with_quality` returns exactly what `search_facilities` returns.

With an overlay:
- `point_status = repaired`: the row is ranked at the repaired point, and its card carries
  `location_estimate` (method and precision) so the screen can say the location is estimated.
- `point_status = unplaced`: the row is not ranked by distance. For a PIN or city search it can still be
  listed under `unplaced_matches`, with no distance and with `location_warning` reason codes.
- `point_status = excluded`: a structurally broken row; it is left out.
- `duplicate_group`: rows describing one facility collapse to the member nearest the origin, and the
  card lists the others' names under `also_listed_as`.
- `evidence_<service>`: an evidence level shown as a badge (`evidence_level`). It never filters or reorders.
"""
import csv
import os

from .evidence import MATCHERS, best_evidence
from .location import coordinates, haversine_km, place_key, validate_location
from .search import DEFAULT_RADIUS_KM, MAX_RESULTS, search_facilities, search_from_source

QUALITY_SETTING = "FIND_CARE_QUALITY_OVERLAY"

POINT_STATUSES = {"repaired", "unplaced", "excluded"}
PRECISIONS = {"building", "pin_area", "city"}
# Same reason codes as the Find care screen's `LOCATION_CHECKS` (PR #242).
LOCATION_CODES = {"no_building_nearby", "far_from_town", "far_from_pin_area", "shared_point"}
EVIDENCE_LEVELS = {
    "self_reported": "Only the facility's own record says this",
    "identity_corroborated": "An independent source confirms the facility exists here; the service is self-reported",
    "dated_related": "A dated outside source names a related department",
    "dated_service": "A dated outside source names this service",
}


def _split(value):
    return [part for part in (value or "").split("|") if part]


def load_overlay(path):
    """Read an overlay CSV into {facility_id: entry}. Raises ValueError on a malformed row."""
    overlay = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for number, row in enumerate(csv.DictReader(handle), start=2):
            facility_id = (row.get("facility_id") or "").strip()
            if not facility_id:
                raise ValueError(f"overlay line {number}: facility_id is empty")
            status = (row.get("point_status") or "").strip()
            if status and status not in POINT_STATUSES:
                raise ValueError(f"overlay line {number}: unknown point_status {status!r}")
            entry = {"point_status": status or None}
            if status == "repaired":
                point = coordinates({"latitude": row.get("latitude"), "longitude": row.get("longitude")})
                precision = (row.get("location_precision") or "").strip()
                if point is None or precision not in PRECISIONS:
                    raise ValueError(f"overlay line {number}: a repaired point needs coordinates and a precision")
                entry.update(point=point, precision=precision, method=(row.get("location_method") or "").strip())
            codes = [code for code in _split(row.get("location_checks")) if code in LOCATION_CODES]
            if codes:
                entry["location_checks"] = codes
            group = (row.get("duplicate_group") or "").strip()
            if group:
                entry["duplicate_group"] = group
            for service in MATCHERS:
                level = (row.get("evidence_" + service) or "").strip()
                if level in EVIDENCE_LEVELS:
                    entry.setdefault("evidence", {})[service] = level
            overlay[facility_id] = entry
    return overlay


def overlay_from_env(environ=None):
    """The overlay named by the FIND_CARE_QUALITY_OVERLAY setting, or None when it is unset."""
    path = (environ if environ is not None else os.environ).get(QUALITY_SETTING, "").strip()
    return load_overlay(path) if path else None


def apply_overlay(rows, overlay):
    """Copies of the rows with repaired points applied, unplaced points removed and excluded rows dropped."""
    out = []
    for row in rows:
        entry = overlay.get(str(row.get("facility_id")), {})
        status = entry.get("point_status")
        if status == "excluded":
            continue
        row = dict(row)
        if status == "repaired":
            row["latitude"], row["longitude"] = entry["point"]
        elif status == "unplaced":
            row["latitude"] = row["longitude"] = None
        out.append(row)
    return out


def _badge(entry, service):
    level = entry.get("evidence", {}).get(service)
    return {"level": level, "label": EVIDENCE_LEVELS[level]} if level else None


def _decorate(card, entry, service, also):
    card = dict(card)
    card["evidence_level"] = _badge(entry, service)
    if entry.get("point_status") == "repaired":
        card["location_estimate"] = {"precision": entry["precision"], "method": entry["method"]}
    if also:
        card["also_listed_as"] = also
    return card


def _unplaced_card(row, entry, evidence, service):
    strength, excerpt, field = evidence
    return {
        "facility_id": row["facility_id"],
        "name": row["name"],
        "location": {"city": row.get("city"), "state": row.get("state"), "pin": row.get("pin"),
                     "latitude": None, "longitude": None},
        "distance_km": None,
        "evidence_strength": strength,
        "evidence_excerpt": excerpt,
        "evidence_field": field,
        "evidence_level": _badge(entry, service),
        "location_warning": entry.get("location_checks") or ["far_from_pin_area"],
        "rank_explanation": "The map pin for this record is unreliable, so it is not ranked by distance.",
        "availability": "unknown",
    }


def search_with_quality(service, location, *, facilities, overlay=None, radius_km=DEFAULT_RADIUS_KM,
                        limit=MAX_RESULTS):
    """`search_facilities` with the optional overlay. Without an overlay the response is unchanged."""
    if not overlay:
        return search_facilities(service, location, facilities=facilities, radius_km=radius_km, limit=limit)

    originals = list(facilities)
    rows = apply_overlay(originals, overlay)
    also_by_id = {}

    def entry(row):
        return overlay.get(str(row.get("facility_id")), {})

    def load_place(kind, key):
        return (row for row in rows if place_key(row.get(kind)) == key)

    def load_candidates(origin, _radius):
        groups, singles = {}, []
        for row in rows:
            group = entry(row).get("duplicate_group")
            (groups.setdefault(group, []) if group else singles).append(row)
        kept = list(singles)
        for members in groups.values():
            placed = [(haversine_km(origin, point), str(row["facility_id"]), row)
                      for row in members for point in [coordinates(row)] if point is not None]
            if not placed:
                continue
            nearest = min(placed, key=lambda item: item[:2])[2]
            names = sorted({row["name"] for row in members if row is not nearest and row["name"] != nearest["name"]})
            also_by_id[str(nearest["facility_id"])] = names
            kept.append(nearest)
        return kept

    response = search_from_source(service, location, load_place=load_place, load_candidates=load_candidates,
                                  radius_km=radius_km, limit=limit)
    if response["status"] in ("invalid_input", "ambiguous_location", "unresolved_location"):
        return response

    by_id = {str(row.get("facility_id")): row for row in rows}
    for key in ("direct_results", "indirect_leads"):
        response[key] = [
            _decorate(card, entry(by_id.get(str(card["facility_id"]), {})), service,
                      also_by_id.get(str(card["facility_id"])))
            for card in response[key]
        ]

    # Unplaced rows can still be named for a PIN or city search, without a distance.
    unplaced = []
    kind, value = validate_location(location)
    if kind != "coordinates":
        for row in rows:
            if entry(row).get("point_status") != "unplaced":
                continue
            if kind == "pin" and place_key(row.get("pin")) != value:
                continue
            if kind == "city" and (place_key(row.get("city")) != value[0]
                                   or (value[1] and place_key(row.get("state")) != value[1])):
                continue
            evidence = best_evidence(row, service)
            if evidence is not None:
                unplaced.append(_unplaced_card(row, entry(row), evidence, service))
    response["unplaced_matches"] = sorted(unplaced, key=lambda card: str(card["facility_id"]))[:MAX_RESULTS]
    return response
