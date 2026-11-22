"""Exact contact-key joins: official phone, website host and email.

Proposal prototype (not wired into `run.py`, `decide.py` or any national run).
It measures how many original VF rows would get an exact-identifier
confirmation if a normalised contact key were treated as an identifier,
under the same rule `decide.auto_confirmation` uses for identifiers:

* the key is exact after normalisation;
* the key sits on exactly one VF original row (counted over every phone,
  website and email value of every row, not only the official ones) and on
  exactly one record of the outside source;
* PIN or distance agrees and nothing disagrees (state alone is not enough);
* one partner each way: the VF row reaches one outside record and that record
  is reached by no other VF row;
* the key is not a shared kind of value: toll-free or short numbers,
  aggregator / social / directory hosts, generic government portals.

Normalised values are retrieval keys only. Original text is never changed.
Nothing here decides a campus; it reports counts and a sample for review.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .normalize import name_evidence, state_key, tokens

# --------------------------------------------------------------------------- phones

# India trunk codes: +91, 0091, 091 or a single leading 0. Toll-free (1800/1860)
# and short service numbers are shared by many campuses and never become keys.
_NON_DIGIT = re.compile(r"\D")
_TOLL_FREE = ("1800", "1860", "1600")


def phone_e164(text):
    """One Indian number as '+91XXXXXXXXXX', or None.

    Accepts '+91 98290 12345', '098290-12345', '0141 2560291', '91-141-2560291'.
    A number written without its STD code (6-8 digits) cannot be placed and is
    dropped rather than guessed."""
    if text is None:
        return None
    digits = _NON_DIGIT.sub("", str(text))
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("091") and len(digits) == 13:
        digits = digits[3:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10 or digits.startswith(_TOLL_FREE) or digits[0] == "0":
        return None
    if len(set(digits)) <= 2:  # 9999999999, 1111111111 and similar placeholders
        return None
    return "+91" + digits


_PHONE_SPLIT = re.compile(r"[,;/|]|\s{2,}(?=\+|0|\d{5})|\bor\b|\band\b")


def phones_from(value):
    """All E.164 numbers in a text, a JSON list text or a list."""
    items = _as_list(value)
    out = set()
    for item in items:
        for part in _PHONE_SPLIT.split(str(item)):
            key = phone_e164(part)
            if key:
                out.add(key)
    return out


# --------------------------------------------------------------------------- hosts

# Hosts that list many facilities. A match on one says nothing about a campus.
SHARED_HOSTS = frozenset("""
facebook.com fb.com m.facebook.com instagram.com twitter.com x.com youtube.com linkedin.com
wa.me whatsapp.com t.me google.com goo.gl g.page maps.google.com business.site sites.google.com
justdial.com practo.com lybrate.com credihealth.com sehat.com indiamart.com dir.indiamart.com
sulekha.com quikr.com yellowpages.in asklaila.com grotal.com tradeindia.com clinicspots.com
medindia.net hexahealth.com vaidam.com logintohealth.com bajajfinservhealth.in apollo247.com
1mg.com pharmeasy.in healthgrades.com mouthshut.com zaubacorp.com tofler.in wikipedia.org
en.wikipedia.org wikimapia.org wikidata.org openstreetmap.org nhp.gov.in data.gov.in
pmjay.gov.in hospitals.pmjay.gov.in esic.nic.in esic.gov.in cghs.gov.in nic.in gov.in
blogspot.com wordpress.com wixsite.com godaddysites.com webs.com weebly.com linktr.ee
docs.google.com forms.gle bit.ly tinyurl.com
""".split())


def host_key(text):
    """Lower-case host without 'www.' and port, or None for shared or unusable hosts.

    The whole host is the key (not the registrable domain), so separate campus
    sub-sites such as 'vbch.dnh.nic.in' stay distinct while a chain's single site
    is caught by the uniqueness count."""
    if text is None:
        return None
    raw = str(text).strip().strip('"').strip()
    if not raw or raw.lower() in ("null", "none", "true", "false", "0", "na"):
        return None
    if "@" in raw and "/" not in raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError:
        return None
    host = host.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host) or not re.search(r"[a-z]", host.rsplit(".", 1)[-1]):
        return None
    if host in SHARED_HOSTS or any(host.endswith("." + s) and s.count(".") >= 1 and s not in ("nic.in", "gov.in")
                                   for s in SHARED_HOSTS):
        return None
    return host


def hosts_from(value):
    return {h for h in (host_key(v) for v in _as_list(value)) if h}


# --------------------------------------------------------------------------- emails

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def emails_from(value):
    out = set()
    for item in _as_list(value):
        for found in _EMAIL.findall(str(item)):
            out.add(found.lower().strip("."))
    return out


# --------------------------------------------------------------------------- helpers

def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            pass
    return [text]


def _pin(value):
    digits = _NON_DIGIT.sub("", str(value or ""))
    return digits if len(digits) == 6 and digits[0] != "0" else None


def _km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(min(1, math.sqrt(h)))


def _point(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if 6 <= lat <= 37.5 and 68 <= lon <= 97.5:
        return lat, lon
    return None


KINDS = ("phone", "host", "email")


# --------------------------------------------------------------------------- VF rows

def vf_record(row):
    """Keys and geography for one original VF row (`base.json` element).

    `official` keys come from officialPhone, officialWebsite and email.
    `listed` keys add the phone_numbers and websites lists, which in this
    snapshot often carry other facilities' directory pages, so they count only
    for uniqueness and for an upper bound."""
    s = row["source_row"]
    official = {"phone": phones_from(s.get("officialPhone")),
                "host": hosts_from(s.get("officialWebsite")),
                "email": emails_from(s.get("email"))}
    listed = {"phone": official["phone"] | phones_from(s.get("phone_numbers")),
              "host": official["host"] | hosts_from(s.get("websites")),
              "email": official["email"]}
    return {"id": row["facility_id"], "name": s.get("name"), "official": official, "listed": listed,
            "state": state_key(s.get("address_stateOrRegion")), "pin": _pin(s.get("address_zipOrPostcode")),
            "city": s.get("address_city"), "point": _point(s.get("latitude"), s.get("longitude"))}


# --------------------------------------------------------------------------- outside lists

def nhp_records(path):
    """NHP Hospital Directory 2025 contact extract (TSV written from the mirror).

    Columns: Sr_No, name, State, District, Pincode, Telephone, Mobile_Number,
    Emergency_Num, Ambulance_Phone_No, Helpline, Tollfree, Website, primary
    email, secondary email. The mirror's coordinates are unusable (swapped or
    out of range), so geography is state and PIN only."""
    out = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            f = line.rstrip("\n").split("\t")
            if len(f) < 14:
                f += [""] * (14 - len(f))
            # Only the facility's own lines. Helpline, toll-free and ambulance lines are shared.
            phones = phones_from(f[5]) | phones_from(f[6]) | phones_from(f[7])
            out.append({"id": "nhp:" + f[0], "name": f[1], "state": state_key(f[2]), "district": f[3],
                        "pin": _pin(f[4]), "point": None,
                        "keys": {"phone": phones, "host": hosts_from(f[11]), "email": emails_from(f[12]) | emails_from(f[13])}})
    return out


def wikidata_records(path):
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for r in data["rows"]:
        point = None
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r.get("coord") or "")
        if m:
            point = _point(m.group(2), m.group(1))
        out.append({"id": r["item"].rsplit("/", 1)[-1], "name": r.get("itemLabel"), "state": None,
                    "district": r.get("admLabel"), "pin": _pin(r.get("postal")), "point": point,
                    "keys": {"phone": phones_from(r.get("phone")), "host": hosts_from(r.get("website")),
                             "email": set()}})
    return out


def overture_records(path, datasets):
    """Overture places CSV from the open-data probe, limited to places whose
    `source_datasets` include one of `datasets` (e.g. {'meta'}). Overture is
    VF's own upstream, so these runs are controls, never confirmations."""
    out = []
    with open(path, encoding="utf-8", newline="") as handle:
        for r in csv.DictReader(handle):
            src = set((r.get("source_datasets") or "").split("|")) - {"Overture"}
            if not src & datasets:
                continue
            out.append({"id": "ovt:" + r["overture_id"], "name": r.get("name"), "state": None,
                        "district": r.get("locality"), "pin": _pin(r.get("postcode")),
                        "point": _point(r.get("lat"), r.get("lon")),
                        "keys": {"phone": {"+91" + p for p in (r.get("phones_10digit") or "").split("|") if phone_e164(p)},
                                 "host": hosts_from((r.get("website_domains") or "").split("|")),
                                 "email": set()}})
    return out


