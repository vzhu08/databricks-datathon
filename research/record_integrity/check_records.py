#!/usr/bin/env python3
"""Flag VF facility rows that look planted, fabricated or corrupted.

Research check only. It never deletes or edits a row: every original row gets
an integrity score, a tier and the reasons behind it, so search and routing
can warn about or filter suspect rows. Rows that independent sources already
corroborate are marked lower risk.

Inputs are local working copies (never committed):
  --base       VF base.json export (list of {facility_id, source_row})
  --postal     India Post pincode directory rows (optional, enables PIN checks)
  --footprint  footprint_check/point_flags.csv (optional)
  --corroboration  any of the corroboration CSVs (optional, repeatable)

Outputs (to --out, keep outside Git):
  integrity_flags.csv  one row per original row, no phones, emails or people
  summary.json         counts per reason and tier
"""
import argparse
import collections
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

# Rough India envelope (mainland plus Andaman & Nicobar and Lakshadweep).
INDIA_BOX = (6.0, 37.6, 68.0, 97.6)
CURRENT_YEAR = 2026

FAMILIES = {
    "structure": {"malformed_row", "name_missing", "placeholder_text"},
    "location": {"coords_outside_india", "coords_null_island", "coords_field_disagree", "coords_low_precision",
                 "pin_invalid_format", "pin_not_in_directory", "pin_state_mismatch", "point_in_other_state", "far_from_pin_100km",
                 "far_from_pin_25km", "far_from_city_50km", "no_building_within_50m", "coords_shared_unrelated"},
    "contact": {"phone_invalid", "phone_placeholder", "phone_shared_unrelated", "email_placeholder"},
    "text": {"description_duplicate_unrelated", "description_templated", "description_names_other_state"},
    "plausibility": {"year_implausible", "capacity_implausible", "doctors_implausible", "small_type_claims_large_services"},
}

# Weight of each reason. A row's score is the sum. Tiers: >=6 high, >=3 medium, >=1 low.
WEIGHTS = {
    "malformed_row": 6,                 # columns shifted / wrong types: parse corruption
    "name_missing": 6,
    "placeholder_text": 6,              # test / dummy / lorem ipsum style content
    "coords_outside_india": 6,
    "coords_null_island": 6,
    "coords_field_disagree": 3,         # latitude/longitude vs GeoJSON coordinates
    "coords_low_precision": 2,          # 2 or fewer decimals: a guessed or rounded pin
    "pin_invalid_format": 2,
    "pin_not_in_directory": 2,
    "pin_state_mismatch": 3,            # PIN's postal state differs from stated state
    "point_in_other_state": 3,          # post offices around the point are in another state
    "far_from_pin_100km": 4,
    "far_from_pin_25km": 1,
    "far_from_city_50km": 2,            # from footprint_check
    "no_building_within_50m": 1,        # from footprint_check
    "coords_shared_unrelated": 3,       # same point as a differently named row
    "phone_invalid": 1,
    "phone_placeholder": 2,
    "phone_shared_unrelated": 2,        # same phone as a distant, differently named row
    "email_placeholder": 2,
    "description_duplicate_unrelated": 3,
    "description_templated": 1,
    "year_implausible": 2,
    "capacity_implausible": 3,
    "doctors_implausible": 3,
    "small_type_claims_large_services": 2,
    "description_names_other_state": 1,
}

PLACEHOLDER_RE = re.compile(
    r"\b(lorem ipsum|dummy (hospital|clinic|data|record|text)|test (record|data|entry)|sample (hospital|clinic|data)|"
    r"asdf|qwerty|placeholder|xxx+|do not use|fake (hospital|clinic))\b", re.I)
NAME_PLACEHOLDER_RE = re.compile(r"^(test|dummy|sample|abc|xyz|na|n/a|none|null|unknown|hospital|clinic)\W*$", re.I)
EMAIL_PLACEHOLDER_RE = re.compile(r"(@example\.|@test\.|^test@|^abc@|^xyz@|^na@|noemail|no-?reply@none)", re.I)

