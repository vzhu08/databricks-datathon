"""The planning simulation on the Storm page: many simulated patients placed across real facility locations.

One results file, storm_ui/data/plan.json, holds the chosen geography, the facilities with the precision
of each location, the simulated patients, and what two policies did with identical inputs: nearest first
and the exact optimum for the stated objective. Nothing is allocated here. This module reads the file,
refuses it unless it is internally consistent, and counts every figure it shows from the assignments
themselves, so a stored total can never disagree with the detail.

The facility locations are real, at the precision the file gives. Patients, need, urgency, which services
a facility offers, staffed places and travel times are simulated. Without a valid file the Storm page
shows the checked replay alone and this section is not offered.
"""
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

FILE = Path(__file__).resolve().parent / "storm_ui" / "data" / "plan.json"
# Roads under the map of real locations: one reviewed GeoJSON layer, packaged beside the plan at deployment and
# not kept in Git. Only these exact bytes are drawn (SHA-256 of the edition handed over on issue #323).
ROADS_FILE = FILE.with_name("roads.geojson")
ROADS_MAX_BYTES = 6 * 1024 * 1024
APPROVED_ROADS = {"02e738e10c2bdd264cb8ed4e2031c94f82767a5a3dc00a233fe9d2d1f7ea181b"}
ROAD_TIERS = (  # drawn in this order, so the main roads lie on top: (OSM highway classes, colour, width)
    ((), "#e1e6ea", 0.6),  # every other class
    (("tertiary", "tertiary_link"), "#d2d9de", 0.9),
    (("secondary", "secondary_link"), "#c0cad1", 1.3),
    (("primary", "primary_link"), "#acb8c1", 1.8),
    (("motorway", "motorway_link", "trunk", "trunk_link"), "#98a7b2", 2.4),
)
ROAD_BUDGET = 600_000  # characters of line drawing; beyond it the smallest roads are left out
ROADS_NOTE = ("The roads are drawn for orientation only. No travel time on this page is calculated from these "
              "lines.")
SCHEMA = "storm-plan-v1"
MAX_BYTES = 4 * 1024 * 1024
POLICIES = (("nearest_first", "Nearest first"), ("exact_optimum", "Exact optimum"))
# How well each location is known, in the data owner's terms. None of them establishes an entrance.
PRECISION = {"mapped_point": "Mapped facility point", "campus_anchor": "Campus simulation anchor",
             "point": "Located point", "area": "Area only"}
ORDER = ("highest", "emergency", "time_sensitive", "urgent", "routine")  # used when the file gives no order
CHOICE = "Planning simulation"
NOTICE = ("Planning simulation. The facility locations are real, each at the precision it is labelled with. "
          "Everything else is simulated: the patients, where they start, what they need and how urgent they are, "
          "which services each facility offers, how many staffed places it has, and the travel times. This is not "
          "a record of a real storm and says nothing about what any facility offers today.")
LIVE_NOTICE = ("Signed-in road-time simulation. Real public map points identify approximate sites, not entrances. "
               "Patients, needs, urgency, capabilities and staffed places are simulated. Ordinary-car estimates "
               "start at two shared synthetic pickups. The modeled replay is available separately.")
NOTICE_SYNTHETIC = ("Planning simulation on a test geography. Everything on this page is simulated, including the "
                    "sites and where they are: no district and no actual hospital is represented. The patients, "
                    "their needs and urgency, the services, the staffed places and the travel times are simulated "
                    "too.")
# geography.location_basis is one of exactly two values. Generated sites say "synthetic" and are shown as
# simulated. Real locations say "public_source" and are shown as real only when the file also carries the
# SHA-256 of a roster approved here, a map credit, and for every facility a cleared precision class and
# its publisher and licence. Anything else is refused, so no other file can appear under the real label.
SYNTHETIC, PUBLIC = "synthetic", "public_source"
APPROVED_ROSTERS = {
    # Pune public-source planning roster, 12 venue-cleared sites (issue 323; read back independently there).
    "b62f377a61f9dee796ff0a4c56afcad96195a3ad196c1e4806dcc8c119e63f35",
}
CLEARED_PRECISION = ("mapped_point", "campus_anchor", "area")
REPRODUCE = ("The planner is app/simulation/batch_planner.py in the project repository. It needs the approved "
             "location roster whose SHA-256 is shown above; the roster itself is not kept in the repository.")
REPRODUCE_SYNTHETIC = ("The planner is app/simulation/batch_planner.py in the project repository. Running it with "
                       "this seed and no roster produces this file.")
SITES_NOTE = "The sites are generated for the test geography. No real place is shown."
LABEL = "Real facility locations · simulated patients, services, staffed places and travel"
LABEL_SYNTHETIC = "Simulated sites, patients, services, staffed places and travel · no real place is shown"
AREA_NOTE = ("A mapped facility point is a named point on a public map. A campus simulation anchor is a point "
             "chosen inside a mapped campus outline. A ring marks a facility known only to an area. None of these "
             "is a building entrance.")
