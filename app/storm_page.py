"""Host the offline replay and an explicit signed-in Pune road-time action."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path

try:  # as a module of the app package (tests) or beside app.py (the deployed folder)
    from . import storm_plan
    from .simulation import traffic_plan
    from .travel import storm as storm_routes
except ImportError:
    import storm_plan
    from simulation import traffic_plan
    from travel import storm as storm_routes

STORM = "Storm demo (simulated)"
SOURCE = Path(__file__).resolve().parent / "storm_ui"
HEIGHT = 1500
SIMULATED = ("Everything on this page is simulated: the scenario, the six campuses and their locations, the "
             "patients and when they arrive, the travel times and the staffed slots. No real hospital, patient or "
             "route is shown, and nothing you do here is sent to the symptom check or the facility search.")
HOW = ("Press Play or Next to run one shift, or Skip to the result to reach the end of the shift. The left side "
       "always sends each patient to the nearest campus. The right side may send a routine patient a little "
       "farther to keep the last specialist slot free for someone urgent. Select a patient in the table to see why "
       "each side chose as it did. Show as: Text only gives the same replay without the maps.")
REPLAY = "Checked 8-request replay"
TWO_VIEWS = ("Two views of the same question: who gets a staffed place when demand outruns capacity. The replay "
             "steps through a few invented requests one at a time, so you can see why each policy chose as it did. "
             "The planning simulation tests how many of {patients:,} simulated patients each policy can place "
             "across {sites:,} {where}, nearest first against the best possible assignment.")
RUN_ROADS = "Run signed-in road-time comparison"
_TRAFFIC_RESULT = "storm_traffic_display"
UNAVAILABLE = "The storm replay files are not in this deployment, so the replay cannot be shown."
NAMES = {"nearest_first": "Nearest first", "scarcity_aware": "Urgency-aware"}
# The offline page links to its sibling pages. Inside the hosted app those files are not served, so the
# frame carries the replay alone and the app's own switch is the way back.
_NAV = re.compile(r'\s*<nav class="steps".*?</nav>', re.S)
# "Open replay file" stays in the document because the replay script wires it at start, but it is not
# offered here: the hosted page shows the committed replays only.
_FILE = '<div class="field file">'


def bundle(source=SOURCE):
    """The committed replays, read from the same generated file the page uses."""
    text = (Path(source) / "data" / "scenarios.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


def headline(found):
    """What the default replay ends on, taken from the fixture and never typed in here."""
    replay = found["replays"][found["default"]]
    lines = []
    for policy in ("nearest_first", "scarcity_aware"):
        metrics = replay["policies"][policy]["metrics"]
        lines.append({"policy": policy, "name": NAMES[policy], "served": metrics["assigned"],
                      "requested": metrics["requested"], "not_served": metrics["unassigned"],
                      "extra_travel_minutes": metrics["extra_travel_minutes"]})
    return {"scenario": replay["scenario"], "seed": replay["seed"], "detour_minutes": replay["detour_minutes"],
            "area": replay["area"], "synthetic": replay["synthetic"] is True, "policies": lines}


def sentence(summary):
    first, second = summary["policies"]
    return (f"Default replay: the {summary['scenario']} scenario, seed {summary['seed']}, with a "
            f"{summary['detour_minutes']}-minute limit on detours. {first['name']} served {first['served']} of "
            f"{first['requested']} simulated patients with {first['extra_travel_minutes']} extra travel minutes. "
            f"{second['name']} served {second['served']} of {second['requested']} with "
            f"{second['extra_travel_minutes']} extra travel minutes.")


def document(source=SOURCE):
    """replay.html with its local styles, fonts, data and scripts inlined. No address in it leaves the page."""
    source = Path(source)
    page = (source / "replay.html").read_text(encoding="utf-8")

    def font(match):
        data = base64.b64encode((source / match.group(1)).read_bytes()).decode("ascii")
        return f'url("data:font/woff2;base64,{data}")'

    def style(match):
        css = (source / match.group(1)).read_text(encoding="utf-8")
        return "<style>\n" + re.sub(r'url\("(fonts/[^"]+)"\)', font, css) + "\n</style>"

    def script(match):
        code = (source / match.group(1)).read_text(encoding="utf-8")
        return "<script>\n" + code.replace("</script", "<\\/script") + "\n</script>"

    page = _NAV.sub("", page, count=1).replace(_FILE, '<div class="field file" hidden style="display:none">', 1)
    page = re.sub(r'<link rel="stylesheet" href="([^"]+)">', style, page)
    return re.sub(r'<script src="([^"]+)"></script>', script, page)


def _traffic_available(plan, environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("TOMTOM_ENABLED") != "true" or not all(
            str(environ.get(key) or "").strip()
            for key in ("TOMTOM_COPYRIGHT_CAPTION", "TOMTOM_COPYRIGHT_NOTICES")):
        return False
    # The four-care recording and other modeled editions are separate.
    population = sorted(patient["service"] for patient in plan["patients"])
    first_edition = ["dialysis"] * 42 + ["mri"] * 42 + ["trauma_care"] * 36
    return (storm_plan.real(plan) and plan["geography"].get("roster_sha256") == traffic_plan.PUNE_ROSTER_SHA256
            and plan["scenario"].get("seed") == 17 and plan["scenario"].get("horizon_minutes") == 360
            and len(plan["facilities"]) == 12 and population == first_edition)


def _render_planning(st, plan):
    if not _traffic_available(plan):
        st.session_state.pop(_TRAFFIC_RESULT, None)
        storm_plan.render(st, plan)
        return

    current = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    saved = st.session_state.get(_TRAFFIC_RESULT)
    if saved is not None and saved[0] != current:
        st.session_state.pop(_TRAFFIC_RESULT, None)
        saved = None
    st.caption("This optional run uses two shared simulated pickups and 12 approved public site points. "
               "A press can request up to 24 road estimates and 48 attempts including retries. "
               "Both policies use the same completed observation.")
    if st.button(RUN_ROADS, key="storm_run_road_times"):
        st.session_state.pop(_TRAFFIC_RESULT, None)
        saved = None
        try:
            observed = traffic_plan.run_traffic_plan(
                plan, pickups=storm_routes.storm_pickups(), observe=storm_routes.storm_car_matrix,
            )
            # Store only the escaped, rounded display for this signed-in session.
            # The raw observation and its assignment records are not cached.
            display = storm_plan.markup(storm_plan.checked(observed))
        except Exception:
            # A failed action must not display an earlier result or hide the baseline.
            st.error("This road-time comparison could not be validated. The modeled baseline is still available.")
        else:
            saved = (current, display)
            st.session_state[_TRAFFIC_RESULT] = saved

    if saved is None:
        st.subheader("Modeled baseline")
        storm_plan.render(st, plan)
    else:
        st.warning(storm_plan.LIVE_NOTICE)
        st.markdown(storm_plan.STYLE + saved[1], unsafe_allow_html=True)
        with st.expander("Modeled baseline"):
            storm_plan.render(st, plan)


def views_note(plan):
    """One line above the switch saying what the two views are, with the plan's own counts."""
    where = "real site locations" if storm_plan.real(plan) else "simulated sites"
    return TWO_VIEWS.format(patients=len(plan["patients"]), sites=len(plan["facilities"]), where=where)


