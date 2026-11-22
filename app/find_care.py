"""Words for the Find care screen: turns one search response into what a health worker reads.

Pure functions with no Streamlit or Databricks dependency. Nothing here searches, ranks or
filters. The order, the distances, the excerpts and the status are read from the response of
`search_warehouse` or `search_facilities` (docs/implementation/SEARCH_CONTRACT.md).
"""

SERVICES = {"dialysis": "Dialysis", "mri": "MRI scan", "trauma_care": "Trauma care"}
SERVICE_PHRASE = {"dialysis": "dialysis", "mri": "an MRI scan", "trauma_care": "trauma care"}
FIELDS = {"description": "description", "capabilities": "capabilities", "procedures": "procedures",
          "equipment": "equipment"}
RADII = (10, 25, 50, 100, 200)
HOW = (
    "Facilities whose records state the service directly come first, nearest first. "
    "Records that only mention something related, such as a kidney clinic for dialysis, are shown "
    "only when nothing states it directly, and are marked as needing confirmation. "
    "Mentions that say a service is planned, unavailable or referred elsewhere are left out. "
    "Distance is a straight line, not road time. Up to three facilities are shown."
)


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


def place_words(location):
    if "pin" in location:
        return f"PIN {location['pin']}"
    if "city" in location:
        return ", ".join(part for part in (location["city"], location.get("state")) if part)
    return f"{location['latitude']:.4f}, {location['longitude']:.4f}"


def _distance(km, approximate):
    text = f"About {km:.0f} km" if km >= 10 else f"About {km:.1f} km"
    return text + (" in a straight line from the middle of that place." if approximate
                   else " in a straight line.")


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
        "approximate_note": ("The place you entered was located from the facilities recorded there, so "
                             "distances are approximate.") if approximate and (direct or leads) else None,
    }
    if status == "ok":
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
        view["subline"] = "Choose the one you mean."
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
