"""Words for the capacity-aware recommendation on the Find care screen (#304). No Streamlit dependency.

The choice itself is P's `recommend_capacity` on the synthetic Jaipur campuses A to F (#303). Drive
minutes are the scenario's simulated minutes unless the operator has switched on A's traffic-aware
ordinary-car source (#96, `travel.hosted.demo_car_travel`). Nothing here ranks, books or calls a
network by itself: `run` is called once per explicit submit, and the rest only words its result.

The campus the model chose is the one destination of a recommendation: the headline, the time, the
reasons, the alternatives and the referral note are all read from the same result, and when the
model recommends nothing there is no destination and no note. Campuses A to F are invented scenario
campuses. They are never joined to the six invented catalogue hospitals of the record lookup.
"""
from datetime import datetime, timezone

try:
    from capacity_recommendation import demo_capacity_inputs, recommend_capacity
except ImportError:  # repository tests import the package
    from app.capacity_recommendation import demo_capacity_inputs, recommend_capacity

SERVICES = {"dialysis": "Dialysis", "mri": "MRI scan", "trauma_care": "Trauma care"}
URGENCIES = {"routine": "Routine", "time_sensitive": "Within hours", "highest": "Highest"}
ORIGINS = {"central": "Central", "east": "East", "south": "South", "west": "West"}
TOOLS = {"dialysis": ("monitored", "a monitored dialysis station")}
SIMULATED = "simulated"
TRAFFIC = "traffic"
SIMULATED_LABEL = "Simulated drive minutes from the Jaipur storm scenario, not a road estimate."
TRAFFIC_SOURCE = "TomTom"
ORIGIN_NOTE = ("The recommendation works from four simulated starting areas in Jaipur. A typed city, PIN code "
               "or search distance is not used for it. Use the record lookup for those.")
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
    "travel_no_route": "no road route found",
}
NO_CHOICE = {
    "no_staffed_slot_left": "Every campus within reach that offers this is full.",
    "unknown_or_stale_capacity": "No campus within reach has a known free staffed place.",
    "outside_travel_window": "No campus with a free place is within the travel limit.",
    "required_service_or_tool_unavailable": "No campus within reach has the equipment this patient needs.",
    "service_evidence_unreviewed": "No campus within reach has reviewed evidence for this service.",
    "travel_unavailable": "Road times could not be fetched. No simulated time is used in their place.",
    "travel_unknown": "Road times are unknown. No simulated time is used in their place.",
    "travel_stale": "Road times are out of date. No simulated time is used in their place.",
    "travel_invalid": "Road times could not be used. No simulated time is used in their place.",
    "travel_no_route": "No road route was found to any campus that could take this patient.",
    "stale_snapshot": "The capacity figures are out of date.",
    "snapshot_unavailable": "The capacity figures are not available.",
    "snapshot_origin_mismatch": "The capacity figures are for a different starting area.",
    "invalid_snapshot": "The capacity figures could not be read.",
    "invalid_request": "This request could not be checked against capacity.",
}
TRAVEL_REASONS = {
    "daily_call_budget_exceeded": "today's road-time request allowance is used up",
    "monthly_call_budget_exceeded": "this month's road-time request allowance is used up",
    "protected_allowance_exhausted": "the road-time request allowance is used up",
    "reserved_budget_exhausted": "the road-time request allowance is used up",
    "shared_provider_cooldown": "the road-time provider asked for a pause",
    "invalid_operator_configuration": "road time is not set up correctly on this deployment",
    "invalid_operator_budget": "road time is not set up correctly on this deployment",
    "budget_store_unavailable": "the road-time allowance could not be checked",
}
HOW = (
    "Only campuses with reviewed, dated evidence for the service, a known free staffed place and a known "
    "travel time inside the limit can be recommended. Full, unknown or out-of-date capacity is never guessed.",
    "The fastest such campus is recommended, unless going there would use up the last free specialist place "
    "within reach. Then a routine or within-hours patient is sent up to 10 minutes further to keep it free.",
    "The highest urgency always gets the fastest campus with a free place.",
    "When it cannot be confirmed which specialist place is the last one, there is no detour.",
    "Nothing is booked. The campuses, places and times are invented for this demonstration.",
)


def campus(facility_id):
    return f"Campus {facility_id}"


