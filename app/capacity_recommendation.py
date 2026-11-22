"""Read-only hosted Find care preview using the storm allocator's selection policy."""

from collections import Counter
from datetime import date
from decimal import Decimal

if __package__:
    from .ranking.urgency import rank_campuses
    from .simulation.replay import preview_assignment
    from .simulation.scenario import SERVICES, URGENCY_ORDER, Campus, Origin, Request, Resource, make_scenario
else:  # Databricks Apps packages and runs app/ as its root.
    from ranking.urgency import rank_campuses
    from simulation.replay import preview_assignment
    from simulation.scenario import SERVICES, URGENCY_ORDER, Campus, Origin, Request, Resource, make_scenario


_SNAPSHOT_MODES = ("synthetic", "reviewed")
_OBSERVATION_STATES = ("known", "unknown", "stale", "unavailable")
_FAILURES = ("travel_unavailable", "travel_stale", "travel_unknown", "travel_invalid")
_DEMO_DAY = "2026-11-22"


def _minutes(value):
    # Use the supplied decimal precision for inclusive window/detour comparisons.
    if type(value) not in (int, float):
        return None
    amount = Decimal(str(value))
    return amount if amount.is_finite() and amount >= 0 else None


def _reference(value):
    return isinstance(value, str) and bool(value.strip())


def _tools(value):
    if not isinstance(value, (list, tuple)) or not all(_reference(tool) for tool in value):
        raise ValueError("Tools must be a collection of nonempty labels")
    return tuple(tool.strip() for tool in value)


def _request_inputs(request):
    service = request.get("service")
    urgency = request.get("urgency")
    day = request.get("as_of")
    window = _minutes(request.get("max_travel_minutes"))
    cap = _minutes(request.get("detour_minutes", 10))
    required = _tools(request.get("required_tools", ()))
    if (service not in SERVICES or not isinstance(urgency, str) or urgency not in URGENCY_ORDER
            or not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
            or window is None or cap is None):
        raise ValueError("Specify a supported service, urgency, date and nonnegative minute limits")
    return Request("preview", 0, "current", service, urgency, required, window), day, cap


def _travel_minutes(row):
    if not isinstance(row, dict) or row.get("status") == "unknown":
        return None, "travel_unknown"
    if row.get("status") in ("stale", "unavailable"):
        return None, "travel_" + row["status"]
    minutes = _minutes(row.get("minutes"))
    if row.get("status") != "known" or minutes is None or not _reference(row.get("source")):
        return None, "travel_invalid"
    return minutes, None


def _resources(rows, request, decision, sources):
    if not isinstance(rows, (tuple, list)):
        raise ValueError("Campus capacity must contain resource pools")
    resources = []
    for row in rows:
        if not isinstance(row, dict) or row.get("service") != request.service:
            continue
        key, status, free = row.get("resource_id"), row.get("status"), row.get("free_slots")
        if (not _reference(key) or key in sources or status not in _OBSERVATION_STATES
                or (status == "known" and (type(free) is not int or free < 0 or not _reference(row.get("source"))))):
            raise ValueError("Resource pools need unique IDs and valid staffed capacity observations")
        # A pool's tool label does not independently confirm reviewed service evidence.
        capabilities = decision.get("capabilities", {})
        tools = tuple(tool for tool in _tools(row.get("tools", ())) if capabilities.get(tool) == "yes")
        resources.append(Resource(key, request.service, tools, free if status == "known" else None, status))
        sources[key] = row.get("source")
    return tuple(resources)


def _eligible_snapshot(snapshot, request, day):
    candidates, travel, capacity = (snapshot.get(key) for key in ("candidates", "travel", "capacity"))
    if (not isinstance(candidates, (tuple, list)) or any(not isinstance(c, dict) for c in candidates)
            or not isinstance(travel, dict) or not isinstance(capacity, dict)):
        raise ValueError("Snapshot needs campus rows and campus-keyed travel and capacity")

    # Run the dated onsite service gate for the full shortlist. Validate tool
    # evidence per pool below. A campus that cannot take this request could
    # still have a spare slot for the independently protected tool profile.
    # Neutral distance is only an evidence probe.
    admitted = rank_campuses(
        request.service, request.urgency, [{**row, "distance_km": 0} for row in candidates],
        as_of=day, travel_metric="distance_km", travel_budget=1, limit=None,
    )
    campus_ids = {row["facility_id"] for row in admitted["ranked"]}
    exclusions = Counter()
    if len(campus_ids) < len(candidates):
        exclusions["service_evidence_unreviewed"] = len(candidates) - len(campus_ids)

    campuses, times, sources = [], {}, {}
    for row in candidates:
        campus_id = row["facility_id"]
        if campus_id not in campus_ids:
            continue
        minutes, reason = _travel_minutes(travel.get(campus_id))
        if reason:
            exclusions[reason] += 1
            continue
        # The allocator needs stable IDs and pools. It never uses coordinates.
        pools = _resources(capacity.get(campus_id, ()), request, row["services"][request.service], sources)
        if not pools:
            exclusions["unknown_or_stale_capacity"] += 1
        campuses.append(Campus(campus_id, 0.0, 0.0, pools))
        times[campus_id] = minutes
    return tuple(campuses), times, sources, exclusions


