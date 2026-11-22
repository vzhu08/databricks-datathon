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
import finding_provenance as provenance  # noqa: E402
import national_directory  # noqa: E402
import patient_ui  # noqa: E402
import storm_page  # noqa: E402
from data_access import search_warehouse  # noqa: E402
from ranking import search_facilities  # noqa: E402

# Kept inside app/ so a deployment of this folder alone still has its demonstration facilities.
# tests/find_care checks it is the same file as contracts/fixtures/search.json.
FIXTURE = HERE / "demo_facilities.json"
# Road time with traffic is offered only when the operator switched the provider on and supplied the
# verified attribution caption to show with every result. Without both, times are simulated and nothing
# can call out.
ATTRIBUTION_SETTING = "FIND_CARE_TRAFFIC_ATTRIBUTION"
ATTRIBUTION = str(os.environ.get(ATTRIBUTION_SETTING) or "").strip()
TRAFFIC_ON = os.environ.get("TOMTOM_ENABLED") == "true" and bool(ATTRIBUTION)
RECOMMEND, LOOKUP = "recommend", "lookup"
MODES = {RECOMMEND: "Recommend a campus", LOOKUP: "Look up the example records"}
DATA = words.data_mode(os.environ)
DEMO = DATA["mode"] == "demo"
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
        return search_facilities(service, location, facilities=_fixture_rows(), radius_km=radius_km)
    # Nothing but the withheld form of a warehouse response leaves this function.
    return words.withheld(search_warehouse(service, location, radius_km=radius_km))


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
    """Put a recommendation request into the form, then ask for it. Examples never use road time."""
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
    cited = f" Cited at: {safe(source['citation'])}." if source["citation"] else ""
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
    parts = [f'<div class="fc-for">{safe(capacity.request_line(check))}</div>',
             f'<div class="fc-answer" role="heading" aria-level="2">{safe(lines["headline"])}</div>']
    if lines["trip"]:
        parts.append(f'<div class="fc-trip">{safe(lines["trip"])}</div>')
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
    if check["travel_kind"] == capacity.TRAFFIC:
        # The operator-verified caption stays visible with every road-time result, a failed one included.
        parts.append(f'<div class="fc-quiet" data-attribution="traffic">{safe(ATTRIBUTION)}</div>')
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


def slip(view, stale, service=None, response=None):
    """The answer, drawn as the slip a health worker hands over. Real records never reach the facility parts.

    The evidence lines are drawn only for a current answer, for the service of the request it answers.
    """
    shown = None if stale else service
    top = view["top"] if DEMO and view["status"] == "ok" else None
    # On demonstration data this is a record lookup. It lists what a record says and sends nobody anywhere.
    headline = f"Nearest record that states the service: {top['name']}." if top else view["headline"]
    lookup = '<div class="fc-quiet">Record lookup. This is not a recommendation.</div>' if DEMO else ""
    parts = [f'<div class="fc-for">{safe(view["request_line"])}</div>',
             f'<div class="fc-answer fc-lookup" role="heading" aria-level="2">{safe(headline)}</div>{lookup}']
    if top:
        place = f"{top['place']}. " if top["place"] else ""
        parts.append(f'<div class="fc-trip">{safe(place + top["distance"])}</div>{warning(top)}')
        parts.append(f'<div class="fc-h">Why it is listed first</div><div class="fc-text">{safe(view["why"])}</div>')
        parts.append(f'<div class="fc-h">What its record says</div>{record(top)}')
        if shown:
            parts.append(f'<div class="fc-h">How well this is supported</div>{claims(top, shown, "direct_results", 0)}')
        if view["caveat"]:
            parts.append(f'<div class="fc-caveat">{safe(view["caveat"])}</div>')
    else:
        parts.append(f'<div class="fc-trip">{safe(view["subline"])}</div>')
        if DEMO and view["leads"]:
            parts.append("<ul>" + "".join(listed(lead, shown, "indirect_leads", index)
                                          for index, lead in enumerate(view["leads"])) + "</ul>")
        if not DEMO and shown and response:
            parts.append(withheld_line(response, shown))
        if view["next_step"]:
            parts.append(f'<div class="fc-text" style="margin-top:1rem">{safe(view["next_step"])}</div>')
    parts.append(not_told(view))
    if view["approximate_note"]:
        parts.append(f'<div class="fc-quiet">{safe(view["approximate_note"])}</div>')
    return f'<div class="fc-slip{" fc-old" if stale else ""}">{"".join(parts)}</div>'