KEYS = {
    "mapped_point": '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="5" '
                    'fill="#14283b"/></svg>',
    "point": '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="5" '
             'fill="#14283b"/></svg>',
    "campus_anchor": '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><rect x="4" y="4" width="10" '
                     'height="10" fill="#14283b"/></svg>',
    "area": '<svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true"><circle cx="11" cy="9" r="7" '
            'fill="none" stroke="#14283b" stroke-width="2" stroke-dasharray="4 3"/></svg>',
}
STYLE = """
<style>
.sp { color: #14283b; }
.sp-label { color: #4b6274; font-size: 0.95rem; }
.sp h3 { margin: 1.6rem 0 0.4rem; font-size: 1.15rem; }
.sp h3.sp-top { margin-top: 0.2rem; font-size: 1.35rem; }
.sp-facts { margin: 0.4rem 0 0; padding: 0; list-style: none; max-width: 100ch; }
.sp-facts li { margin-bottom: 0.3rem; overflow-wrap: anywhere; }
.sp-pair { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.8rem; }
.sp-card { flex: 1 1 17rem; padding: 0.9rem 1.1rem; background: #ffffff; border: 1.5px solid #c3ced6;
  border-radius: 3px; }
.sp-card.sp-best { border-color: #14283b; }
.sp-name { font-weight: 700; }
.sp-big { margin-top: 0.2rem; font-size: 2rem; line-height: 1.1; font-weight: 700; letter-spacing: -0.01em; }
.sp-small { margin-top: 0.3rem; color: #4b6274; font-size: 0.95rem; }
.sp-say { margin-top: 0.8rem; font-size: 1.0625rem; max-width: 90ch; }
.sp table { margin-top: 0.4rem; border-collapse: collapse; font-size: 1rem; }
.sp th, .sp td { padding: 0.3rem 1.25rem 0.3rem 0; text-align: left; border-bottom: 1px solid #dbe2e7; }
.sp td.sp-n, .sp th.sp-n { text-align: right; font-variant-numeric: tabular-nums; }
.sp td.sp-full { font-weight: 700; }
.sp details { margin-top: 0.8rem; }
.sp summary { cursor: pointer; font-weight: 600; }
.sp-scroll { overflow-x: auto; }
.sp-map { margin-top: 0.6rem; background: #ffffff; border: 1.5px solid #c3ced6; border-radius: 3px;
  max-width: 46rem; }
.sp-map svg { display: block; width: 100%; height: auto; }
.sp-key { margin-top: 0.4rem; color: #4b6274; font-size: 0.95rem; max-width: 90ch; }
.sp-key svg { vertical-align: -0.2em; }
.sp a { color: #14283b; }
.sp-live { margin: 0.7rem 0 1.5rem; padding: 0.9rem 1.1rem 1rem; background: #ffffff; border: 1.5px solid #c3ced6;
  border-radius: 3px; }
.sp .sp-live h3 { margin-top: 0; }
.sp-live p { margin: 0.4rem 0 0; max-width: 100ch; }
</style>
"""


class Unavailable(Exception):
    """No results file, or one that does not hold together. Nothing from it is shown."""


def _text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} is missing")
    return value.strip()


def _whole(value, what):
    if type(value) is not int or value < 0:
        raise ValueError(f"{what} is not a count")
    return value


