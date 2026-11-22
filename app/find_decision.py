"""Words for one individual Find care decision (#330). No Streamlit dependency.

The decision is A's `ranking.individual.select_individual`: an assignment from the capacity allocator
when one is supported, otherwise the best supported candidate as a provisional lead to verify, an
identity or area lead, or a plain statement of what is missing. The claims on each candidate are B's
#315 objects, passed through unchanged. Nothing here ranks, scores or rebuilds provenance: this
module builds the candidate rows the screen already holds, and words the result.

Two rules every surface depends on:

* Only an `assigned` result is a referral. A provisional result gets a confirmation call script,
  which is never titled or worded as a referral or a reservation.
* "VF only" is said only when the candidate's `source_scope` is exactly `vf_only`, which Vincent's
  provenance classification sets. Demonstration rows say they are synthetic.
"""
try:
    from finding_provenance import SYNTHETIC, Observation, Review, summarize_claim
except ImportError:  # repository tests import the package
    from app.finding_provenance import SYNTHETIC, Observation, Review, summarize_claim

STATUSES = ("assigned", "provisional", "verification_lead", "no_usable_evidence", "withheld", "emergency")
SERVICE_PHRASE = {"dialysis": "dialysis", "mri": "an MRI scan", "trauma_care": "trauma care"}
SCOPES = {"synthetic": "Synthetic demo record", "vf_only": "VF only"}
AVAILABILITY = {"unknown": "Free staffed places: unknown.", "full": "Reported full, with no free staffed place.",
                "stale": "Free staffed places: last count is out of date.",
                "unavailable": "Free staffed places: could not be read.",
                "available": "A free staffed place was reported when checked."}
NEXT_ACTIONS = {
    "referral_note": "Hand over the referral note.",
    "confirmation_note": "Phone the facility with the confirmation call script before anyone travels.",
    "verify_identity": "Confirm which facility and branch this record is before relying on it.",
    "clarify_input": "Change the request and search again.",
    "request_clearance": "Ask the data owner to review and clear a named destination for this audience.",
    "emergency_guidance": "Call 112 now. Do not wait for this screen.",
}
MISSING = {
    "service_date": "the date the service statement applies to",
    "physical_branch": "which physical branch the statement is about",
    "staffed_capacity": "whether a staffed place is free",
    "travel_time": "the travel time by road",
    "independent_corroboration": "any independent source for the service",
    "entrance": "the building and entrance",
    "service_evidence": "any statement that the service is offered",
}
EMERGENCY = "If this could be an emergency, call 112 now. Do not wait for this screen."
WORKER_CHECK = ("Until then, do not send the patient on this result. Phone a facility through your usual referral "
                "contact and ask whether it provides the service onsite today and has a free place.")
# The selector's reason codes, as the reader is told them.
REASONS = {
    "reviewed_service": "Its record states the service, and that statement has been reviewed.",
    "reported_service": "Its record states the service. Nobody has confirmed the statement.",
    "identity_or_area_only": "Only who or where it is can be told from its record. Nothing there states the service.",
    "conflicting_service_evidence": "Its sources disagree about whether the service is offered.",
    "service_reported_absent": "A source says the service is not offered there, or that patients are sent elsewhere.",
    "availability_full": "It was reported full.",
    "availability_unavailable": "Whether it has a free place could not be read.",
    "conflicting_location_evidence": "Its sources disagree about which branch or place it is.",
    "missing_individual_evidence": "No record for this request states the service or identifies a facility or area.",
    "no_cleared_individual_projection": "No individual facility has been cleared to be named to this audience.",
    "unsupported_individual_assignment": "The capacity result could not be supported as an individual assignment.",
}
ORDER = ("Leads are put in order by what their records say about the service, then by how well that is "
         "supported, then by the most recent dated statement, then by straight-line distance. The order says "
         "nothing about quality.")
HOW = (
    "Each record found by the search is read as two separate claims: where the facility is, and whether it "
    "offers the service. Each claim keeps the words it rests on, the field they came from, how many "
    "independent origins support it and its date, or says unknown.",
    "A record that states the service is a provisional lead even when nobody has confirmed it. A record that "
    "only identifies a facility or area is a lead to verify, and says the service evidence is missing.",
    ORDER,
    "Nothing here is a referral. A referral needs a reviewed, dated service, a known free staffed place and a "
    "known travel time, which is what Recommend a campus checks. A provisional lead gets a confirmation call "
    "script, and its free places and road time stay unknown.",
)


def _plain(code):
    """A reason or missing-item code as words. Text that is already a sentence is kept as written."""
    text = str(code or "").strip()
    if text in MISSING:
        return MISSING[text]
    if text in REASONS:
        return REASONS[text]
    return text.replace("_", " ") if "_" in text or text.islower() else text


