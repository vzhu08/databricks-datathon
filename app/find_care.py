"""Words for the Find care screen: turns one search response into what a health worker reads.

Pure functions with no Streamlit or Databricks dependency. Nothing here searches, ranks or
filters. The order, the distances, the excerpts and the status are read from the response of
`search_warehouse` or `search_facilities` (docs/implementation/SEARCH_CONTRACT.md).

Two rules live here because every surface of the screen depends on them:

* `data_mode` decides, from the app's settings alone, whether the screen runs on the invented
  demonstration facilities, reads the warehouse, or stops with a setup problem. A half-configured
  warehouse never falls back to invented data.
* `withheld` is applied to every warehouse response before anything else sees it. Until a reviewed
  service, campus and destination and the right to show record text reach this screen through a
  verified interface, no facility field from the real records is kept, shown or exported.
"""
import re

SERVICES = {"dialysis": "Dialysis", "mri": "MRI scan", "trauma_care": "Trauma care"}
SERVICE_PHRASE = {"dialysis": "dialysis", "mri": "an MRI scan", "trauma_care": "trauma care"}
FIELDS = {"description": "description", "capabilities": "capabilities", "procedures": "procedures",
          "equipment": "equipment"}
RADII = (2, 5, 10, 25, 50, 100, 200)
# The search's own rules, one per line, in the order they apply.
HOW = (
    "A facility qualifies when its record states the service directly. The nearest one comes first.",
    "A record that only mentions something related, such as a kidney clinic for dialysis, is shown only "
    "when nothing states the service directly, and is marked as needing confirmation.",
    "A mention that says the service is planned, unavailable or referred elsewhere does not count.",
    "Distance is a straight line, not road time. Up to three facilities are shown.",
)


HOW_WITHHELD = (
    "This screen is reading the real facility records. A record that mentions a service is a claim "
    "collected from the web, and the nearest such record is not a safe referral. The team has not yet "
    "reviewed the service, the campus and the right to show record text for any facility, so the "
    "screen names none, shows no record text or links, and offers no referral note."
)
DATA_SETTING = "FIND_CARE_DATA"
WAREHOUSE_SETTINGS = {
    "DATABRICKS_WAREHOUSE_ID": "Add the SQL warehouse resource to this app.",
    "DATABRICKS_PREPARED_TABLE": "Set it to the prepared table, written as catalog.schema.table.",
    "DATABRICKS_HOST": "Databricks Apps supplies it when the app runs there.",
    "DATABRICKS_CLIENT_ID": "Databricks Apps supplies it when the app runs there.",
    "DATABRICKS_CLIENT_SECRET": "Databricks Apps supplies it when the app runs there.",
}
_TABLE = re.compile(r"[\w-]+\.[\w-]+\.[\w-]+")
_COORDINATES = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*[,\s]\s*([+-]?\d+(?:\.\d+)?)")
# Typed-place cleanup for parse_location. Measured on 599 messy inputs (state abbreviations, old names,
# "near X", "X, India", "PIN 560034" and similar); see the location-input check linked from #40.
_STATES = ("Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
           "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana",
           "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep",
           "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry",
           "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
           "West Bengal")
_STATE_ALIASES = {
    **{name.lower(): name for name in _STATES},
    # vehicle-registration and common short forms
    "an": "Andaman and Nicobar Islands", "ap": "Andhra Pradesh", "ar": "Arunachal Pradesh", "as": "Assam", "br": "Bihar",
    "ch": "Chandigarh", "cg": "Chhattisgarh", "ct": "Chhattisgarh", "dl": "Delhi", "nct of delhi": "Delhi", "ga": "Goa",
    "gj": "Gujarat", "hr": "Haryana", "hp": "Himachal Pradesh", "jk": "Jammu and Kashmir", "j&k": "Jammu and Kashmir",
    "j & k": "Jammu and Kashmir", "jh": "Jharkhand", "ka": "Karnataka", "kl": "Kerala", "la": "Ladakh", "mp": "Madhya Pradesh",
    "mh": "Maharashtra", "mn": "Manipur", "ml": "Meghalaya", "mz": "Mizoram", "nl": "Nagaland", "od": "Odisha", "or": "Odisha",
    "py": "Puducherry", "pb": "Punjab", "rj": "Rajasthan", "sk": "Sikkim", "tn": "Tamil Nadu", "ts": "Telangana",
    "tg": "Telangana", "tr": "Tripura", "up": "Uttar Pradesh", "uk": "Uttarakhand", "ut": "Uttarakhand", "wb": "West Bengal",
    # former and frequent alternative spellings
    "orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand", "tamilnadu": "Tamil Nadu",
    "gujrat": "Gujarat", "chattisgarh": "Chhattisgarh", "chhatisgarh": "Chhattisgarh", "jammu & kashmir": "Jammu and Kashmir",
}
# Only former names that the facility records rarely or never use. Names the records use widely
# (Bangalore, Gurgaon, Allahabad, Trivandrum) are left as typed, because they resolve already.
_CITY_ALIASES = {"bombay": "Mumbai", "calcutta": "Kolkata", "madras": "Chennai", "poona": "Pune", "cawnpore": "Kanpur",
                 "simla": "Shimla", "benares": "Varanasi", "banaras": "Varanasi",
                 "dilli": "Delhi", "pondy": "Puducherry", "vizag": "Visakhapatnam", "vishakhapatnam": "Visakhapatnam",
                 "tiruchi": "Tiruchirappalli",
                 "ootacamund": "Ooty", "udhagamandalam": "Ooty", "amdavad": "Ahmedabad"}
