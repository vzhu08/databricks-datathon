"""Explicit, one-action ordinary-car observation for the signed-in Pune plan."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_EVEN
from fractions import Fraction
from math import isfinite, lcm

if "." in __package__:
    from ..ranking.location import coordinates, haversine_km
else:
    from ranking.location import coordinates, haversine_km

from .batch_planner import (
    HORIZON_MINUTES, REQUEST_COUNT, SCHEMA_VERSION, _instance_edges, _keyed, _validate_geography, solve,
)


PUNE_ROSTER_SHA256 = "b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35"
PICKUP_WEST = "PUNE-SIM-PICKUP-W"
PICKUP_EAST = "PUNE-SIM-PICKUP-E"
_SITE_IDS = {f"C{i:02}" for i in range(1, 13)}
_SOURCE = "TomTom traffic-aware ordinary car, shared synthetic Pune pickups"
_PICKUP_RULE = (
    "Two simulated pickup points represent this shift. Each request uses its closest pickup "
    "by straight-line distance. Road observations start at the shared pickup."
)


def _point_rows(rows):
    by_id = _keyed(rows, "id")
    points = {key: coordinates(row) for key, row in by_id.items()}
    if None in points.values() or len(set(points.values())) != len(points):
        raise ValueError("Expected distinct WGS84 points")
    return points


def derive_pickups(facilities):
    """Vincent's approved half-even west/east mean rule for the 12 public points."""
    points = _point_rows(facilities)
    if points.keys() != _SITE_IDS:
        raise ValueError("Expected the complete edition-1 Pune roster")
    ordered = sorted(points, key=lambda fid: (points[fid][1], points[fid][0], fid))

    def mean(ids, axis):
        total = sum(Decimal(str(points[fid][axis])) for fid in ids)
        return float((total / len(ids)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))

    return tuple(
        {"id": label, "latitude": mean(ids, 0), "longitude": mean(ids, 1)}
        for label, ids in ((PICKUP_WEST, ordered[:6]), (PICKUP_EAST, ordered[6:]))
    )


def _prepare(plan, configured_pickups):
    if not isinstance(plan, dict):
        raise ValueError("Traffic preview requires an approved plan object")
    geography, scenario = plan.get("geography"), plan.get("scenario")
    patients, facilities = plan.get("patients"), plan.get("facilities")
    if (plan.get("schema_version") != SCHEMA_VERSION or "traffic" in plan
            or not isinstance(geography, dict) or geography.get("roster_sha256") != PUNE_ROSTER_SHA256
            or geography.get("location_basis") != "public_source"
            or not isinstance(scenario, dict) or scenario.get("seed") != 17
            or scenario.get("horizon_minutes") != HORIZON_MINUTES
            or not isinstance(patients, list) or len(patients) != REQUEST_COUNT
            or not isinstance(facilities, list) or len(facilities) != len(_SITE_IDS)
            or any(not isinstance(row, dict) for row in facilities)
            or Counter(f.get("precision") for f in facilities) != {"mapped_point": 8, "campus_anchor": 4}):
        raise ValueError("Traffic preview requires the first-edition approved Pune plan")
    _validate_geography(geography)
    instance = {key: deepcopy(plan[key]) for key in ("geography", "scenario", "facilities", "patients")}
    _, _, pools, _, _ = _instance_edges(instance, travel_ticks={})
    if sum(row["slots"] for _, row in pools.values()) != 144:
        raise ValueError("Traffic preview requires the existing simulated staffing stock")

    pickup_rows = derive_pickups(instance["facilities"])
    pickup_points = _point_rows(pickup_rows)
    if (not isinstance(configured_pickups, (tuple, list)) or len(configured_pickups) != 2
            or _point_rows(configured_pickups) != pickup_points):
        raise ValueError("Shared pickup points do not match the edition-1 rule")
    destination_rows = tuple(
        {key: facility[key] for key in ("id", "latitude", "longitude")}
        for facility in instance["facilities"]
    )
    counts = Counter()
    for patient in instance["patients"]:
        point = coordinates(patient)
        if point is None:
            raise ValueError("Each simulated demand row needs an original sample point")
        chosen = min(pickup_points, key=lambda pid: (haversine_km(point, pickup_points[pid]), pid))
        counts[chosen] += 1
        patient.update(pickup_id=chosen, latitude=pickup_points[chosen][0], longitude=pickup_points[chosen][1])
    return instance, pickup_rows, destination_rows, counts


