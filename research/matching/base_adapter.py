"""Read-only views over base rows and external rows.

The base file is D's documented adapter shape: a JSON array of objects with a
unique `facility_id`. Real exports nest every original column under
`source_row`; the column mapping must be the one D observed in the workspace.
This module never guesses a column and never writes to a base row.
"""
from __future__ import annotations

from research.geography.checks import coordinate_status
from .common import field_value, require
from .normalize import (address_tokens, core, fold, phone_keys, pin_key, place_key,
                        state_key, tokens)

BASE_ROLES = ("name", "alt_names", "address", "city", "district", "state", "pin",
              "latitude", "longitude", "phone", "type")
MULTI = {"alt_names", "phone"}


def default_mapping(base):
    """Identity mapping for a base whose top-level keys already use role names
    (the shared synthetic base). A `source_row` export needs an explicit mapping."""
    keys = set()
    for row in base:
        keys.update(row)
    require("source_row" not in keys, "base_mapping",
            "base rows use the export shape (source_row); supply --base-mapping with the "
            "column mapping D observed. Refusing to guess source columns.")
    return {role: role for role in BASE_ROLES if role in keys}


def check_mapping(mapping, base):
    require(isinstance(mapping, dict) and set(mapping) <= set(BASE_ROLES), "base_mapping",
            "unknown role; allowed: " + ", ".join(BASE_ROLES))
    for role, selector in mapping.items():
        selectors = selector if isinstance(selector, list) else [selector]
        require(bool(selectors) and all(isinstance(s, str) and s.strip() for s in selectors),
                f"base_mapping.{role}", "selector must be a column path or a list of them")
        require(isinstance(selector, str) or role in MULTI, f"base_mapping.{role}",
                "only alt_names and phone accept several columns")
        for s in selectors:
            require(any(_present(row, s) for row in base), f"base_mapping.{role}",
                    "selector names a column that no base row has")
    return mapping


def _present(row, selector):
    if selector in row:
        return True
    value = row
    for part in selector.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _many(row, selector):
    selectors = selector if isinstance(selector, list) else [selector]
    out = []
    for s in selectors:
        value = field_value(row, s)
        for item in (value if isinstance(value, list) else [value]):
            if _text(item):
                out.append(item)
    return out


def base_views(base, mapping):
    views = []
    for row in base:
        get = lambda role: field_value(row, mapping[role]) if role in mapping and isinstance(mapping[role], str) else None
        name = _text(get("name"))
        aliases = _many(row, mapping["alt_names"]) if "alt_names" in mapping else []
        names = [tokens(n) for n in ([name] if name else []) + aliases]
        phones = frozenset().union(*[phone_keys(p) for p in _many(row, mapping["phone"])]) if "phone" in mapping else frozenset()
        raw_pin = get("pin")
        views.append({
            "id": row["facility_id"], "row": row,
            "names": [n for n in names if n], "has_alias": bool(aliases),
            "address": address_tokens(_text(get("address"))),
            "city": place_key(_text(get("city"))), "district": place_key(_text(get("district"))),
            "state": state_key(_text(get("state"))),
            "pin": pin_key(raw_pin), "pin_invalid": raw_pin is not None and pin_key(raw_pin) is None,
            "coord": coordinate_status(get("latitude"), get("longitude")),
            "phones": phones, "type": fold(_text(get("type"))),
        })
    return views


def external_views(batch, attributes=None):
    """`attributes` is an optional sidecar keyed by external_facility_id with
    'aliases', 'phones' and 'district'. It carries values that live only in the
    producer's raw artifact (the contract has no such columns)."""
    attributes = attributes or {}
    require(isinstance(attributes, dict), "external_attributes", "expected an object keyed by external_facility_id")
    known = {row["external_facility_id"] for row in batch["external_facilities"]}
    for key, value in attributes.items():
        require(key in known, "external_attributes", "refers to an external_facility_id that is not in the batches")
        require(isinstance(value, dict) and set(value) <= {"aliases", "phones", "district"},
                "external_attributes", "allowed keys: aliases, phones, district")
    sources = {s["snapshot_id"]: s for s in batch["source_snapshots"]}
    views = []
    for row in batch["external_facilities"]:
        extra = attributes.get(row["external_facility_id"], {})
        require(row["snapshot_id"] in sources, "external_facilities.snapshot_id", "snapshot not found in the batches")
        aliases = [a for a in extra.get("aliases", []) if _text(a)]
        names = [tokens(n) for n in ([row["name_original"]] if row["name_original"] else []) + aliases]
        source = sources[row["snapshot_id"]]
        views.append({
            "id": row["external_facility_id"], "row": row,
            "names": [n for n in names if n], "has_alias": bool(aliases),
            "address": address_tokens(row["address_original"]),
            "city": place_key(row["city"]), "district": place_key(_text(extra.get("district"))),
            "state": state_key(row["state"]), "pin": pin_key(row["pin"]),
            "coord": coordinate_status(row["latitude"], row["longitude"]),
            "phones": phone_keys(extra.get("phones")),
            "type": fold(row["facility_type"]),
            "source_key": source["source_key"], "source_family": source["source_family"],
        })
    return views


def name_core_sets(view):
    return [frozenset(core(n)) for n in view["names"]]