# --------------------------------------------------------------------------- join

def geography(vf, ext, far_km=5.0):
    """'agree', 'unknown' or 'conflict' (first conflict wins)."""
    checks = []
    if vf["state"] and ext.get("state"):
        checks.append(vf["state"] == ext["state"])
    if vf["pin"] and ext.get("pin"):
        checks.append(vf["pin"] == ext["pin"])
    if vf["point"] and ext.get("point"):
        checks.append(_km(vf["point"], ext["point"]) <= far_km)
    if not checks:
        return "unknown"
    if not all(checks):
        return "conflict"
    # State alone cannot tell two campuses of one institution apart.
    return "agree" if len(checks) > 1 or not (vf["state"] and ext.get("state")) else "state_only"


def join(vf_rows, externals, key_set="official"):
    """Exact joins of VF keys against one outside list.

    Returns per-pair rows with an `outcome`:
      would_confirm   key unique on both sides, PIN or distance agrees (state
                      alone is not enough) and nothing disagrees, each side has
                      exactly one partner,
                      the VF row has no second outside record, and the names
                      carry at least weak evidence;
      not_unique      key shared by several VF rows or several outside records;
      geo_conflict    state, PIN or distance disagrees;
      geo_unknown     no geography, or only state, can be compared (review);
      competing       the VF row reaches more than one outside record, or the
                      outside record is reached by more than one VF row;
      name_disagrees  everything else holds but the names share no evidence
                      (`normalize.name_evidence` level 'none'): review, never confirm."""
    vf_count = {k: Counter() for k in KINDS}
    for v in vf_rows:
        for k in KINDS:
            for key in v["listed"][k]:
                vf_count[k][key] += 1
    ext_count = {k: Counter() for k in KINDS}
    index = {k: defaultdict(list) for k in KINDS}
    for i, e in enumerate(externals):
        for k in KINDS:
            for key in e["keys"][k]:
                ext_count[k][key] += 1
                index[k][key].append(i)

    pairs = defaultdict(lambda: {"keys": []})
    for vi, v in enumerate(vf_rows):
        for k in KINDS:
            for key in v[key_set][k]:
                for ei in index[k].get(key, ()):
                    pairs[(vi, ei)]["keys"].append((k, key, vf_count[k][key], ext_count[k][key]))
    reach = Counter(vi for vi, _ in pairs)
    reverse = Counter(ei for _, ei in pairs)
    rows = []
    for (vi, ei), p in sorted(pairs.items()):
        v, e = vf_rows[vi], externals[ei]
        unique = [x for x in p["keys"] if x[2] == 1 and x[3] == 1]
        geo = geography(v, e)
        name_level, name_detail = name_evidence(tokens(v["name"]), tokens(e["name"]))
        if not unique:
            outcome = "not_unique"
        elif geo == "conflict":
            outcome = "geo_conflict"
        elif geo in ("unknown", "state_only"):
            outcome = "geo_unknown"
        elif reach[vi] > 1 or reverse[ei] > 1:
            outcome = "competing"
        elif name_level == "none":
            outcome = "name_disagrees"
        else:
            outcome = "would_confirm"
        rows.append({"vf_id": v["id"], "vf_name": v["name"], "vf_state": v["state"], "vf_pin": v["pin"],
                     "vf_city": v["city"], "ext_id": e["id"], "ext_name": e["name"], "ext_pin": e.get("pin"),
                     "ext_district": e.get("district"),
                     "keys": [{"kind": k, "key": key, "vf_rows": a, "ext_rows": b} for k, key, a, b in p["keys"]],
                     "unique_kinds": sorted({k for k, *_ in unique}), "geography": geo, "name": name_level, "name_detail": name_detail,
                     "outcome": outcome})
    return rows


