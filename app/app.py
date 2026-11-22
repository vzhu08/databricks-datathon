"""Find care: the Streamlit screen for Databricks Apps.

    streamlit run app/app.py

The data mode is explicit (find_care.data_mode) and named at the top of the screen:

* demonstration: the six invented facilities in demo_facilities.json, with the full recommendation,
  record text, backups and referral note.
* real records: search_warehouse on the prepared table. Every response passes through
  find_care.withheld first, so no facility is named, no record text or link is shown, and there is
  no backup, referral note, download or raw response, until reviewed destinations and display
  permission reach this screen through a verified interface.
* setup problem: a half-configured warehouse says what is missing and never shows invented data.

On demonstration data the screen has two clearly separate jobs. "Recommend a campus" is the one
actionable answer: the campus P's capacity model chose (app/find_capacity.py) is the only destination,
and the time, reasons, alternatives and referral note all come from that one result. "Look up the
example records" is the earlier six-hospital record search with its evidence lines. It directs nobody
anywhere and exports no note. The two use different invented places and are never joined.

The screen never ranks: it words what the model or the search returns.
"""
import html
import json
import os
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # so the same imports work from the repository root and from a deployed `app/`
    sys.path.append(str(HERE))

import find_capacity as capacity  # noqa: E402
import find_care as words  # noqa: E402
import find_decision as decisions  # noqa: E402
import finding_provenance as provenance  # noqa: E402
import national_directory  # noqa: E402
import patient_ui  # noqa: E402
from public_facility_search import search_public_facilities  # noqa: E402
import storm_page  # noqa: E402
from data_access import search_warehouse  # noqa: E402
from ranking import search_facilities  # noqa: E402
from ranking.individual import select_individual  # noqa: E402

# Kept inside app/ so a deployment of this folder alone still has its demonstration facilities.
# tests/find_care checks it is the same file as contracts/fixtures/search.json.
FIXTURE = HERE / "demo_facilities.json"
# Road time with traffic needs three operator settings: the provider switched on, the verified copyright
# caption (shown beside every road-time result) and the complete supplier notices (one press away on the
# same result). With all three it is the default travel-time source. Without any one, times are simulated
# and nothing can call out. The values are shown as escaped plain text and no key is ever read here.
CAPTION_SETTING, NOTICES_SETTING = "TOMTOM_COPYRIGHT_CAPTION", "TOMTOM_COPYRIGHT_NOTICES"
CAPTION = str(os.environ.get(CAPTION_SETTING) or "").strip()
NOTICES = str(os.environ.get(NOTICES_SETTING) or "").strip()
TRAFFIC_ON = os.environ.get("TOMTOM_ENABLED") == "true" and bool(CAPTION) and bool(NOTICES)
TRAVEL_SOURCES = {True: f"Road time with traffic ({capacity.TRAFFIC_SOURCE}, ordinary car)",
                  False: "Simulated minutes"}
