"""Ordinary-car observations for the synthetic Jaipur capacity recommendation."""

import atexit
from threading import Lock

if "." in __package__:
    from ..simulation.scenario import make_scenario
else:
    from simulation.scenario import make_scenario

from .finder import find_campuses
from .tomtom import from_environment


_scenario = make_scenario()
_ORIGINS = {p.id: (p.latitude, p.longitude) for p in _scenario.origins}
_CAMPUSES = {c.id: (c.latitude, c.longitude) for c in _scenario.campuses}
_SOURCE = "TomTom traffic-aware ordinary car, simulated Jaipur places"
_client = None
_lock = Lock()


def _process_client():
    global _client
    with _lock:
        if _client is None:
            _client = from_environment()
            atexit.register(_client.close)
        return _client


def _unavailable(reason):
    return {"status": "unavailable", "minutes": None, "source": _SOURCE,
            "reason": reason, "outcome": "unavailable"}


def demo_car_travel(request, snapshot, *, origin_id, provider=None):
    """Replace the entire travel map before capacity allocation. No result cache.

    Only the server-built synthetic snapshot is supported. Resolve coordinates by
    scenario ID; incoming coordinates, when present, must agree with the fixture.
    """
    if type(request.get("emergency", False)) is not bool:
        raise ValueError("Emergency must be a boolean")
    if request.get("emergency") or snapshot is None:
        return {}
    candidates = snapshot.get("candidates", [])
    if not isinstance(candidates, (tuple, list)) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError("Expected server-built campus records")
    ids = [c.get("facility_id") for c in candidates]
    if any(not isinstance(fid, str) or not fid.strip() for fid in ids) or len(ids) != len(set(ids)):
        raise ValueError("Campus IDs must be nonempty and unique")
    origin = _ORIGINS.get(origin_id)
    context_error = None
    if snapshot.get("mode") != "synthetic":
        context_error = "unapproved_snapshot"
    elif origin is None or snapshot.get("origin_id") != origin_id or request.get("origin_id", origin_id) != origin_id:
        context_error = "unapproved_origin"
    elif not request.get("as_of") or request["as_of"] != snapshot.get("as_of"):
        context_error = "snapshot_date_mismatch"
    if context_error:
        return {fid: _unavailable(context_error) for fid in ids}

    travel, approved = {}, []
    for campus in candidates:
        fid = campus["facility_id"]
        point = _CAMPUSES.get(fid)
        if point is None or (("latitude" in campus or "longitude" in campus) and
                             (campus.get("latitude"), campus.get("longitude")) != point):
            travel[fid] = _unavailable("unapproved_campus_point")
            continue
        approved.append({**campus, "latitude": point[0], "longitude": point[1],
                         "coordinate_status": campus.get("coordinate_status", "reviewed")})
    if not approved:
        return travel
    normalized = {"service": request["service"], "urgency": request["urgency"],
                  "as_of": request["as_of"], "required": request.get("required_tools", []),
                  "travel_budget": request["max_travel_minutes"], "travel_metric": "travel_minutes",
                  "candidates": approved, "routing": {"provider": "tomtom", "origin": {
                      "latitude": origin[0], "longitude": origin[1], "kind": "coordinates"}}}
    if provider is None:
        try:
            provider = _process_client()
        except ValueError:  # Malformed backend configuration. No call can be admitted.
            travel.update({c["facility_id"]: _unavailable("invalid_operator_configuration") for c in approved})
            return travel
    result = find_campuses(normalized, provider=provider)
    for row in result["routing"]["results"]:
        travel[row["facility_id"]] = {
            "status": "known" if row["outcome"] == "ok" else "unavailable",
            "minutes": row["estimated_minutes"], "source": _SOURCE,
            "reason": row["reason"], "outcome": row["outcome"],
        }
    return travel
