"""Structured address features for candidate retrieval."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .base_adapter import _present
from .common import field_value, require
from .normalize import core, fold, tokens

ROLES = {"address", "locality", "district", "alias", "description"}
MISSING = {"", "na", "n/a", "none", "null", "unknown", "-", "not available"}
SPLIT = re.compile(r"[,;\n|]+")
PIN = re.compile(r"(?<![0-9])[1-9][0-9]{5}(?![0-9])")
PREMISE = re.compile(
    r"\b(plot|survey|khasra|door|house|building|site|premises|flat|unit)"
    r"(?:\s+(?:no\.?|number))?[\s:#.-]+([0-9]+[a-z]?(?:\s*[/–-]\s*[0-9a-z]+)*)(?!\w)", re.I,
)
NAMED_PREMISE = re.compile(r"\b(?:building|tower|complex|bhavan|plaza)\b$")
CIVIC = re.compile(r"^\s*([0-9]+[a-z]?(?:[/\-][0-9a-z]+)*)\s+(.+)", re.I)
STREET = re.compile(r"\b(road|rd|street|st|lane|marg|highway)\b")
LOCALITY = re.compile(r"\b(?:locality|ward|sector|nagar|colony|layout|village|mohalla|pally|pura)\b")
DISTRICT = re.compile(r"^(?:(?:district|dist|distt)\s+(.+)|(.+)\s+(?:district|dist|distt))$")
QUALIFIER = re.compile(r"\s+[-–—]\s*|[(),]|\b(?:branch|campus|unit)\s*[:.-]\s*", re.I)
MIXED = re.compile(r"\b(?:multiple|several|different|two|three)\s+(?:separate\s+)?(?:campuses|branches)\b"
                   r"|\b(?:campuses|branches)\s+(?:located\s+)?(?:at|in|include|are)\b", re.I)
LANDMARK = re.compile(r"^(?:near|opposite|opp|beside|behind|next to|adjacent)\b")
BLOCKS = ("exact_structured_address", "premises_locality", "distinctive_name_district",
          "documented_branch_alias", "distinctive_name_fallback")


def check_mapping(mapping, rows):
    require(isinstance(mapping, dict) and "address" in mapping and set(mapping) <= ROLES,
            "premises_mapping", "needs address and known roles: " + ", ".join(sorted(ROLES)))
    mapped = {}
    for role, value in mapping.items():
        selectors = [value] if isinstance(value, str) else value
        require(isinstance(selectors, list) and selectors
                and all(isinstance(s, str) and s.strip() for s in selectors),
                f"premises_mapping.{role}", "expected observed column path(s)")
        require(len(selectors) == len(set(selectors)), f"premises_mapping.{role}", "duplicate selector")
        for selector in selectors:
            require(any(_present(row, selector) for row in rows), f"premises_mapping.{role}",
                    "selector names a column that no input row has")
        mapped[role] = selectors
    return mapped


def _fields(row, role, selectors):
    if isinstance(selectors, str):
        selectors = [selectors]
    for selector in selectors:
        raw = field_value(row, selector)
        for i, value in enumerate(raw if isinstance(raw, list) else [raw]):
            if isinstance(value, str) and value.strip().casefold() not in MISSING:
                yield {"role": role, "field": selector, "ordinal": i if isinstance(raw, list) else None, "raw": value}


def base_fields(view, mapping, control_mapping):
    fields = {**mapping}
    for role in ("name", "city", "district", "state", "pin", "alias"):
        selectors = control_mapping.get("alt_names" if role == "alias" else role, [])
        if isinstance(selectors, str):
            selectors = [selectors]
        fields[role] = list(dict.fromkeys([*fields.get(role, []), *selectors]))
    return [field for role, selectors in fields.items() for field in _fields(view["row"], role, selectors)]


def external_fields(view, attributes):
    row = {**view["row"], "external_attributes": attributes}
    fields = {"address": "address_original", "name": "name_original", "city": "city", "state": "state", "pin": "pin",
              "alias": "external_attributes.aliases", "district": "external_attributes.district"}
    return [field for role, selector in fields.items() for field in _fields(row, role, selector)]


def _place(raw):
    value = fold(raw)
    return value if value and len(value) >= 4 and any(c.isalpha() for c in value) else None


def _address_component(segment):
    address_pins = PIN.findall(segment)
    without_pin = PIN.sub("", segment)
    premise = [(match[1].lower(), re.sub(r"\s+", "", match[2].lower()).replace("–", "-"))
               for match in PREMISE.finditer(without_pin)]
    text = fold(PREMISE.sub("", without_pin))
    component = {}
    if address_pins:
        component["pins"] = address_pins
    if LANDMARK.match(fold(without_pin) or ""):
        return component
    if premise:
        component["premises"] = premise
    if not text:
        return component
    if not premise and NAMED_PREMISE.search(text) and len(text.split()) >= 2:
        component["premises"] = [("named", text)]
    if match := DISTRICT.fullmatch(text):
        if district := _place(match[1] or match[2]):
            component["districts"] = [district]
    if match := STREET.search(text):
        if _place(text[:match.start()].strip() or text[match.end():].strip()):
            if not premise and (civic := CIVIC.match(without_pin)):
                component["premises"] = [("civic", civic[1].lower())]
                text = fold(civic[2])
            component["streets"] = [re.sub(r"\brd\b", "road", re.sub(r"\bst\b", "street", text))]
    elif LOCALITY.search(text) and _place(text):
        component["localities"] = [text]
    return component


def derive(view, fields, postal_table):
    """Preserve each observed field and multiple place labels in private evidence."""
    parts = {key: set() for key in ("premises", "streets", "localities", "districts", "cities", "pins",
                                    "names", "aliases", "qualifiers")}
    observations = []
    mixed_wording = False
    for field in fields:
        role, raw = field["role"], field["raw"]
        components = []
        if role == "description":
            if MIXED.search(raw):
                mixed_wording = True
                observations.append({**field, "raw": None, "mixed_campus_wording": True})
            continue
        if role == "address":
            for segment in SPLIT.split(raw):
                component = _address_component(segment)
                if component:
                    components.append({"raw": segment.strip(), **component})
                for key, values in component.items():
                    parts[key].update(values)
        elif role in ("name", "alias"):
            name = tuple(core(tokens(raw)))
            if name:
                parts["names" if role == "name" else "aliases"].add(name)
            parts["qualifiers"].update(q for tail in QUALIFIER.split(raw)[1:] if (q := _place(tail)))
        elif role in ("district", "locality", "city"):
            key = {"district": "districts", "locality": "localities", "city": "cities"}[role]
            parts[key].update(p for segment in SPLIT.split(raw) if (p := _place(segment)))
        elif role == "pin":
            parts["pins"].update(PIN.findall(raw))
        observations.append({**field, "components": components})
    if view["pin"]:
        parts["pins"].add(view["pin"])
    contexts = {p: postal_table[p] for p in parts["pins"] if postal_table and p in postal_table}
    postal_districts = {district for c in contexts.values() for district in c["districts"]}
    state_disagreement = any(view["state"] and c["state_complete"] and view["state"] not in c["states"]
                             for c in contexts.values())
    premises, streets = parts["premises"], parts["streets"]
    mixed = mixed_wording or len(premises) > 1 and (len(streets) > 1 or len(parts["localities"]) > 1)
    places = parts["districts"] | parts["cities"] | postal_districts
    keys = {
        BLOCKS[0]: {(p, s) for p in premises for s in streets} if not mixed and len(premises) == len(streets) == 1 else set(),
        BLOCKS[1]: {(p, l) for p in premises for l in parts["localities"]} if not mixed and len(premises) == 1 else set(),
        BLOCKS[2]: {(name, place) for name in parts["names"] for place in places},
        BLOCKS[3]: parts["names"] | parts["aliases"],
        BLOCKS[4]: {name for name in parts["names"] if sum(map(len, name)) >= 7},
    }
    return {**parts, "observations": observations, "postal_districts": postal_districts,
            "postal_pins": set(contexts), "keys": keys, "mixed_campus": mixed,
            "postal_state_disagreement": state_disagreement,
            "geography_incomplete_or_disputed": not (view["state"] and view["pin"] and view["coord"]["usable"])
            or len(parts["pins"]) > 1 or state_disagreement
            or any(not c["state_complete"] or c["ambiguous_state"] for c in contexts.values())}


def evidence(view):
    return {key: sorted(value) if isinstance(value, set) else value
            for key, value in view["premises"].items() if key != "keys"}


class PremisesIndex:
    def __init__(self, externals, max_block):
        self.index = {block: defaultdict(list) for block in BLOCKS}
        self.max_block = max_block
        for i, external in enumerate(externals):
            for block, keys in external["premises"]["keys"].items():
                for key in keys:
                    self.index[block][key].append(i)

    def block(self, base):
        found, capped = defaultdict(list), Counter()
        for block, keys in base["premises"]["keys"].items():
            hits = set()
            for key in keys:
                indexes = self.index[block].get(key, ())
                if len(indexes) > self.max_block:
                    capped[block] += 1
                else:
                    hits.update(indexes)
            for i in hits:
                found[i].append(block)
        return found, capped


def _disjoint(a, b, key):
    return bool(a[key] and b[key] and a[key].isdisjoint(b[key]))


def pair_features(b, e, blocks, signals):
    """Check name and place support independent of a shared building or a postal lookup."""
    a, z = b["premises"], e["premises"]
    a_place, z_place = a["districts"] | a["cities"], z["districts"] | z["cities"]
    named_place = bool((a_place & (z_place | z["postal_districts"])) or (z_place & a["postal_districts"]))
    related = signals["name_level"] in ("strong", "moderate")
    alias = bool((a["aliases"] & (z["names"] | z["aliases"])) or (z["aliases"] & a["names"]))
    qualifier = bool(a["qualifiers"] & z["qualifiers"])
    anchor = (signals["pin"] == "agree" or signals["place"] == "agree" or named_place
              or bool(a["localities"] & z["localities"]) or signals["distance_band"] in ("same_site", "near"))
    postcode_conflict = a["postal_state_disagreement"] or z["postal_state_disagreement"]
    multiple_pins = len(a["pins"]) > 1 or len(z["pins"]) > 1
    competing_coordinates = signals["distance_band"] in ("region", "far")
    conflict = (any(signals[key] == "conflict" for key in ("state", "pin", "place"))
                or postcode_conflict or multiple_pins or competing_coordinates)
    premise_conflict = (_disjoint(a, z, "premises")
                        and bool({p[0] for p in a["premises"]} & {p[0] for p in z["premises"]}))
    street_conflict = _disjoint(a, z, "streets")
    qualifier_conflict = _disjoint(a, z, "qualifiers")
    mixed = a["mixed_campus"] or z["mixed_campus"]
    address = BLOCKS[0] in blocks and (related or alias) and (anchor or signals["name_level"] == "strong")
    locality = BLOCKS[1] in blocks and (related or alias) and not street_conflict
    valid = (address and not mixed, locality and not mixed, named_place and related,
             alias and (anchor or qualifier or address) and not (mixed or premise_conflict or qualifier_conflict),
             signals["name_level"] == "strong" and (a["geography_incomplete_or_disputed"]
                                                     or z["geography_incomplete_or_disputed"] or conflict)
             and (qualifier or named_place or not conflict)
             and not (mixed or premise_conflict or street_conflict or qualifier_conflict))
    admissions = [key for key, supported in zip(BLOCKS, valid) if key in blocks and supported]
    return {"admission": admissions[0] if admissions else None,
            "campus_rank": 3 if BLOCKS[0] in admissions else 2 if BLOCKS[1] in admissions else
                           1 if BLOCKS[3] in admissions else 0,
            "documented_alias": alias, "shared_branch_qualifier": qualifier,
            "premises_conflict": premise_conflict, "street_conflict": street_conflict,
            "branch_qualifier_conflict": qualifier_conflict, "mixed_campus_description": mixed,
            "own_postal_state_conflict": postcode_conflict, "multiple_observed_pins": multiple_pins,
            "competing_coordinates": competing_coordinates}