STATES = [
    "andaman and nicobar", "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chandigarh",
    "chhattisgarh", "dadra and nagar haveli", "daman and diu", "delhi", "goa", "gujarat", "haryana",
    "himachal pradesh", "jammu and kashmir", "jharkhand", "karnataka", "kerala", "ladakh",
    "lakshadweep", "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "puducherry", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana", "tripura",
    "uttar pradesh", "uttarakhand", "west bengal",
]
STATE_ALIASES = {
    "orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand",
    "new delhi": "delhi", "nct of delhi": "delhi", "the dadra and nagar haveli and daman and diu": "dadra and nagar haveli",
    "andaman & nicobar islands": "andaman and nicobar", "andaman and nicobar islands": "andaman and nicobar",
    "jammu & kashmir": "jammu and kashmir", "dadra & nagar haveli": "dadra and nagar haveli",
    "daman & diu": "daman and diu",
}
# States that share PIN ranges or were split recently; treat as compatible.
STATE_COMPAT = [
    {"andhra pradesh", "telangana"}, {"jammu and kashmir", "ladakh"},
    {"dadra and nagar haveli", "daman and diu", "gujarat"}, {"punjab", "chandigarh", "haryana"},
    {"tamil nadu", "puducherry"}, {"kerala", "puducherry", "lakshadweep"},
    {"west bengal", "sikkim"}, {"goa", "maharashtra"}, {"madhya pradesh", "chhattisgarh"},
    {"bihar", "jharkhand"}, {"uttar pradesh", "uttarakhand"},
]
LARGE_SERVICE_RE = re.compile(
    r"\b(mri|magnetic resonance|cath(eter(isation|ization))? lab|dialysis|haemodialysis|hemodialysis|"
    r"trauma (centre|center|care)|icu|intensive care|transplant|ct scan|blood bank)\b", re.I)
GENERIC_NAME_TOKENS = {
    "hospital", "hospitals", "clinic", "clinics", "centre", "center", "care", "health", "healthcare",
    "medical", "multispeciality", "multispecialty", "super", "speciality", "specialty", "the", "and",
    "of", "dental", "eye", "nursing", "home", "pvt", "ltd", "private", "limited", "dr", "dr.",
    "institute", "sciences", "research", "diagnostic", "diagnostics", "memorial", "trust", "&",
}


def norm_state(value):
    if not value:
        return None
    s = re.sub(r"\s+", " ", str(value).strip().lower().replace("&", "and"))
    s = STATE_ALIASES.get(s, s)
    return s if s in STATES else None


def compatible(a, b):
    return a == b or any(a in g and b in g for g in STATE_COMPAT)


def as_list(value):
    if value in (None, "", "null"):
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [value]
    return parsed if isinstance(parsed, list) else [parsed]


def as_num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(min(1, math.sqrt(h)))