st.set_page_config(page_title="Check symptoms and find care", layout="wide")
# The patient screen is the product and opens first. Find care below is the separate facility search.
VIEW = patient_ui.entry(st, "Find care (demonstration)" if DEMO else "Find care", storm_page.STORM)
if VIEW == patient_ui.PATIENT:
    patient_ui.render()
    st.stop()
if VIEW == storm_page.STORM:  # a simulated replay on its own: no patient visit, facility search or warehouse
    storm_page.render(st)
    st.stop()
st.markdown(STYLE, unsafe_allow_html=True)
st.title("Find care")
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
st.session_state.setdefault("where", "Jaipur, Rajasthan" if DEMO else "")
st.session_state.setdefault("radius", 50)
# Kept in step with the form even while a field is off screen, so an answer is always checked against
# the whole request and never against a default the reader did not choose.
for key, start in (("mode", RECOMMEND), ("urgency", "routine"), ("origin", "central"), ("needs_tool", False),
                   ("traffic", False)):
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
            st.checkbox("Use road time with traffic (ordinary car)", key="traffic")
            st.caption("Sends only the simulated starting point and the simulated campus points to "
                       f"{capacity.TRAFFIC_SOURCE}. No patient details are sent. One request per press. "
                       "If a road time fails, no simulated time is used in its place.")
        else:
            st.caption("Road time with traffic is switched off here. Drive minutes are simulated.")
        st.button("Find a facility", type="primary", use_container_width=True, on_click=submit, key="find")
        st.caption("Or start from an example")
        for label, ex_service, ex_urgency, ex_origin, ex_tool in CAPACITY_EXAMPLES:
            st.button(label, key="capacity-" + label, on_click=fill_recommendation,
                      args=(ex_service, ex_urgency, ex_origin, ex_tool))
    else:
        where = st.text_input("2. Where the patient is", key="where", placeholder="For example: Jaipur, Rajasthan")
        st.caption("A city or town (add the state after a comma), a six-digit PIN code, or coordinates.")
        radius = st.select_slider("Search within", options=list(words.RADII), key="radius",
                                  format_func=lambda km: f"{km} km")
        st.button("Search the example records" if DEMO else "Find a facility", type="primary",
                  use_container_width=True, on_click=submit, key="find")
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
        else:
            st.markdown(recommendation_slip(check), unsafe_allow_html=True)
            note = capacity.referral_note(check)
            if note:  # no recommendation, no destination to hand on
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
        with st.container(border=True):
            if DEMO:
                st.markdown("**The matching records appear here.**")
                st.write("You see which of six invented facility records mention the service, the words each "
                         "relied on and how well they are supported. Nothing here is a recommendation.")
            else:
                st.markdown("**The recommendation appears here.**")
                st.write("You are told whether nearby records mention the service. No facility is named until "
                         "the team has reviewed and approved destinations.")
    else:
        try:
            shown_now = {"service": service, "location": words.parse_location(where), "radius_km": radius}
        except ValueError:
            shown_now = None
        stale = shown_now != asked
        view = words.present(response, asked["service"], asked["location"], asked["radius_km"])
        if stale:
            st.markdown('<div class="fc-stale">You changed the request. The answer below is for the earlier one. '
                        "Press the button to update it.</div>", unsafe_allow_html=True)
        st.markdown(slip(view, stale, asked["service"], response), unsafe_allow_html=True)
        for choice in view["choices"] if DEMO and not stale else []:
            label = ", ".join(part for part in (choice.get("city"), choice.get("state")) if part)
            st.button(label, key="choice-" + label, on_click=fill,
                      args=(asked["service"], label, asked["radius_km"]))
        if DEMO and not stale and view["backups"]:
            st.subheader("Other records that state the service")
            st.caption("Listed nearest first. The order says nothing about quality.")
            st.markdown('<div class="fc-slip fc-more"><ol start="2">'
                        + "".join(listed(backup, asked["service"], "direct_results", index)
                                  for index, backup in enumerate(view["backups"], start=1)) + "</ol></div>",
                        unsafe_allow_html=True)
        # A record lookup hands nothing on: the only referral note is the recommendation's.
        st.subheader("How the lookup works" if DEMO else "How this was decided")
        if DEMO:
            st.markdown("\n".join(f"{number}. {plain(rule)}" for number, rule in enumerate(words.HOW, start=1)))
        else:
            st.write(words.HOW_WITHHELD)
        with st.expander("Technical details"):
            if DEMO:
                st.caption("The request and the unedited response from the search.")
                st.json({"request": asked, "response": response})
            else:
                st.caption("The request and the search status. The response itself is not shown for real records.")
                st.json({"request": asked, "data": "warehouse", "status": response["status"]})
