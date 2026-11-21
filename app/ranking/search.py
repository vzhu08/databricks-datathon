import json
from urllib.parse import urlsplit

from .evidence import MATCHERS, best_evidence
from .location import coordinates, finite_number, haversine_km, place_key, resolve_place, validate_location

DEFAULT_RADIUS_KM = 50
MAX_RESULTS = 3


def _response(status, *, cards=(), choices=(), approximate=False, message=None):
    return {
        "status": status,
        "direct_results": list(cards) if status == "ok" else [],
        "indirect_leads": list(cards) if status == "needs_confirmation" else [],
        "location_choices": list(choices),
        "approximate_location": approximate,
        "message": message,
    }


def _record_urls(value):
    if isinstance(value, str):
        if value.lstrip().startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                return []
        else:
            value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    urls = []
    for item in value:
        if not isinstance(item, str):
            continue
        url = item.strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme in {"http", "https"} and parsed.hostname and url not in urls:
                urls.append(url)
        except ValueError:
            continue
    return urls


def _card(row, point, distance, evidence):
    strength, excerpt, field = evidence
    return {
        "facility_id": row["facility_id"],
        "name": row["name"],
        "location": {
            "city": row.get("city"),
            "state": row.get("state"),
            "pin": row.get("pin"),
            "latitude": point[0],
            "longitude": point[1],
        },
        "distance_km": distance,
        "evidence_strength": strength,
        "evidence_excerpt": excerpt,
        "evidence_field": field,
        "record_source_urls": _record_urls(row.get("record_source_urls")),
        "rank_explanation": (
            "Direct service evidence. Ordered by straight-line distance."
            if strength == "direct"
            else "Related service evidence needs confirmation. Ordered by straight-line distance."
        ),
        "availability": "unknown",
    }


def search_from_source(service, location, *, load_place, load_candidates, radius_km=DEFAULT_RADIUS_KM,
                       limit=MAX_RESULTS):
    """Search with row loaders for (place kind, normalized value) and (origin, radius)."""
    if not isinstance(service, str) or service not in MATCHERS:
        return _response("invalid_input", message="Choose dialysis, MRI, or trauma care.")
    radius = finite_number(radius_km)
    if radius is None or radius <= 0:
        return _response("invalid_input", message="Enter a finite radius greater than zero.")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return _response("invalid_input", message="Enter a positive whole-number result limit.")
    try:
        kind, value = validate_location(location)
    except ValueError as error:
        return _response("invalid_input", message=str(error))

    approximate = kind != "coordinates"
    if approximate:
        key, state = value if kind == "city" else (value, "")
        origin, choices = resolve_place(list(load_place(kind, key)), kind, state)
        if choices:
            return _response("ambiguous_location", choices=choices, message="Choose a state for this city.")
        if origin is None:
            place = "PIN" if kind == "pin" else "city/state"
            return _response("unresolved_location", message="No dataset coordinates found for that {}.".format(place))
    else:
        origin = value

    matches = {"direct": [], "indirect": []}
    for row in load_candidates(origin, radius):
        point = coordinates(row)
        if point is None:
            continue
        distance = haversine_km(origin, point)
        if distance > radius:
            continue
        evidence = best_evidence(row, service)
        if evidence is not None:
            matches[evidence[0]].append((distance, str(row["facility_id"]), row, point, evidence))

    if matches["direct"]:
        status, candidates, message = "ok", matches["direct"], None
    elif matches["indirect"]:
        status, candidates = "needs_confirmation", matches["indirect"]
        message = "No direct matches within this radius. Confirm the service with these facilities."
    else:
        return _response("no_match", approximate=approximate, message="No matching facilities within this radius.")
    ranked = sorted(candidates, key=lambda match: match[:2])[:min(limit, MAX_RESULTS)]
    cards = [_card(row, point, distance, evidence) for distance, _, row, point, evidence in ranked]
    return _response(status, cards=cards, approximate=approximate, message=message)


def search_facilities(service, location, *, facilities, radius_km=DEFAULT_RADIUS_KM, limit=MAX_RESULTS):
    """Search prepared rows in memory with no Streamlit or Databricks dependencies."""
    rows = list(facilities)

    def load_place(kind, key):
        return (row for row in rows if place_key(row.get(kind)) == key)

    return search_from_source(
        service, location, load_place=load_place, load_candidates=lambda _origin, _radius: rows,
        radius_km=radius_km, limit=limit,
    )
