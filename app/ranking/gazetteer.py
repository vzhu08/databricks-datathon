"""Optional place fallback from a public postal gazetteer (off unless a file is configured).

The file is a CSV with columns kind (city or pin), key, state, latitude, longitude. It is built outside Git by
research/geography/postal_gazetteer/build_postal_gazetteer.py from India Post's All India Pincode Directory
(data.gov.in, Government Open Data License - India; attribution: "Department of Posts, Government of India").
Only aggregates are kept: one median point per PIN and per town (head and sub post offices). No real facility
data is involved, and nothing here is committed with real values; tests use synthetic rows.
"""
import csv
from collections import defaultdict
from statistics import median

from .location import finite_number, place_key


def load_gazetteer(lines):
    """Index gazetteer rows (an iterable of CSV lines) by (kind, key)."""
    index = defaultdict(list)
    for row in csv.DictReader(lines):
        kind, key = (row.get("kind") or "").strip(), place_key(row.get("key"))
        lat, lon = finite_number(row.get("latitude")), finite_number(row.get("longitude"))
        if kind in {"city", "pin"} and key and lat is not None and lon is not None:
            index[kind, key].append((place_key(row.get("state")), lat, lon))
    return dict(index)


def gazetteer_fallback(index):
    """A place_fallback(kind, key, state) for search_from_source.

    A PIN resolves to its point. A town resolves only within the typed state, or when every entry of that name
    is in one state, so a name shared by towns in several states (or a typo that equals a village elsewhere in
    another state) is not guessed.
    """
    def fallback(kind, key, state):
        entries = index.get((kind, place_key(key)), [])
        if kind == "city":
            if state:
                entries = [entry for entry in entries if entry[0] == place_key(state)]
            elif len({entry[0] for entry in entries}) > 1:
                return None
        if not entries:
            return None
        return median(entry[1] for entry in entries), median(entry[2] for entry in entries)
    return fallback
