"""Online assignment for an explicitly synthetic, single-shift storm demonstration."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from itertools import groupby
from operator import attrgetter
from math import ceil

from .scenario import URGENCY_ORDER, Campus, Origin, Request, Resource, Scenario

POLICIES = ("nearest_first", "scarcity_aware")
# A protected profile is a scenario input visible before arrivals. It is not a prediction.
PROTECTED_PROFILES = (("dialysis", ("monitored",), 20),)


@dataclass(frozen=True)
class Option:
    campus: Campus
    resource: Resource
    travel: int | Decimal


def _supports(resource: Resource, service: str, tools: tuple[str, ...]) -> bool:
    return resource.service == service and set(tools).issubset(resource.tools)


def _options(campuses: tuple[Campus, ...], origin: Origin, request: Request,
             remaining: dict[str, int | None]) -> tuple[list[Option], dict[str, int]]:
    options = []
    excluded = Counter()
    for campus in campuses:
        travel = origin.travel_minutes[campus.id]
        for resource in campus.resources:
            if not _supports(resource, request.service, request.required_tools):
                reason = "required_service_or_tool_unavailable"
            elif travel > request.max_travel_minutes:
                reason = "outside_travel_window"
            elif resource.capacity_status != "known" or remaining[resource.id] is None:
                reason = "unknown_or_stale_capacity"
            elif remaining[resource.id] == 0:
                reason = "no_staffed_slot_left"
            else:
                options.append(Option(campus, resource, travel))
                continue
            excluded[reason] += 1
    return sorted(options, key=lambda o: (o.travel, o.campus.id, o.resource.id)), dict(excluded)


def _losses(campuses: tuple[Campus, ...], origin: Origin, request: Request,
            remaining: dict[str, int | None]) -> dict[str, list[str]]:
    """Which optional assignments would consume the final known reachable specialist slot?"""
    losses = {}
    for service, tools, catchment in PROTECTED_PROFILES:
        if service != request.service or set(tools).issubset(request.required_tools):
            continue
        available = []
        for campus in campuses:
            if origin.travel_minutes[campus.id] > catchment:
                continue
            for resource in campus.resources:
                if (_supports(resource, service, tools) and resource.capacity_status == "known"
                        and remaining[resource.id]):
                    available.append(resource.id)
        if len(available) == 1 and remaining[available[0]] == 1:
            losses.setdefault(available[0], []).append(f"{service}/{'/'.join(tools)}")
    return losses


def preview_assignment(request: Request, origin: Origin, campuses: tuple[Campus, ...],
                       remaining: dict[str, int | None], policy: str, cap: int | Decimal) -> dict:
    """Choose from the current snapshot without reserving or consuming a slot."""
    options, excluded = _options(campuses, origin, request, remaining)
    event = {"request_id": request.id, "minute": request.arrival_minute, "origin_id": origin.id,
             "service": request.service, "urgency": request.urgency,
             "excluded_pool_counts": excluded, "status": "unassigned",
             "eligible_campuses": list(dict.fromkeys(o.campus.id for o in options)),
             "campus_id": None, "resource_id": None, "travel_minutes": None,
             "nearest_feasible_minutes": None, "extra_travel_minutes": None,
             "nearest_campus_id": None, "resource_before": None, "resource_after": None,
             "preserved_profiles": []}
    if not options:
        # Report the closest actionable reason, plus the full exclusions in the trace.
        event["reason"] = next((reason for reason in (
            "no_staffed_slot_left", "unknown_or_stale_capacity", "outside_travel_window",
            "required_service_or_tool_unavailable") if excluded.get(reason, 0)), "required_service_or_tool_unavailable")
        return event

    nearest = options[0]
    chosen = nearest
    reason = "nearest_feasible"
    if policy == "scarcity_aware" and request.urgency != "highest":
        losses = _losses(campuses, origin, request, remaining)
        nearby = [o for o in options if o.travel <= nearest.travel + cap]
        chosen = min(nearby, key=lambda o: (len(losses.get(o.resource.id, ())),
                                            o.travel, o.campus.id, o.resource.id))
        if chosen != nearest:
            reason = "preserve_reachable_specialist_slot"
            event["preserved_profiles"] = sorted(set(losses[nearest.resource.id])
                                                   - set(losses.get(chosen.resource.id, ())))
    resource = chosen.resource
    free = remaining[resource.id]
    if free is None or resource.slots is None or free <= 0:
        raise ValueError("Assignment requires known positive staffed capacity")
    event.update(status="recommended", reason=reason, campus_id=chosen.campus.id,
                 resource_id=resource.id, travel_minutes=chosen.travel,
                 nearest_feasible_minutes=nearest.travel, nearest_campus_id=nearest.campus.id,
                 extra_travel_minutes=chosen.travel - nearest.travel)
    event["nearest_resource_id"] = nearest.resource.id
    return event


def _event(request: Request, origin: Origin, campuses: tuple[Campus, ...],
           remaining: dict[str, int | None], used: Counter, policy: str, cap: int) -> dict:
    event = preview_assignment(request, origin, campuses, remaining, policy, cap)
    event.pop("nearest_resource_id", None)
    if event["status"] == "recommended":
        resource_id = event["resource_id"]
        free, already_used = remaining[resource_id], used[resource_id]
        used[resource_id] += 1
        remaining[resource_id] = free - 1
        event.update(status="assigned",
                     resource_before={"used": already_used, "free": free},
                     resource_after={"used": already_used + 1, "free": free - 1})
    return event


def _stats(events: list[dict]) -> dict:
    assigned = [e for e in events if e["status"] == "assigned"]
    times = sorted(e["extra_travel_minutes"] for e in assigned)
    return {"requested": len(events), "assigned": len(assigned),
            "unassigned": len(events) - len(assigned),
            "extra_travel_minutes": sum(times),
            "p90_extra_travel_minutes": times[ceil(.9 * len(times)) - 1] if times else None}


def _apply_change(change, remaining, used):
    free = remaining[change.resource_id]
    if free is None or change.lost_free_slots < 0:
        raise ValueError("Downtime changes require known capacity and a nonnegative reduction")
    lost = min(free, change.lost_free_slots)
    remaining[change.resource_id] -= lost
    return {"minute": change.minute, "resource_id": change.resource_id,
            "reason": "unbooked_slots_went_offline", "lost_free_slots": lost,
            "resource_before": {"used": used[change.resource_id], "free": free},
            "resource_after": {"used": used[change.resource_id], "free": free - lost}}


def run_policy(scenario: Scenario, policy: str, detour_minutes: int) -> dict:
    if policy not in (*POLICIES, "arrival_fifo"):
        raise ValueError(f"Unknown policy {policy!r}")
    if type(detour_minutes) is not int or detour_minutes < 0:
        raise ValueError("detour_minutes must be a nonnegative integer")
    origins = {origin.id: origin for origin in scenario.origins}
    resources = [r for c in scenario.campuses for r in c.resources]
    remaining = {r.id: r.slots if r.capacity_status == "known" else None for r in resources}
    events = []
    updates = []
    used = Counter()
    changes = iter(sorted(scenario.capacity_changes, key=attrgetter("minute")))
    next_change = next(changes, None)
    last_minute = -1
    for minute, arrivals in groupby(scenario.requests, key=lambda request: request.arrival_minute):
        if minute < last_minute:
            raise ValueError("Arrivals must be in chronological order")
        last_minute = minute
        while next_change is not None and next_change.minute <= minute:
            updates.append(_apply_change(next_change, remaining, used))
            next_change = next(changes, None)
        current = list(arrivals)
        if policy != "arrival_fifo":
            current.sort(key=lambda request: URGENCY_ORDER[request.urgency])
        for request in current:
            events.append(_event(request, origins[request.origin_id], scenario.campuses,
                                 remaining, used, policy, detour_minutes))
    while next_change is not None:
        updates.append(_apply_change(next_change, remaining, used))
        next_change = next(changes, None)
    metrics = _stats(events)
    metrics["by_urgency"] = {urgency: _stats([e for e in events if e["urgency"] == urgency])
                             for urgency in URGENCY_ORDER}
    metrics["within_window"] = sum(e["status"] == "assigned" for e in events)
    metrics["unassigned_reasons"] = dict(Counter(e["reason"] for e in events
                                                 if e["status"] == "unassigned"))
    metrics["capacity_violations"] = sum(free < 0 for free in remaining.values() if free is not None)
    return {"events": events, "capacity_events": updates, "metrics": metrics, "final_free_slots": remaining}


def replay(scenario: Scenario, detour_minutes: int = 10, include_control: bool = False) -> dict:
    policies = (*POLICIES, "arrival_fifo") if include_control else POLICIES
    return {
        "schema_version": "storm-replay-v1", "synthetic": True, "scenario": scenario.name,
        "seed": scenario.seed, "area": "Jaipur area, India",
        "label": "Fictional campuses, origins, requests, staffed slots and travel times.",
        "window": "One shift of shared staffed appointments. Each assignment consumes one slot.",
        "travel_basis": "Illustrative origin-to-campus travel minutes",
        "policy_version": "online-allocation-v1", "detour_minutes": detour_minutes,
        "highest_urgency_detour_minutes": 0,
        "protected_profiles": [{"service": s, "required_tools": tools, "catchment_minutes": t}
                               for s, tools, t in PROTECTED_PROFILES],
        "campuses": [asdict(c) for c in scenario.campuses],
        "origins": [asdict(o) for o in scenario.origins],
        "requests": [asdict(r) for r in scenario.requests],
        "capacity_changes": [asdict(c) for c in scenario.capacity_changes],
        "policies": {policy: run_policy(scenario, policy, detour_minutes) for policy in policies},
    }