RECOMMEND, LOOKUP = "recommend", "lookup"
MODES = {RECOMMEND: "Recommend a campus", LOOKUP: "Look up the example records"}
DATA = words.data_mode(os.environ)
DEMO = DATA["mode"] == "demo"
SEARCH_LABEL = "Search the example records" if DEMO else "Find a facility"  # the record lookup's button
START_WHERE = "Jaipur, Rajasthan" if DEMO else ""  # what the lookup's place field opens with
# label, care, the line typed into "Where", distance
EXAMPLES = [
    ("Dialysis near Jaipur, Rajasthan", "dialysis", "Jaipur, Rajasthan", 50),
    ("MRI scan near PIN 302001", "mri", "302001", 50),
    ("Dialysis within 2 km of PIN 302001", "dialysis", "302001", 2),
]
# Recommendation examples (#304) on the simulated Jaipur campuses: label, care, urgency, starting area, needs a tool
CAPACITY_EXAMPLES = [
    ("Routine dialysis: keeps a scarce station free", "dialysis", "routine", "central", False),
    ("Highest urgency dialysis: fastest free place", "dialysis", "highest", "central", False),
    ("Dialysis from the south: nearest campus capacity unknown", "dialysis", "routine", "south", False),
]
# Same paper, ink and caution colours as the offline Find care page, and the same referral slip.
STYLE = """
<style>
[data-testid="stMainBlockContainer"], .block-container { padding-top: 2.75rem; max-width: 78rem; }
.fc-lede { margin: -0.5rem 0 1rem; max-width: 64ch; font-size: 1.125rem; color: #14283b; }
.fc-mode { margin: 0 0 1.5rem; padding: 0.6rem 0.9rem; background: #ffffff; border: 1.5px solid #c3ced6;
  border-radius: 3px; color: #14283b; font-size: 1rem; }
.fc-slip { background: #ffffff; border: 1.5px solid #14283b; border-radius: 3px; padding: 0 1.75rem 1.5rem;
  margin-bottom: 1.25rem; color: #14283b; }
.fc-slip.fc-more { border-color: #c3ced6; padding-top: 0.75rem; }
.fc-slip div, .fc-slip li { font-size: 1.0625rem; line-height: 1.5; }
.fc-slip .fc-for { margin: 0 -1.75rem; padding: 0.7rem 1.75rem; border-bottom: 1.5px dashed #4b6274;
  color: #4b6274; font-size: 0.95rem; }
.fc-slip .fc-answer { margin-top: 1.25rem; font-size: 2.25rem; line-height: 1.1; font-weight: 700;
  letter-spacing: -0.015em; }
.fc-slip .fc-trip { margin-top: 0.6rem; font-size: 1.25rem; line-height: 1.3; font-weight: 600; }
.fc-slip .fc-h { margin-top: 1.4rem; font-weight: 700; }
.fc-slip .fc-text { max-width: 62ch; }
.fc-record { margin-top: 0.5rem; padding: 0.85rem 1.1rem; background: #edf1f3; border-radius: 3px; }
.fc-record .fc-quote { font-size: 1.125rem; line-height: 1.4; max-width: 56ch; }
.fc-record .fc-from, .fc-slip .fc-quiet { margin-top: 0.45rem; color: #4b6274; font-size: 0.95rem; }
.fc-record a { color: #14283b; }
.fc-slip .fc-caveat { margin-top: 1.25rem; padding: 0.75rem 1rem; background: #f6ebcd; color: #6b4a00;
  border: 1.5px solid #b97a06; border-radius: 3px; font-weight: 600; }
.fc-slip .fc-warning { margin-top: 0.6rem; padding: 0.5rem 0.8rem; background: #f6ebcd; color: #6b4a00;
  border: 1.5px solid #b97a06; border-radius: 3px; font-size: 1rem; }
.fc-slip ul.fc-limits { max-width: 62ch; }
.fc-slip ul.fc-limits li { margin-bottom: 0.35rem; }
.fc-slip ol, .fc-slip ul { margin: 0.5rem 0 0; padding-left: 1.4rem; }
.fc-slip li { margin-bottom: 0.9rem; }
.fc-stale { margin: 0 0 0.75rem; padding: 0.6rem 0.9rem; border: 1.5px solid #14283b; border-radius: 3px;
  background: #ffffff; color: #14283b; font-weight: 600; }
.fc-old { opacity: 0.55; }
.fc-slip .fc-answer.fc-lookup { font-size: 1.5rem; line-height: 1.25; }
.fc-emergency { margin: 0.25rem 0 0.75rem; padding: 0.5rem 0.8rem; border-left: 4px solid #b3261e;
  background: #fbeceb; color: #5c1410; font-weight: 600; }
.fc-claims { margin-top: 0.75rem; padding: 0.7rem 1rem; border-left: 4px solid #4b6274; background: #f7f9fa; }
.fc-claim { margin: 0.2rem 0; }
.fc-claim strong { font-weight: 700; }
.fc-claims details { margin-top: 0.5rem; }
.fc-claims summary { cursor: pointer; font-weight: 600; color: #14283b; }
.fc-claims ul.fc-sources { margin-top: 0.4rem; }
.fc-claims ul.fc-sources li { margin-bottom: 0.5rem; font-size: 0.98rem; }
.fc-claims .fc-next { color: #4b6274; font-size: 0.95rem; }
@media (max-width: 640px) {
  .fc-slip { padding: 0 1rem 1.25rem; }
  .fc-slip .fc-for { margin: 0 -1rem; padding: 0.7rem 1rem; }
  .fc-slip .fc-answer { font-size: 1.75rem; }
}
</style>
"""


@st.cache_data
def _fixture_rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["facilities"]


def run_search(service, location, radius_km):
    if DEMO:
        response = search_facilities(service, location, facilities=_fixture_rows(), radius_km=radius_km)
        if response.get("status") == "unresolved_location":  # say why Mumbai or Delhi fails here
            response = {**response, "message": demo_places_note()}
        return response
    # Nothing but the withheld form of a warehouse response leaves this function.
    return words.withheld(search_warehouse(service, location, radius_km=radius_km))


def demo_places_note():
    """Why a real town fails on the demonstration: it only knows the places its invented facilities name."""
    places = sorted({f"{row['city']}, {row['state']} (PIN {row['pin']})" for row in _fixture_rows()})
    return ("The demonstration can only find the places its six invented facilities are recorded in: "
            + " and ".join(places) + ". Type one of those, or coordinates.")


def plain(text):
    """Record text is shown as written, never interpreted as Markdown or HTML."""
    out = str(text)
    for mark in "\\`*_{}[]()#+-.!|<>~$":
        out = out.replace(mark, "\\" + mark)
    return out


def safe(text):
    """Text placed inside the slip's HTML. Record text can never add markup."""
    return html.escape(str(text), quote=False)


def ask(service, location, radius_km):
    try:
        response = run_search(service, location, radius_km)
    except ValueError as error:  # the search rejects malformed input with a plain message
        response = {"status": "invalid_input", "direct_results": [], "indirect_leads": [], "location_choices": [],
                    "approximate_location": False, "message": str(error)}
    st.session_state["asked"] = {"service": service, "location": location, "radius_km": radius_km}
    st.session_state["response"] = response


def _travel():
    from travel import hosted  # imported only when the operator has switched road time on
    return hosted


def mode():
    """Which of the two jobs the form is doing. Real records only ever get the record search."""
    return st.session_state.get("mode", RECOMMEND) if DEMO else LOOKUP


def recommend():
    """The one place a recommendation, and so any road-time request, can start: an explicit press.

    The earlier result is dropped first, so a failure can never leave an old destination on the screen.
    """
    for key in ("capacity", "asked", "response", "problem"):
        st.session_state.pop(key, None)
    traffic = TRAFFIC_ON and bool(st.session_state.get("traffic"))
    st.session_state["capacity"] = capacity.run(
        st.session_state["service"], st.session_state.get("urgency", "routine"), st.session_state.get("origin"),
        st.session_state.get("needs_tool", False), traffic, travel=_travel() if traffic else None)


