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
import json
import os
import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # so the same imports work from the repository root and from a deployed `app/`
    sys.path.append(str(HERE))

import find_care as words  # noqa: E402
from data_access import search_warehouse  # noqa: E402
from ranking import search_facilities  # noqa: E402

# Kept inside app/ so a deployment of this folder alone still has its demonstration facilities.
# tests/find_care checks it is the same file as contracts/fixtures/search.json.
FIXTURE = HERE / "demo_facilities.json"
DATA = words.data_mode(os.environ)
DEMO = DATA["mode"] == "demo"
MODES = {"city": "City or town", "pin": "PIN code", "coordinates": "Coordinates"}
EXAMPLES = [
    ("Dialysis near Jaipur, Rajasthan", "dialysis", "city", {"city": "Jaipur", "state": "Rajasthan"}, 50),
    ("MRI scan near PIN 302001", "mri", "pin", {"pin": "302001"}, 50),
    ("Dialysis within 2 km of PIN 302001", "dialysis", "pin", {"pin": "302001"}, 2),
]


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


def ask(service, location, radius_km):
    try:
        response = run_search(service, location, radius_km)
    except ValueError as error:  # the search rejects malformed input with a plain message
        response = {"status": "invalid_input", "direct_results": [], "indirect_leads": [], "location_choices": [],
                    "approximate_location": False, "message": str(error)}
    st.session_state["asked"] = {"service": service, "location": location, "radius_km": radius_km}
    st.session_state["response"] = response


def facility(card, heading=None):
    if heading:
        st.markdown(f"**{plain(heading)}**")
    st.markdown("\n".join("> " + plain(line) for line in card["excerpt"].splitlines() or [""]))
    st.caption(f"From the {card['field']} field of this facility's record."
               + ("" if card["strength"] == "direct" else " It mentions something related, not the service itself."))
    if card["sources"]:
        st.markdown("Record sources: " + ", ".join(f"[{plain(url.split('/')[2])}]({url})" for url in card["sources"]))
    else:
        st.caption("This record lists no source link.")


st.set_page_config(page_title="Find care", layout="wide")
st.title("Find care")
if DATA["mode"] == "setup":
    st.error("Data: not available. This app is set to read the real facility records, but its setup is incomplete.")
    for problem in DATA["problems"]:
        st.markdown("- " + plain(problem))
    st.caption(f"To run on the invented demonstration facilities instead, set {words.DATA_SETTING} to demo.")
    st.stop()
if DEMO:
    st.caption("Data: demonstration. This screen is running on six invented facilities, not the real records.")
    if not FIXTURE.exists():
        st.error("The demonstration facilities (demo_facilities.json) are missing from this deployment.")
        st.stop()
else:
    st.caption("Data: real records. Searching the Virtue Foundation facility records. No facility is named or "
               "recommended here until the team has reviewed and approved destinations.")

left, right = st.columns([5, 9], gap="large")

with left:
    st.subheader("Where should this patient go?")
    mode = st.radio("Give the location as", list(MODES), format_func=MODES.get, horizontal=True, key="mode")
    with st.form("ask"):
        service = st.radio("Care needed", list(words.SERVICES), format_func=words.SERVICES.get, key="service")
        if mode == "city":
            city = st.text_input("City or town", key="city", placeholder="Jaipur")
            state = st.text_input("State (optional)", key="state", placeholder="Rajasthan")
            typed = {"city": city, "state": state}
        elif mode == "pin":
            typed = {"pin": st.text_input("PIN code", key="pin", placeholder="302001", max_chars=7)}
        else:
            typed = {"latitude": st.text_input("Latitude", key="latitude", placeholder="26.92"),
                     "longitude": st.text_input("Longitude", key="longitude", placeholder="75.82")}
        radius = st.select_slider("Search within", options=list(words.RADII), value=50, key="radius",
                                  format_func=lambda km: f"{km} km")
        if st.form_submit_button("Find a facility", type="primary", use_container_width=True):
            try:
                ask(service, words.build_location(mode, **typed), radius)
            except ValueError as error:
                st.session_state.pop("response", None)
                st.error(str(error))
    st.caption("Or try an example")
    for label, ex_service, _ex_mode, ex_location, ex_radius in EXAMPLES:
        if st.button(label, key="example-" + label):
            ask(ex_service, ex_location, ex_radius)

with right:
    response, asked = st.session_state.get("response"), st.session_state.get("asked")
    if not response:
        with st.container(border=True):
            st.markdown("**The recommendation appears here.**")
            st.write("You get one facility to send the patient to, the words from its record that back it, "
                     "and what nobody has confirmed yet." if DEMO else
                     "You are told whether nearby records mention the service. No facility is named until "
                     "the team has reviewed and approved destinations.")
    else:
        view = words.present(response, asked["service"], asked["location"], asked["radius_km"])
        with st.container(border=True):
            st.caption(view["request_line"])
            st.header(view["headline"])
            st.markdown(f"**{plain(view['subline'])}**")
            if DEMO and view["status"] == "ok":
                top = view["top"]
                if top["place"]:
                    st.write(top["place"])
                st.write(view["why"])
                facility(top)
                if view["caveat"]:
                    st.warning(view["caveat"])
            for lead in view["leads"] if DEMO else []:
                facility(lead, f"{lead['name']}. {lead['distance']}")
            for choice in view["choices"] if DEMO else []:
                label = ", ".join(part for part in (choice.get("city"), choice.get("state")) if part)
                if st.button(label, key="choice-" + label):
                    ask(asked["service"], choice, asked["radius_km"])
                    st.rerun()
            if view["next_step"]:
                st.write(view["next_step"])
            if view["approximate_note"]:
                st.caption(view["approximate_note"])
        if DEMO and view["backups"]:
            st.subheader(f"If {view['top']['name']} cannot take the patient")
            for number, backup in enumerate(view["backups"], start=2):
                facility(backup, f"{number}. {backup['name']}. {backup['distance']}")
        if DEMO and view["status"] in ("ok", "needs_confirmation"):
            st.subheader("Referral note")
            st.caption("Use the copy button on the note, or save it as a file.")
            note = words.referral_note(view, synthetic=True)
            st.code(note, language=None)
            st.download_button("Save referral note", note, file_name="referral-note.txt", mime="text/plain")
        st.subheader("How this was decided")
        st.write(words.HOW if DEMO else words.HOW_WITHHELD)
        with st.expander("Technical details"):
            if DEMO:
                st.caption("The request and the unedited response from the search.")
                st.json({"request": asked, "response": response})
            else:
                st.caption("The request and the search status. The response itself is not shown for real records.")
                st.json({"request": asked, "data": "warehouse", "status": response["status"]})
