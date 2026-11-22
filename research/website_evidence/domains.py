"""Pick each VF row's own website domain(s) from the original source fields.

A domain counts as first-party when its name contains a distinctive word of
the facility name (or the name's initials), or when it is the row's
officialWebsite and at most two rows use it. Directory, social, map and
listing sites are dropped, as are .gov.in / .nic.in portals and any domain
shared by more than 60 rows. At most two domains are kept per row.
"""
from __future__ import annotations

import collections
import json
import re

AGGREGATORS = set(
    "facebook.com google.com instagram.com justdial.com practo.com linkedin.com twitter.com x.com youtube.com "
    "wikipedia.org lybrate.com zoominfo.com policyx.com indiamart.com sulekha.com goo.gl bit.ly wa.me "
    "blogspot.com wordpress.com wixsite.com business.site apollo247.com yelp.com quora.com vaidam.com "
    "medifee.com hexahealth.com clinicspots.com drlogy.com healthfrog.in sehat.com credihealth.com "
    "medindia.net docprime.com mfine.co joonsquare.com asklaila.com grotal.com nearbyme.in threebestrated.in "
    "indiakidneyfoundation.org onefivenine.com mappls.com docindia.org healthinsuranceindia.org "
    "medicineindia.org proptiger.com chotu.com ayushmancardhospitals.com magicpin.in watchdoq.com "
    "5bestincity.com latlong.net shuru.co.in eka.care bharatibiz.com tradeindia.com myupchar.com "
    "bajajfinservhealth.in kivihealth.com mapcarta.com bdir.in mediyaar.com scribd.com policybazaar.com "
    "nih.gov".split()
)
STOP = set(
    "hospital hospitals clinic clinics centre center care health healthcare medical multispeciality multi "
    "speciality super specialty nursing home trust the and india pvt private limited ltd foundation "
    "institute research dental eye diagnostic diagnostics".split()
)
HOST = re.compile(r"^(?:[a-z]+://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
SECOND_LEVEL_IN = {"co", "org", "net", "ac", "gov", "nic", "edu", "res", "gen", "firm", "ind"}


def host(value: str) -> str | None:
    m = HOST.match((value or "").strip().strip('"'))
    if not m:
        return None
    h = m.group(1).lower().rstrip(".")
    return None if h[-1].isdigit() else h


def registered(h: str) -> str:
    p = h.split(".")
    if len(p) >= 3 and p[-1] == "in" and p[-2] in SECOND_LEVEL_IN:
        return ".".join(p[-3:])
    return ".".join(p[-2:])


def candidate_hosts(source_row: dict) -> list[str]:
    urls = []
    if isinstance(source_row.get("officialWebsite"), str):
        urls.append(source_row["officialWebsite"])
    websites = source_row.get("websites")
    if isinstance(websites, str):
        try:
            websites = json.loads(websites)
        except ValueError:
            websites = []
    if isinstance(websites, list):
        urls += [u for u in websites if isinstance(u, str)]
    out = []
    for u in urls:
        h = host(u)
        if h and registered(h) not in AGGREGATORS and not h.endswith((".gov.in", ".nic.in")) and h not in out:
            out.append(h)
    return out


def _name_hit(name: str, h: str) -> bool:
    label = re.sub(r"[^a-z]", "", "".join(h.split(".")[:-1]))
    words = re.findall(r"[a-z]+", (name or "").lower())
    tokens = [w for w in words if len(w) >= 4 and w not in STOP]
    initials = "".join(w[0] for w in words if w not in ("the", "and", "of"))
    return any(t in label for t in tokens) or (len(initials) >= 3 and initials in label)


def first_party(base_rows: list[dict], max_rows_per_domain: int = 60, per_row: int = 2) -> list[dict]:
    """[{facility_id, name, state, domains}] for rows with at least one first-party domain."""
    hosts = [(r, candidate_hosts(r["source_row"])) for r in base_rows]
    use = collections.Counter(h for _, hs in hosts for h in hs)
    out = []
    for r, hs in hosts:
        s = r["source_row"]
        official = host(s.get("officialWebsite") or "") if isinstance(s.get("officialWebsite"), str) else None
        keep = [
            h for h in hs
            if use[h] <= max_rows_per_domain and (_name_hit(s.get("name"), h) or (h == official and use[h] <= 2))
        ][:per_row]
        if keep:
            out.append({"facility_id": r["facility_id"], "name": s.get("name"),
                        "state": s.get("address_stateOrRegion"), "domains": keep})
    return out