def name_tokens(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {w for w in words if w not in GENERIC_NAME_TOKENS and len(w) > 1}


def related(n1, n2):
    """Two names plausibly belong to one organisation (chain, branch, same place)."""
    t1, t2 = name_tokens(n1), name_tokens(n2)
    if not t1 or not t2:
        return (n1 or "").strip().lower() == (n2 or "").strip().lower()
    return bool(t1 & t2)


def digits(phone):
    d = re.sub(r"\D", "", str(phone))
    if d.startswith("0091"):
        d = d[4:]
    elif d.startswith("91") and len(d) == 12:
        d = d[2:]
    elif d.startswith("0") and len(d) == 11:
        d = d[1:]
    return d


def phone_problem(phone):
    d = digits(phone)
    if len(d) != 10:
        return None if len(d) in (8, 11, 12, 13) else "phone_invalid"  # tolerate STD/toll-free shapes
    if len(set(d)) <= 2 or d in ("1234567890", "0123456789", "9876543210") or re.fullmatch(r"\d{3}(\d)\1{6}", d) and d[3] == "0":
        return "phone_placeholder"
    if d[0] == "0":  # landlines start 1-5 (STD code), mobiles 6-9
        return "phone_invalid"
    return None


def precision(value):
    s = repr(value) if isinstance(value, float) else str(value)
    return len(s.split(".", 1)[1].rstrip("0")) if "." in s else 0


def text_fingerprint(text, name, city):
    t = (text or "").lower()
    for part in (name, city):
        for tok in re.findall(r"[a-z0-9]+", (part or "").lower()):
            if len(tok) > 2:
                t = re.sub(r"\b%s\b" % re.escape(tok), " ", t)
    t = re.sub(r"[^a-z]+", " ", t).strip()
    return hashlib.sha1(t.encode()).hexdigest() if len(t) >= 60 else None


def malformed(src):
    problems = []
    if src.get("source") not in ("kie", None):
        problems.append("source")
    if src.get("address_country") not in ("India", None, "null"):
        problems.append("address_country")
    if src.get("organization_type") not in ("facility", None, "null"):
        problems.append("organization_type")
    if src.get("facilityTypeId") not in (None, "null") and not re.fullmatch(r"[a-z]+", str(src["facilityTypeId"])):
        problems.append("facilityTypeId")
    if src.get("operatorTypeId") not in (None, "null", "private", "public", "government", "ngo", "nonprofit"):
        if not re.fullmatch(r"[a-z]+", str(src["operatorTypeId"])):
            problems.append("operatorTypeId")
    for key in ("latitude", "longitude"):
        if src.get(key) not in (None, "null") and as_num(src.get(key)) is None:
            problems.append(key)
    return problems


def load_postal(path):
    """PIN -> {states, office points}, plus a 0.1-degree grid of (point, state) for every office."""
    grid = collections.defaultdict(list)
    by_pin = collections.defaultdict(lambda: {"states": collections.Counter(), "pts": []})
    with open(path) as fh:
        postal_rows = json.load(fh)
    for r in postal_rows:
        pin = str(r.get("pincode") or "")
        if not re.fullmatch(r"\d{6}", pin):
            continue
        st = norm_state(r.get("statename"))
        if st:
            by_pin[pin]["states"][st] += 1
        la, lo = as_num(r.get("latitude")), as_num(r.get("longitude"))
        if la is not None and lo is not None and INDIA_BOX[0] <= la <= INDIA_BOX[1] and INDIA_BOX[2] <= lo <= INDIA_BOX[3]:
            by_pin[pin]["pts"].append((la, lo))
            if st:
                grid[(int(la * 10), int(lo * 10))].append((la, lo, st))
    out = {"__grid__": grid}
    for pin, v in by_pin.items():
        pts = v["pts"]
        # Post office coordinates in this directory are noisy, so distance is measured to the
        # nearest office of the PIN: a far point is far from every office.
        out[pin] = {"states": set(v["states"]), "pts": pts}
    return out


def local_state(grid, pt, radius_km=10, min_offices=3, share=0.8):
    """State that at least `share` of the post offices within `radius_km` agree on, else None."""
    cy, cx = int(pt[0] * 10), int(pt[1] * 10)
    states = collections.Counter()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for la, lo, st in grid.get((cy + dy, cx + dx), ()):
                if km(pt, (la, lo)) <= radius_km:
                    states[st] += 1
    total = sum(states.values())
    if total < min_offices:
        return None
    st, n = states.most_common(1)[0]
    return st if n / total >= share else None


def load_corroboration(paths):
    """Return facility_id -> (level, sources). level: 2 strong, 1 some."""
    result = collections.defaultdict(lambda: [0, set()])
    for path in paths:
        name = Path(path).parent.name + "/" + Path(path).name
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                fid = r.get("facility_id") or r.get("vf_id") or r.get("vf_facility_id")
                if not fid:
                    continue
                level = 0
                if "n_agreeing" in r:
                    n = int(r["n_agreeing"] or 0)
                    level = 2 if n >= 2 else (1 if n == 1 else 0)
                elif "n_sets" in r:
                    n = int(r["n_sets"] or 0)
                    level = 2 if n >= 2 else (1 if n == 1 else 0)
                elif "outcome" in r:
                    level = 2 if r["outcome"] == "would_confirm" else 0
                if level:
                    cur = result[fid]
                    cur[0] = max(cur[0], level)
                    cur[1].add(name)
    return result


def load_footprint(path):
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["facility_id"]] = r
    return out