def submit():
    """Answer what the form shows now. Runs before the screen is drawn again."""
    if mode() == RECOMMEND:
        return recommend()
    st.session_state.pop("capacity", None)
    try:
        location = words.parse_location(st.session_state.get("where", ""))
    except ValueError as error:
        st.session_state["problem"] = str(error)
        st.session_state.pop("asked", None)
        st.session_state.pop("response", None)
        return
    st.session_state.pop("problem", None)
    ask(st.session_state["service"], location, st.session_state["radius"])


def fill(service, where, radius_km):
    """Put a record lookup into the form, so the form always shows what the answer is for, then search."""
    st.session_state.update(service=service, where=where, radius=radius_km, mode=LOOKUP)
    submit()


def fill_recommendation(service, urgency, origin, needs_tool):
    """Put a recommendation request into the form, then ask for it.

    Examples always use simulated minutes, and say so, so they send no road-time request and give the
    same answer on any deployment.
    """
    st.session_state.update(service=service, urgency=urgency, origin=origin, needs_tool=needs_tool,
                            traffic=False, mode=RECOMMEND)
    submit()


def record(card):
    """A facility's cited record: its words and the field they came from, which is the source of the claim.

    A record address is a reference to the whole record, shown as text. It is never a link and never
    called the source: the demonstration addresses do not resolve and prove nothing about the statement.
    """
    related = "" if card["strength"] == "direct" else " It mentions a related specialty, not the service itself."
    reference = (f" {words.RECORD_REFERENCE}: " + ", ".join(safe(url) for url in card["sources"]) + "."
                 if card["sources"] else " This record lists no record reference.")
    return (f'<div class="fc-record"><div class="fc-quote">“{safe(card["excerpt"])}”</div>'
            f'<div class="fc-from">Source of this statement: the {safe(card["field"])} field of this facility\'s '
            f"record.{related}{reference}</div></div>")


def warning(card):
    """The location-warning badge for one facility. Empty until a search supplies a reviewed warning."""
    if not card.get("location_warning"):
        return ""
    return f'<div class="fc-warning"><strong>Check the address.</strong> {safe(card["location_warning"])}</div>'


def source_item(source):
    """One source behind a claim: what it supports, publisher, origin, field, scope, date and any reference."""
    reference = (f" {words.RECORD_REFERENCE}: {safe(source['reference'])}. {safe(words.RECORD_LINK_NOTE)}"
                 if source["reference"] else "")
    cited = (f" Cited at: {safe(source['citation'])}. {safe(words.citation_scope_note(source['citation_scope']))}"
             if source["citation"] else "")
    return (f"<li><strong>{safe(source['role'])}:</strong> {safe(source['fact'])}<br>"
            f"Publisher: {safe(source['publisher'])}. Origin: {safe(source['origin'])}. "
            f"Where: {safe(source['field'])}. Scope: {safe(source['scope'])} "
            f"Evidence date: {safe(source['date'])}.{cited}{reference}</li>")


def finding(response, service, group, index):
    """B's mapped finding for one card of one response, or None. Never built from another request."""
    if not DEMO or not response or response.get("withheld"):
        return None
    mapped = provenance.project_find_care(response, service, mode="demo")
    return next((item for item in mapped["findings"]
                 if (item["result_group"], item["index"]) == (group, index)), None)


def claims(card, service, group, index):
    """The location and service lines for one card (#302), then the sources behind them on request."""
    mapped = finding(st.session_state.get("response"), service, group, index)
    if not mapped:
        return ""
    found = words.claim_view(mapped, service, card["place"])
    lines, sources = [], []
    for claim in (found["location"], found["service"]):
        lines.append(f'<div class="fc-claim"><strong>{safe(claim["label"])}</strong> · {safe(claim["line"])}</div>')
        if claim["review"]:
            lines.append(f'<div class="fc-claim">{safe(claim["review"])}</div>')
        sources += [source_item(source) for source in claim["sources"]]
        sources.append(f'<li class="fc-next">{safe(claim["label"])}: {safe(claim["counts"])}. Next check: '
                       f'{safe(claim["missing_check"])}</li>')
    return (f'<div class="fc-claims" data-claims="{group}-{index}">{"".join(lines)}'
            '<details><summary>Why this finding?</summary><ul class="fc-sources">'
            + "".join(sources) + "</ul></details></div>")


def decide(response, service):
    """The individual decision for one stored response and the service it was asked for (#330).

    Demonstration cards go to the selector with their own two claims, joined on (result_group, index)
    inside this one response. Real records pass only the mapper's cleared summary: no row, name or key.
    """
    if not response:
        return None
    if DEMO:
        if not (response.get("direct_results") or response.get("indirect_leads")):
            return None  # nothing was found: the search's own words say which input to change
        mapped = provenance.project_find_care(response, service, mode="demo")
        return select_individual(service, decisions.card_candidates(response, mapped["findings"]))
    mapped = provenance.project_find_care(response, service, mode="warehouse")
    return select_individual(service, [], withheld_summary=mapped["summary"])


def positions(view):
    """Where each demonstration card sits in its response: facility key to (result_group, index, card)."""
    direct = ([view["top"]] if view["top"] else []) + list(view["backups"])
    found = {card["facility_id"]: ("direct_results", index, card) for index, card in enumerate(direct)}
    found.update({card["facility_id"]: ("indirect_leads", index, card) for index, card in enumerate(view["leads"])
                  if card["facility_id"] not in found})
    return found


