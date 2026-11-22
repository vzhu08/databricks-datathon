"""Exact offline planning for one simulated storm shift, plus an online comparator."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import csv
from dataclasses import dataclass
from hashlib import sha256
from heapq import heappop, heappush
import io
import json
from math import ceil
from pathlib import Path
import random
import sys

if "." in __package__:
    from ..ranking.location import coordinates, haversine_km
else:
    from ranking.location import coordinates, haversine_km

from .scenario import SERVICES, URGENCY_ORDER


SCHEMA_VERSION = "storm-plan-v1"
REQUEST_COUNT = 120
HORIZON_MINUTES = 360
SPEED_KMH = 30


@dataclass
class _Arc:
    node: int
    reverse: int
    residual: int
    cost: int


@dataclass(frozen=True)
class _Option:
    facility: str
    slot_id: str
    start: int
    seconds: int


def _keyed(rows, key):
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Expected object records")
        value = row.get(key)
        if not isinstance(value, str) or not value.strip() or value in result:
            raise ValueError(f"Expected unique, nonempty {key} values")
        result[value] = row
    return dict(sorted(result.items()))


def _integer(value, lower=0, upper=None):
    return type(value) is int and value >= lower and (upper is None or value <= upper)


def _tools(labels):
    if not isinstance(labels, (tuple, list)) or any(not isinstance(s, str) or not s.strip() for s in labels):
        raise ValueError("Tools must be lists of nonempty labels")
    return set(labels)


def _instance_edges(data):
    """Build both policies' common feasible edge list with integer-second boundaries."""
    horizon = data["scenario"]["horizon_minutes"]
    if not _integer(horizon, 1):
        raise ValueError("Expected a positive horizon in minutes")
    facilities = _keyed(data["facilities"], "id")
    patients = _keyed(data["patients"], "id")
    slots = {}
    bucket_keys = set()
    points = {}
    for fid, facility in facilities.items():
        precision = facility.get("precision")
        if precision not in ("point", "area"):
            raise ValueError("Expected point or area location precision")
        points[fid] = coordinates(facility) if precision == "point" else None
        resources = _keyed(facility.get("resources", []), "slot_id")
        for sid, slot in resources.items():
            start = slot.get("start_minute")
            pool = slot.get("resource_id")
            if (precision != "point" or sid in slots or not isinstance(pool, str) or not pool.strip()
                    or not _integer(start, upper=horizon) or not _integer(slot.get("slots"))
                    or slot.get("service") not in SERVICES or (fid, pool, start) in bucket_keys):
                raise ValueError("Invalid or duplicate staffed appointment bucket")
            bucket_keys.add((fid, pool, start))
            _tools(slot["tools"])
            slots[sid] = (fid, slot)
        facility["resources"] = list(resources.values())

    explicit = data.get("travel_seconds")
    if explicit is not None and (not isinstance(explicit, dict) or set(explicit) - patients.keys()):
        raise ValueError("Travel seconds must be keyed by known patient ID")
    if explicit is None and data["scenario"].get("speed_kmh") != SPEED_KMH:
        raise ValueError("Supply a modelled travel matrix or declare the supported synthetic speed")

    options, blocked = {}, {}
    for pid, patient in patients.items():
        service = patient.get("service")
        start, deadline = patient.get("arrival_minute"), patient.get("deadline_minute")
        if (service not in SERVICES or patient.get("priority") not in URGENCY_ORDER
                or not _integer(start, upper=horizon) or not _integer(deadline, start, horizon)):
            raise ValueError("Invalid simulated request service, priority or time window")
        required = _tools(patient["required_tools"])
        point = coordinates(patient)
        times = {} if explicit is None else explicit.get(pid, {})
        if (not isinstance(times, dict) or set(times) - facilities.keys()
                or any(value is not None and not _integer(value) for value in times.values())):
            raise ValueError("Travel entries must be integer seconds or null for known facilities")
        if explicit is None and point is not None:
            times = {fid: ceil(haversine_km(point, dest) * 3600 / SPEED_KMH)
                     for fid, dest in points.items() if dest is not None}

        fitting, timed = 0, 0
        eligible = []
        for sid, (fid, slot) in slots.items():
            if slot["service"] != service or not required.issubset(slot["tools"]):
                continue
            fitting += 1
            seconds = times.get(fid)
            if seconds is None:
                continue
            timed += 1
            appointment = slot["start_minute"]
            if start * 60 + seconds <= appointment * 60 <= deadline * 60:
                eligible.append(_Option(fid, sid, appointment, seconds))
        options[pid] = sorted(eligible, key=lambda o: (o.seconds, o.start, o.facility, o.slot_id))
        blocked[pid] = ("compatible_slots_exhausted" if eligible
                        else "no_matching_service_or_tools" if not fitting
                        else "modelled_travel_unknown" if not timed else "outside_appointment_window")
    return facilities, patients, slots, options, blocked