def run(service, urgency, origin_id, needs_tool, traffic, *, provider=None, travel=None):
    """One recommendation for one submitted request. The only place a route request can start.

    `traffic` asks A's ordinary-car source for minutes; `travel` (the module) and `provider` are passed
    in by the screen and by tests. A failed road time is kept as a failure: simulated minutes never
    stand in for it. Returns everything the screen shows, so a rerun reads it back and calls nothing.
    """
    if origin_id not in ORIGINS:
        raise ValueError("Choose one of the simulated starting areas.")
    tools = (TOOLS[service][0],) if needs_tool and service in TOOLS else ()
    request, snapshot = demo_capacity_inputs(service=service, urgency=urgency, origin_id=origin_id,
                                             required_tools=tools)
    kind = SIMULATED
    if traffic:
        kind = TRAFFIC
        snapshot = {**snapshot, "travel": travel.demo_car_travel(request, snapshot, origin_id=origin_id,
                                                                 provider=provider)}
    result = recommend_capacity(request, snapshot)
    evidence = None
    if result.get("chosen"):
        row = next(c for c in snapshot["candidates"] if c["facility_id"] == result["chosen"]["facility_id"])
        decision = row["services"][service]
        evidence = {"source_date": decision.get("source_date"),
                    "families": list(decision.get("independent_families") or [])}
    roster = []  # the same campuses and the same evidence the model read for this request, kept for a fallback lead
    for row in snapshot["candidates"]:
        pools = [pool for pool in snapshot.get("capacity", {}).get(row["facility_id"], ())
                 if pool.get("service") == service and set(tools).issubset(pool.get("tools", ()))]
        roster.append({"facility_id": row["facility_id"], "decision": dict(row["services"].get(service) or {}),
                       "pools": [{k: pool.get(k) for k in ("status", "free_slots", "source")} for pool in pools]})
    return {"asked": {"service": service, "urgency": urgency, "origin_id": origin_id,
                      "needs_tool": bool(tools), "traffic": bool(traffic)},
            "as_of": snapshot.get("as_of"), "roster": roster,
            "travel_kind": kind, "max_minutes": request["max_travel_minutes"],
            "detour_minutes": request["detour_minutes"], "evidence": evidence,
            "travel_rows": {key: {k: row.get(k) for k in ("status", "minutes", "source", "reason", "outcome", "requested_at")}
                            for key, row in snapshot["travel"].items()},
            "result": result}


def _minutes(value):
    return f"{value:.0f} min" if float(value).is_integer() else f"{value:.1f} min"