def _number(value, what, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise ValueError(f"{what} is not a usable number")
    return float(value)


def urgency(patient):
    """A patient's priority. The planner calls it urgency; either name is read."""
    return _text(patient.get("priority", patient.get("urgency")), "patient priority")


def travel(row):
    """Travel for one assignment in minutes, using observed or modeled seconds when present."""
    if row.get("travel_seconds") is not None:
        return _number(row["travel_seconds"], "travel seconds", 0, 6_000_000) / 60
    return _number(row["travel_minutes"], "travel minutes", 0, 100000)


def _unique(rows, what):
    ids = [_text(row["id"], what + " id") for row in rows]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError(f"{what} ids are missing or repeated")
    return ids


def _checked_traffic(plan, facts):
    if not real(plan) or facts["patient_count"] != len(plan["patients"]):
        raise ValueError("road-time results need the approved simulated demand")
    pickups = facts["pickups"]
    if len(_unique(pickups, "pickup")) != 2 or facts["pickup_count"] != len(pickups):
        raise ValueError("road-time results need two shared pickups")
    groups = Counter(patient["pickup_id"] for patient in plan["patients"])
    if set(groups) != {p["id"] for p in pickups}:
        raise ValueError("a simulation request has no shared pickup")
    points = {}
    for pickup in pickups:
        key = pickup["id"]
        if _whole(pickup["patient_count"], "pickup patients") != groups[key]:
            raise ValueError("pickup counts differ from patient groups")
        points[key] = (_number(pickup["latitude"], "pickup latitude", -90, 90),
                       _number(pickup["longitude"], "pickup longitude", -180, 180))
    if len(set(points.values())) != 2:
        raise ValueError("shared pickup locations must be distinct")
    for patient in plan["patients"]:
        if (patient["latitude"], patient["longitude"]) != points[patient["pickup_id"]]:
            raise ValueError("a road-time result uses an individual origin")
    sites = _whole(facts["site_count"], "sites")
    total = _whole(facts["eligible_pairs"], "eligible pairs")
    usable = _whole(facts["usable_pairs"], "usable pairs")
    unavailable = _whole(facts["unavailable_pairs"], "unavailable pairs")
    attempted, attempts = facts["attempted_pairs"], facts["actual_attempts"]
    if (sites != 12 or sites != len(plan["facilities"]) or total != sites * len(pickups)
            or usable + unavailable != total):
        raise ValueError("road-time pair counts do not reconcile")
    if attempted is None or attempts is None:
        if usable or attempted is not None or attempts is not None:
            raise ValueError("incomplete road-time attempt counts")
    elif not (usable <= _whole(attempted, "attempted pairs") <= total
              and attempted <= _whole(attempts, "actual attempts") <= 2 * attempted):
        raise ValueError("road-time attempt counts do not reconcile")
    _text(facts["pickup_rule"], "pickup rule")
    _text(facts["source"], "road-time source")
    if usable:
        time = _text(facts["observed_at"], "road-time observation time")
        if datetime.fromisoformat(time.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("road-time observation has no timezone")
        credit = facts["attribution"]
        _text(credit["caption"], "road-time copyright caption")
        _text(credit["notices"], "road-time copyright notices")
    elif any(result["assignments"] for result in plan["policies"].values()):
        raise ValueError("an assignment has no observed road-time pair")


def checked(plan):
    """The plan, or ValueError/KeyError/TypeError. Every rule here is one a wrong allocation would break."""
    if plan["schema_version"] != SCHEMA:
        raise ValueError("unknown plan version")
    place, scenario = plan["geography"], plan["scenario"]
    for key in ("name", "selection", "source", "verification"):
        _text(place[key], "geography " + key)
    basis = place["location_basis"]
    if basis not in (SYNTHETIC, PUBLIC):
        raise ValueError("the location basis is neither synthetic nor public_source")
    if basis == PUBLIC:
        if place.get("roster_sha256") not in APPROVED_ROSTERS:
            raise ValueError("real locations need the hash of an approved roster")
        if not place.get("attribution"):
            raise ValueError("real locations need a map credit")
    for credit in place.get("attribution", []):
        _text(credit["text"], "attribution")
        if not _text(credit["url"], "attribution link").startswith("https://"):
            raise ValueError("attribution link is not https")
    for key in ("horizon", "objective", "travel_basis", "simulated"):
        _text(scenario[key], "scenario " + key)
    _whole(scenario["seed"], "seed")

    offers, buckets, areas = Counter(), {}, set()
    _unique(plan["facilities"], "facility")
    for facility in plan["facilities"]:
        _text(facility["label"], "facility label")
        _number(facility["latitude"], "latitude", -90, 90)
        _number(facility["longitude"], "longitude", -180, 180)
        if facility["precision"] not in PRECISION:
            raise ValueError("unknown location precision")
        if basis == PUBLIC and (facility["precision"] not in CLEARED_PRECISION or not facility.get("source")):
            raise ValueError("a real location needs a cleared precision class and its source")
        origin = facility.get("source")
        if origin is not None:
            _text(origin["publisher"], "source publisher")
            _text(origin["license"], "source licence")
            if origin.get("url") is not None and not _text(origin["url"], "source link").startswith("https://"):
                raise ValueError("source link is not https")
        if facility["precision"] == "area":
            areas.add(facility["id"])
        for resource in facility["resources"]:  # a facility may hold several appointment buckets of one service
            key = (facility["id"], _text(resource["service"], "service"))
            offers[key] += _whole(resource["slots"], "slots")
            if resource.get("slot_id") is not None:
                if resource["slot_id"] in buckets:
                    raise ValueError("a slot id is repeated")
                buckets[resource["slot_id"]] = (key, resource["slots"])

    _unique(plan["patients"], "patient")
    needs = {}
    for patient in plan["patients"]:
        needs[patient["id"]] = _text(patient["service"], "patient service")
        urgency(patient)
        if patient.get("latitude") is not None or patient.get("longitude") is not None:
            _number(patient["latitude"], "latitude", -90, 90)
            _number(patient["longitude"], "longitude", -180, 180)
    order = scenario.get("priorities")
    if order is not None and (len(set(order)) != len(order)
                              or {urgency(patient) for patient in plan["patients"]} - set(order)):
        raise ValueError("the priority order does not cover the patients")

    for key, _ in POLICIES:
        result, placed, used, booked = plan["policies"][key], set(), Counter(), Counter()
        for row in result["assignments"]:
            patient, facility, service = row["patient"], row["facility"], row["service"]
            if patient not in needs or patient in placed:
                raise ValueError("a patient is unknown or assigned twice")
            if service != needs[patient] or (facility, service) not in offers:
                raise ValueError("an assignment is to a facility without the needed service")
            if facility in areas:
                raise ValueError("an area-only marker is used as a travel endpoint")
            if "traffic" in plan and row.get("travel_seconds") is None:
                raise ValueError("a road-time assignment has no observed seconds")
            travel(row)
            placed.add(patient)
            used[(facility, service)] += 1
            if row.get("slot_id") is not None:
                if buckets.get(row["slot_id"], (None,))[0] != (facility, service):
                    raise ValueError("an assignment names a slot that is not that facility's")
                booked[row["slot_id"]] += 1
        if any(count > offers[resource] for resource, count in used.items()) \
                or any(count > buckets[slot][1] for slot, count in booked.items()):
            raise ValueError("a resource is used beyond its staffed places")
        left = [row["patient"] for row in result["unserved"]]
        for row in result["unserved"]:
            _text(row["reason"], "unserved reason")
        if set(left) & placed or len(set(left)) != len(left) or placed | set(left) != set(needs):
            raise ValueError("assigned and unserved patients do not add up to the patients")
        stored = result.get("metrics") or {}
        for name, counted in (("assigned", len(placed)), ("unmet", len(left)), ("unserved", len(left))):
            if type(stored.get(name)) is int and stored[name] != counted:
                raise ValueError("a stored total disagrees with the assignments")
    if "traffic" in plan:
        _checked_traffic(plan, plan["traffic"])
    return plan


def read_roads(raw):
    """The road layer from its bytes, or ValueError/KeyError/TypeError. The pin is checked before parsing."""
    if hashlib.sha256(raw).hexdigest() not in APPROVED_ROADS:
        raise ValueError("not a reviewed road layer")
    layer = json.loads(raw)
    credits = [{"text": _text(credit["text"], "road credit"), "url": _text(credit["url"], "road credit link")}
               for credit in layer["attribution"]]
    if not credits or any(not credit["url"].startswith("https://") for credit in credits):
        raise ValueError("the road layer has no usable credit")
    lines = []
    for feature in layer["features"]:
        geometry, about = feature["geometry"], feature.get("properties") or {}
        parts = {"LineString": [geometry["coordinates"]], "MultiLineString": geometry["coordinates"]}.get(
            geometry["type"], [])
        kind, name = about.get("highway"), about.get("name")
        for part in parts:
            points = [(float(point[0]), float(point[1])) for point in part]
            if len(points) > 1 and all(math.isfinite(x) and math.isfinite(y) and abs(x) <= 180 and abs(y) <= 90
                                       for x, y in points):
                lines.append((kind if isinstance(kind, str) else "", name.strip() if isinstance(name, str) else "",
                              points))
    if not lines:
        raise ValueError("the road layer has no line")
    return {"attribution": credits, "lines": lines}


_ROADS = {}  # the one parsed layer, kept while the file is unchanged


def load_roads(path=None):
    """The reviewed road layer, or None. Roads are context under the map, so any problem draws no road."""
    path = Path(path or ROADS_FILE)
    try:
        if not path.is_file():
            return None
        state = path.stat()
        if state.st_size > ROADS_MAX_BYTES:
            return None
        key = (str(path), state.st_mtime_ns, state.st_size, tuple(sorted(APPROVED_ROADS)))
        if key not in _ROADS:
            layer = read_roads(path.read_bytes())
            _ROADS.clear()
            _ROADS[key] = layer
        return _ROADS[key]
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        return None


def load(path=None):
    """Read and check the results file. Any failure is the same state: not available."""
    path = Path(path or FILE)
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise Unavailable("no results file")
        plan = json.loads(path.read_text(encoding="utf-8"))
        if "traffic" in plan:
            raise Unavailable("saved planner files must use modeled travel")
        return checked(plan)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise Unavailable(str(error)) from error


def patient_class(patient):
    """The kind of patient (for example high-acuity trauma or routine scheduled), when the file gives one."""
    value = patient.get("patient_class", patient.get("class"))
    return value.strip() if isinstance(value, str) and value.strip() else None


def basis(resource, facility):
    """Where a site's service and capacity come from. Unless the file says otherwise, they are simulated."""
    value = resource.get("basis", facility.get("capability_basis"))
    return _plain(value) if isinstance(value, str) and value.strip() and value != SYNTHETIC else "Simulated"


def breakdown(plan, key, results):
    """Patients, placed and not placed under each policy, and unmet reasons, grouped by `key(patient)`."""
    patients = {patient["id"]: patient for patient in plan["patients"]}
    groups = list(dict.fromkeys(key(patient) for patient in plan["patients"]))
    asked = Counter(key(patient) for patient in plan["patients"])
    placed = [Counter(key(patients[row["patient"]]) for row in plan["policies"][name]["assignments"])
              for name, _ in POLICIES]
    unmet = [Counter((key(patients[row["patient"]]), _plain(row["reason"])) for row in plan["policies"][name]["unserved"])
             for name, _ in POLICIES]
    pairs = list(dict.fromkeys(pair for group in groups for counts in unmet for pair in counts if pair[0] == group))
    return {"rows": [{"group": group, "patients": asked[group], "placed": [counts[group] for counts in placed]}
                     for group in groups],
            "unmet": [{"group": group, "reason": reason, "counts": [counts[(group, reason)] for counts in unmet]}
                      for group, reason in pairs]}


def difference(plan, order):
    """One patient the two policies treated differently, picked by a fixed rule: first a patient only the
    optimum placed, else one sent to a different facility; highest priority first, then patient id."""
    patients = {patient["id"]: patient for patient in plan["patients"]}
    sites = {facility["id"]: facility for facility in plan["facilities"]}
    first, best = (plan["policies"][key] for key, _ in POLICIES)
    near = {row["patient"]: row for row in first["assignments"]}
    left = {row["patient"]: _plain(row["reason"]) for row in first["unserved"]}
    rank = lambda row: (order.index(urgency(patients[row["patient"]])), row["patient"])  # noqa: E731
    gained = sorted((row for row in best["assignments"] if row["patient"] in left), key=rank)
    moved = sorted((row for row in best["assignments"]
                    if row["patient"] in near and near[row["patient"]]["facility"] != row["facility"]), key=rank)
    if not gained and not moved:
        return None
    chosen = (gained or moved)[0]
    patient = patients[chosen["patient"]]

    def place(row):
        site = sites[row["facility"]]
        bucket = next((resource for resource in site["resources"] if resource.get("slot_id") is not None
                       and resource.get("slot_id") == row.get("slot_id")), {})
        return {"label": site["label"], "precision": PRECISION[site["precision"]].lower(),
                "minutes": _minutes(travel(row)), "start": row.get("slot_start_minute", bucket.get("start_minute")),
                "basis": basis(bucket, site).lower()}

    holder = None
    if gained and chosen.get("slot_id") is not None:  # who had that same place under nearest first
        others = sorted((row for row in first["assignments"] if row.get("slot_id") == chosen["slot_id"]), key=rank)
        if others:
            other = patients[others[-1]["patient"]]
            holder = {"id": other["id"], "priority": _inline(urgency(other)),
                      "arrival": other.get("arrival_minute")}
    return {"id": patient["id"], "priority": _inline(urgency(patient)),
            "service": _inline(patient["service"]), "arrival": patient.get("arrival_minute"),
            "kind": _inline(patient_class(patient)) if patient_class(patient) else None,
            "reason": left.get(patient["id"]), "near": place(near[patient["id"]]) if patient["id"] in near else None,
            "best": place(chosen), "holder": holder}


def advice(plan, results, order, total):
    """What a district planner could take from the run. Every number is counted here; nothing is promised."""
    if "traffic" in plan:
        return ["Both policies used the same road observations and simulated slots. Missing routes received no "
                "modeled time. An unmet request can reflect an unavailable route, appointment window or staffing."]
    first, best = results
    lines, gain = [], best["assigned"] - first["assigned"]
    top = order[0]
    if gain > 0:
        urgent = best["by_priority"][top] - first["by_priority"][top]
        lines.append(f"Assigning the same staffed places differently placed {gain} more of the {total:,} simulated "
                     f"patients, {urgent} of them {_inline(top)} priority, with no added capacity.")
    patients = {patient["id"]: patient for patient in plan["patients"]}
    short = Counter(patients[row["patient"]]["service"] for row in plan["policies"][best["key"]]["unserved"])
    if short:
        service, count = sorted(short.items(), key=lambda item: (-item[1], item[0]))[0]
        places = sum(resource["slots"] for facility in plan["facilities"] for resource in facility["resources"]
                     if resource["service"] == service)
        used = sum(1 for row in plan["policies"][best["key"]]["assignments"] if row["service"] == service)
        name = _inline(service)
        if places:
            lines.append(f"Even at the optimum {best['unmet']:,} had no place, {count:,} of them needing {name}: "
                         f"{used:,} of the {places:,} {name} places in the shift were used. That is the shortage to "
                         "test next: more staffed places for that service, or longer hours.")
        else:
            lines.append(f"Even at the optimum {best['unmet']:,} had no place, {count:,} of them needing {name}, "
                         "which no site in this file offers. That is the gap to test next: where that service "
                         "could be staffed.")
    elif gain > 0:
        lines.append("At the optimum every simulated patient had a place, so in this scenario the staffed places "
                     "were enough and the gap was in how they were assigned.")
    else:
        lines.append("Both policies placed every simulated patient, so in this scenario the staffed places were "
                     "enough.")
    return lines


def shared(plan):
    """Travel for the patients both policies placed, so the two totals describe the same people."""
    first, best = ({row["patient"]: travel(row) for row in plan["policies"][key]["assignments"]} for key, _ in POLICIES)
    both = sorted(set(first) & set(best))
    return {"patients": len(both), "near": _minutes(sum(first[patient] for patient in both)),
            "best": _minutes(sum(best[patient] for patient in both))}


def real(plan):
    """Whether the file says its facility locations are real. Generated sites are never presented as real."""
    return plan["geography"]["location_basis"] == PUBLIC


def _minutes(value):
    value = round(float(value), 1)
    return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"


INITIALS = ("mri", "ct", "icu", "nicu", "ecg")


def _plain(reason):
    """A code such as time_sensitive or mri as words, with medical initials kept in capitals."""
    words = reason.replace("_", " ").strip().capitalize().split(" ")
    return " ".join(word.upper() if word.lower() in INITIALS else word for word in words)


def _inline(reason):
    """The same words for the middle of a sentence: lower case, except the initials."""
    return " ".join(word if word.lower() in INITIALS else word.lower() for word in _plain(reason).split(" "))


def _pickup_name(code):
    """PUNE-SIM-PICKUP-W as words. An id this page does not know is shown as written."""
    code = str(code)
    for ending, name in (("PICKUP-W", "West shared pickup"), ("PICKUP-E", "East shared pickup")):
        if code.endswith(ending):
            return name
    return code


def _when(stamp):
    """2026-11-22T17:40:00Z as 22 November 2026, 17:40 UTC. Anything else is shown as written."""
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)
    if moment.utcoffset() is None:
        return str(stamp)
    moment = moment.astimezone(timezone.utc)
    return f"{moment.day} {moment:%B %Y}, {moment:%H:%M} UTC"


def view(plan):
    """Every figure on the page, counted from the assignments. No markup."""
    patients = {patient["id"]: patient for patient in plan["patients"]}
    labels = {facility["id"]: facility["label"] for facility in plan["facilities"]}
    seen = list(dict.fromkeys(urgency(patient) for patient in plan["patients"]))
    order = plan["scenario"].get("priorities") or [level for level in ORDER if level in seen] \
        + [level for level in seen if level not in ORDER]
    order = [priority for priority in order if priority in seen]
    asked = Counter(urgency(patient) for patient in plan["patients"])
    slots = Counter()
    for facility in plan["facilities"]:
        for resource in facility["resources"]:
            slots[(facility["id"], resource["service"])] += resource["slots"]
    results = []
    for key, name in POLICIES:
        result = plan["policies"][key]
        minutes = [travel(row) for row in result["assignments"]]
        placed = Counter(urgency(patients[row["patient"]]) for row in result["assignments"])
        used = Counter((row["facility"], row["service"]) for row in result["assignments"])
        results.append({
            "key": key, "name": name, "assigned": len(minutes), "unmet": len(result["unserved"]),
            "by_priority": {priority: placed[priority] for priority in order},
            "reasons": Counter(_plain(row["reason"]) for row in result["unserved"]),
            "used": used, "full": sum(1 for resource, count in used.items() if count == slots[resource]),
            "travel_total": _minutes(sum(minutes)),
            "travel_mean": _minutes(sum(minutes) / len(minutes)) if minutes else "0",
            "travel_longest": _minutes(max(minutes)) if minutes else "0",
        })
    first, best = results
    total = len(patients)
    gain = best["assigned"] - first["assigned"]
    if gain > 0:
        say = (f"On identical inputs the exact optimum placed {gain} more simulated "
               f"{'patient' if gain == 1 else 'patients'} than nearest first.")
    elif plan.get("traffic") and not best["assigned"]:
        say = ("No road time came back for any route, so neither policy could place a simulated patient in this "
               "run. That is the road-time service being unavailable, not the planner: the modeled result is "
               "unchanged.")
    elif gain == 0:
        say = "On identical inputs both policies placed the same number of simulated patients."
    else:
        say = (f"On identical inputs nearest first placed {-gain} more simulated "
               f"{'patient' if gain == -1 else 'patients'}; the exact optimum is optimal for the stated objective, "
               "which is not the count alone.")
    reasons = sorted({reason for result in results for reason in result["reasons"]})
    kinds = {}
    for facility in plan["facilities"]:
        for resource in facility["resources"]:
            kinds.setdefault((facility["id"], resource["service"]), set()).add(basis(resource, facility))
    classed = any(patient_class(patient) for patient in plan["patients"])
    resources = [{"facility": labels[facility], "service": service, "slots": count,
                  "basis": ", ".join(sorted(kinds[(facility, service)])),
                  "used": [result["used"][(facility, service)] for result in results]}
                 for (facility, service), count in slots.items()]
    precision = Counter(facility["precision"] for facility in plan["facilities"])
    return {
        "patients": total, "results": results, "say": say, "order": order, "asked": asked, "reasons": reasons,
        "by_class": breakdown(plan, lambda patient: patient_class(patient) or "Class not given", results)
        if classed else None,
        "by_service": breakdown(plan, lambda patient: patient["service"], results),
        "difference": difference(plan, order), "advice": advice(plan, results, order, total), "shared": shared(plan),
        "resources": resources, "places": sum(slots.values()), "facilities": len(labels),
        "precision": [(key, name, precision[key]) for key, name in PRECISION.items() if precision[key]],
        "roster": [{"label": facility["label"], "precision": PRECISION[facility["precision"]],
                    "source": facility.get("source")} for facility in plan["facilities"]],
        "geography": plan["geography"], "scenario": plan["scenario"],
    }


def _road_marks(roads, project, sites, width, height):
    """The road lines and a few road names inside the frame, as two pieces of SVG: the lines go under
    everything, the names over the patient dots. Both are empty when no road is in view."""
    tier_of = {kind: index for index, (kinds, _, _) in enumerate(ROAD_TIERS) for kind in kinds}
    drawn, named = [[] for _ in ROAD_TIERS], {}
    for kind, name, points in roads["lines"]:
        tier = tier_of.get(kind, 0)
        spots = [project(x, y) for x, y in points]
        near = [-30 <= x <= width + 30 and -30 <= y <= height + 30 for x, y in spots]
        run = []
        for index, spot in enumerate(spots + [None]):
            keep = spot is not None and (near[index] or (index and near[index - 1])
                                         or (index + 1 < len(near) and near[index + 1]))
            if keep:
                # points closer together than the eye can tell are left out, except the end of a line
                if not run or math.dist(run[-1], spot) >= 0.8 or index + 1 == len(spots):
                    run.append(spot)
                continue
            if len(run) > 1:
                drawn[tier].append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in run))
                length = sum(math.dist(first, second) for first, second in zip(run, run[1:]))
                if name:  # a name is written once, at the middle of its longest stretch in view
                    best, total, longest, middle = named.get(name, (tier, 0, 0, None))
                    if length > longest:
                        longest, middle = length, run[len(run) // 2]
                    named[name] = (max(best, tier), total + length, longest, middle)
            run = []
    while sum(len(path) for paths in drawn for path in paths) > ROAD_BUDGET and sum(map(bool, drawn)) > 1:
        drawn[next(index for index, paths in enumerate(drawn) if paths)] = []
    if not any(drawn):
        return "", ""
    lines = [f'<path d="{" ".join(paths)}" fill="none" stroke="{colour}" stroke-width="{size}" '
             'stroke-linecap="round" stroke-linejoin="round"/>'
             for paths, (_, colour, size) in zip(drawn, ROAD_TIERS) if paths]
    names = []
    # Up to eight names, main roads and longest first, none on top of a site, another name or the frame's edge.
    boxes = [(x - 10, y - 10, x + 10, y + 10) for x, y in sites]
    for name, (tier, total, _, (x, y)) in sorted(named.items(), key=lambda item: (-item[1][0], -item[1][1], item[0])):
        if len(boxes) - len(sites) == 8:
            break
        half = 3 * len(name) + 4
        box = (x - half, y - 11, x + half, y + 4)
        if (tier < 2 or total < 60 or box[0] < 4 or box[2] > width - 4 or box[1] < 4 or box[3] > height - 24
                or any(box[0] < other[2] and other[0] < box[2] and box[1] < other[3] and other[1] < box[3]
                       for other in boxes)):
            continue
        boxes.append(box)
        names.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" font-size="10.5" fill="#4b6274" '
                     'stroke="#ffffff" stroke-width="3" paint-order="stroke" stroke-linejoin="round">'
                     f"{html.escape(name, quote=False)}</text>")
    return "".join(lines), "".join(names)