def run(base_path, postal_path, footprint_path, corroboration_paths):
    with open(base_path) as fh:
        base = json.load(fh)
    postal = load_postal(postal_path) if postal_path else None
    footprint = load_footprint(footprint_path) if footprint_path else {}
    corr = load_corroboration(corroboration_paths or [])

    rows = []
    for index, rec in enumerate(base):
        src = rec.get("source_row") or {}
        rows.append({"index": index, "facility_id": rec.get("facility_id"), "src": src, "reasons": {}})

    # Pass 1: per-row checks, and build cross-row indexes.
    by_point = collections.defaultdict(list)
    by_phone = collections.defaultdict(list)
    by_text = collections.defaultdict(list)
    for row in rows:
        src, add = row["src"], row["reasons"].__setitem__
        name = (src.get("name") or "").strip()
        if name.lower() == "null":
            name = ""
        row["name"] = name
        row["city"] = src.get("address_city") if isinstance(src.get("address_city"), str) else ""
        row["state_raw"] = src.get("address_stateOrRegion") if isinstance(src.get("address_stateOrRegion"), str) else ""
        row["state"] = norm_state(row["state_raw"])
        row["type"] = src.get("facilityTypeId") if re.fullmatch(r"[a-z]+", str(src.get("facilityTypeId") or "")) else ""

        bad = malformed(src)
        if bad:
            add("malformed_row", "fields out of place: " + ",".join(bad))
        if not name:
            add("name_missing", "no facility name")
        elif not bad and NAME_PLACEHOLDER_RE.match(name):
            add("placeholder_text", f"name is a placeholder: {name!r}")
        text = " ".join(str(src.get(k) or "") for k in ("description", "capability", "procedure", "equipment"))
        m = PLACEHOLDER_RE.search(text)
        if m and "placeholder_text" not in row["reasons"]:
            add("placeholder_text", f"text contains {m.group(0)!r}")

        la, lo = as_num(src.get("latitude")), as_num(src.get("longitude"))
        row["pt"] = None
        if la is not None and lo is not None and not bad:
            row["pt"] = (la, lo)
            if abs(la) < 1 and abs(lo) < 1:
                add("coords_null_island", "coordinates at 0,0")
            elif not (INDIA_BOX[0] <= la <= INDIA_BOX[1] and INDIA_BOX[2] <= lo <= INDIA_BOX[3]):
                swapped = INDIA_BOX[0] <= lo <= INDIA_BOX[1] and INDIA_BOX[2] <= la <= INDIA_BOX[3]
                add("coords_outside_india", f"{la:.4f},{lo:.4f} outside India" + (" (lat/lon swapped?)" if swapped else ""))
            if min(precision(src.get("latitude")), precision(src.get("longitude"))) <= 2:
                add("coords_low_precision", "coordinates have 2 or fewer decimals")
            try:
                geo = json.loads(src.get("coordinates") or "null")
                gx, gy = geo["coordinates"]
                if km((gy, gx), (la, lo)) > 1:
                    add("coords_field_disagree", f"GeoJSON point is {km((gy, gx), (la, lo)):.0f} km from latitude/longitude")
            except (TypeError, ValueError, KeyError):
                pass
            by_point[(round(la, 5), round(lo, 5))].append(row)

        if postal is not None and row["pt"] and row["state"] and "coords_outside_india" not in row["reasons"]:
            here = local_state(postal["__grid__"], row["pt"])
            if here and not compatible(row["state"], here):
                add("point_in_other_state", f"post offices around the point are in {here}, row says {row['state']}")

        pin = re.sub(r"\s", "", str(src.get("address_zipOrPostcode") or ""))
        row["pin"] = pin if re.fullmatch(r"\d{6}", pin) else ""
        if pin and not bad and pin != "null":
            if not re.fullmatch(r"[1-8]\d{5}", pin):
                add("pin_invalid_format", "PIN is not a 6-digit Indian PIN")
            elif postal is not None:
                p = postal.get(pin)
                if p is None:
                    add("pin_not_in_directory", "PIN not in the India Post directory")
                else:
                    if row["state"] and p["states"] and not any(compatible(row["state"], s) for s in p["states"]):
                        add("pin_state_mismatch", f"PIN is in {'/'.join(sorted(p['states']))}, row says {row['state']}")
                    if row["pt"] and p["pts"]:
                        d = min(km(row["pt"], q) for q in p["pts"])
                        row["km_from_pin"] = round(d, 1)
                        if d > 100:
                            add("far_from_pin_100km", f"point is {d:.0f} km from the nearest post office of its PIN")
                        elif d > 25:
                            add("far_from_pin_25km", f"point is {d:.0f} km from the nearest post office of its PIN")

        if not bad:
            phones = {digits(p) for p in as_list(src.get("phone_numbers")) + as_list(src.get("officialPhone")) if p}
            phones.discard("")
            problems = {phone_problem(p) for p in phones} - {None}
            for prob in problems:
                add(prob, "phone number has a placeholder pattern" if prob == "phone_placeholder" else "phone number is not a valid Indian number")
            for p in phones:
                if len(p) == 10 and not phone_problem(p):
                    by_phone[p].append(row)
            email = str(src.get("email") or "")
            if email and email != "null" and EMAIL_PLACEHOLDER_RE.search(email):
                add("email_placeholder", "email looks like a placeholder")

            fp = text_fingerprint(src.get("description"), name, row["city"])
            if fp:
                by_text[fp].append(row)

            year = as_num(src.get("yearEstablished"))
            if year is not None and (year < 1800 or year > CURRENT_YEAR):
                add("year_implausible", f"established {year:.0f}")
            cap = as_num(src.get("capacity"))
            docs = as_num(src.get("numberDoctors"))
            ftype = row["type"]
            if cap is not None and (cap > 5000 or cap < 0 or (ftype in ("clinic", "dentist", "doctor", "pharmacy", "farmacy") and cap > 300)):
                add("capacity_implausible", f"{cap:.0f} beds for a {ftype or 'facility'}")
            if docs is not None and (docs > 3000 or docs < 0 or (ftype in ("dentist", "doctor") and docs > 100)
                                     or (cap is not None and cap > 0 and docs > 20 * cap and docs > 100)):
                add("doctors_implausible", f"{docs:.0f} doctors" + (f" for {cap:.0f} beds" if cap else ""))
            if ftype in ("dentist", "pharmacy", "farmacy", "doctor"):
                services = set(m.group(0).lower() for m in LARGE_SERVICE_RE.finditer(text))
                if len(services) >= 3:
                    add("small_type_claims_large_services", f"{ftype} claims {', '.join(sorted(services))}")

            desc = (src.get("description") or "").lower()
            if row["state"] and desc:
                named = {s for s in STATES if re.search(r"\b%s\b" % re.escape(s), desc)}
                if named and not any(compatible(row["state"], s) for s in named) and row["state"] not in desc:
                    add("description_names_other_state", f"description mentions {', '.join(sorted(named))}, row says {row['state']}")

    # Pass 2: cross-row checks. A shared value only counts against rows whose names are unrelated.
    for pt, group in by_point.items():
        if len(group) < 2:
            continue
        for row in group:
            others = [o for o in group if o is not row and not related(row["name"], o["name"])]
            if others:
                row["reasons"]["coords_shared_unrelated"] = f"same point as {len(others)} differently named row(s)"
    for phone, group in by_phone.items():
        if len(group) < 2 or len(group) > 25:  # very common numbers are call centres / chains
            continue
        for row in group:
            others = [o for o in group if o is not row and not related(row["name"], o["name"])
                      and row["pt"] and o["pt"] and km(row["pt"], o["pt"]) > 5]
            if others:
                row["reasons"]["phone_shared_unrelated"] = f"phone shared with {len(others)} unrelated row(s) >5 km away"
    for fp, group in by_text.items():
        if len(group) < 2:
            continue
        unrelated = [r for r in group if any(not related(r["name"], o["name"]) for o in group if o is not r)]
        for row in group:
            if row in unrelated:
                row["reasons"]["description_duplicate_unrelated"] = f"description identical (names removed) to {len(group) - 1} other row(s)"
            else:
                row["reasons"]["description_templated"] = f"description identical to {len(group) - 1} related row(s)"

    # Earlier point-quality work.
    for row in rows:
        f = footprint.get(row["facility_id"])
        if not f:
            continue
        if f.get("far_from_city_50km") == "True":
            row["reasons"]["far_from_city_50km"] = f"{f.get('km_from_city_median')} km from other rows in its city"
        if f.get("primary_flag") == "no_building_within_50m":
            row["reasons"]["no_building_within_50m"] = "no building outline within 50 m"

    # Score and tier.
    for row in rows:
        score = sum(WEIGHTS[k] for k in row["reasons"])
        level, sources = corr.get(row["facility_id"], (0, set()))
        structural = {"malformed_row", "name_missing", "placeholder_text", "coords_outside_india", "coords_null_island"}
        hard = bool(structural & set(row["reasons"]))
        adjusted = score if hard else max(0, score - (3 if level == 2 else 1 if level == 1 else 0))
        row["score"], row["adjusted"] = score, adjusted
        row["corroboration"] = {2: "strong", 1: "some", 0: ""}[level]
        row["corroboration_sources"] = ";".join(sorted(sources))
        row["tier"] = "high" if adjusted >= 6 else "medium" if adjusted >= 3 else "low" if adjusted >= 1 else "none"
    return rows


