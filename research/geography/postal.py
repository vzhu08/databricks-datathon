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


def aggregate(rows, mapping, known_states=None):
    """rows: list of postal objects; mapping: role -> observed column selector.

    `known_states`: folded names of recognised states. With it, an office state
    label outside the set is kept apart in `states_unrecognised` and is never
    counted as a state. An office with no state label is counted in
    `offices_without_state`. `state_complete` is true only when every office of
    the PIN carries a recognised state, so a comparison against it is sound.

    The mapping must come from an inspected schema (D's notebook 01); it is
    never guessed here. Returns {pin: {...}} and a profile with counts.
    """
    require(isinstance(rows, list), "postal", "expected an array of rows")
    require(isinstance(mapping, dict) and "pin" in mapping and set(mapping) <= ROLES,
            "postal_mapping", "needs a 'pin' column and only known roles")
    table, invalid = {}, 0
    for index, row in enumerate(rows):
        require(isinstance(row, dict), "postal", "expected objects")
        pin = pin_key(field_value(row, mapping["pin"]))
        if pin is None:
            invalid += 1
            continue
        entry = table.setdefault(pin, {"pin": pin, "office_count": 0, "states": set(),
                                        "districts": set(), "state_text": set(), "district_text": set(),
                                        "states_unrecognised": set(), "offices_without_state": 0})
        entry["office_count"] += 1
        if "office" in mapping:
            entry.setdefault("offices", []).append({"row_index": index, **{
                role: field_value(row, mapping[role]) for role in ("office", "district", "state") if role in mapping
            }})
        for role, norm in (("state", state_key), ("district", place_key)):
            if role in mapping:
                raw = field_value(row, mapping[role])
                key = norm(raw) if isinstance(raw, str) else None
                if role == "state" and not key:
                    entry["offices_without_state"] += 1
                elif role == "state" and known_states is not None and key not in known_states:
                    entry["states_unrecognised"].add(key)
                elif key:
                    entry[role + "s"].add(key)
                    entry[role + "_text"].add(raw)
    result = {}
    for pin in sorted(table):
        entry = table[pin]
        result[pin] = {"pin": pin, "office_count": entry["office_count"],
                       "states": sorted(entry["states"]), "districts": sorted(entry["districts"]),
                       "state_text": sorted(entry["state_text"]), "district_text": sorted(entry["district_text"]),
                       "states_unrecognised": sorted(entry["states_unrecognised"]),
                       "offices_without_state": entry["offices_without_state"] if "state" in mapping else 0,
                       "state_complete": (bool(entry["states"]) and not entry["states_unrecognised"]
                                          and not entry["offices_without_state"]) if "state" in mapping else None,
                       "ambiguous_state": len(entry["states"]) > 1,
                       "ambiguous_district": len(entry["districts"]) > 1}
        if "offices" in entry:
            result[pin]["offices"] = entry["offices"]
    profile = {"postal_rows": len(rows), "rows_without_valid_pin": invalid, "distinct_pins": len(result),
               "pins_with_multiple_offices": sum(e["office_count"] > 1 for e in result.values()),
               "pins_with_multiple_districts": sum(e["ambiguous_district"] for e in result.values()),
               "pins_with_multiple_states": sum(e["ambiguous_state"] for e in result.values()),
               "pins_with_unrecognised_state_label": sum(bool(e["states_unrecognised"]) for e in result.values()),
               "pins_with_office_without_state": sum(bool(e["offices_without_state"]) for e in result.values())}
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
            # A disagreement is established only when every office of the PIN names a recognised state.
            if (record.get("state_key") and context["states"] and record["state_key"] not in context["states"]
                    and context.get("state_complete") is not False):
                flags.append("state_disagrees_with_pin")
            if context.get("state_complete") is False:
                flags.append("pin_state_evidence_incomplete")
            if record.get("district_key") and context["districts"] and record["district_key"] not in context["districts"]:
                flags.append("district_disagrees_with_pin")
            if context["ambiguous_district"]:
                flags.append("pin_spans_multiple_districts")
        out.append({"postal": context, "postal_flags": flags})
    require(len(out) == len(records), "postal_join", "row count changed during postal join")
    return out
