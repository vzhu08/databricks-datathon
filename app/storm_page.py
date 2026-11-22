"""The Storm demo page of the hosted app: the offline storm replay, embedded whole.

The replay is the accepted page in storm_ui/ (replay.html, its styles, scripts, fonts and the
committed simulation outputs in storm_ui/data/scenarios.js). Here it is folded into one document
and shown in a frame, so the hosted app needs no network, map key, warehouse or extra file route.
Nothing is ranked, allocated or re-simulated here, and nothing on this page reads or writes the
patient visit. Every campus, origin, patient, arrival, slot count and travel time is simulated.
"""
import base64
import json
import re
from pathlib import Path

try:  # as a module of the app package (tests) or beside app.py (the deployed folder)
    from . import storm_plan
except ImportError:
    import storm_plan

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


def render(st):
    """Draw the page. Called by app.py before any patient or facility code runs."""
    st.title("Storm demo")
    try:  # the planning simulation is offered only once a results file that holds together is present
        plan = storm_plan.load()
    except storm_plan.Unavailable:
        plan = None
    if plan is not None:
        views = [REPLAY, storm_plan.choice(plan)]
        if st.radio("Storm view", views, horizontal=True, key="storm_view", label_visibility="collapsed") != REPLAY:
            storm_plan.render(st, plan)
            return
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
