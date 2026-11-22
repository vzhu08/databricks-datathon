"""Words for the capacity-aware choice on the Find care screen (#304). No Streamlit dependency.

The choice itself is P's `recommend_capacity` on the synthetic Jaipur campuses A to F (#303). Drive
minutes are the scenario's simulated minutes unless the operator has switched on A's traffic-aware
ordinary-car source (#96, `travel.hosted.demo_car_travel`). Nothing here ranks, books or calls a
network by itself: `run` is called once per explicit submit, and `explain` only words its result.

Campuses A to F are invented scenario campuses. They are never the six invented catalogue hospitals
of the facility search, and their IDs are never mixed with those.
"""
from datetime import datetime, timezone

try:
    from capacity_recommendation import demo_capacity_inputs, recommend_capacity
except ImportError:  # repository tests import the package
    from app.capacity_recommendation import demo_capacity_inputs, recommend_capacity

URGENCIES = {"routine": "Routine", "time_sensitive": "Within hours", "highest": "Highest"}
ORIGINS = {"central": "Central", "east": "East", "south": "South", "west": "West"}
TOOLS = {"dialysis": ("monitored", "a monitored dialysis station")}
SIMULATED = "simulated"
TRAFFIC = "traffic"
SIMULATED_LABEL = "Simulated drive minutes from the Jaipur storm scenario, not a road estimate."
TRAFFIC_SOURCE = "TomTom"
EXCLUSIONS = {
    "outside_travel_window": "beyond the travel limit",
    "service_evidence_unreviewed": "no reviewed, dated evidence that the service runs there",
    "unknown_or_stale_capacity": "free staffed places unknown or out of date",
    "no_staffed_slot_left": "full, with no free staffed place",
    "required_service_or_tool_unavailable": "without the equipment this patient needs",
    "travel_unavailable": "road time unavailable",
    "travel_unknown": "road time unknown",
    "travel_stale": "road time out of date",
    "travel_invalid": "road time could not be used",
}
NO_CHOICE = {
    "no_staffed_slot_left": "Every campus within reach that offers this is full.",
    "unknown_or_stale_capacity": "No campus within reach has a known free staffed place.",
    "outside_travel_window": "No campus with a free place is within the travel limit.",
    "required_service_or_tool_unavailable": "No campus within reach has the equipment this patient needs.",
    "service_evidence_unreviewed": "No campus within reach has reviewed evidence for this service.",
    "travel_unavailable": "Road times could not be fetched, so no campus is suggested.",
    "travel_unknown": "Road times are unknown, so no campus is suggested.",
    "travel_stale": "Road times are out of date, so no campus is suggested.",
    "travel_invalid": "Road times could not be used, so no campus is suggested.",
    "stale_snapshot": "The capacity figures are out of date, so no campus is suggested.",
    "snapshot_unavailable": "The capacity figures are not available, so no campus is suggested.",
    "invalid_snapshot": "The capacity figures could not be read, so no campus is suggested.",
    "invalid_request": "This request could not be checked against capacity.",
}


def campus(facility_id):
    return f"Campus {facility_id}"


def run(service, urgency, origin_id, needs_tool, traffic, *, provider=None, travel=None, now=None):
    """One capacity check for one submitted request. The only place a route request can start.

    `traffic` asks A's ordinary-car source for minutes; `travel` (the module) and `provider` are passed
    in by the screen and by tests. Returns everything the screen shows, so a rerun reads it back.
    """
    tools = (TOOLS[service][0],) if needs_tool and service in TOOLS else ()
    request, snapshot = demo_capacity_inputs(service=service, urgency=urgency, origin_id=origin_id,
                                             required_tools=tools)
    snapshot = {**snapshot, "origin_id": origin_id}
    kind, as_of = SIMULATED, None
    if traffic:
        kind = TRAFFIC
        as_of = (now or datetime.now(timezone.utc)).strftime("%H:%M UTC, %d %b %Y")
        snapshot["travel"] = travel.demo_car_travel(request, snapshot, origin_id=origin_id, provider=provider)
    return {"asked": {"service": service, "urgency": urgency, "origin_id": origin_id,
                      "needs_tool": bool(tools), "traffic": bool(traffic)},
            "travel_kind": kind, "travel_as_of": as_of, "max_minutes": request["max_travel_minutes"],
            "detour_minutes": request["detour_minutes"],
            "travel_rows": {key: {k: row.get(k) for k in ("status", "minutes", "reason")}
                            for key, row in snapshot["travel"].items()},
            "result": recommend_capacity(request, snapshot)}