def _seconds(value):
    if type(value) not in (int, float) or (type(value) is float and not isfinite(value)) or value < 0:
        return None
    return Fraction(str(value))


def _observation(result, pickups, sites):
    """Validate counts and normalize only the 24 approved OD cells."""
    if not isinstance(result, dict) or not isinstance(result.get("travel_seconds"), dict):
        raise ValueError("Traffic adapter did not supply a matrix")
    attempted = result.get("attempted_pairs")
    attempts = result.get("actual_attempts", result.get("attempts"))
    source = result.get("source")
    total = len(pickups) * len(sites)
    if (type(attempted) is not int or type(attempts) is not int or not isinstance(source, str)
            or not source.strip() or not 0 <= attempted <= total or not attempted <= attempts <= 2 * attempted):
        raise ValueError("Traffic observation has inconsistent counts")
    rows = result["travel_seconds"]
    matrix = {}
    for pickup in pickups:
        row = rows.get(pickup, {})
        if not isinstance(row, dict):
            row = {}
        matrix[pickup] = {site: _seconds(row.get(site)) for site in sites}
    usable = sum(value is not None for row in matrix.values() for value in row.values())
    if usable > attempted:
        raise ValueError("Traffic observation has more usable than attempted routes")
    return matrix, {
        "status": "complete" if usable == total else "partial" if usable else "unavailable",
        "attempted_pairs": attempted,
        "actual_attempts": attempts,
        "usable_pairs": usable,
        "unavailable_pairs": total - usable,
        "observed_at": result.get("observed_at", result.get("requested_at")),
        "completed_at": result.get("completed_at"),
        "source": source,
        "attribution": deepcopy(result.get("attribution")),
    }


def run_traffic_plan(plan, *, pickups, observe):
    """Observe one matrix on explicit presenter action, then solve with no modeled fill.

    The callback is the approved server action. Raw observations are request
    scoped; the returned display plan includes assigned times and counts only.
    """
    instance, pickup_rows, destination_rows, counts = _prepare(plan, pickups)
    pickup_ids = tuple(row["id"] for row in pickup_rows)
    facility_ids = tuple(row["id"] for row in destination_rows)
    total = len(pickup_ids) * len(facility_ids)
    try:
        result = observe(pickups=deepcopy(pickup_rows), destinations=deepcopy(destination_rows))
        matrix, facts = _observation(result, pickup_ids, facility_ids)
    except Exception:
        # A failed adapter may already have spent quota. Do not invent a
        # counter or recover a modeled ETA. Preserve all unmet requests.
        matrix = {pid: dict.fromkeys(facility_ids) for pid in pickup_ids}
        facts = {
            "status": "unavailable", "attempted_pairs": None, "actual_attempts": None,
            "usable_pairs": 0, "unavailable_pairs": total, "observed_at": None, "completed_at": None,
            "source": _SOURCE, "attribution": None,
        }

    scale = lcm(1, *(value.denominator for row in matrix.values() for value in row.values() if value is not None))
    ticks = {
        patient["id"]: {site: int(seconds * scale) if seconds is not None else None
                        for site, seconds in matrix[patient["pickup_id"]].items()}
        for patient in instance["patients"]
    }
    instance["scenario"].update(
        travel_basis=f"{facts['source']}. Unavailable pairs remain unavailable.",
        simulated="Synthetic demand, urgency, capabilities and staffing with one observed ordinary-car matrix.",
    )
    planned = solve(instance, travel_ticks=ticks, ticks_per_second=scale)
    planned["traffic"] = {
        **facts, "eligible_pairs": total, "pickup_count": len(pickup_ids), "site_count": len(facility_ids),
        "patient_count": len(instance["patients"]), "pickup_rule": _PICKUP_RULE,
        "pickups": [{**row, "patient_count": counts[row["id"]]} for row in pickup_rows],
    }
    return planned