def _add_edge(graph, tail, head, capacity, cost):
    arc = _Arc(head, len(graph[head]), capacity, cost)
    graph[head].append(_Arc(tail, len(graph[tail]), 0, -cost))
    graph[tail].append(arc)
    return arc


def _send_units(graph, source, sink, total):
    """Successive shortest augmenting paths with reduced costs and potentials."""
    potential = [0] * len(graph)
    for _ in range(total):
        dist = [None] * len(graph)
        prev = [None] * len(graph)
        dist[source] = 0
        queue = [(0, source)]
        while queue:
            cost, here = heappop(queue)
            if dist[here] != cost:
                continue
            for index, arc in enumerate(graph[here]):
                score = cost + arc.cost + potential[here] - potential[arc.node]
                if arc.residual and (dist[arc.node] is None or score < dist[arc.node]):
                    dist[arc.node], prev[arc.node] = score, (here, index)
                    heappush(queue, (score, arc.node))
        # Each patient also has a direct unserved arc to the sink.
        if prev[sink] is None:
            raise RuntimeError("Each patient must have an unserved alternative")
        for i, value in enumerate(dist):
            if value is not None:
                potential[i] += value
        node = sink
        while node != source:
            here, index = prev[node]
            arc = graph[here][index]
            arc.residual -= 1
            graph[node][arc.reverse].residual += 1
            node = here


def _exact(patients, slots, options):
    count = len(patients)
    max_seconds = max((o.seconds for rows in options.values() for o in rows), default=0)
    # Maximum total travel fits strictly below travel_base. Each unmet
    # priority digit fits below priority_base, so scalar cost is lexicographic.
    travel_base = count * max_seconds + 1
    priority_base = count + 1
    slot_nodes = {key: i for i, key in enumerate(sorted(slots), count + 1)}
    source, sink = 0, count + len(slots) + 1
    graph = [[] for _ in range(sink + 1)]
    for sid, node in slot_nodes.items():
        _add_edge(graph, node, sink, slots[sid][1]["slots"], 0)
    tracked = {}
    for i, (pid, patient) in enumerate(patients.items(), 1):
        _add_edge(graph, source, i, 1, 0)
        penalty = travel_base * priority_base ** (2 - URGENCY_ORDER[patient["priority"]])
        _add_edge(graph, i, sink, 1, penalty)
        tracked[pid] = [
            (option, _add_edge(graph, i, slot_nodes[option.slot_id], 1, option.seconds))
            for option in options[pid]
        ]
    _send_units(graph, source, sink, count)
    return {pid: option for pid, rows in tracked.items() for option, arc in rows if arc.residual == 0}


def _nearest(patients, slots, options):
    remaining = {sid: slot[1]["slots"] for sid, slot in slots.items()}
    picked = {}
    for pid in sorted(patients, key=lambda pid: (patients[pid]["arrival_minute"], pid)):
        option = next((row for row in options[pid] if remaining[row.slot_id]), None)
        if option is not None:
            remaining[option.slot_id] -= 1
            picked[pid] = option
    return picked