def write(rows, out):
    out.mkdir(parents=True, exist_ok=True)
    cols = ["facility_id", "row_index", "tier", "adjusted_score", "raw_score", "families", "reasons", "details",
            "corroboration", "corroboration_sources", "name", "type", "city", "state", "pin", "lat", "lon", "km_from_pin"]
    order = sorted(rows, key=lambda r: (-r["adjusted"], -r["score"], r["index"]))
    with open(out / "integrity_flags.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in order:
            fams = "|".join(f for f, keys in FAMILIES.items() if keys & set(r["reasons"]))
            w.writerow([r["facility_id"], r["index"], r["tier"], r["adjusted"], r["score"], fams,
                        "|".join(sorted(r["reasons"])), " | ".join(r["reasons"][k] for k in sorted(r["reasons"])),
                        r["corroboration"], r["corroboration_sources"], r["name"], r["type"], r["city"],
                        r["state_raw"], r["pin"], *(r["pt"] or ("", "")), r.get("km_from_pin", "")])
    reasons = collections.Counter(k for r in rows for k in r["reasons"])
    summary = {
        "rows": len(rows),
        "rows_with_coordinates": sum(1 for r in rows if r["pt"]),
        "tiers": dict(collections.Counter(r["tier"] for r in rows)),
        "tiers_with_coordinates": dict(collections.Counter(r["tier"] for r in rows if r["pt"])),
        "reasons": dict(reasons.most_common()),
        "rows_by_family": {f: sum(1 for r in rows if keys & set(r["reasons"])) for f, keys in FAMILIES.items()},
        "high_tier_by_family": {f: sum(1 for r in rows if r["tier"] == "high" and keys & set(r["reasons"]))
                                for f, keys in FAMILIES.items()},
        "corroborated_rows": dict(collections.Counter(r["corroboration"] or "none" for r in rows)),
        "corroborated_but_flagged_medium_or_high": sum(1 for r in rows if r["corroboration"] and r["tier"] in ("medium", "high")),
        "weights": WEIGHTS,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--postal")
    ap.add_argument("--footprint")
    ap.add_argument("--corroboration", action="append", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows = run(args.base, args.postal, args.footprint, args.corroboration)
    summary = write(rows, Path(args.out))
    json.dump({k: summary[k] for k in ("rows", "tiers", "reasons")}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