def _minutes(value):
    return f"{value:.0f} min" if float(value).is_integer() else f"{value:.1f} min"


def time_label(check):
    if check["travel_kind"] == TRAFFIC:
        return (f"Road time for an ordinary car with traffic, from {TRAFFIC_SOURCE}, as of {check['travel_as_of']}. "
                "It is an estimate between simulated Jaipur places, not the patient's own address.")
    return SIMULATED_LABEL


def _profile(profile):
    service, _, tool = profile.partition("/")
    if service in TOOLS and tool == TOOLS[service][0]:
        return TOOLS[service][1]
    return f"{tool} {service}".strip()


def explain(check):
    """Everything the screen shows for one capacity check, as plain lines."""
    result = check["result"]
    service, urgency = check["asked"]["service"], check["asked"]["urgency"]
    lines = {"headline": None, "chosen": None, "fastest": None, "why": None, "status": [],
             "time_label": time_label(check), "excluded": [], "unavailable_minutes": []}
    for key, count in result.get("exclusions", {}).items():
        lines["excluded"].append(f"{count} campus{'es' if count != 1 else ''} left out: "
                                 + EXCLUSIONS.get(key, key.replace("_", " ")) + ".")
    for key, row in sorted(check["travel_rows"].items()):
        if row["status"] != "known":
            lines["unavailable_minutes"].append(f"{campus(key)}: road time unavailable"
                                                + (f" ({row['reason'].replace('_', ' ')})." if row.get("reason") else "."))
    if result["status"] == "emergency":
        lines["headline"] = "Emergency: do not use this choice. Call 112 now."
        return lines
    if result["status"] != "recommended":
        lines["headline"] = "No campus is suggested."
        lines["why"] = NO_CHOICE.get(result["reason"], "The capacity check found no campus it can suggest.")
        return lines
    chosen, fastest = result["chosen"], result["fastest"]
    unit = "road" if check["travel_kind"] == TRAFFIC else "simulated"
    lines["headline"] = f"Suggested by free places: {campus(chosen['facility_id'])}."
    lines["chosen"] = (f"{campus(chosen['facility_id'])}: {_minutes(chosen['travel_minutes'])} ({unit}), "
                       f"{chosen['free_staffed_slots']} free staffed place"
                       f"{'s' if chosen['free_staffed_slots'] != 1 else ''} for this service now.")
    if result["reason"] == "preserve_reachable_specialist_slot":
        protected = ", ".join(_profile(p) for p in result["preserved_profiles"]) or "a scarcer place"
        lines["fastest"] = (f"Fastest with a free place: {campus(fastest['facility_id'])}, "
                            f"{_minutes(fastest['travel_minutes'])} ({unit}).")
        lines["why"] = (f"{campus(chosen['facility_id'])} adds {_minutes(result['extra_travel_minutes'])}. "
                        f"{campus(fastest['facility_id'])} has the last free place with {protected} within reach, "
                        "so it is kept for a patient who needs it. The detour is allowed only up to "
                        f"{check['detour_minutes']} minutes and never for the highest urgency.")
    elif urgency == "highest":
        lines["why"] = ("Highest urgency: the fastest campus with a free staffed place is suggested, "
                        "with no detour to protect scarcer places.")
    else:
        lines["why"] = (f"It is the fastest campus with a free staffed place within {check['max_minutes']} minutes. "
                        "No detour was needed to keep a scarcer place free.")
    lines["status"].append("A suggestion from capacity and travel time only, not a judgement of quality. "
                           "Nothing is booked. Phone ahead.")
    return lines