def _scale_bar(per_km, height):
    """A bar of a round number of kilometres, bottom left."""
    km = next((size for size in (50, 20, 10, 5, 2, 1, 0.5) if size * per_km <= 140), 0.5)
    end = 14 + km * per_km
    return (f'<g data-scale="{km} km"><path d="M14 {height - 12} v5 H{end:.1f} v-5" fill="none" stroke="#14283b" '
            f'stroke-width="1.5"/><text x="{end + 6:.1f}" y="{height - 6}" font-size="11" fill="#14283b" '
            f'stroke="#ffffff" stroke-width="3" paint-order="stroke">{km} km</text></g>')


def chart(plan, roads=None, width=720, height=440, pad=28):
    """The map: facilities by precision and simulated patients as small dots, over the reviewed roads when a
    layer is given and the locations are real. Without one there is no background at all."""
    facilities = plan["facilities"]
    traffic = plan.get("traffic")
    starts = (traffic["pickups"] if traffic else
              [patient for patient in plan["patients"] if patient.get("latitude") is not None])
    points = [(row["longitude"], row["latitude"]) for row in facilities + starts]
    west, east = min(x for x, _ in points), max(x for x, _ in points)
    south, north = min(y for _, y in points), max(y for _, y in points)
    squeeze = math.cos(math.radians((south + north) / 2)) or 1.0
    span_x, span_y = max((east - west) * squeeze, 1e-6), max(north - south, 1e-6)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    left = (width - span_x * scale) / 2
    top = (height - span_y * scale) / 2

    def project(longitude, latitude):  # at the size of a city this is the same picture as Web Mercator
        return left + (longitude - west) * squeeze * scale, top + (north - latitude) * scale

    def at(row):
        x, y = project(row["longitude"], row["latitude"])
        return round(x, 1), round(y, 1)

    under, names = (_road_marks(roads, project, [at(row) for row in facilities + (starts if traffic else [])],
                                width, height) if roads and real(plan) else ("", ""))
    marks = []
    for start in starts:
        x, y = at(start)
        if traffic:
            name = html.escape(_pickup_name(start["id"]), quote=False)
            marks.append(f'<path data-pickup="shared" d="M{x} {y-7} l7 7 -7 7 -7 -7 Z" fill="#0b7067" '
                         f'stroke="white"><title>{name}, simulated</title></path>')
        elif under:
            marks.append(f'<circle cx="{x}" cy="{y}" r="2.2" fill="#8a9aa7" stroke="#ffffff" stroke-width="0.6"/>')
        else:
            marks.append(f'<circle cx="{x}" cy="{y}" r="2" fill="#8a9aa7"/>')
    marks.append(names)
    for facility in sorted(facilities, key=lambda row: row["precision"] != "area"):
        x, y = at(facility)
        name = html.escape(f"{facility['label']} ({PRECISION[facility['precision']].lower()})", quote=False)
        if facility["precision"] == "area":
            marks.append(f'<circle cx="{x}" cy="{y}" r="12" fill="#14283b" fill-opacity="0.06" stroke="#14283b" '
                         f'stroke-width="2" stroke-dasharray="4 3"><title>{name}</title></circle>')
        elif facility["precision"] == "campus_anchor":
            marks.append(f'<rect x="{round(x - 5.5, 1)}" y="{round(y - 5.5, 1)}" width="11" height="11" fill="#14283b" '
                         f'stroke="#ffffff" stroke-width="2"><title>{name}</title></rect>')
        else:
            marks.append(f'<circle cx="{x}" cy="{y}" r="6" fill="#14283b" stroke="#ffffff" stroke-width="2">'
                         f"<title>{name}</title></circle>")
    origins = "shared simulated pickups" if traffic else "simulated patient starting points"
    described = f"Map of {len(facilities)} facilities and {len(starts)} {origins}. "
    extras = ""
    if under:
        credit = html.escape(roads["attribution"][0]["text"], quote=False)
        described += "Roads are drawn underneath for orientation."
        extras = (_scale_bar(scale / 111.32, height)
                  + f'<text data-credit="roads" x="{width - 8}" y="{height - 6}" text-anchor="end" font-size="10" '
                    f'fill="#4b6274" stroke="#ffffff" stroke-width="3" paint-order="stroke">{credit}</text>')
    else:
        described += "No roads or background are drawn."
    shown = ' data-roads="shown"' if under else ""
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(described, quote=True)}"{shown}>'
            + under + "".join(marks) + extras + "</svg>")


