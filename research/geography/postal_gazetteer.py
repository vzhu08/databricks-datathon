"""Build the optional Find care place gazetteer from India Post's All India Pincode Directory.

Source: data.gov.in "All India Pincode Directory" (Department of Posts, Government of India), Government Open
Data License - India; keep the attribution with the output. Input is the directory as JSON rows or CSV with the
columns officename, officetype, pincode, statename, latitude, longitude. Output CSV columns: kind, key, state,
latitude, longitude (one median point per PIN and per head or sub post office town and state). The output is
not committed: stage it with the team's data and point FIND_CARE_PLACE_GAZETTEER at it.

Office points in the directory are sometimes placeholders or far off (a whole district at another state's
latitude), so the builder drops "NA" and 1.0/1.0 points, points outside India, points outside the middle of their
state's spread, and offices more than 50 km from their PIN's median.

Usage: python3 -I -m research.geography.postal_gazetteer DIRECTORY.(json|csv) OUT.csv
"""
import csv
import json
import math
import re
import sys
from collections import defaultdict
from statistics import median

FAR_KM = 50.0
SUFFIX = re.compile(r"\s+(?:h\.?\s?o|s\.?\s?o|g\.?\s?p\.?\s?o)\.?$", re.I)


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742.0 * math.asin(math.sqrt(min(1.0, h)))


def _quantile(values, share):
    values = sorted(values)
    return values[min(len(values) - 1, int(share * len(values)))]


def offices(rows):
    kept = []
    for row in rows:
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        pin = str(row.get("pincode", "")).strip()
        if not (6 <= lat <= 37.5 and 68 <= lon <= 97.5) or not re.fullmatch(r"[1-8]\d{5}", pin):
            continue
        kept.append({"name": str(row.get("officename", "")).strip(), "type": str(row.get("officetype", "")).strip().upper(),
                     "pin": pin, "state": " ".join(str(row.get("statename", "")).split()).title(), "point": (lat, lon)})
    by_state = defaultdict(list)
    for office in kept:
        by_state[office["state"]].append(office["point"])
    box = {state: (_quantile([p[0] for p in pts], .1) - 1, _quantile([p[0] for p in pts], .9) + 1,
                   _quantile([p[1] for p in pts], .1) - 1, _quantile([p[1] for p in pts], .9) + 1)
           for state, pts in by_state.items()}
    kept = [o for o in kept if box[o["state"]][0] <= o["point"][0] <= box[o["state"]][1]
            and box[o["state"]][2] <= o["point"][1] <= box[o["state"]][3]]
    by_pin = defaultdict(list)
    for office in kept:
        by_pin[office["pin"]].append(office)
    out = []
    for group in by_pin.values():
        centre = (median(o["point"][0] for o in group), median(o["point"][1] for o in group))
        out.extend(o for o in group if _km(o["point"], centre) <= FAR_KM)
    return out


def build(rows):
    kept = offices(rows)
    pins, towns = defaultdict(list), defaultdict(list)
    for office in kept:
        pins[office["pin"], office["state"]].append(office["point"])
        if office["type"] in {"HO", "SO", "PO"}:
            town = SUFFIX.sub("", office["name"]).strip().title()
            if town:
                towns[town, office["state"]].append(office["point"])
    lines = []
    for kind, groups in (("pin", pins), ("city", towns)):
        for (key, state), pts in sorted(groups.items()):
            lines.append((kind, key, state, round(median(p[0] for p in pts), 5), round(median(p[1] for p in pts), 5)))
    return lines


def main(src, dst):
    if src.endswith(".json"):
        rows = json.load(open(src, encoding="utf-8"))
        rows = rows.get("records", rows) if isinstance(rows, dict) else rows
    else:
        rows = list(csv.DictReader(open(src, newline="", encoding="utf-8")))
    lines = build(rows)
    with open(dst, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(("kind", "key", "state", "latitude", "longitude"))
        writer.writerows(lines)
    print(f"{len(lines)} places written; source: India Post All India Pincode Directory, GODL-India")


if __name__ == "__main__":
    main(*sys.argv[1:3])
