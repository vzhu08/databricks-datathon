"""Corroborate written VF addresses and describe compact hospital-name search areas."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
import re

from research.geography.distance import haversine_m
from research.matching.normalize import ADDRESS_GENERIC, GENERIC, core, fold, name_evidence, pin_key, state_key, tokens
from research.matching.premises import MISSING, PIN

LIMIT_M = 1000
NUMBER = r"[0-9]{1,4}[a-z]?(?:[/-][0-9a-z]{1,5})*"
CIVIC = re.compile(rf"^\s*(?:(?:plot|house|door|premises|building|no\.?|number)\s*(?:no\.?|number)?\s*[:#.-]?\s*)?({NUMBER})(?![\w/-])", re.I)
STREET = re.compile(r"\b(?:road|street|lane|avenue|marg|highway)\b")
BUILDING = re.compile(r"\b(?:complex|bhavan|bhawan|tower|plaza|arcade|building)\b")
LANDMARK = re.compile(r"\b(opposite|near|beside|behind|next to|adjacent to)\s+")
GENERIC_PLACE = GENERIC | ADDRESS_GENERIC | {
    "complex", "bhavan", "bhawan", "tower", "plaza", "arcade", "building", "opposite", "beside",
    "adjacent", "landmark", "next", "to", "station", "bus", "stop", "stand", "railway", "police",
    "school", "square", "junction", "temple", "church", "mandir", "bank", "phase", "india",
    "shopping", "commercial", "residential", "office", "apartment", "apts", "municipal", "corporation",
}


@dataclass(frozen=True)
class Address:
    numbers: frozenset
    streets: frozenset
    buildings: frozenset
    landmarks: frozenset
    words: frozenset


@lru_cache(maxsize=32_768)
def parse_address(text, exclude):
    numbers, streets, buildings, landmarks, words = (set() for _ in range(5))
    def distinctive(phrase):
        return tuple(t for t in phrase.split() if len(t) >= 3 and t.isalpha()
                     and t not in GENERIC_PLACE and t not in exclude)
    for part in re.split(r"[,;|\n]+", text):
        match = CIVIC.match(part)
        if match:
            numbers.add(match[1].lower())
        normalized = fold(PIN.sub(" ", part)) or ""
        normalized = re.sub(r"\brd\b", "road", re.sub(r"\bst\b", "street", normalized))
        normalized = re.sub(r"\bopp\b", "opposite", normalized)
        for token in distinctive(normalized):
            words.add(token)
        direction = LANDMARK.search(normalized)
        if direction:
            target = distinctive(normalized[direction.end():])
            # Preserve orientation. A building opposite a landmark and one behind it can differ.
            if target:
                landmarks.add((direction[1], target))
            normalized = normalized[:direction.start()].strip()
        for marker, target in ((STREET, streets), (BUILDING, buildings)):
            match = marker.search(normalized)
            if match:
                prefix = normalized[:match.start()]
                name = distinctive(prefix)
                if name and marker is STREET:
                    if number := CIVIC.match(part):
                        # The house number is compared separately; a numbered cross street is significant.
                        prefix = re.sub(r"^(?:(?:plot|house|door|no|number)\s+)*(?:"
                                        + re.escape(number[1]) + r")\s+", "", prefix)
                    name = tuple(t for t in prefix.split() if t in name or re.fullmatch(r"\d+(?:st|nd|rd|th)?", t))
                if name:
                    target.add(name)
    return Address(*(frozenset(v) for v in (numbers, streets, buildings, landmarks, words)))


def incompatible(a, b):
    for left, right in ((a.numbers, b.numbers), (a.buildings, b.buildings)):
        if left and right and left.isdisjoint(right):
            return True
    if a.streets and b.streets and not compatible_street(a, b):
        return True
    return any(name == other and side != direction for side, name in a.landmarks
               for direction, other in b.landmarks)


def compatible_street(a, b):
    # One publisher may prepend the locality to the same street.
    return any(x[-len(y):] == y or y[-len(x):] == x for x in a.streets for y in b.streets)


def competing_written_addresses(a, b):
    return incompatible(a, b) or not (
        a.numbers & b.numbers or a.landmarks & b.landmarks or a.buildings & b.buildings or compatible_street(a, b))


def agreement(a, b):
    if incompatible(a, b):
        return None
    if a.buildings & b.buildings:
        return "named_building"
    if a.landmarks & b.landmarks:
        return "named_landmark"
    if a.numbers & b.numbers and len(a.numbers | b.numbers) == 1:
        if compatible_street(a, b) or len(a.words & b.words) >= 2:
            return "civic_number_and_street_or_locality"
    return None


def written_lines(row):
    return list(dict.fromkeys(v.strip() for i in (1, 2, 3)
                              if isinstance(v := row.get(f"address_line{i}"), str)
                              and v.strip() and fold(v) not in MISSING))


def shared_source(ref, providers, source_types, source_urls):
    if ref.family == "osm" and "openstreetmap.org" in source_urls:
        return True
    if ref.family == "nhp" and ("nhp.gov.in" in source_urls or "nrhm-mis.nic.in" in source_urls):
        return True
    if ref.id.startswith("overture-place:"):
        if "overture" in source_types or "overturemaps.org" in source_urls:
            return True
        origins = providers.get(ref.source_record_id, ())
        return (not origins or "meta" in origins and "facebook.com" in source_urls
                or any(origin in source_urls for origin in origins))
    return False


def search_result(row, original, candidates, signals, registry_rival, providers):
    empty = {"status": "no_new_result"}
    name = row.get("name")
    name_tokens = tokens(name)
    if not core(name_tokens) or any(original["branch_evidence"].get(k) for k in
                                    ("mixed_campus", "postal_state_disagreement")):
        return empty
    state = state_key(original.get("state_for_matching"))
    city = fold(row.get("address_city"))
    if city in MISSING:
        city = None
    pin = pin_key(row.get("address_zipOrPostcode"))
    lines = written_lines(row)
    excluded = frozenset(name_tokens + tokens(city) + tokens(state))
    base = parse_address(", ".join(lines), excluded)
    orig_point = original["original_point"]
    from research.matching.consensus import NAME_LEVELS, point
    xy = point(orig_point.get("latitude"), orig_point.get("longitude"))
    alternatives, witnesses, fitting_addresses = [], [], []
    has_area_witness = False
    declared_sources = str(row.get("source_urls") or "").lower()
    source_types = str(row.get("source_types") or "").lower()
    for candidate in candidates:
        ref = candidate.reference
        evidence = signals.get(ref.id)
        if evidence is not None:
            if evidence["non_hospital_type"] or evidence["name_level"] not in NAME_LEVELS:
                continue
        elif name_evidence(name_tokens, ref.name_tokens)[0] not in NAME_LEVELS:
            continue
        addr_text = ref.address or ""
        folded = fold(addr_text) or ""
        ref_pins = set(PIN.findall(addr_text))
        if ref.pin:
            ref_pins.add(ref.pin)
        same_city = bool(city and (city == ref.city or f" {city} " in f" {folded} "))
        same_pin = bool(pin and pin in ref_pins)
        context = same_city or same_pin
        state_mismatch = bool(state and ref.state and state != ref.state)
        city_mismatch = bool(evidence and evidence.get("place") == "conflict" and not same_city)
        adjacent = bool(xy and ref.coordinates and haversine_m(*xy, *ref.coordinates) < LIMIT_M)
        if not (context or candidate.plausible_branch or adjacent):
            continue
        if state_mismatch and not (context or adjacent):
            continue
        parts = parse_address(addr_text, excluded)
        feature = agreement(base, parts)
        premises = evidence.get("premises", {}) if evidence else {}
        branch_mismatch = premises.get("branch_qualifier_conflict") or premises.get("mixed_campus_description")
        # Already-admitted rivals still count even if their producer is unknown or their PIN differs.
        alternatives.append(ref)
        shared = shared_source(ref, providers, source_types, declared_sources)
        eligible = bool(candidate.votes and ref.family and not shared and not state_mismatch and not city_mismatch
                        and not branch_mismatch and (context or adjacent))
        has_area_witness |= eligible
        if feature and not state_mismatch and (context or adjacent):
            fitting_addresses.append(parts)
            if eligible:
                witnesses.append({"reference": ref.id, "family": ref.family, "basis": feature,
                                  "source_address": addr_text, "source_pins": sorted(ref_pins)})
    # A different point alone is not a competing written address. Equally fitting but
    # incompatible house numbers/streets are competitors even when the pins coincide.
    if witnesses and not registry_rival and not any(competing_written_addresses(a, b)
                                                    for a, b in combinations(fitting_addresses, 2)):
        supported_pins = {p for w in witnesses for p in w["source_pins"]}
        return {"status": "corroborated_address", "name": name, "vf_address_lines": lines,
                "city": city, "corroborated_pin": pin if supported_pins == {pin} else None,
                "witnesses": witnesses}
    if registry_rival or not alternatives or any(not r.coordinates for r in alternatives):
        return empty
    if not has_area_witness:
        return empty
    external_points = {r.coordinates for r in alternatives}
    points = set(external_points)
    if xy:
        points.add(xy)
    if len(points) < 2:
        return empty
    diameter = 0.0
    for a, b in combinations(sorted(points), 2):
        diameter = max(diameter, haversine_m(*a, *b))
        if diameter >= LIMIT_M:
            return empty
    return {"status": "nearby_name_search", "name": name, "city": city, "exact_location_uncertain": True,
            "external_point_count": len(external_points),
            "vf_point": xy, "max_separation_m": round(diameter, 3),
            "alternatives": [{"reference": r.id, "name": r.name, "address": r.address,
                              "coordinates": r.coordinates} for r in alternatives]}


def summarize(occurrences, results):
    cross = defaultdict(Counter)
    states = defaultdict(Counter)
    nearby = defaultdict(Counter)
    usable = Counter()
    accepted_sources = Counter()
    for row in occurrences:
        decision = results[row["retrieval_representative"]]
        prior = decision["directory_location"]
        old = prior["basis"] if prior["status"] == "campus_located" else prior["status"]
        status = decision["address_search"]["status"]
        cross[old][status] += 1
        states[row["state"]][status] += 1
        if status == "corroborated_address" or old == "matching_branch_address":
            usable["written_address"] += 1
            accepted_sources.update({v["family"] for v in decision["address_search"].get("witnesses", [])})
        elif old == "named_map_listing":
            usable["prior_named_map_only"] += 1
        elif status == "nearby_name_search":
            usable["new_name_search_area"] += 1
        else:
            usable["remaining"] += 1
        if status == "nearby_name_search":
            count = decision["address_search"]["external_point_count"]
            nearby[old]["multiple_external_points" if count >= 2 else "vf_and_one_external_point"] += 1
    return {"prior_by_new": dict(cross), "by_state": dict(states), "nearby_by_evidence": dict(nearby),
            "combined_directory_counts": dict(usable), "address_witness_families_overlapping": dict(accepted_sources),
            "occurrences": len(occurrences), "distinct_upstream_ids": len({r["original_upstream_id"] for r in occurrences}),
            "nearby_diameter_limit_m_exclusive": LIMIT_M}