def render(st):
    """Draw the page. Called by app.py before any patient or facility code runs."""
    st.title("Storm demo")
    try:  # the planning simulation is offered only once a results file that holds together is present
        plan = storm_plan.load()
    except storm_plan.Unavailable:
        plan = None
    if plan is not None:
        st.caption(views_note(plan))
        views = [REPLAY, storm_plan.choice(plan)]
        if st.radio("Storm view", views, horizontal=True, key="storm_view", label_visibility="collapsed") != REPLAY:
            _render_planning(st, plan)
            return
    st.session_state.pop(_TRAFFIC_RESULT, None)
    st.warning(SIMULATED)
    try:
        summary, page = headline(bundle()), document()
    except (OSError, ValueError, KeyError):
        st.error(UNAVAILABLE)
        return
    st.markdown(sentence(summary))
    st.caption(HOW + " To go back, choose Check symptoms or Find care at the top of the page.")
    frame(st, page)


def frame(st, page):
    """Show the document in a frame. Newer Streamlit sizes the frame to the replay; older Streamlit
    (the app allows 1.40 and later) gets a fixed, scrolling frame from the earlier call."""
    if hasattr(st, "iframe"):
        st.iframe(page, height="content")
        return
    import streamlit.components.v1 as components
    components.html(page, height=HEIGHT, scrolling=True)