def note_evidence(card, service, group, index):
    """The lead's own evidence lines for the call script: the same claims the screen shows, as plain text."""
    mapped = finding(st.session_state.get("response"), service, group, index)
    if not mapped:
        return []
    found, lines, references = words.claim_view(mapped, service, card["place"]), [], []
    for claim in (found["location"], found["service"]):
        lines.append(f"{claim['label']} evidence: {claim['line']} ({claim['counts']}.)")
        references += [source["reference"] for source in claim["sources"] if source["reference"]]
    for source in found["location"]["sources"]:
        if source["citation"]:
            lines.append(f"Location citation: {source['citation']}. {words.citation_scope_note(source['citation_scope'])}")
    for reference in dict.fromkeys(references):
        lines.append(f"{words.RECORD_REFERENCE}: {reference} ({words.RECORD_LINK_NOTE})")
    return lines


def lead_block(found, name_in_heading=False):
    """A lead to verify, or the real-records next step: what is missing and the one allowed next action."""
    parts = []
    if found["lead"]:
        name = ("" if name_in_heading else '<div class="fc-h">Closest lead to verify</div>')
        label = (safe(found["label"]) if name_in_heading else
                 f'<strong>{safe(found["lead"]["name"])}</strong> · {safe(found["label"])}')
        parts.append(f'{name}<div class="fc-text">{label}. {safe(found["lead"]["reason"] or "")}</div>')
        missing = found["lead"]["missing"]
    else:
        if found["status"] == "withheld":
            parts.append(f'<div class="fc-text" style="margin-top:1rem"><strong>{safe(found["headline"])}'
                         "</strong></div>")
        missing = found["missing"]
    if missing:
        parts.append('<div class="fc-h">Not known yet</div>' + bullets(missing))
    if found["next_action"]:
        worker = f' {decisions.WORKER_CHECK}' if found["status"] == "withheld" else ""
        parts.append(f'<div class="fc-h">Next step</div><div class="fc-text">{safe(found["next_action"] + worker)}'
                     "</div>")
    return f'<div data-decision="{safe(found["status"])}">{"".join(parts)}</div>'


def campus_lead(found):
    """The fallback on a recommendation that assigns nobody (#330): the best supported campus as a lead to check.

    It is drawn from the same campuses and the same evidence the model read for this request. It is never
    worded as a destination, and its free places and travel time are shown at their own status.
    """
    lead = found["lead"]
    headline = (found["headline"] if found["status"] == "provisional" else
                f"Closest lead to verify: {lead['name']}.")
    parts = [f'<div class="fc-answer fc-lookup" role="heading" aria-level="2">{safe(headline)}</div>',
             f'<div class="fc-quiet" data-decision="{safe(found["status"])}">{safe(found["label"])}. A lead to '
             "check by phone. This is not a referral, and nothing is reserved.</div>",
             f'<div class="fc-h">Why this lead comes first</div><div class="fc-text">{safe(lead["reason"] or "")} '
             f"{safe(decisions.ORDER)}</div>",
             '<div class="fc-h">What its record says</div><div class="fc-claims">'
             + "".join(f'<div class="fc-claim">{safe(line)}</div>'
                       for line in lead["says"] + [lead["date"] + " " + lead["origins"], lead["citation"]])
             + "</div>",
             '<div class="fc-h">Not known yet</div>' + bullets(lead["missing"])
             + f'<div class="fc-text">{safe(lead["availability"])} {safe(lead["travel"])}</div>']
    if found["next_action"]:
        parts.append(f'<div class="fc-h">Next step</div><div class="fc-text">{safe(found["next_action"])}</div>')
    if found["others"]:
        parts.append('<div class="fc-h">Other campuses with a record for this service</div>' + bullets(
            [f'{other["name"]} · {other["label"]}. {other["reason"] or ""} {other["availability"]}'
             for other in found["others"]]))
    return f'<div class="fc-slip fc-more" data-fallback="campus">{"".join(parts)}</div>'


def listed(card, service=None, group=None, index=None):
    place = f"{safe(card['place'])}. " if card["place"] else ""
    evidence = claims(card, service, group, index) if service else ""
    return (f"<li><strong>{safe(card['name'])}</strong><br>{place}{safe(card['distance'])}{warning(card)}"
            f"{record(card)}{evidence}</li>")


def not_told(view):
    """What the answer does not tell the reader. Fixed wording, so it is shown for real records too."""
    if not view["limits"]:
        return ""
    return ('<div class="fc-h">What this does not tell you</div><ul class="fc-limits">'
            + "".join(f"<li>{safe(line)}</li>" for line in view["limits"]) + "</ul>")


def bullets(lines):
    return '<ul class="fc-limits">' + "".join(f"<li>{safe(line)}</li>" for line in lines) + "</ul>"