_CITY_STATES = {"delhi", "chandigarh", "puducherry", "pondicherry", "goa"}
_KEEP_CITY = re.compile(r"\b(?:steel|salt lake|lake|port|sports) city$", re.I)  # "City" belongs to these names
_PREFIX = re.compile(r"^(?:near(?:by)?|in|at|around|close to|next to)\s+", re.I)
_SUFFIX = re.compile(r"(?:\s*,?\s*\bindia|\s+(?:city|town|district|dist\.?))$", re.I)
# a PIN must stand alone: no letters, digits or decimal points touching it ("AB560034", "12.560034" are not PINs)
_PIN_IN_TEXT = re.compile(r"(?<![\w.])([1-9]\d{2})[ -]?(\d{3})(?![\w.])")
_SIX_DIGITS = re.compile(r"\d{3}[ -]?\d{3}")
_PIN_WORDS = re.compile(r"\b(?:pin(?:\s*code)?|pincode|postal code|zip)\b[\s:#.-]*", re.I)


def _clean_place(text):
    """Strip the words around a place that the records never contain."""
    previous = None
    while previous != text:
        previous = text
        # a leading minus can be the sign of a latitude ("near -12.5, 77.6"), so only the end loses dashes
        text = text.lstrip(" ;:!?").rstrip(" .;:!?-").strip()
        text = _PREFIX.sub("", text)
        if not _KEEP_CITY.search(text):
            text = _SUFFIX.sub("", text).strip(" ,")
    return text


def _state(text):
    return _STATE_ALIASES.get(" ".join(text.lower().replace(".", "").split()))


def _split_state(text):
    """City and state from 'Pune, Maharashtra', 'Pune, MH' or 'Pune Maharashtra'; state may be empty."""
    if "," in text:
        city, _, state = (part.strip() for part in text.partition(","))
        return city, (_state(state) or state)
    words = text.split()
    for size in (6, 5, 4, 3, 2, 1):
        if len(words) > size:
            tail = " ".join(words[-size:])
            state = _state(tail)
            # without a comma, a short code counts only in capitals ("Pune MH"), and a state that is also a
            # city name ("New Delhi", "Old Goa") is never split off
            if state and (len(tail) > 3 or tail.isupper()) and tail.lower() not in _CITY_STATES:
                return " ".join(words[:-size]), state
    return text, ""


def data_mode(environ):
    """Where the screen gets its facilities: {"mode": "demo" | "warehouse" | "setup", "problems": [...]}.

    FIND_CARE_DATA chooses it outright. Left unset, the screen is a demonstration only when none of
    the five warehouse settings is present: the host or the app's credentials alone already mean the
    real records were intended, so whatever is missing is reported instead of quietly showing
    invented facilities. Setting values are never repeated in a problem line.
    """
    def has(name):
        return bool(str(environ.get(name) or "").strip())

    chosen = str(environ.get(DATA_SETTING) or "").strip().lower()
    if chosen not in ("", "demo", "warehouse"):
        return {"mode": "setup", "problems": [f"{DATA_SETTING} must be demo or warehouse."]}
    if chosen == "demo" or (not chosen and not any(has(name) for name in WAREHOUSE_SETTINGS)):
        return {"mode": "demo", "problems": []}
    problems = [f"{name} is not set. {fix}" for name, fix in WAREHOUSE_SETTINGS.items() if not has(name)]
    if has("DATABRICKS_PREPARED_TABLE") and not _TABLE.fullmatch(str(environ["DATABRICKS_PREPARED_TABLE"]).strip()):
        problems.append("DATABRICKS_PREPARED_TABLE must be written as catalog.schema.table.")
    return {"mode": "setup" if problems else "warehouse", "problems": problems}


