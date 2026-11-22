"""Find the named facility in a postal or local area, retaining the actual evidence."""
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
import re
import sqlite3

from research.geography.distance import haversine_m
from research.matching.address_search import GENERIC_PLACE, LIMIT_M, shared_source, written_lines
from research.matching.consensus import json_lines, point
from research.matching.national import STATES
from research.matching.normalize import core, fold, pin_key, state_key, tokens
from research.matching.premises import LANDMARK, MISSING, PIN, QUALIFIER, SPLIT

SPECIALTY_OR_BRANCH = frozenset(
    "north south east west dental eye kidney cancer dialysis maternity children womens orthopaedic "
    "orthopedic cardiology oncology emergency pharmacy diagnostic diagnostics laboratory physiotherapy "
    "rehabilitation surgeon surgery fertility imaging trauma".split())


def words(value):
    return tuple(tokens(value))


def contains(text, phrase):
    return bool(phrase) and f" {phrase} " in f" {text} "


def postal(value):
    pin = pin_key(value)
    return pin if pin and PIN.fullmatch(pin) else None


def title(name, city=None, state=None):
    # NABH sometimes appends the name of the legal owner to the hospital name.
    name = re.split(r"\s*[(,]\s*(?:a |an )?unit of\b", name or "", flags=re.I)[0]
    if fold(name) in MISSING:
        return ""
    # Treat promotional copy as such only when it repeats the actual city.
    parts = re.split(r"\s+[-–—]\s+", name, maxsplit=1)
    if len(parts) == 2 and city and re.fullmatch(
            r"(?:best|top) (?:[a-z]+ )*hospital in " + re.escape(city), fold(parts[1]) or ""):
        name = parts[0]
    for match in reversed(list(re.finditer(r"\(([A-Za-z]{2,8})\)", name))):
        initials = "".join(w[0] for w in words(name[:match.start()]) if w not in {"of", "and", "the"})
        if initials.endswith(match[1].lower()):
            name = name[:match.start()] + name[match.end():]
    pieces = name.split(",")
    while len(pieces) > 1:
        suffix = fold(pieces[-1])
        if suffix and (suffix == city or state in STATES and len(suffix) >= 6
                       and SequenceMatcher(None, suffix, state).ratio() >= 0.90):
            pieces.pop()
        else:
            break
    return ",".join(pieces).strip()


def identity(name, city=None, state=None):
    return tuple(core(tokens(title(name, city, state))))


def named(left, right, geography, adjacent=False):
    if not left or not right:
        return False
    a, b = set(left), set(right)
    shared = a & b
    if a == b or "".join(left) == "".join(right):
        return True
    if shared and (a ^ b) <= geography and shared - geography:
        return True
    if (adjacent and len(shared) >= 2 and (a < b or b < a) and len(a ^ b) == 1
            and not (a ^ b) & SPECIALTY_OR_BRANCH):
        return True
    return (len(left) == len(right) and SequenceMatcher(
        None, " ".join(left), " ".join(right), autojunk=False).ratio() >= 0.93)


@dataclass(frozen=True)
class Listing:
    family: str
    key: str
    name: str
    address: str
    pin: str | None
    state: str | None
    city: str | None
    signature: tuple
    folded_address: str


def listing(family, key, name, address, pin=None, state=None, city=None):
    return Listing(family, str(key), name or "", address or "", postal(pin), state_key(state),
                   fold(city), identity(name, fold(city), state_key(state)), fold(address) or "")