def _traffic_header(facts, safe):
    """What one signed-in road-time run asked for and got back, in words a first-time reader can follow."""
    pickups, total = facts["pickups"], facts["eligible_pairs"]
    attempted, attempts = facts["attempted_pairs"], facts["actual_attempts"]
    asked = (f"Road times were asked for {attempted:,} of the {total:,} pickup-to-site routes"
             if attempted is not None else
             f"It is not known how many of the {total:,} pickup-to-site routes were asked for")
    sent = (f"{attempts:,} {'request was' if attempts == 1 else 'requests were'} sent in all, counting retries."
            if attempts is not None else "The number of requests sent is not known.")
    summary = (f"{asked} ({len(pickups)} pickups × {facts['site_count']} sites). {facts['usable_pairs']:,} came "
               f"back usable and {facts['unavailable_pairs']:,} are unavailable. {sent}")
    groups = " · ".join(f"{safe(_pickup_name(row['id']))}: {row['patient_count']:,} simulated requests"
                        for row in pickups)
    stamp = facts.get("observed_at")
    seen = (f'Observed <time datetime="{html.escape(str(stamp), quote=True)}">{safe(_when(stamp))}</time>.'
            if stamp else "No observation time, because no route was observed.")
    credit = facts.get("attribution") or {}
    attribution = (f'<p data-attribution="storm-traffic">{safe(credit["caption"])}</p>'
                   f'<details><summary>Map data copyright notices</summary><p>{safe(credit["notices"])}</p></details>'
                   if credit.get("caption") and credit.get("notices") else "")
    state = ("" if facts["usable_pairs"] else
             '<p role="status"><strong>No road estimates available for this run.</strong> '
             "The modeled baseline remains available below. Nothing is wrong with the planner or the modeled "
             "result: without a road time for any route, neither policy can place a simulated patient.</p>")
    return (f'<div class="sp-live" data-storm-traffic="observed" data-usable="{facts["usable_pairs"]}">'
            f"<h3>Signed-in road-time comparison</h3>{state}"
            f'<p>{safe(facts["pickup_rule"])} {groups}.</p><p>{summary}</p>'
            f'<p>Source: {safe(facts["source"])}. {seen}</p>{attribution}</div>')