def recommendation_slip(check):
    """The recommendation: the one campus the capacity model chose, or plainly none. Nothing else is a destination."""
    lines = capacity.explain(check)
    traffic = check["travel_kind"] == capacity.TRAFFIC
    parts = [f'<div class="fc-for">{safe(capacity.request_line(check))}</div>',
             f'<div class="fc-answer" role="heading" aria-level="2">{safe(lines["headline"])}</div>']
    if check["result"]["status"] == "emergency":
        return f'<div class="fc-slip">{"".join(parts)}</div>'
    if lines["trip"]:
        parts.append(f'<div class="fc-trip">{safe(lines["trip"])}</div>')
    if traffic:
        # The operator-verified caption sits beside every road-time result, a failed or partial one included.
        parts.append(f'<div class="fc-quiet" data-attribution="traffic">{safe(CAPTION)}</div>')
    if lines["why"]:
        title = "Why this campus" if lines["destination"] else "Why"
        parts.append(f'<div class="fc-h">{title}</div><div class="fc-text">{safe(lines["why"])}</div>')
    if lines["fastest"]:
        parts.append(f'<div class="fc-text" style="margin-top:0.5rem">{safe(lines["fastest"])}</div>')
    if lines["uncertain"]:
        parts.append(f'<div class="fc-caveat">{safe(lines["uncertain"])}</div>')
    if lines["evidence"]:
        parts.append('<div class="fc-h">How well this is supported</div><div class="fc-claims">'
                     + "".join(f'<div class="fc-claim">{safe(line)}</div>' for line in lines["evidence"]) + "</div>")
    if lines["alternatives"]:
        parts.append(f'<div class="fc-h">If {safe(lines["destination"])} cannot take the patient</div>'
                     '<div class="fc-text">Others with a free staffed place inside the travel limit, fastest first: '
                     f'{safe("; ".join(lines["alternatives"]))}. The order says nothing about quality.</div>')
    if lines["excluded"] or lines["travel_failures"]:
        parts.append('<div class="fc-h">Not recommended</div>' + bullets(lines["excluded"] + lines["travel_failures"]))
    if lines["limits"]:
        parts.append('<div class="fc-h">What this does not tell you</div>' + bullets(lines["limits"]))
    parts.append(f'<div class="fc-quiet">Travel time: {safe(lines["time_label"])}</div>')
    if traffic:
        parts.append('<details data-notices="traffic"><summary>Map data copyright notices</summary>'
                     f'<div class="fc-quiet" style="white-space:pre-wrap">{safe(NOTICES)}</div></details>')
    return f'<div class="fc-slip">{"".join(parts)}</div>'


def withheld_line(response, service):
    """The result-level evidence summary for real records. Names no facility and lists no source."""
    mapped = provenance.project_find_care(response, service, mode="warehouse")
    summary = words.withheld_summary(mapped["summary"], service)
    if not summary:
        return ""
    return (f'<div class="fc-claims"><div class="fc-claim"><strong>{safe(summary["line"])}</strong></div>'
            f'<div class="fc-claim">{safe(summary["detail"])}</div>'
            f'<div class="fc-next">Next check: {safe(summary["missing_check"])}</div></div>')


def slip(view, stale, service=None, response=None, found=None):
    """The answer, drawn as the slip a health worker hands over. Real records never reach the facility parts.

    `found` is the worded individual decision for this same response (#330). The evidence lines are drawn
    only for a current answer, for the service of the request it answers.
    """
    shown = None if stale else service
    selected = positions(view).get(found["lead"]["key"]) if DEMO and found and found["lead"] else None
    provisional = bool(selected and found["status"] == "provisional")
    use_decision = provisional or (DEMO and view["status"] == "ok")
    headline = (found["headline"] if found else "No usable evidence for this request.") if use_decision else view["headline"]
    tag = ""
    if DEMO:
        tag = ('<div class="fc-quiet" data-decision="provisional">'
               f'{safe(found["label"])}. A lead to check by phone. This is not a referral or a recommendation, '
               "and nothing is reserved.</div>" if provisional else
               '<div class="fc-quiet">Record lookup. This is not a recommendation.</div>')
    parts = [f'<div class="fc-for">{safe(view["request_line"])}</div>',
             f'<div class="fc-answer fc-lookup" role="heading" aria-level="2">{safe(headline)}</div>{tag}']
    limits = view["limits"]
    if provisional:
        group, index, top = selected
        place = f"{top['place']}. " if top["place"] else ""
        parts.append(f'<div class="fc-trip">{safe(place + top["distance"])}</div>{warning(top)}')
        why = f'{found["lead"]["reason"]} {decisions.ORDER}'
        parts.append(f'<div class="fc-h">Why this lead comes first</div><div class="fc-text">{safe(why)}</div>')
        parts.append(f'<div class="fc-h">What its record says</div>{record(top)}')
        parts.append(f'<div class="fc-text">{safe(found["lead"]["date"])} {safe(found["lead"]["origins"])}</div>')
        if shown:
            parts.append(f'<div class="fc-h">How well this is supported</div>{claims(top, shown, group, index)}')
            parts.append('<div class="fc-h">Not known yet</div>' + bullets(found["lead"]["missing"])
                         + f'<div class="fc-text">{safe(found["lead"]["availability"])} '
                         f'{safe(found["lead"]["travel"])}</div>')
            parts.append(f'<div class="fc-h">Next step</div><div class="fc-text">{safe(found["next_action"])}</div>')
        limits = [words.STRAIGHT_LINE]
    elif use_decision:
        limits = []
        if shown and selected:
            group, index, card = selected
            parts.append(f'<div class="fc-h">How well this is supported</div>{claims(card, shown, group, index)}')
        if found and not stale:
            parts.append(lead_block(found, name_in_heading=True))
    else:
        parts.append(f'<div class="fc-trip">{safe(view["subline"])}</div>')
        if DEMO and view["leads"]:
            parts.append("<ul>" + "".join(listed(lead, shown, "indirect_leads", index)
                                          for index, lead in enumerate(view["leads"])) + "</ul>")
        if not DEMO and shown and response:
            parts.append(withheld_line(response, shown))
        if view["next_step"]:
            parts.append(f'<div class="fc-text" style="margin-top:1rem">{safe(view["next_step"])}</div>')
        if found and not stale:
            parts.append(lead_block(found))
    parts.append(not_told({**view, "limits": limits}))
    if view["approximate_note"] and (provisional or not use_decision):
        parts.append(f'<div class="fc-quiet">{safe(view["approximate_note"])}</div>')
    return f'<div class="fc-slip{" fc-old" if stale else ""}">{"".join(parts)}</div>'