def registry_listings(nhp, nabh, operators):
    for row in json_lines(nhp):
        yield listing("nhp_official", row["official_locator"], row["Hospital_Name"],
                      row["Address_Original_First_Line"], row["Pincode"], row["State"], row["Town"])
    with closing(sqlite3.connect(nabh.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        for key, name, address, pin in db.execute(
                "SELECT listing_id, hco_name, address, pin_from_address FROM listings ORDER BY listing_id"):
            parts = [state_key(part) for part in SPLIT.split(address or "")]
            state = next((part for part in reversed(parts) if part in STATES), None)
            yield listing("nabh", key, name, address, pin, state)
    for path in operators:
        for row in json_lines(path):
            if not row.get("operator_url") or not row.get("name"):
                raise ValueError("Operator observations require a facility name and a first-party record URL")
            yield listing("operator", row["operator_url"], row["name"], row.get("address"),
                          row.get("pin"), row.get("state"), row.get("city"))


class RegistryIndex:
    def __init__(self, listings):
        self.items = []
        self.pins = defaultdict(set)
        self.terms = defaultdict(set)
        for record in listings:
            i = len(self.items)
            self.items.append(record)
            if record.pin:
                self.pins[record.pin].add(i)
            for token in set(record.signature):
                self.terms[token].add(i)

    def candidates(self, signature, pin):
        hits = set(self.pins.get(pin, ()))
        # Include different-PIN and PIN-less records when the name supplies a retrieval key.
        for term in set(signature):
            hits.update(self.terms.get(term, ()))
        return (self.items[i] for i in sorted(hits))


def local_labels(row, branch, city, state):
    excluded = set(words(row.get("name"))) | set(words(city)) | set(words(state))
    excluded.update("east west north south central railway hospital district ground floor first second".split())
    excluded.update(w for place in branch.get("postal_districts", []) for w in words(place))
    labels = set()
    for value in [*written_lines(row), *branch.get("localities", [])]:
        for part in SPLIT.split(value):
            term = fold(PIN.sub("", part))
            if not term or term in MISSING or term in STATES or "district" in term.split():
                continue
            is_landmark = LANDMARK.match(term)
            if is_landmark:
                term = term[is_landmark.end():].removeprefix(" to ").strip()
            if (term and not re.match(r"^\d", term)
                    and any(len(w) >= 4 and w.isalpha() and w not in GENERIC_PLACE and w not in excluded
                            for w in term.split())):
                labels.add(("landmark" if is_landmark else "locality", term))
    return sorted(labels, key=lambda item: (-len(item[1]), item))


def matched_area(ref, pin, labels, city, state):
    if state in STATES and ref.state in STATES and state != ref.state:
        return None
    if pin and ref.pin == pin:
        return ("pin", pin)
    context = (state in STATES and (state == ref.state or contains(ref.folded_address, state))
               or city and (city == ref.city or contains(ref.folded_address, city)))
    if context:
        return next(((kind, label) for kind, label in labels if contains(ref.folded_address, label)), None)
    return None


def branch_collision(left, right):
    def qualifiers(value):
        value = re.split(r"\s*[(,]\s*(?:a |an )?unit of\b", value or "", flags=re.I)[0]
        return {fold(t) for t in QUALIFIER.split(value)[1:] if fold(t)}
    a, b = qualifiers(left), qualifiers(right)
    return bool(a and b and a.isdisjoint(b))


def facility_area(row, original, candidates, signals, providers, registry):
    name = row.get("name")
    city = fold(row.get("address_city"))
    state = state_key(original.get("state_for_matching"))
    base_title = title(name, city, state)
    sig = tuple(core(tokens(base_title)))
    branch = original["branch_evidence"]
    result = {"registry_or_operator": [], "map_area": [], "nearby_points": None}
    if not sig or branch.get("mixed_campus"):
        return result
    pin = postal(row.get("address_zipOrPostcode"))
    if branch.get("postal_state_disagreement") or "address_pin_disagrees" in original.get("input_problems", ()):
        pin = None
    labels = local_labels(row, branch, city, state)
    geography = set(words(city)) | set(words(state)) | {w for _, label in labels for w in words(label)}
    for ref in registry.candidates(sig, pin):
        area = matched_area(ref, pin, labels, city, state)
        if area and named(sig, ref.signature, geography) and not branch_collision(
                base_title, title(ref.name, city, state)):
            result["registry_or_operator"].append({"family": ref.family, "reference": ref.key,
                                                   "area_kind": area[0], "area": area[1]})

    vf = original["original_point"]
    xy = point(vf.get("latitude"), vf.get("longitude"))
    located = []
    for candidate in candidates:
        ref = candidate.reference
        signal = signals.get(ref.id, {})
        if signal.get("non_hospital_type") or not ref.coordinates:
            continue
        is_map = ref.family == "osm" or ref.id.startswith("overture-place:") and ref.family
        if not (is_map or candidate.votes and ref.family):
            continue
        if state in STATES and ref.state in STATES and state != ref.state:
            continue
        ref_title = title(ref.name, city, state)
        if branch_collision(base_title, ref_title):
            continue
        close = bool(xy and haversine_m(*xy, *ref.coordinates) < LIMIT_M)
        ref_record = listing(ref.family, ref.id, ref.name, ref.address, ref.pin, ref.state, ref.city)
        if not named(sig, tuple(core(tokens(ref_title))), geography, close):
            continue
        area = matched_area(ref_record, pin, labels, city, state)
        if not (area or close) and city and ref.city and city != ref.city:
            continue
        if not (area or close or candidate.plausible_branch):
            continue
        shared = shared_source(ref, providers, str(row.get("source_types") or "").lower(),
                               str(row.get("source_urls") or "").lower())
        evidence = {"family": ref.family, "reference": ref.id, "coordinates": ref.coordinates,
                    "possible_shared_origin": shared}
        if is_map and area:
            result["map_area"].append({"family": ref.family, "reference": ref.id, "possible_shared_origin": shared,
                                       "area_kind": area[0], "area": area[1]})
        located.append((evidence, bool(area), close))

    # A coordinate-free reference can identify a hospital in a PIN but cannot widen a point cluster.
    if located and any(area or close for _, area, close in located):
        external = {e["coordinates"] for e, _, _ in located}
        families = {e["family"] for e, _, _ in located}
        external_span = max((haversine_m(*a, *b) for a, b in combinations(sorted(external), 2)), default=0)
        vf_span = max((haversine_m(*xy, *p) for p in external), default=0) if xy else None
        vf_agrees = vf_span is not None and vf_span < LIMIT_M
        outside_agreement = len(families) >= 2 and any(area for _, area, _ in located)
        if external_span < LIMIT_M and (vf_agrees or outside_agreement):
            result["nearby_points"] = {"vf_point": xy if vf_agrees else None,
                                       "vf_point_disagrees": bool(xy and not vf_agrees),
                                       "max_separation_m": round(max(external_span, vf_span if vf_agrees else 0), 3),
                                       "exact_location_uncertain": True,
                                       "alternatives": [e for e, _, _ in located]}
    return result


def area_counts(occurrences, decisions):
    totals, tiers, sources, by_state = Counter(), Counter(), Counter(), defaultdict(Counter)
    for occurrence in occurrences:
        decision = decisions[occurrence["retrieval_representative"]]
        area = decision["facility_area"]
        prior = (decision["directory_location"]["status"] == "campus_located"
                 or decision["address_search"]["status"] != "no_new_result")
        registry = bool(area["registry_or_operator"])
        nearby = bool(area["nearby_points"])
        mapped = bool(area["map_area"])
        tier = ("previously_findable" if prior else "registry_or_operator" if registry else
                "agreeing_points" if nearby else "map_name_and_area" if mapped else "unresolved")
        tiers[tier] += 1
        by_state[occurrence["state"]][tier] += 1
        totals.update(previously_findable=int(prior), registry_or_operator=int(registry),
                      agreeing_points=int(nearby), map_name_and_area=int(mapped),
                      registry_or_agreeing_points=int(registry or nearby),
                      nearby_only_possible_shared_origins=int(nearby and all(
                          w["possible_shared_origin"] for w in area["nearby_points"]["alternatives"])),
                      covered=int(prior or registry or nearby or mapped))
        sources.update({w["family"] for w in area["registry_or_operator"]})
    return {"mutually_exclusive": dict(tiers), "overlapping": dict(totals),
            "registry_families_overlapping": dict(sources), "by_state": dict(by_state)}