def _when(requested_at):
    """The provider request time as the travel source reported it. Never this screen's own clock."""
    if not requested_at:
        return "no request was sent"
    try:
        moment = datetime.fromisoformat(str(requested_at).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return f"requested at {requested_at}"
    return "requested at " + moment.strftime("%H:%M:%S UTC on %d %b %Y")


def _profile(profile):
    service, _, tool = profile.partition("/")
    if service in TOOLS and tool == TOOLS[service][0]:
        return TOOLS[service][1]
    return f"{tool} {service}".strip()


def request_line(check):
    asked = check["asked"]
    tool = f", needs {TOOLS[asked['service']][1]}" if asked["needs_tool"] else ""
    return (f"{SERVICES[asked['service']]}, {URGENCIES[asked['urgency']].lower()} urgency{tool}, from "
            f"{ORIGINS[asked['origin_id']].lower()} Jaipur (simulated).")


def explain(check):
    """Everything the screen shows for one recommendation, as plain lines.

    `destination` is the model's chosen campus, or None. Every other line about a destination is
    built from that same result, so nothing can name a different campus.
    """
    result = check["result"]
    asked = check["asked"]
    traffic = check["travel_kind"] == TRAFFIC
    unit = "by road, ordinary car with traffic" if traffic else "simulated"
    lines = {"destination": None, "headline": None, "trip": None, "why": None, "fastest": None,
             "uncertain": None, "alternatives": [], "evidence": [], "excluded": [], "travel_failures": [],
             "time_label": SIMULATED_LABEL, "limits": []}
    for key, count in result.get("exclusions", {}).items():
        lines["excluded"].append(f"{count} campus{'es' if count != 1 else ''} left out: "
                                 + EXCLUSIONS.get(key, key.replace("_", " ")) + ".")
    if traffic:
        for key, row in sorted(check["travel_rows"].items()):
            if row["status"] != "known" and row.get("reason") != "service_ineligible":
                reason = (f" ({TRAVEL_REASONS.get(row['reason']) or str(row['reason']).replace('_', ' ')})"
                          if row.get("reason") else "")
                lines["travel_failures"].append(
                    f"{campus(key)}: road time unavailable{reason}, {_when(row.get('requested_at'))}.")
        lines["time_label"] = (f"Road time for an ordinary car with traffic, from {TRAFFIC_SOURCE}. It is an estimate "
                               "between simulated Jaipur places, not the patient's own address.")
    if result["status"] == "emergency":
        lines["headline"] = "Emergency: call 112 now. No campus is recommended from this screen."
        return lines
    if result["status"] != "recommended":
        lines["headline"] = "No campus is recommended."
        lines["why"] = NO_CHOICE.get(result["reason"], "The capacity check found no campus it can recommend.")
        lines["limits"] = ["No recommendation is not the same as no campus offering the service. It means none "
                           "could be confirmed with a free staffed place and a known travel time."]
        return lines

    chosen, fastest = result["chosen"], result["fastest"]
    chosen_id = chosen["facility_id"]
    lines["destination"] = campus(chosen_id)
    lines["headline"] = f"Send the patient to {campus(chosen_id)}."
    places = chosen["free_staffed_slots"]
    lines["trip"] = (f"{_minutes(chosen['travel_minutes'])} ({unit}). {places} free staffed place"
                     f"{'s' if places != 1 else ''} for this service when checked.")
    if traffic:
        lines["time_label"] += " This time was " + _when(check["travel_rows"][chosen_id].get("requested_at")) + "."
    if result["reason"] == "preserve_reachable_specialist_slot":
        protected = ", ".join(_profile(p) for p in result["preserved_profiles"]) or "a scarcer place"
        lines["fastest"] = (f"Fastest with a free place: {campus(fastest['facility_id'])}, "
                            f"{_minutes(fastest['travel_minutes'])}. Not recommended for this patient.")
        lines["why"] = (f"{campus(chosen_id)} is {_minutes(result['extra_travel_minutes'])} further. "
                        f"{campus(fastest['facility_id'])} has the last free place with {protected} within reach, "
                        "so it is kept for a patient who needs it. A detour is allowed only up to "
                        f"{check['detour_minutes']} minutes and never for the highest urgency.")
    elif result["reason"] == "scarcity_indeterminate":
        unsure = ", ".join(_profile(p) for p in result.get("uncertain_profiles", [])) or "a specialist place"
        lines["why"] = (f"It is the fastest campus with a free staffed place within {check['max_minutes']} minutes.")
        lines["uncertain"] = (f"Not certain: this may use the last free place with {unsure} within reach. Capacity "
                              "or travel time at another campus is unknown, so that could not be confirmed, and "
                              "no detour was made on a guess.")
    elif asked["urgency"] == "highest":
        lines["why"] = ("Highest urgency: it is the fastest campus with a free staffed place. No detour is made "
                        "to keep scarcer places free.")
    else:
        lines["why"] = (f"It is the fastest campus with a free staffed place within {check['max_minutes']} minutes. "
                        "No detour was needed to keep a scarcer place free.")
    rows = check["travel_rows"]
    protected_id = fastest["facility_id"] if result["reason"] == "preserve_reachable_specialist_slot" else None
    for other in result.get("eligible_campus_ids", []):
        if other not in (chosen_id, protected_id) and rows.get(other, {}).get("minutes") is not None:
            lines["alternatives"].append(f"{campus(other)} ({_minutes(rows[other]['minutes'])})")
    evidence = check.get("evidence") or {}
    lines["evidence"] = [
        f"Location · {campus(chosen_id)} is an invented campus at a simulated point in the Jaipur storm scenario. "
        "It has no real address.",
        f"{SERVICES[asked['service']]} · Marked as running in the scenario's own record, dated "
        f"{evidence.get('source_date') or 'unknown'}. One invented origin (the synthetic storm fixture). "
        "Not a reviewed real facility.",
    ]
    lines["limits"] = ["Chosen by free staffed places and travel time only. It is not a judgement of quality or cost.",
                       "Nothing is booked. A free place when checked can be gone on arrival. Phone ahead.",
                       "Every campus, place count and time here is invented for the demonstration."]
    return lines


def referral_note(check, attribution=None):
    """Plain text to copy or save, for the model's chosen campus only. None when nothing is recommended.

    `attribution` is the operator's copyright caption. It goes on a note that carries a road time.
    """
    lines = explain(check)
    if not lines["destination"]:
        return None
    note = ["Referral note (demonstration data, invented campuses)",
            "Request: " + request_line(check),
            "Send to: " + lines["destination"],
            "Travel and places: " + lines["trip"],
            "Why: " + lines["why"]]
    if lines["fastest"]:
        note.append(lines["fastest"])
    if lines["uncertain"]:
        note.append(lines["uncertain"])
    if lines["alternatives"]:
        note.append("If it cannot take the patient: " + "; ".join(lines["alternatives"]))
    note.append("Travel time: " + lines["time_label"])
    if attribution and check["travel_kind"] == TRAFFIC:
        note.append("Map data: " + attribution)
    note.append("Limits: chosen by free places and travel time, not quality. Nothing is booked. Phone ahead.")
    note.append("If this could be an emergency, call 112.")
    return "\n".join(note)