def summary(vf_rows, externals, rows):
    by = Counter(r["outcome"] for r in rows)
    confirmed = {r["vf_id"] for r in rows if r["outcome"] == "would_confirm"}
    kinds = Counter(k for r in rows if r["outcome"] == "would_confirm" for k in r["unique_kinds"])
    return {"outside_records": len(externals),
            "outside_with_key": {k: sum(1 for e in externals if e["keys"][k]) for k in KINDS},
            "pairs": len(rows), "outcomes": dict(sorted(by.items())),
            "vf_rows_would_confirm": len(confirmed), "would_confirm_by_key_kind": dict(sorted(kinds.items()))}


def vf_key_stats(vf_rows):
    out = {}
    for k in KINDS:
        counts = Counter(key for v in vf_rows for key in v["listed"][k])
        official = [v for v in vf_rows if v["official"][k]]
        out[k] = {"rows_with_official": len(official),
                  "rows_with_unique_official": sum(1 for v in official if any(counts[x] == 1 for x in v["official"][k]))}
    return out


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="base.json (original VF rows with source_row)")
    parser.add_argument("--nhp-tsv")
    parser.add_argument("--wikidata")
    parser.add_argument("--overture-csv", help="control only: Overture is VF's own upstream")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    vf_rows = [vf_record(r) for r in json.load(open(args.base, encoding="utf-8"))]
    sources = {}
    if args.nhp_tsv:
        sources["nhp_2025_contacts"] = nhp_records(args.nhp_tsv)
    if args.wikidata:
        sources["wikidata_hospitals"] = wikidata_records(args.wikidata)
    if args.overture_csv:
        sources["CONTROL_overture_meta"] = overture_records(args.overture_csv, {"meta"})
        sources["CONTROL_overture_non_meta"] = overture_records(args.overture_csv, {"Microsoft", "Foursquare", "PinMeTo", "DAC"})
    report = {"vf_rows": len(vf_rows), "vf_keys": vf_key_stats(vf_rows), "sources": {}, "pairs": {}}
    all_confirmed = set()
    for name, ext in sources.items():
        rows = join(vf_rows, ext)
        report["sources"][name] = summary(vf_rows, ext, rows)
        report["pairs"][name] = rows
        if not name.startswith("CONTROL"):
            all_confirmed |= {r["vf_id"] for r in rows if r["outcome"] == "would_confirm"}
    report["vf_rows_would_confirm_independent_sources"] = len(all_confirmed)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, sort_keys=True, default=sorted)
    json.dump({k: v for k, v in report.items() if k != "pairs"}, sys.stdout, indent=1, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