st.set_page_config(page_title="Check symptoms and find care", layout="wide")
# Streamlit draws captions as the text colour at 60% opacity, which is 3.97:1 on this paper. Slate at full
# opacity is 5.5:1 and passes the 4.5:1 minimum for small text. Applied here so all three screens get it.
st.markdown('<style>[data-testid="stCaptionContainer"] { color: #4b6274; opacity: 1; }</style>',
            unsafe_allow_html=True)
# The patient screen is the product and opens first. Find care below is the separate facility search.
VIEW = patient_ui.entry(st, "Find care", storm_page.STORM)
if VIEW == patient_ui.PATIENT:
    patient_ui.render()
    st.stop()
if VIEW == storm_page.STORM:  # a simulated replay on its own: no patient visit, facility search or warehouse
    storm_page.render(st)
    st.stop()
st.markdown(STYLE, unsafe_allow_html=True)
st.title("Find care")
lookup_modes = ["Public facility evidence"]
if DEMO:
    lookup_modes.append("Simulated scenarios")
elif DATA["mode"] in ("warehouse", "setup"):
    lookup_modes.append("Private warehouse lookup")
lookup_mode = st.radio("Find care mode", lookup_modes, horizontal=True, key="lookup_source")
if lookup_mode == "Public facility evidence":
    st.caption("Search the reviewed public-source collection by city and service. Coverage is limited.")
    # The widget's max_chars silently rejects an over-limit paste, leaving the previous query in place.
    limit = 120
    hint = f"Enter up to {limit} characters."
    place = st.text_input("City", value="Pune", help=hint)
    service = st.text_input("Service", value="maintenance haemodialysis", help=hint)
    submitted = st.button("Search public sources", type="primary")
    over_limit = [label for label, value in (("City", place), ("Service", service)) if len(value) > limit]
    if submitted and over_limit:
        st.warning(f"Shorten {' and '.join(over_limit)} to {limit} characters or fewer and search again.")
    elif submitted:
        try:
            missing = [f"**{label}**" for label, value in (("City", place), ("Service", service))
                       if not value.strip()]
            claims = [] if missing else search_public_facilities(place=place, service=service)
        except (OSError, ValueError):
            st.error("Public facility evidence is currently unavailable.")
        else:
            if missing:
                st.warning(f"Fill in {' and '.join(missing)}, then select **Search public sources**.")
            elif not claims:
                st.info("This collection has no reviewed public claim for that city and service. "
                        "For a covered example, enter **Pune** in **City** and **dialysis** or "
                        "**maintenance haemodialysis** in **Service**, then select **Search public sources** again.")
            for claim in claims:
                st.subheader(claim["operator"])
                st.write(claim["service"])
                st.caption(f"Operator-reported service · {claim['location_scope']}")
                st.link_button("Read the operator’s service page", claim["source_url"])
                st.write(f"Page checked {claim['checked_on']}. Treatment observation date unknown.")
                st.write("Current availability, staffing, appointment acceptance and exact entrance are unknown.")
                st.caption("Source scope: public operator evidence. No reviewed match to a Virtue Foundation record.")
                st.write(f"Call the published {claim['contact_label'].lower()} ({claim['contact_phone']}) "
                         "to confirm the service and current availability.")
    national_directory.render(st, HERE, False)
    st.stop()
if DATA["mode"] == "setup":
    st.error("Data: not available. This app is set to read the real facility records, but its setup is incomplete.")
    for problem in DATA["problems"]:
        st.markdown("- " + plain(problem))
    st.caption(f"To run on the invented demonstration facilities instead, set {words.DATA_SETTING} to demo.")
    st.stop()
if DEMO:
    st.markdown('<div class="fc-lede">Say what care a patient needs, how urgent it is and where they start. You '
                "get one campus to send them to, chosen by free staffed places and travel time.</div>"
                '<div class="fc-mode"><strong>Data: demonstration.</strong> This screen is running on invented '
                "campuses and six invented facilities, not the real records.</div>", unsafe_allow_html=True)
    if not FIXTURE.exists():
        st.error("The demonstration facilities (demo_facilities.json) are missing from this deployment.")
        st.stop()
else:
    st.markdown('<div class="fc-lede">Say what care a patient needs and where they are. You are told whether '
                "nearby facility records mention that care.</div>"
                '<div class="fc-mode"><strong>Data: real records.</strong> Searching the Virtue Foundation '
                "facility records. No facility is named or recommended here until the team has reviewed and "
                "approved destinations.</div>", unsafe_allow_html=True)

st.session_state.setdefault("service", "dialysis")
st.session_state.setdefault("where", START_WHERE)
st.session_state.setdefault("radius", 50)
# Kept in step with the form even while a field is off screen, so an answer is always checked against
# the whole request and never against a default the reader did not choose.
for key, start in (("mode", RECOMMEND), ("urgency", "routine"), ("origin", "central"), ("needs_tool", False),
                   ("traffic", bool(TRAFFIC_ON))):
    st.session_state.setdefault(key, start)
# Counts for the whole real directory, the same whatever is asked below. No search or patient state is read.
national_directory.render(st, HERE, DEMO)
left, right = st.columns([5, 9], gap="large")