def _output(patients, slots, blocked, assigned):
    bookings = []
    unmet = []
    by_priority = {priority: {"assigned": 0, "unmet": 0} for priority in URGENCY_ORDER}
    used = Counter()
    for pid, patient in patients.items():
        bucket = by_priority[patient["priority"]]
        if pid not in assigned:
            bucket["unmet"] += 1
            unmet.append({"patient": pid, "reason": blocked[pid]})
            continue
        bucket["assigned"] += 1
        option = assigned[pid]
        used[option.slot_id] += 1
        bookings.append({"patient": pid, "facility": option.facility, "service": patient["service"],
                         "slot_id": option.slot_id, "slot_start_minute": option.start,
                         "travel_seconds": option.seconds, "travel_minutes": option.seconds / 60})
    return {
        "assignments": bookings,
        "unserved": unmet,
        "metrics": {
            "assigned": len(bookings), "unmet": len(unmet), "by_priority": by_priority,
            "total_travel_seconds": sum(row["travel_seconds"] for row in bookings),
            "resources_used": [
                {"slot_id": sid, "facility": fid, "service": slot["service"],
                 "used": used[sid], "slots": slot["slots"]}
                for sid, (fid, slot) in sorted(slots.items())
            ],
            "unserved_reasons": dict(sorted(Counter(row["reason"] for row in unmet).items())),
        },
    }


def _validate_geography(geography):
    kind = geography.get("location_basis")
    if kind not in ("synthetic", "public_source"):
        raise ValueError("Label geography as synthetic or approved public-source input")
    if kind == "public_source":
        for field in ("name", "selection", "source", "verification", "roster_sha256"):
            if not isinstance(geography.get(field), str) or not geography[field].strip():
                raise ValueError("Public-source geography requires selection, verification and custody metadata")
        attribution = geography.get("attribution")
        if (not isinstance(attribution, list) or not attribution
                or any(not isinstance(item, dict) or not item.get("text") or not item.get("url")
                       for item in attribution)):
            raise ValueError("Public-source geography requires attribution")


def solve(instance):
    """Return both policies' storm-plan-v1 results without modifying the input."""
    data = deepcopy(instance)
    _validate_geography(data["geography"])
    facilities, patients, slots, options, blocked = _instance_edges(data)
    return {
        "schema_version": SCHEMA_VERSION,
        "geography": data["geography"],
        "scenario": data["scenario"],
        "facilities": list(facilities.values()),
        "patients": list(patients.values()),
        "policies": {
            "nearest_first": _output(patients, slots, blocked, _nearest(patients, slots, options)),
            "exact_optimum": _output(patients, slots, blocked, _exact(patients, slots, options)),
        },
    }


