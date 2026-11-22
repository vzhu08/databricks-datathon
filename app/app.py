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

The screen never ranks: it words what the search returns (app/find_care.py).
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

import find_care as words  # noqa: E402
import patient_ui  # noqa: E402
import storm_page  # noqa: E402
from data_access import search_warehouse  # noqa: E402
from ranking import search_facilities  # noqa: E402

# Kept inside app/ so a deployment of this folder alone still has its demonstration facilities.
# tests/find_care checks it is the same file as contracts/fixtures/search.json.
FIXTURE = HERE / "demo_facilities.json"
DATA = words.data_mode(os.environ)
DEMO = DATA["mode"] == "demo"
# label, care, the line typed into "Where", distance
EXAMPLES = [
    ("Dialysis near Jaipur, Rajasthan", "dialysis", "Jaipur, Rajasthan", 50),
    ("MRI scan near PIN 302001", "mri", "302001", 50),
    ("Dialysis within 2 km of PIN 302001", "dialysis", "302001", 2),
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


def submit():
    """Search for what the form shows now. Runs before the screen is drawn again."""
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
    """Put a request into the form, so the form always shows what the answer is for, then search."""
    st.session_state.update(service=service, where=where, radius=radius_km)
    submit()


def record(card):
    """A facility's cited record: its words, the field they came from, and its sources."""
    links = ", ".join(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                      f"{safe(url.split('/')[2])}</a>" for url in card["sources"])
    related = "" if card["strength"] == "direct" else " It mentions something related, not the service itself."
    source = f"Source: {links}." if links else "This record lists no source link."
    return (f'<div class="fc-record"><div class="fc-quote">“{safe(card["excerpt"])}”</div>'
            f'<div class="fc-from">From the {safe(card["field"])} field of this facility\'s record.{related} '
            f"{source}</div></div>")


def warning(card):
    """The location-warning badge for one facility. Empty until a search supplies a reviewed warning."""
    if not card.get("location_warning"):
        return ""
    return f'<div class="fc-warning"><strong>Check the address.</strong> {safe(card["location_warning"])}</div>'


def source_item(claim_name, source):
    """One source behind a claim: publisher, origin, the fact, field, date and any record reference."""
    links = "".join(f' <a href="{html.escape(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
                    f"{safe(item['url'].split('/')[2])}</a> ({safe(item['note'])})" for item in source["links"])
    role = {"support": "Supports", "conflict": "Conflicts with", "context": "Context for"}[source["role"]]
    return (f"<li><strong>{role} {safe(claim_name.lower())}:</strong> {safe(source['fact'])}<br>"
            f"Publisher: {safe(source['publisher'])}. Origin: {safe(source['origin'])} "
            f"Where: {safe(source['field'])}. Evidence date: {safe(source['date'])}.{links}</li>")


def claims(card, service, group, index):
    """The location and service lines for one card (#302), then the sources behind them on request."""
    found = words.claim_lines(card, service, group, index)
    lines, sources = [], []
    for claim in (found["location"], found["service"]):
        lines.append(f'<div class="fc-claim"><strong>{safe(claim["label"])}</strong> · {safe(claim["line"])}</div>')
        sources += [source_item(claim["label"], source) for source in claim["sources"]]
        sources.append(f'<li class="fc-next">{safe(claim["label"])}: {claim["source_records"]} record, '
                       f'{claim["independent_supporting_origins"]} known supporting origin. Next check: '
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


def withheld_line(response, service):
    """The result-level evidence summary for real records. Names no facility and lists no source."""
    summary = words.withheld_summary(response, service)
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
    parts = [f'<div class="fc-for">{safe(view["request_line"])}</div>',
             f'<div class="fc-answer" role="heading" aria-level="2">{safe(view["headline"])}</div>']
    top = view["top"] if DEMO and view["status"] == "ok" else None
    if top:
        place = f"{top['place']}. " if top["place"] else ""
        parts.append(f'<div class="fc-trip">{safe(place + top["distance"])}</div>{warning(top)}')
        parts.append(f'<div class="fc-h">Why this facility</div><div class="fc-text">{safe(view["why"])}</div>')
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
    st.markdown('<div class="fc-lede">Say what care a patient needs and where they are. You get the nearest '
                "facility whose record says it offers that care, with the words it relied on.</div>"
                '<div class="fc-mode"><strong>Data: demonstration.</strong> This screen is running on six '
                "invented facilities, not the real records.</div>", unsafe_allow_html=True)
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
left, right = st.columns([5, 9], gap="large")

with left:
    st.subheader("Your request")
    service = st.radio("1. Care needed", list(words.SERVICES), format_func=words.SERVICES.get, key="service",
                       horizontal=True)
    where = st.text_input("2. Where the patient is", key="where", placeholder="For example: Jaipur, Rajasthan")
    st.caption("A city or town (add the state after a comma), a six-digit PIN code, or coordinates.")
    radius = st.select_slider("Search within", options=list(words.RADII), key="radius",
                              format_func=lambda km: f"{km} km")
    st.button("Find a facility", type="primary", use_container_width=True, on_click=submit, key="find")
    if st.session_state.get("problem"):
        st.error(st.session_state["problem"])
    st.caption("Or start from an example")
    for label, ex_service, ex_where, ex_radius in EXAMPLES:
        st.button(label, key="example-" + label, on_click=fill, args=(ex_service, ex_where, ex_radius))

with right:
    response, asked = st.session_state.get("response"), st.session_state.get("asked")
    if not response:
        with st.container(border=True):
            st.markdown("**The recommendation appears here.**")
            st.write("You get one facility to send the patient to, the words from its record that back it, "
                     "and what nobody has confirmed yet. Press Find a facility, or start from an example."
                     if DEMO else
                     "You are told whether nearby records mention the service. No facility is named until "
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
                        "Press Find a facility to update it.</div>", unsafe_allow_html=True)
        st.markdown(slip(view, stale, asked["service"], response), unsafe_allow_html=True)
        for choice in view["choices"] if DEMO and not stale else []:
            label = ", ".join(part for part in (choice.get("city"), choice.get("state")) if part)
            st.button(label, key="choice-" + label, on_click=fill,
                      args=(asked["service"], label, asked["radius_km"]))
        if DEMO and not stale and view["backups"]:
            st.subheader(f"If {view['top']['name']} cannot take the patient")
            st.caption("Listed nearest first. The order says nothing about quality.")
            st.markdown('<div class="fc-slip fc-more"><ol start="2">'
                        + "".join(listed(backup, asked["service"], "direct_results", index)
                                  for index, backup in enumerate(view["backups"], start=1)) + "</ol></div>",
                        unsafe_allow_html=True)
        # An out-of-date answer can be read but not handed on: no backups, no note to copy, nothing to save.
        if DEMO and not stale and view["status"] in ("ok", "needs_confirmation"):
            st.subheader("Referral note")
            st.caption("Use the copy button on the note, or save it as a file.")
            note = words.referral_note(view, synthetic=True)
            st.code(note, language=None, wrap_lines=True)
            st.download_button("Save referral note", note, file_name="referral-note.txt", mime="text/plain")
        st.subheader("How this was decided")
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
