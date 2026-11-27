from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from statistics import median

EARTH_RADIUS_KM = 6371.0088
PIN = re.compile(r"[0-9]{6}")


def _display_name(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def place_key(value):
    return _display_name(value).lower()


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def coordinates(row):
    lat = finite_number(row.get("latitude"))
    lon = finite_number(row.get("longitude"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def validate_location(location):
    """Return the normalized input mode and value, or raise with a user-facing message."""
    if not isinstance(location, Mapping):
        raise ValueError("Enter a city and optional state, a PIN, or coordinates.")
    keys = set(location)
    if keys == {"latitude", "longitude"}:
        point = coordinates(location)
        if point is None:
            raise ValueError("Enter a finite latitude from −90 to 90 and longitude from −180 to 180.")
        return "coordinates", point
    if keys == {"pin"}:
        pin = _display_name(location["pin"])
        if not PIN.fullmatch(pin):
            raise ValueError("Enter a six-digit PIN as text.")
        return "pin", pin
    if keys in ({"city"}, {"city", "state"}):
        city = place_key(location["city"])
        state = location.get("state")
        if not city or (state is not None and not isinstance(state, str)):
            raise ValueError("Enter a city name and, optionally, a state name.")
        return "city", (city, place_key(state))
    raise ValueError("Enter one location using a city and optional state, a PIN, or both coordinates.")


# Indian states and union territories, with the spellings the facility records also use. Used only by the
# opt-in majority-state rule: a record whose state field holds a city or locality ("Pune", "Thane") is set aside.
STATES_AND_UNION_TERRITORIES = frozenset({
    "andaman and nicobar islands", "andaman & nicobar islands", "andhra pradesh", "arunachal pradesh", "assam", "bihar",
    "chandigarh", "chhattisgarh", "chattisgarh", "dadra and nagar haveli and daman and diu", "dadra and nagar haveli",
    "daman and diu", "delhi", "nct of delhi", "goa", "gujarat", "haryana", "himachal pradesh", "jammu and kashmir",
    "jammu & kashmir", "jharkhand", "karnataka", "kerala", "ladakh", "lakshadweep", "madhya pradesh", "maharashtra",
    "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "puducherry", "pondicherry", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "tamilnadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "uttaranchal", "west bengal",
})
MAJORITY_SHARE = 0.8


def majority_state(rows):
    """The state holding at least MAJORITY_SHARE of the rows whose state field is a real state, else ""."""
    states = Counter(key for key in (place_key(row.get("state")) for row in rows) if key in STATES_AND_UNION_TERRITORIES)
    if not states:
        return ""
    state, count = states.most_common(1)[0]
    return state if count >= MAJORITY_SHARE * sum(states.values()) else ""


def resolve_place(rows, kind, state, *, prefer_majority_state=False):
    """Resolve matching city or PIN rows to a point, or return sorted city choices.

    With prefer_majority_state, a city typed without a state resolves in the state that holds most of its
    records instead of asking, when that state holds at least MAJORITY_SHARE of them.
    """
    if kind == "city" and prefer_majority_state and not state:
        rows = list(rows)
        state = majority_state(rows)
    if kind == "city":
        states = {}
        for row in rows:
            key = place_key(row.get("state"))
            if key:
                label = (_display_name(row["city"]), _display_name(row["state"]))
                states[key] = min(states.get(key, label), label)
        if not state and len(states) > 1:
            return None, [dict(city=states[key][0], state=states[key][1]) for key in sorted(states)]
        if not state and states:
            state = next(iter(states))
        if state:
            rows = [row for row in rows if place_key(row.get("state")) == state]

    points = [point for point in map(coordinates, rows) if point is not None]
    if not points:
        return None, []
    latitudes, longitudes = zip(*points)
    return (median(latitudes), median(longitudes)), []


def haversine_km(origin, destination):
    lat1, lon1 = origin
    lat2, lon2 = destination
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(math.remainder(lon2 - lon1, 360))
    a = math.sin(delta_lat / 2) ** 2
    if abs(lat1) != 90 and abs(lat2) != 90:
        a += math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(a, 1.0)))
