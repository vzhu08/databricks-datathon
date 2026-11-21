"""Postal context aggregated to one row per PIN before any join.

Many post offices share one PIN. Joining facility rows to raw postal rows would
multiply facilities, so the directory is first collapsed to a dictionary keyed
by PIN that keeps every distinct state/district it saw. Ambiguity is retained,
not resolved.
"""
from __future__ import annotations

from research.matching.common import field_value, require
from research.matching.normalize import pin_key, place_key, state_key

ROLES = {"pin", "state", "district", "office", "latitude", "longitude"}


def aggregate(rows, mapping):
    """rows: list of postal objects; mapping: role -> observed column selector.

    The mapping must come from an inspected schema (D's notebook 01); it is
    never guessed here. Returns {pin: {...}} and a profile with counts.
    """
    require(isinstance(rows, list), "postal", "expected an array of rows")
    require(isinstance(mapping, dict) and "pin" in mapping and set(mapping) <= ROLES,
            "postal_mapping", "needs a 'pin' column and only known roles")
    table, invalid = {}, 0
    for row in rows:
        require(isinstance(row, dict), "postal", "expected objects")
        pin = pin_key(field_value(row, mapping["pin"]))
        if pin is None:
            invalid += 1
            continue
        entry = table.setdefault(pin, {"pin": pin, "office_count": 0, "states": set(),
                                        "districts": set(), "state_text": set(), "district_text": set()})
        entry["office_count"] += 1
        for role, norm in (("state", state_key), ("district", place_key)):
            if role in mapping:
                raw = field_value(row, mapping[role])
                key = norm(raw) if isinstance(raw, str) else None
                if key:
                    entry[role + "s"].add(key)
                    entry[role + "_text"].add(raw)
    result = {}
    for pin in sorted(table):
        entry = table[pin]
        result[pin] = {"pin": pin, "office_count": entry["office_count"],
                       "states": sorted(entry["states"]), "districts": sorted(entry["districts"]),
                       "state_text": sorted(entry["state_text"]), "district_text": sorted(entry["district_text"]),
                       "ambiguous_state": len(entry["states"]) > 1,
                       "ambiguous_district": len(entry["districts"]) > 1}
    profile = {"postal_rows": len(rows), "rows_without_valid_pin": invalid, "distinct_pins": len(result),
               "pins_with_multiple_offices": sum(e["office_count"] > 1 for e in result.values()),
               "pins_with_multiple_districts": sum(e["ambiguous_district"] for e in result.values()),
               "pins_with_multiple_states": sum(e["ambiguous_state"] for e in result.values())}
    return result, profile


def join(records, postal):
    """Attach postal context by dictionary lookup. One output per input, in order.

    `records` are dicts with 'pin', 'state_key', 'district_key'. The output count
    is asserted equal to the input count so a fan-out cannot go unnoticed.
    """
    out = []
    for record in records:
        pin = record.get("pin")
        context = postal.get(pin) if pin else None
        flags = []
        if pin is None:
            flags.append("pin_missing_or_invalid")
        elif context is None:
            flags.append("pin_not_in_postal_directory")
        else:
            if record.get("state_key") and context["states"] and record["state_key"] not in context["states"]:
                flags.append("state_disagrees_with_pin")
            if record.get("district_key") and context["districts"] and record["district_key"] not in context["districts"]:
                flags.append("district_disagrees_with_pin")
            if context["ambiguous_district"]:
                flags.append("pin_spans_multiple_districts")
        out.append({"postal": context, "postal_flags": flags})
    require(len(out) == len(records), "postal_join", "row count changed during postal join")
    return out