def _fixture_roster():
    return {
        "geography": {
            "name": "Synthetic test geography", "location_basis": "synthetic",
            "selection": "Eight generated sites. No district or actual hospital is represented.",
            "source": "Seeded planning fixture", "verification": "Synthetic points only", "attribution": [],
        },
        "facilities": [{"id": f"test-{i + 1}", "label": f"Simulated site {i + 1}", "precision": "point",
                        "latitude": (i // 4) * 0.055, "longitude": (i % 4) * 0.06}
                       for i in range(8)],
    }


def make_instance(roster=None, *, seed=17):
    """Generate one fixed 120-request shift against point sites in an operator-cleared roster."""
    roster = _fixture_roster() if roster is None else deepcopy(roster)
    geography = roster["geography"]
    _validate_geography(geography)
    facilities = list(_keyed(roster["facilities"], "id").values())
    points = [f for f in facilities if f.get("precision") == "point" and coordinates(f) is not None]
    # Pick eight deterministic point/anchor endpoints. Area records are context only.
    points = points[:8]
    if not points:
        raise ValueError("The roster needs at least one usable point or campus simulation anchor")
    areas = [f for f in facilities if f.get("precision") == "area"]
    selected = points + areas
    for i, facility in enumerate(points):
        fid = facility["id"]
        facility["resources"] = [
            {"slot_id": f"{fid}:{service}:{start}", "resource_id": f"{fid}:{service}", "service": service,
             "start_minute": start, "slots": 1,
             "tools": ["monitored"] if service == "dialysis" and i % 3 == 0 else []}
            for start in (45, 90, 135, 180, 225, 270)
            for service in SERVICES
        ]
    for facility in areas:
        facility["resources"] = []
    rng = random.Random(seed)
    patients = []
    for i in range(REQUEST_COUNT):
        wave, position = divmod(i, 20)
        service = SERVICES[position % len(SERVICES)]
        priority = rng.choices(list(URGENCY_ORDER), weights=(2, 3, 5))[0]
        arrival = wave * 45 + rng.randrange(0, 20)
        # Demand locations are generated near, never identified with, a roster point.
        site = rng.choice(points)
        lat, lon = coordinates(site)
        tools = ["monitored"] if service == "dialysis" and priority == "highest" else []
        allowance = {"highest": 47, "time_sensitive": 70, "routine": 94}[priority]
        patients.append({
            "id": f"sim-{i + 1:03}", "priority": priority, "service": service, "required_tools": tools,
            "latitude": max(-90, min(90, lat + rng.uniform(-0.018, 0.018))),
            "longitude": max(-180, min(180, lon + rng.uniform(-0.018, 0.018))),
            "arrival_minute": arrival, "deadline_minute": min(HORIZON_MINUTES, arrival + allowance),
        })
    return {
        "geography": {**geography, "planning_point_sites": len(points),
                      "input_point_sites": sum(f.get("precision") == "point" for f in facilities)},
        "scenario": {
            "seed": seed, "horizon_minutes": HORIZON_MINUTES, "horizon": "One six-hour simulated shift",
            "objective": "Minimize unmet highest, time-sensitive and routine requests, in order, then travel seconds",
            "travel_basis": "Geodesic distance at a constant synthetic 30 km/h, rounded up to whole seconds",
            "simulated": "Synthetic demand, urgency, capabilities, staffing and travel. The planner sees the full shift.",
            "speed_kmh": SPEED_KMH, "point_selection": "First eight usable points by stable source ID",
        },
        "facilities": selected,
        "patients": patients,
    }


def load_roster_csv(path, geography):
    """Read Vincent's cleared four-column public-source file at its approved byte pin."""
    _validate_geography(geography)
    if geography["location_basis"] != "public_source":
        raise ValueError("CSV operator roster must carry public-source geography metadata")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != geography["roster_sha256"]:
        raise ValueError("The roster bytes do not match the approved SHA-256")
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if rows.fieldnames != ["facility_id", "facility_name", "latitude", "longitude"]:
        raise ValueError("Expected the cleared four-column location roster")
    facilities = []
    for row in rows:
        point = coordinates(row)
        if point is None or not row["facility_name"] or None in row:
            raise ValueError("Invalid name or point in the cleared location roster")
        facilities.append({
            "id": row["facility_id"], "label": row["facility_name"], "precision": "point",
            "point_scope": "Publisher-reported mapped facility point; entrance unknown",
            "latitude": point[0], "longitude": point[1],
        })
    _keyed(facilities, "id")
    return {"geography": geography, "facilities": facilities}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, help="Operator-cleared roster JSON or pinned four-column CSV.")
    parser.add_argument("--geography", type=Path, help="Cleared geography metadata JSON for a CSV roster.")
    parser.add_argument("--instance", type=Path, help="Replay a complete synthetic planning instance.")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)
    if args.roster and args.instance:
        parser.error("Select --roster or --instance")
    csv_input = args.roster is not None and args.roster.suffix.lower() == ".csv"
    if csv_input != (args.geography is not None):
        parser.error("Supply --geography with a CSV roster")
    if args.instance:
        instance = json.loads(args.instance.read_text(encoding="utf-8"))
    else:
        roster = None
        if csv_input:
            geography = json.loads(args.geography.read_text(encoding="utf-8"))
            roster = load_roster_csv(args.roster, geography)
        elif args.roster:
            roster = json.loads(args.roster.read_text(encoding="utf-8"))
        instance = make_instance(roster, seed=args.seed)
    json.dump(solve(instance), sys.stdout, ensure_ascii=False, allow_nan=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