def withheld(response):
    """All that is kept of a warehouse response before reviewed destinations and display permission exist.

    Keeps the status and the search's own fixed messages. Drops every facility field: names, places,
    distances, record text, source links and identifiers, and the place names offered for an
    ambiguous city. A search that found records answers "withheld", never "ok".
    """
    status = response.get("status")
    kept = {"status": status, "direct_results": [], "indirect_leads": [], "location_choices": [],
            "approximate_location": False, "message": None, "withheld": True}
    if status == "ok":
        kept.update(status="withheld", evidence="direct")
    elif status == "needs_confirmation":
        kept.update(status="withheld", evidence="related")
    elif status in ("invalid_input", "unresolved_location", "unavailable"):
        kept["message"] = response.get("message")
    return kept


def build_location(mode, *, city="", state="", pin="", latitude="", longitude=""):
    """The location object the search expects, from what was typed. Raises ValueError with a plain message."""
    if mode == "city":
        city, state = city.strip(), state.strip()
        if not city:
            raise ValueError("Type the city or town.")
        return {"city": city, "state": state} if state else {"city": city}
    if mode == "pin":
        pin = pin.strip().replace(" ", "")
        if not pin:
            raise ValueError("Type the six-digit PIN code.")
        return {"pin": pin}
    if mode == "coordinates":
        try:
            return {"latitude": float(str(latitude).strip()), "longitude": float(str(longitude).strip())}
        except ValueError:
            raise ValueError("Type the latitude and longitude as numbers, for example 26.92 and 75.82.") from None
    raise ValueError("Choose how to give the location.")


def parse_location(text):
    """The location object the search expects, from one typed line. Raises ValueError with a plain message.

    Six digits are a PIN code, two numbers are coordinates, and anything else is a city or town with an
    optional state after a comma.
    """
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("Type a city or town, a PIN code, or coordinates.")
    digits = text.replace(" ", "")
    if digits.isdigit() and len(digits) == 6:
        return {"pin": digits}
    pair = _COORDINATES.fullmatch(text)
    if pair:
        return {"latitude": float(pair[1]), "longitude": float(pair[2])}
    if digits.isdigit():
        raise ValueError("A PIN code has six digits.")
    if text.startswith(","):
        raise ValueError("Type the city or town before the comma.")
    cleaned = _clean_place(text)
    pair = _COORDINATES.fullmatch(cleaned)
    if pair:
        return {"latitude": float(pair[1]), "longitude": float(pair[2])}
    pins = _PIN_IN_TEXT.findall(cleaned)
    if len(pins) > 1:
        raise ValueError("Type one PIN code.")
    if pins:
        # a PIN is the most precise thing typed, so "PIN 560 034", "560-034" and "Jaipur 302001" search by PIN
        return {"pin": "".join(pins[0])}
    if _SIX_DIGITS.search(cleaned):
        raise ValueError("Type the six-digit PIN code on its own, for example 560034.")
    if not any(character.isalpha() for character in text):
        raise ValueError("Type coordinates as latitude, then longitude, for example 26.92, 75.82.")
    city, state = _split_state(cleaned)
    city = _clean_place(city)
    if not city:
        if state:
            raise ValueError("Type the city or town as well as the state.")
        raise ValueError("Type the city or town before the comma.")
    city = _CITY_ALIASES.get(" ".join(city.lower().split()), city)
    return {"city": city, "state": state} if state else {"city": city}


def location_text(location):
    """The typed line that parse_location reads back as this location."""
    if "pin" in location:
        return str(location["pin"])
    if "city" in location:
        return ", ".join(part for part in (location["city"], location.get("state")) if part)
    return f"{location['latitude']}, {location['longitude']}"


def place_words(location):
    if "pin" in location:
        return f"PIN {location['pin']}"
    if "city" in location:
        return ", ".join(part for part in (location["city"], location.get("state")) if part)
    return f"{location['latitude']:.4f}, {location['longitude']:.4f}"


def _distance(km, approximate):
    # When the starting point is approximate the screen says so once, in approximate_note.
    if km < 0.1:
        return "Less than 100 m away, in a straight line."
    return (f"About {km:.0f} km" if km >= 10 else f"About {km:.1f} km") + " away, in a straight line."


def _card(card, approximate):
    where = card.get("location") or {}
    return {
        "facility_id": card["facility_id"],
        "name": card["name"],
        "place": ", ".join(str(part) for part in (where.get("city"), where.get("state"), where.get("pin")) if part),
        "distance_km": card["distance_km"],
        "distance": _distance(card["distance_km"], approximate),
        "excerpt": card["evidence_excerpt"],
        "field": FIELDS.get(card["evidence_field"], card["evidence_field"]),
        "strength": card["evidence_strength"],
        "sources": list(card.get("record_source_urls") or []),
        "availability": card.get("availability"),
    }