with left:
    st.subheader("Your request")
    if DEMO:
        st.radio("What you want", list(MODES), format_func=MODES.get, key="mode", horizontal=True)
    MODE = mode()
    service = st.radio("1. Care needed", list(words.SERVICES), format_func=words.SERVICES.get, key="service",
                       horizontal=True)
    where, radius = st.session_state["where"], st.session_state["radius"]
    if MODE == RECOMMEND:
        st.radio("2. How urgent", list(capacity.URGENCIES), format_func=capacity.URGENCIES.get, key="urgency",
                 horizontal=True)
        st.markdown(f'<div class="fc-emergency">{safe(patient_ui.EMERGENCY)}</div>', unsafe_allow_html=True)
        st.radio("3. Where the patient starts (simulated Jaipur)", list(capacity.ORIGINS),
                 format_func=capacity.ORIGINS.get, key="origin", horizontal=True)
        st.caption(capacity.ORIGIN_NOTE)
        if service in capacity.TOOLS:
            st.checkbox(f"Needs {capacity.TOOLS[service][1]}", key="needs_tool")
        if TRAFFIC_ON:
            st.radio("4. Travel time", (True, False), format_func=TRAVEL_SOURCES.get, key="traffic")
            st.caption("Road time sends only the simulated starting point and the simulated campus points to "
                       f"{capacity.TRAFFIC_SOURCE}. No patient details are sent. One batch of requests per press "
                       "of Find a facility, and none when the page opens or redraws. If a road time fails, no "
                       "simulated or straight-line time is used in its place.")
        else:
            st.caption("Road time with traffic is switched off here. Drive minutes are simulated.")
        st.button("Find a facility", type="primary", use_container_width=True, on_click=submit, key="find")
        st.caption("Or start from an example. Examples always use simulated minutes and send no road-time "
                   "request." if TRAFFIC_ON else "Or start from an example")
        for label, ex_service, ex_urgency, ex_origin, ex_tool in CAPACITY_EXAMPLES:
            st.button(label, key="capacity-" + label, on_click=fill_recommendation,
                      args=(ex_service, ex_urgency, ex_origin, ex_tool))
    else:
        where = st.text_input("2. Where the patient is", key="where", placeholder="For example: Jaipur, Rajasthan")
        st.caption("A city or town (add the state after a comma), a six-digit PIN code, or coordinates.")
        radius = st.select_slider("Search within", options=list(words.RADII), key="radius",
                                  format_func=lambda km: f"{km} km")
        st.button(SEARCH_LABEL, type="primary", use_container_width=True, on_click=submit, key="find")
        if st.session_state.get("problem"):
            st.error(st.session_state["problem"])
        st.caption("Or start from an example")
        for label, ex_service, ex_where, ex_radius in EXAMPLES:
            st.button(label, key="example-" + label, on_click=fill, args=(ex_service, ex_where, ex_radius))