def _option(campus, resource, travel, slots, snapshot, capacity_sources):
    return {
        "facility_id": campus, "resource_id": resource, "travel_minutes": float(travel),
        "travel_source": snapshot["travel"][campus]["source"], "free_staffed_slots": slots,
        "capacity_source": capacity_sources[resource],
    }


def recommend_capacity(request, snapshot=None):
    """Preview one current request against a server-verified evidence and inventory snapshot.

    Known minutes and capacity are observations certified current by the producing
    server. Distance fallbacks, stale records and bed counts do not qualify. The
    snapshot and its nested records are read only. No booking or network I/O occurs.
    """
    result = {
        "status": "no_recommendation", "reason": "invalid_request",
        "mode": None, "chosen": None, "fastest": None,
        "extra_travel_minutes": None, "preserved_profiles": [], "eligible_campus_ids": [], "exclusions": {},
    }
    if not isinstance(request, dict) or type(request.get("emergency", False)) is not bool:
        return result
    if request.get("emergency") is True:
        return dict(result, status="emergency", reason="emergency_stop")
    try:
        plan, day, cap = _request_inputs(request)
    except ValueError:
        return result
    mode = snapshot.get("mode") if isinstance(snapshot, dict) else None
    if mode not in _SNAPSHOT_MODES:
        return dict(result, reason="snapshot_unavailable")
    result["mode"] = mode
    if snapshot.get("as_of") != day:
        return dict(result, reason="stale_snapshot")
    try:
        campuses, times, capacity_sources, exclusions = _eligible_snapshot(snapshot, plan, day)
    except ValueError:
        return dict(result, reason="invalid_snapshot")

    slots = {pool.id: pool.slots for campus in campuses for pool in campus.resources}
    origin = Origin("current", 0.0, 0.0, times)
    choice = preview_assignment(plan, origin, campuses, slots, "scarcity_aware", cap)
    exclusions.update(choice["excluded_pool_counts"])
    result["exclusions"] = dict(sorted(exclusions.items()))
    result["eligible_campus_ids"] = choice["eligible_campuses"]
    if choice["status"] != "recommended":
        reason = choice["reason"]
        if reason == "required_service_or_tool_unavailable":
            reason = next((key for key in ("unknown_or_stale_capacity", *_FAILURES,
                                          "service_evidence_unreviewed") if exclusions[key]), reason)
        return dict(result, reason=reason)

    chosen_campus, chosen_pool = choice["campus_id"], choice["resource_id"]
    fastest_campus, fastest_pool = choice["nearest_campus_id"], choice["nearest_resource_id"]
    return dict(
        result, status="recommended", reason=choice["reason"],
        chosen=_option(chosen_campus, chosen_pool, choice["travel_minutes"], slots[chosen_pool],
                       snapshot, capacity_sources),
        fastest=_option(fastest_campus, fastest_pool, choice["nearest_feasible_minutes"], slots[fastest_pool],
                        snapshot, capacity_sources),
        extra_travel_minutes=float(choice["extra_travel_minutes"]),
        preserved_profiles=choice["preserved_profiles"],
    )


def demo_capacity_inputs(*, service="dialysis", urgency="routine", origin_id="central",
                         required_tools=(), variant="baseline"):
    """Return fresh fictional request and snapshot inputs from the Jaipur storm scenario."""
    if variant not in ("baseline", "spare_specialist", "fastest_pool_exhausted"):
        raise ValueError("Unknown synthetic capacity variant")
    scenario = make_scenario()
    origin = next((origin for origin in scenario.origins if origin.id == origin_id), None)
    if origin is None:
        raise ValueError("Unknown synthetic origin")
    request = {
        "service": service, "urgency": urgency, "required_tools": list(required_tools),
        "as_of": _DEMO_DAY, "max_travel_minutes": 25 if service == "dialysis" else 30,
        "detour_minutes": 10,
    }
    snapshot = {"mode": "synthetic", "as_of": _DEMO_DAY, "candidates": [], "travel": {}, "capacity": {}}
    for campus in scenario.campuses:
        services = {}
        snapshot["travel"][campus.id] = {"status": "known", "minutes": origin.travel_minutes[campus.id],
                                          "source": "Synthetic Jaipur storm travel fixture"}
        pools = []
        for pool in campus.resources:
            decision = services.setdefault(pool.service, {
                "status": "yes", "source_date": _DEMO_DAY, "capabilities": {},
                "independent_families": ["synthetic_storm_fixture"],
            })
            decision["capabilities"].update({tool: "yes" for tool in pool.tools})
            free = pool.slots
            if (pool.id, variant) == ("A-dialysis", "spare_specialist"):
                free = 2
            elif (pool.id, variant) == ("A-dialysis", "fastest_pool_exhausted"):
                free = 0
            pools.append({"resource_id": pool.id, "service": pool.service, "tools": list(pool.tools),
                          "status": pool.capacity_status, "free_slots": free,
                          "source": "Synthetic Jaipur storm staffed slots"})
        snapshot["candidates"].append({"facility_id": campus.id, "as_of": _DEMO_DAY, "services": services})
        snapshot["capacity"][campus.id] = pools
    return request, snapshot