def present(response, service, location, radius_km):
    """Everything the screen shows for one response."""
    status = response["status"]
    phrase = SERVICE_PHRASE.get(service, service)
    approximate = bool(response.get("approximate_location"))
    direct = [_card(card, approximate) for card in response.get("direct_results", [])]
    leads = [_card(card, approximate) for card in response.get("indirect_leads", [])]
    view = {
        "status": status,
        "request_line": f"{SERVICES.get(service, service)} near {place_words(location)}, within {radius_km} km.",
        "top": direct[0] if direct else None,
        "backups": direct[1:],
        "leads": leads,
        "choices": list(response.get("location_choices", [])),
        "why": None, "caveat": None, "next_step": None,
        "approximate_note": ("Distances are measured from the middle of the facilities recorded in that "
                             "place, so they are approximate.") if approximate and (direct or leads) else None,
    }
    if status == "withheld":
        found = phrase if response.get("evidence") == "direct" else f"something related to {phrase}"
        view["headline"] = "No facility is recommended from the real records yet."
        view["subline"] = (f"Records within {radius_km} km mention {found}, but none has been reviewed and "
                           "approved as a place to send a patient.")
        view["next_step"] = ("Until the service and the campus have been checked for these records, this "
                             "screen names no facility.")
    elif status == "ok":
        top = direct[0]
        view["headline"] = f"Send the patient to {top['name']}."
        view["subline"] = top["distance"]
        view["why"] = (f"It is the nearest facility within {radius_km} km whose record directly says it offers "
                       f"{phrase}." if len(direct) > 1 else
                       f"It is the only facility within {radius_km} km whose record directly says it offers {phrase}.")
        if top["availability"] == "unknown":
            view["caveat"] = ("This comes from the facility's record, which nobody has checked. Phone to confirm "
                              "the service and a free place before the patient travels.")
    elif status == "needs_confirmation":
        view["headline"] = f"No facility within {radius_km} km clearly offers {phrase}."
        view["subline"] = ("One record mentions something related." if len(leads) == 1 else
                           f"{len(leads)} records mention something related.") + " Phone before sending anyone."
        view["next_step"] = "You can also search a wider distance."
    elif status == "no_match":
        view["headline"] = f"No facility within {radius_km} km has a record of {phrase}."
        view["subline"] = "Nothing is recommended."
        view["next_step"] = ("Search a wider distance." if radius_km < RADII[-1]
                             else "Try a nearby larger town, or phone the district hospital.")
    elif status == "ambiguous_location":
        view["headline"] = "More than one place has that name."
        view["subline"] = ("Type the state as well and search again." if response.get("withheld")
                           else "Choose the one you mean.")
    elif status == "unavailable":
        view["headline"] = "The facility records cannot be reached right now."
        view["subline"] = response.get("message") or "Try again shortly."
    else:  # invalid_input, unresolved_location, or a status this screen does not know
        view["headline"] = ("That location cannot be used." if status == "invalid_input"
                            else "That place could not be located." if status == "unresolved_location"
                            else "The search did not return an answer.")
        view["subline"] = response.get("message") or "Check the location and search again."
    return view


def referral_note(view, synthetic):
    """Plain text a health worker can copy or save. Recommends nothing unless the search did."""
    lines = ["Referral note" + (" (demonstration data, invented facilities)" if synthetic else ""),
             "Request: " + view["request_line"]]
    if view["status"] == "ok":
        top = view["top"]
        lines.append(f"Send to: {top['name']}" + (f", {top['place']}" if top["place"] else ""))
        lines.append("Distance: " + top["distance"])
        lines.append(f"Its record says ({top['field']}): \"{top['excerpt']}\"")
        lines += ["Record source: " + url for url in top["sources"]]
        if view["backups"]:
            lines.append("If it cannot take the patient: " + "; then ".join(
                f"{card['name']} ({card['distance_km']:.1f} km)" for card in view["backups"]))
        if view["caveat"]:
            lines.append("Before travelling: " + view["caveat"])
    elif view["status"] == "needs_confirmation":
        lines.append(view["headline"])
        lines.append("Phone first: " + "; ".join(
            f"{card['name']} ({card['distance_km']:.1f} km), record says \"{card['excerpt']}\"" for card in view["leads"]))
    else:
        lines += [view["headline"], view["subline"]]
    return "\n".join(lines)