with right:
    response, asked = st.session_state.get("response"), st.session_state.get("asked")
    check = st.session_state.get("capacity")
    if MODE == RECOMMEND:
        now = {"service": service, "urgency": st.session_state["urgency"], "origin_id": st.session_state["origin"],
               "needs_tool": bool(st.session_state["needs_tool"]) and service in capacity.TOOLS,
               "traffic": TRAFFIC_ON and bool(st.session_state["traffic"])}
        if check and now != check["asked"]:
            # A changed request shows no destination at all, and an earlier road-time result is not kept.
            st.session_state.pop("capacity", None)
            check = None
            st.markdown('<div class="fc-stale">You changed the request, so the earlier recommendation was removed. '
                        "Press Find a facility for a new one.</div>", unsafe_allow_html=True)
        if not check:
            with st.container(border=True):
                st.markdown("**The recommendation appears here.**")
                st.write("You get one campus to send the patient to, how long the trip is, why it was chosen "
                         "over the others, and what nobody has confirmed. Press Find a facility, or start "
                         "from an example.")
        elif check["result"]["status"] == "emergency":
            st.markdown(recommendation_slip(check), unsafe_allow_html=True)
            st.stop()
        else:
            # The same selector decides every individual result (#330). Only its "assigned" is a referral. It
            # reads the campuses and evidence kept from this same request, so a fallback needs no second search.
            asked_service = check["asked"]["service"]
            invalid = check["result"]["reason"] == "invalid_request"
            candidates = [] if invalid else decisions.campus_candidates(check)
            assigned = select_individual(asked_service, candidates, allocation=check["result"])
            unsupported = check["result"]["status"] == "recommended" and assigned["status"] != "assigned"
            if unsupported:  # never show a destination the selector does not stand behind
                st.markdown(f'<div class="fc-slip"><div class="fc-for">{safe(capacity.request_line(check))}</div>'
                            '<div class="fc-answer" role="heading" aria-level="2">No campus is recommended.</div>'
                            f'<div class="fc-text">{safe(decisions.REASONS["unsupported_individual_assignment"])}'
                            "</div></div>", unsafe_allow_html=True)
            else:
                st.markdown(recommendation_slip(check), unsafe_allow_html=True)
            note = capacity.referral_note(check, CAPTION) if assigned["status"] == "assigned" else None
            fallback = decisions.explain(assigned, asked_service) if assigned["status"] != "assigned" and not invalid else None
            if fallback and fallback["lead"]:
                st.markdown(campus_lead(fallback), unsafe_allow_html=True)
                script = decisions.confirmation_note(assigned, asked_service, capacity.request_line(check), True)
                if script:
                    st.subheader("Confirmation call script")
                    st.caption("For checking the lead by phone. It is not a referral. Use the copy button on it, "
                               "or save it as a file.")
                    st.code(script, language=None, wrap_lines=True)
                    st.download_button("Save call script", script, file_name="confirmation-call-script.txt",
                                       mime="text/plain")
            elif fallback:
                st.markdown('<div class="fc-text" data-decision="fallback"><strong>Next step.</strong> No campus '
                            "has a record to check for this request. The record lookup lists what the six "
                            "invented example records say about this service. They are different invented "
                            "places from campuses A to F.</div>", unsafe_allow_html=True)
                st.button("Look up records that mention " + decisions.SERVICE_PHRASE[asked_service],
                          key="fallback", on_click=fill,
                          args=(asked_service, st.session_state["where"], st.session_state["radius"]))
            if note:  # no assignment, no destination to hand on
                st.subheader("Referral note")
                st.caption("Use the copy button on the note, or save it as a file.")
                st.code(note, language=None, wrap_lines=True)
                st.download_button("Save referral note", note, file_name="referral-note.txt", mime="text/plain")
            st.subheader("How this was decided")
            st.markdown("\n".join(f"{number}. {plain(rule)}" for number, rule in enumerate(capacity.HOW, start=1)))
            with st.expander("Technical details"):
                st.caption("The request, the travel observations and the unedited result from the capacity model.")
                st.json({"request": check["asked"], "travel_kind": check["travel_kind"],
                         "travel": check["travel_rows"], "result": check["result"]})
    elif not response:
        if where.strip() and where != START_WHERE and not st.session_state.get("problem"):
            # Enter in the field only keeps the text. Without this line a first search by Enter shows nothing.
            st.markdown(f'<div class="fc-stale">Nothing has been searched yet. Press {safe(SEARCH_LABEL)} to '
                        "search for the place you typed.</div>", unsafe_allow_html=True)
        with st.container(border=True):
            if DEMO:
                st.markdown("**The best supported lead appears here.**")
                st.write("You see which of six invented facility records mention the service, the words each "
                         "relied on, how well they are supported and what is still unknown, with a call script "
                         "for checking the first one. Nothing here is a referral or a recommendation. "
                         f"Press {SEARCH_LABEL}, or start from an example.")
            else:
                st.markdown("**The recommendation appears here.**")
                st.write("You are told whether nearby records mention the service. No facility is named until "
                         f"the team has reviewed and approved destinations. Press {SEARCH_LABEL} to search.")
    else:
        try:
            shown_now = {"service": service, "location": words.parse_location(where), "radius_km": radius}
        except ValueError:
            shown_now = None
        stale = shown_now != asked
        view = words.present(response, asked["service"], asked["location"], asked["radius_km"])
        # The decision is read from the stored response and the service it was asked for, never the form.
        decision = decide(response, asked["service"])
        found = decisions.explain(decision, asked["service"]) if decision else None
        if stale:
            st.markdown('<div class="fc-stale">You changed the request. The answer below is for the earlier one. '
                        "Press the button to update it.</div>", unsafe_allow_html=True)
        st.markdown(slip(view, stale, asked["service"], response, found), unsafe_allow_html=True)
        for choice in view["choices"] if DEMO and not stale else []:
            label = ", ".join(part for part in (choice.get("city"), choice.get("state")) if part)
            st.button(label, key="choice-" + label, on_click=fill,
                      args=(asked["service"], label, asked["radius_km"]))
        where_is = positions(view) if DEMO else {}
        chosen = where_is.get(found["lead"]["key"]) if DEMO and found and found["lead"] else None
        if chosen and not stale and found["note_kind"] == "confirmation":
            # A provisional lead is checked by phone. The script is never a referral and reserves nothing.
            script = decisions.confirmation_note(decision, asked["service"], view["request_line"], True,
                                                 note_evidence(chosen[2], asked["service"], chosen[0], chosen[1]))
            st.subheader("Confirmation call script")
            st.caption("For checking the lead by phone. It is not a referral. Use the copy button on it, or "
                       "save it as a file.")
            st.code(script, language=None, wrap_lines=True)
            st.download_button("Save call script", script, file_name="confirmation-call-script.txt",
                               mime="text/plain")
        others = [where_is[row["key"]] for row in (found["others"] if DEMO and found else [])
                  if row["next_action"] == decisions.NEXT_ACTIONS["confirmation_note"]
                  and row["key"] in where_is and where_is[row["key"]][0] == "direct_results"]
        if DEMO and not stale and view["status"] == "ok" and others:
            st.subheader("Other records that state the service")
            st.caption("Each is a provisional lead to confirm, in the same order as above. The order says "
                       "nothing about quality.")
            st.markdown('<div class="fc-slip fc-more"><ol start="2">'
                        + "".join(listed(card, asked["service"], group, index) for group, index, card in others)
                        + "</ol></div>", unsafe_allow_html=True)
        # Only an assignment from Recommend a campus is a referral. A lead here gets a call script at most.
        st.subheader("How this was decided")
        if DEMO:
            st.markdown("\n".join(f"{number}. {plain(rule)}"
                                  for number, rule in enumerate(words.HOW[1:3] + decisions.HOW, start=1)))
        else:
            st.write(words.HOW_WITHHELD)
        with st.expander("Technical details"):
            if DEMO:
                st.caption("The request and the unedited response from the search.")
                st.json({"request": asked, "response": response})
            else:
                st.caption("The request and the search status. The response itself is not shown for real records.")
                st.json({"request": asked, "data": "warehouse", "status": response["status"]})

# Below the search: how often outside sources back up what the real directory's records mention. Counts only.
# Imported here, beside its one use, so this stays clear of the imports other sections add at the top.
import capability_coverage  # noqa: E402

capability_coverage.render(st, HERE, DEMO)