def card_candidates(response, findings):
    """Candidate rows for the demonstration cards of one search response, each with its own #315 claims.

    A card and its claims are joined on (result_group, index) inside this one response, as B's mapper
    documents. A card without a matching finding is passed with null claims, never with another card's.
    """
    claims = {(item["result_group"], item["index"]): item for item in findings or ()}
    rows = []
    for group in ("direct_results", "indirect_leads"):
        for index, card in enumerate(response.get(group) or ()):
            found = claims.get((group, index)) or {}
            where = card.get("location") or {}
            rows.append({
                "key": card["facility_id"], "name": card.get("name"),
                "area": ", ".join(str(part) for part in (where.get("city"), where.get("state"), where.get("pin")) if part)
                or None,
                "location": found.get("location"), "service": found.get("service"), "source_scope": "synthetic",
                "availability": card.get("availability") or "unknown", "travel": None,
                "distance_km": card.get("distance_km"),
            })
    return rows


def _availability(pools):
    """One scoped status for the staffed places that fit this request. Unknown is never read as free."""
    states = {("full" if pool.get("status") == "known" and not pool.get("free_slots") else
               "available" if pool.get("status") == "known" else
               "stale" if pool.get("status") == "stale" else "unknown") for pool in pools}
    for state in ("available", "stale", "unknown", "full"):
        if state in states:
            return state
    return "unknown"


def campus_candidates(check):
    """Candidate rows for the scenario campuses of one recommendation request (`find_capacity.run`).

    The evidence is the scenario's own record that the capacity model read for this same request: its
    reviewed service decision and date, its staffed-place status and the travel observation as it came
    back. Each row gets claims built by B's `summarize_claim`, so nothing is scored here. A failed or
    missing road time stays unknown: no straight-line or simulated value is put in its place.
    """
    service, phrase, rows = check["asked"]["service"], SERVICE_PHRASE.get(check["asked"]["service"]), []
    for campus in check.get("roster") or ():
        key, decision, pools = campus["facility_id"], campus["decision"], campus["pools"]
        if check["asked"]["needs_tool"] and not pools:
            continue  # it has no place with the equipment this patient needs, so it is not a lead for them
        scope = f"Campus {key} in the synthetic Jaipur storm scenario"
        cited = f"Synthetic Jaipur storm scenario, Campus {key} service record"
        location = summarize_claim(
            "location", scope, (Observation(SYNTHETIC, "The scenario places this campus at one simulated point.",
                                            scope, role="support", origin="synthetic_storm_fixture",
                                            field="scenario campus point"),),
            precision="identified_campus", missing_check="It is an invented campus with no real address.")
        observed, review = (), None
        if decision.get("status") in ("yes", "no"):
            runs = decision["status"] == "yes"
            observed = (Observation(
                SYNTHETIC, f"The scenario record marks {phrase} as {'running' if runs else 'not offered'} at this campus.",
                scope, role="support", match="exact", origin="synthetic_storm_fixture", independent=True,
                field="scenario service record", observed_on=decision.get("source_date"), citation=cited,
                citation_scope="record", assertion="onsite_delivery" if runs else "explicit_absence"),)
            if decision.get("source_date"):
                review = Review(scope, decision["source_date"], decision["status"])
        claim = summarize_claim("service", scope, observed, service=service, as_of=check.get("as_of"), review=review,
                                missing_check="Phone the campus to confirm the service runs today.")
        travel = (check.get("travel_rows") or {}).get(key) or {}
        rows.append({"key": key, "name": f"Campus {key}", "area": "simulated Jaipur", "location": location,
                     "service": claim, "source_scope": "synthetic", "availability": _availability(pools),
                     "travel": {k: travel.get(k) for k in ("status", "minutes", "source", "reason", "outcome",
                                                           "requested_at")} if travel else None,
                     "distance_km": None})
    return rows


def label(candidate):
    """The label shown with a lead. Says "VF only" exactly when the provenance classification established it.

    The selector's own label is kept. A demonstration row also says it is synthetic.
    """
    scope = candidate.get("source_scope")
    given = str(candidate.get("label") or "").strip()
    if given:
        # The selector writes "VF only" only for a row whose scope is exactly vf_only.
        return given + " · " + SCOPES["synthetic"] if scope == "synthetic" else given
    return "Provisional · " + SCOPES[scope] if scope in SCOPES else "Provisional · source scope unknown"


def _travel(candidate):
    travel = candidate.get("travel") or {}
    if travel.get("status") == "known" and travel.get("minutes") is not None:
        minutes = float(travel["minutes"])
        shown = f"{minutes:.0f}" if minutes.is_integer() else f"{minutes:.1f}"
        return f"Travel time: {shown} min ({travel.get('source') or 'source not stated'})."
    failed = travel.get("status") in ("unavailable", "stale")
    opening = "Road time could not be fetched." if failed else "Travel time by road: unknown."
    if candidate.get("distance_km") is not None:
        km = float(candidate["distance_km"])
        return f"{opening} About {km:.0f} km" + " away in a straight line." if km >= 10 else \
            f"{opening} About {km:.1f} km away in a straight line."
    return (opening + " No simulated or straight-line time is used in its place.") if failed else "Travel time: unknown."


