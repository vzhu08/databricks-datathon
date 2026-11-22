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
import html
import json
import math
from collections import Counter
from pathlib import Path

FILE = Path(__file__).resolve().parent / "storm_ui" / "data" / "plan.json"
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
.sp-facts li { margin-bottom: 0.3rem; }
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
    """Travel for one assignment in minutes. The planner's whole seconds win over a rounded display value."""
    if row.get("travel_seconds") is not None:
        return _whole(row["travel_seconds"], "travel seconds") / 60
    return _number(row["travel_minutes"], "travel minutes", 0, 100000)


def _unique(rows, what):
    ids = [_text(row["id"], what + " id") for row in rows]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError(f"{what} ids are missing or repeated")
    return ids


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
    return plan


def load(path=None):
    """Read and check the results file. Any failure is the same state: not available."""
    path = Path(path or FILE)
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise Unavailable("no results file")
        return checked(json.loads(path.read_text(encoding="utf-8")))
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


def real(plan):
    """Whether the file says its facility locations are real. Generated sites are never presented as real."""
    return plan["geography"]["location_basis"] == PUBLIC


def _minutes(value):
    value = round(float(value), 1)
    return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"


def _plain(reason):
    return reason.replace("_", " ").strip().capitalize()


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
        "resources": resources, "places": sum(slots.values()), "facilities": len(labels),
        "precision": [(key, name, precision[key]) for key, name in PRECISION.items() if precision[key]],
        "roster": [{"label": facility["label"], "precision": PRECISION[facility["precision"]],
                    "source": facility.get("source")} for facility in plan["facilities"]],
        "geography": plan["geography"], "scenario": plan["scenario"],
    }


def chart(plan, width=720, height=440, pad=28):
    """A plain map with no background: facilities by precision, simulated patients as small dots."""
    facilities = plan["facilities"]
    starts = [patient for patient in plan["patients"] if patient.get("latitude") is not None]
    points = [(row["longitude"], row["latitude"]) for row in facilities + starts]
    west, east = min(x for x, _ in points), max(x for x, _ in points)
    south, north = min(y for _, y in points), max(y for _, y in points)
    squeeze = math.cos(math.radians((south + north) / 2)) or 1.0
    span_x, span_y = max((east - west) * squeeze, 1e-6), max(north - south, 1e-6)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    left = (width - span_x * scale) / 2
    top = (height - span_y * scale) / 2

    def at(row):
        return (round(left + (row["longitude"] - west) * squeeze * scale, 1),
                round(top + (north - row["latitude"]) * scale, 1))

    marks = []
    for patient in starts:
        x, y = at(patient)
        marks.append(f'<circle cx="{x}" cy="{y}" r="2" fill="#8a9aa7"/>')
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
    described = (f"Map of {len(facilities)} facilities and {len(starts)} simulated patient starting points. "
                 "No roads or background are drawn.")
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(described, quote=True)}">'
            + "".join(marks) + "</svg>")


def markup(plan):
    """The section as HTML. Every word from the file is escaped."""
    found, actual = view(plan), real(plan)
    safe = lambda text: html.escape(str(text), quote=False)  # noqa: E731
    place, scenario, results, total = found["geography"], found["scenario"], found["results"], found["patients"]
    credits = " ".join(f'<a href="{html.escape(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
                       f"{safe(item['text'])}</a>." for item in place.get("attribution", []))
    cards = "".join(
        f'<div class="sp-card{" sp-best" if result["key"] == "exact_optimum" else ""}" data-policy="{result["key"]}">'
        f'<div class="sp-name">{safe(result["name"])}</div>'
        f'<div class="sp-big">{result["assigned"]:,} of {total:,} placed</div>'
        f'<div class="sp-small">{result["unmet"]:,} left without a place. Travel for those placed: '
        f'{result["travel_total"]} minutes in total, {result["travel_mean"]} on average, '
        f'{result["travel_longest"]} at the longest. {result["full"]:,} staffed resources completely used.</div></div>'
        for result in results)
    heads = "".join(f'<th class="sp-n">{safe(result["name"])}</th>' for result in results)
    priority = "".join(
        f"<tr><td>{safe(_plain(level))}</td><td class=\"sp-n\">{found['asked'][level]:,}</td>"
        + "".join(f'<td class="sp-n">{result["by_priority"][level]:,}</td>'
                  f'<td class="sp-n">{found["asked"][level] - result["by_priority"][level]:,}</td>' for result in results)
        + "</tr>" for level in found["order"])
    pairs = "".join(f'<th class="sp-n">{safe(result["name"])}: placed</th><th class="sp-n">not placed</th>'
                    for result in results)
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
    return (
        f'<div class="sp" data-plan="shown" data-locations="{"real" if actual else "simulated"}">'
        f'<div class="sp-label">{LABEL if actual else LABEL_SYNTHETIC} · seed {scenario["seed"]}</div>'
        f'<h3 class="sp-top">{safe(place["name"])}: {total:,} simulated patients, {found["facilities"]:,} facilities, '
        f'{found["places"]:,} staffed places</h3>'
        f'<div class="sp-pair">{cards}</div><div class="sp-say">{safe(found["say"])} '
        f'<strong>Objective.</strong> {safe(scenario["objective"])}</div>'
        f'<h3>By priority</h3><div class="sp-scroll"><table><thead><tr><th>Priority</th><th class="sp-n">Patients</th>'
        f"{pairs}</tr></thead><tbody>{priority}</tbody></table></div>"
        f"{groups}"
        f'<h3>Why patients were not placed</h3><div class="sp-scroll"><table><thead><tr><th>{first}</th>'
        f"<th>Reason</th>{heads}</tr>"
        f"</thead><tbody>{reasons}</tbody></table></div>"
        f'<h3>{"Where the facilities are" if actual else "Where the simulated sites are"}</h3>'
        f'<div class="sp-map">{chart(plan)}</div>'
        f'<div class="sp-key">{key}</div><div class="sp-key">{safe(AREA_NOTE if actual else SITES_NOTE)} '
        "No roads or background map are "
        f"drawn. Point at a mark for the facility's label. {credits}</div>"
        f'<h3>About the area</h3><ul class="sp-facts">'
        f'<li><strong>Why this area.</strong> {safe(place["selection"])}</li>'
        f'<li><strong>Location source.</strong> {safe(place["source"])} {credits}</li>'
        f'<li><strong>What was verified.</strong> {safe(place["verification"])}</li>{extra}</ul>'
        f'<h3>About the simulated shift</h3><ul class="sp-facts">'
        f'<li><strong>What is simulated.</strong> {safe(scenario["simulated"])}</li>'
        f'<li><strong>Time covered.</strong> {safe(scenario["horizon"])}</li>'
        f'<li><strong>Travel.</strong> {safe(scenario["travel_basis"])}</li></ul>'
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
