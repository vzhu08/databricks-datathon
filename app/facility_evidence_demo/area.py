"""Area view (#270): how precisely the records place facilities, as audience-cleared counts. No Streamlit here.

The aggregate file comes from B3/Vincent and is read at run time from FACILITY_AREA_DISPLAY, like the main
walkthrough's file: it must match AREA_PINNED_SHA256 and area_schema.json, and its counts must reconcile.
Until an edition is cleared and pinned, the area view says so and shows nothing else.

It never shows a facility pin, a point travel time, a distance order, receiving capacity or a service claim:
the schema has no field that could carry one.
"""
import hashlib
import json
import os
from pathlib import Path

try:
    from . import loader
    from .walkthrough import count, source
except ImportError:  # run as a script by Streamlit
    import loader
    from walkthrough import count, source

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "area_schema.json").read_text(encoding="utf-8"))
PATH_SETTING = "FACILITY_AREA_DISPLAY"
# B3's cleared area aggregate for the judge walkthrough, #252 (comment 7077110474) and #270 (comment 7077111112).
AREA_REAL_SHA256 = "0ac26497a9914aa2c42b445f37a2c0e2399fe1c232e3fea38a073d0f5802032f"
AREA_PINNED_SHA256 = AREA_REAL_SHA256  # what load() accepts; only tests ever change it

# Most specific first. Each row: key, label, what the label means on screen.
LEVELS = (
    ("campus_classified", "Campus (directory category)",
     "Classified as campus-located by the directory. This is not an independently verified building or entrance."),
    ("locality", "Locality", "The smallest named area the record supports."),
    ("city", "City only", "City only. No neighbourhood or point is inferred from the city name."),
    ("postal_area", "Postal area (PIN)", "The six-digit postal area the record supports."),
    ("district", "District only", "Only the district is supported."),
    ("unresolved", "Location unknown", "No defensible area. Kept in the count, never guessed."),
)
AREA_ONLY = ("locality", "city", "postal_area", "district")


def parse(raw, expected_sha256):
    if len(raw) > loader.MAX_BYTES:
        raise loader.Unavailable("The area file is larger than an aggregate should be.")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise loader.Unavailable("The area file is not the approved edition (its fingerprint does not match).")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise loader.Unavailable("The area file is not readable JSON.") from None
    loader.check(data, SCHEMA, "area")
    p = data["precision"]
    if sum(p.values()) != data["originals"]:
        raise loader.Unavailable("The area counts do not add up to the number of original records.")
    if sum(data["campus_basis"].values()) != p["campus_classified"]:
        raise loader.Unavailable("The campus categories do not add up to the campus count.")
    if sum(data["unresolved_reasons"].values()) != p["unresolved"]:
        raise loader.Unavailable("The reasons for unknown locations do not add up to the unknown count.")
    if data["distinct_upstream_ids"] > data["originals"]:
        raise loader.Unavailable("There are more upstream IDs than original records.")
    return data


def load(environ=None, expected_sha256=None):
    """{"status": "ok", "data": ..., "synthetic": bool} or {"status": "unavailable", "reason": ...}."""
    environ = os.environ if environ is None else environ
    expected_sha256 = expected_sha256 or AREA_PINNED_SHA256
    if not expected_sha256:
        return loader.unavailable("No area edition has been cleared for this audience yet.")
    location = (environ.get(PATH_SETTING) or "").strip()
    if not location:
        return loader.unavailable(f"No area file is configured ({PATH_SETTING} is not set).")
    try:
        raw = loader.read_bytes(location)
        data = parse(raw, expected_sha256)
    except loader.Unavailable as problem:
        return loader.unavailable(str(problem))
    except OSError:
        return loader.unavailable("The area file could not be read.")
    # Anything other than the cleared edition's bytes is labelled on screen as a test file.
    return {"status": "ok", "data": data, "synthetic": hashlib.sha256(raw).hexdigest() != AREA_REAL_SHA256}


def build(data):
    p = data["precision"]
    total = data["originals"]
    basis, why = data["campus_basis"], data["unresolved_reasons"]
    notes = {
        "campus_classified": (f"{count(basis['named_map_listing'], 'named map listing')} and "
                              f"{count(basis['matching_address'], 'matching address', 'matching addresses')}."),
        "unresolved": (f"{why['missing_state']:,} missing a state, {why['unrecognized_label']:,} with an "
                       f"unrecognised label, {why['other']:,} for other reasons."),
    }
    rows = [{"key": key, "label": label, "meaning": meaning, "count": p[key],
             "share": p[key] / total if total else 0.0, "note": notes.get(key, "")}
            for key, label, meaning in LEVELS]
    area_only = sum(p[key] for key in AREA_ONLY)
    return {
        "headline": f"{area_only:,} of {total:,}",
        "line": (f"{count(area_only, 'record')} can be placed only to an area: "
                 f"{p['locality']:,} to a locality, {p['city']:,} to a city, {p['postal_area']:,} to a postal area "
                 f"and {p['district']:,} to a district. {p['unresolved']:,} cannot be placed at all."),
        "rows": rows,
        "total": total,
        "ids": (f"{count(total, 'original record')} and {count(data['distinct_upstream_ids'], 'distinct upstream ID')}"
                f" ({data['edition']}, as of {data['as_of']})."),
        "source": source(data["source"], "aggregate receipt"),
        "audience": data["audience"],
    }