def _says(claim):
    """What the record actually says about the service, with the field it came from."""
    lines = []
    for source in (claim or {}).get("sources") or ():
        if source.get("fact"):
            field = f" ({source['field']} field" + (f", {source['publisher']}" if source.get("publisher") else "") + ")"
            role = "" if source.get("role") == "support" else "Related, not the service itself: "
            lines.append(f"{role}“{source['fact']}”{field if source.get('field') else ''}")
    return lines


def lead(candidate, service):
    """One candidate as plain lines: who, what its record says, and what is not known."""
    claim = candidate.get("service") or {}
    origins = claim.get("independent_supporting_origins")
    support = [source for source in claim.get("sources") or () if source.get("role") == "support"]
    # The date of the statement itself. The claim's as_of is only the day it was assessed.
    dated = sorted(str(source["observed_on"]) for source in support if source.get("observed_on"))
    cited = list(dict.fromkeys(str(source["citation"]) for source in claim.get("sources") or ()
                               if source.get("citation")))
    return {
        "key": candidate.get("key"),
        "name": candidate.get("name") or "A facility that cannot be named here",
        "area": candidate.get("area") or "Area not shown",
        "label": label(candidate),
        "says": _says(claim) or [f"No statement about {SERVICE_PHRASE.get(service, service)} was supplied."],
        "origins": ("Independent sources for the service: unknown." if origins is None else
                    f"Independent sources for the service: {origins}."),
        "date": f"Service statement dated: {dated[-1] if dated else 'unknown'}.",
        "citation": ("Citation: " + "; ".join(cited) + ". It points to the whole record, not to this statement."
                     if cited else "Citation: none on the record."),
        "availability": AVAILABILITY.get(candidate.get("availability"), AVAILABILITY["unknown"]),
        "travel": _travel(candidate),
        "reason": _plain(candidate.get("reason")) if candidate.get("reason") else None,
        "missing": [_plain(item) for item in candidate.get("missing") or ()],
        "next_action": NEXT_ACTIONS.get(candidate.get("next_action")),
    }


def explain(decision, service):
    """Everything the screen shows for one decision. Reads only the decision it is given."""
    status = decision.get("status")
    phrase = SERVICE_PHRASE.get(service, service)
    view = {"status": status, "headline": None, "label": None, "lead": None, "others": [],
            "missing": [_plain(item) for item in decision.get("missing") or ()],
            "reason": _plain(decision.get("reason")) if decision.get("reason") else None,
            "next_action": NEXT_ACTIONS.get(decision.get("next_action")), "note_kind": None}
    chosen = decision.get("chosen")
    if status == "emergency":
        view["headline"] = EMERGENCY
        view["next_action"] = NEXT_ACTIONS["emergency_guidance"]
    elif status == "assigned":
        view["note_kind"] = "referral"  # the allocator's own result is worded by find_capacity
    elif status in ("provisional", "verification_lead") and chosen:
        view["lead"] = lead(chosen, service)
        view["label"] = view["lead"]["label"]
        view["others"] = [lead(row, service) for row in decision.get("candidates") or ()
                          if row.get("key") != chosen.get("key")]
        if status == "provisional":
            view["headline"] = f"Provisional lead: {view['lead']['name']}. Confirm before anyone travels."
            view["note_kind"] = "confirmation" if decision.get("next_action") == "confirmation_note" else None
        else:
            view["headline"] = (f"No record states {phrase}. Closest identifiable lead: {view['lead']['name']}.")
    elif status == "withheld":
        view["headline"] = "A lead exists in the real records, but no facility can be named here yet."
    else:
        view["status"] = "no_usable_evidence"
        view["headline"] = f"No usable evidence for {phrase} with this request."
    return view


def confirmation_note(decision, service, request_line, synthetic, evidence=()):
    """A call script for a provisional lead. None unless the decision asks for a confirmation note.

    It is a script for checking a claim. It never says referral, reservation or booked as a fact.
    `evidence` is the lead's own location and service lines and record references, as the screen shows them.
    """
    view = explain(decision, service)
    if view["note_kind"] != "confirmation":
        return None
    found, phrase = view["lead"], SERVICE_PHRASE.get(service, service)
    lines = ["Confirmation call script" + (" (demonstration data, invented facilities)" if synthetic else ""),
             "This is not a referral and nothing is reserved. It is a claim to check by phone.",
             "Request: " + request_line,
             f"Call: {found['name']}, {found['area']}",
             "Status: " + found["label"],
             "Its record says: " + " ".join(found["says"]),
             found["origins"] + " " + found["date"],
             found["citation"]]
    lines += list(evidence)
    if found["reason"]:
        lines.append("Why this lead: " + found["reason"])
    lines += [found["availability"] + " " + found["travel"],
              "Ask:",
              f"1. Do you provide {phrase} at this site today, yourselves, not by sending patients elsewhere?",
              "2. Which building and entrance should the patient come to?",
              "3. Is there a free staffed place for this patient, and until when?"]
    if found["missing"]:
        lines.append("Not known yet:")
        lines += ["- " + item for item in found["missing"]]
    if found["next_action"]:
        lines.append("Next step: " + found["next_action"])
    lines.append("Nobody should travel until the facility confirms. " + EMERGENCY)
    return "\n".join(lines)