def markup(plan, roads=None):
    """The section as HTML. Every word from the file is escaped. The packaged road layer is drawn under real
    locations unless roads is False; pass a layer to use that one."""
    found, actual = view(plan), real(plan)
    if roads is None and actual:
        roads = load_roads()
    drawing = chart(plan, roads or None)
    streets = 'data-roads="shown"' in drawing
    traffic = plan.get("traffic")
    safe = lambda text: html.escape(str(text), quote=False)  # noqa: E731
    place, scenario, results, total = found["geography"], found["scenario"], found["results"], found["patients"]
    credits = " ".join(f'<a href="{html.escape(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
                       f"{safe(item['text'])}</a>." for item in place.get("attribution", []))
    def result_travel(result):
        if traffic and not result["assigned"]:
            return "No assigned road travel is shown."
        return (f'Travel for those placed: {result["travel_total"]} minutes in total, '
                f'{result["travel_mean"]} on average, {result["travel_longest"]} at the longest.')

    cards = "".join(
        f'<div class="sp-card{" sp-best" if result["key"] == "exact_optimum" else ""}" data-policy="{result["key"]}">'
        f'<div class="sp-name">{safe(result["name"])}</div>'
        f'<div class="sp-big">{result["assigned"]:,} of {total:,} placed</div>'
        f'<div class="sp-small">{result["unmet"]:,} left without a place. {result_travel(result)} '
        f'{result["full"]:,} staffed resources completely used.</div></div>'
        for result in results)
    heads = "".join(f'<th class="sp-n">{safe(result["name"])}</th>' for result in results)
    priority = "".join(
        f"<tr><td>{safe(_plain(level))}</td><td class=\"sp-n\">{found['asked'][level]:,}</td>"
        + "".join(f'<td class="sp-n">{result["by_priority"][level]:,}</td>'
                  f'<td class="sp-n">{found["asked"][level] - result["by_priority"][level]:,}</td>' for result in results)
        + "</tr>" for level in found["order"])
    pairs = "".join(f'<th class="sp-n">{safe(result["name"])}: placed</th><th class="sp-n">not placed</th>'
                    for result in results)
    case, same = found["difference"], found["shared"]
    story = ""
    if case:
        who = f"{case['priority']} priority" + (f", {case['kind']}" if case["kind"] else "") \
            + f", needs {case['service']}" + (f", arrives at minute {case['arrival']}" if case["arrival"] is not None else "")

        def where(spot):
            start = f", in the place starting at minute {spot['start']}" if spot["start"] is not None else ""
            kind = "observed ordinary-car travel" if traffic else "modelled travel"
            return (f"{spot['label']} ({spot['precision']}; service and capacity {spot['basis']}){start}, "
                    f"{spot['minutes']} minutes of {kind}")

        before = (f"sent to {where(case['near'])}" if case["near"] else f"not placed ({case['reason'].lower()})")
        held = ""
        if case["holder"]:
            came = (f", who arrived at minute {case['holder']['arrival']}"
                    if case["holder"]["arrival"] is not None else "")
            held = (f"<li>Under nearest first that same place went to {safe(case['holder']['id'])}, a "
                    f"{safe(case['holder']['priority'])}-priority patient{came}.</li>")
        story = (f'<h3>One simulated patient, two decisions</h3><ul class="sp-facts" data-case="{safe(case["id"])}">'
                 f"<li><strong>{safe(case['id'])}</strong> ({safe(who)}).</li>"
                 f"<li><strong>Nearest first:</strong> {safe(before)}.</li>"
                 f"<li><strong>Exact optimum:</strong> placed at {safe(where(case['best']))}.</li>{held}</ul>")
    cohort = (f" The {same['patients']:,} patients placed under both policies travelled {same['near']} minutes in "
              f"total under nearest first and {same['best']} under the exact optimum; the totals on the cards cover "
              "different patients." if same["patients"] else "")
    planner = ('<h3>For a district planner</h3><ul class="sp-facts">'
               + "".join(f"<li>{safe(line)}</li>" for line in found["advice"])
               + "<li>These are outcomes of a simulation with invented demand and capacity. They show what to test, "
               "not what any facility can deliver today, and they are not treatment outcomes.</li></ul>")

    def grouped(title, first, found_groups):
        body = "".join(
            f"<tr><td>{safe(_plain(row['group']))}</td><td class=\"sp-n\">{row['patients']:,}</td>"
            + "".join(f'<td class="sp-n">{count:,}</td><td class="sp-n">{row["patients"] - count:,}</td>'
                      for count in row["placed"]) + "</tr>" for row in found_groups["rows"])
        return (f'<h3>{title}</h3><div class="sp-scroll"><table><thead><tr><th>{first}</th>'
                f'<th class="sp-n">Patients</th>{pairs}</tr></thead><tbody>{body}</tbody></table></div>')

    main = found["by_class"] or found["by_service"]
    first = "Patient class" if found["by_class"] else "Service"
    groups = (grouped("By patient class", "Patient class", found["by_class"]) if found["by_class"] else "") \
        + grouped("By service needed", "Service", found["by_service"])
    reasons = "".join(
        f"<tr><td>{safe(_plain(row['group']))}</td><td>{safe(row['reason'])}</td>"
        + "".join(f'<td class="sp-n">{count:,}</td>' for count in row["counts"]) + "</tr>"
        for row in main["unmet"]) or (f'<tr><td colspan="{len(results) + 2}">Every simulated patient was placed.'
                                      "</td></tr>")
    use = "".join(
        f"<tr><td>{safe(row['facility'])}</td><td>{safe(_plain(row['service']))}</td>"
        f"<td>{safe(row['basis'])}</td><td class=\"sp-n\">{row['slots']:,}</td>"
        + "".join(f'<td class="sp-n{" sp-full" if count == row["slots"] and count else ""}">{count:,}'
                  f'{" (full)" if count == row["slots"] and count else ""}</td>' for count in row["used"])
        + "</tr>" for row in found["resources"])
    key = " &nbsp; ".join(f"{KEYS[kind]} {safe(name.lower())} ({count:,})" for kind, name, count in found["precision"])
    if streets:
        key += (' &nbsp; <svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true">'
                '<path d="M1 9 H21" stroke="#98a7b2" stroke-width="2.4" stroke-linecap="round"/></svg> road')
    road_credits = " ".join(
        f'<a href="{html.escape(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
        f"{safe(item['text'])}</a>." for item in (roads["attribution"] if streets else []))
    if traffic:
        key += (' &nbsp; <svg width="16" height="18" viewBox="0 0 16 18" aria-hidden="true">'
                '<path d="M8 2 l7 7 -7 7 -7 -7 Z" fill="#0b7067"/></svg> '
                f"shared simulated pickup ({len(traffic['pickups']):,})")
    else:
        key += (' &nbsp; <svg width="12" height="18" viewBox="0 0 12 18" aria-hidden="true"><circle cx="6" cy="9" r="2.5" '
            'fill="#8a9aa7"/></svg> simulated patient start')

    def origin(row):
        source = row["source"]
        if not source:
            return "<td>Not given</td><td>Not given</td>"
        link = source.get("url")
        name = safe(source["publisher"]) + (f" ({safe(source['id'])})" if source.get("id") else "")
        if link:
            name = (f'<a href="{html.escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">'
                    f"{name}</a>")
        return f"<td>{name}</td><td>{safe(source['license'])}</td>"

    roster = "".join(f"<tr><td>{safe(row['label'])}</td><td>{safe(row['precision'])}</td>{origin(row)}</tr>"
                     for row in found["roster"])
    extra = "".join(f"<li><strong>{title}.</strong> {safe(place[field])}</li>"
                    for field, title in (("venue", "Cleared for"), ("roster_sha256", "Roster SHA-256"))
                    if isinstance(place.get(field), str) and place[field].strip())
    label = ("Real facility locations · simulated demand and staffed slots · observed ordinary-car travel" if traffic
             else LABEL if actual else LABEL_SYNTHETIC)
    replay = ("" if traffic else
              f"<li><strong>To reproduce.</strong> {safe(REPRODUCE if actual else REPRODUCE_SYNTHETIC)} "
              f"Seed {scenario['seed']}. This page recounts every figure from the assignment rows in the file.</li>")
    return (
        f'<div class="sp" data-plan="shown" data-locations="{"real" if actual else "simulated"}">'
        f'<div class="sp-label">{label} · seed {scenario["seed"]}</div>'
        f'{_traffic_header(traffic, safe) if traffic else ""}'
        f'<h3 class="sp-top">{safe(place["name"])}: {total:,} simulated patients, {found["facilities"]:,} facilities, '
        f'{found["places"]:,} staffed places</h3>'
        f'<div class="sp-pair">{cards}</div><div class="sp-say">{safe(found["say"])}{safe(cohort)} '
        f'<strong>Objective.</strong> {safe(scenario["objective"])}</div>'
        f"{story}{planner}"
        f'<h3>By priority</h3><div class="sp-scroll"><table><thead><tr><th>Priority</th><th class="sp-n">Patients</th>'
        f"{pairs}</tr></thead><tbody>{priority}</tbody></table></div>"
        f"{groups}"
        f'<h3>Why patients were not placed</h3><div class="sp-scroll"><table><thead><tr><th>{first}</th>'
        f"<th>Reason</th>{heads}</tr>"
        f"</thead><tbody>{reasons}</tbody></table></div>"
        f'<h3>{"Where the facilities are" if actual else "Where the simulated sites are"}</h3>'
        f'<div class="sp-map">{drawing}</div>'
        f'<div class="sp-key">{key}</div><div class="sp-key">{safe(AREA_NOTE if actual else SITES_NOTE)} '
        f'{safe(ROADS_NOTE) + " Roads: " + road_credits if streets else "No roads or background map are drawn."} '
        f"Point at a mark for the facility's label. {credits}</div>"
        f'<h3>About the area</h3><ul class="sp-facts">'
        f'<li><strong>Why this area.</strong> {safe(place["selection"])}</li>'
        f'<li><strong>Location source.</strong> {safe(place["source"])} {credits}</li>'
        f'<li><strong>What was verified.</strong> {safe(place["verification"])}</li>{extra}</ul>'
        f'<h3>About the simulated shift</h3><ul class="sp-facts">'
        f'<li><strong>What is simulated.</strong> {safe(scenario["simulated"])}</li>'
        f'<li><strong>Time covered.</strong> {safe(scenario["horizon"])}</li>'
        f'<li><strong>Travel.</strong> {safe(scenario["travel_basis"])}</li>'
        f"{replay}</ul>"
        f"<details><summary>Staffed places used, by facility and service</summary>"
        f'<div class="sp-scroll"><table><thead><tr><th>Facility</th><th>Service</th><th>Service and capacity basis</th>'
        f'<th class="sp-n">Staffed places</th>'
        f"{heads}</tr></thead><tbody>{use}</tbody></table></div></details>"
        "<details><summary>Facility locations and their sources</summary>"
        '<div class="sp-scroll"><table><thead><tr><th>Facility</th><th>Location precision</th><th>Publisher</th>'
        f"<th>Licence</th></tr></thead><tbody>{roster}</tbody></table></div></details></div>")


def choice(plan):
    """The name of this view in the Storm page's own switch."""
    where = "real locations" if real(plan) else "simulated sites"
    return f"{CHOICE}: {len(plan['patients']):,} simulated patients, {where}"


def render(st, plan):
    st.warning(NOTICE if real(plan) else NOTICE_SYNTHETIC)
    st.markdown(STYLE + markup(plan), unsafe_allow_html=True)
