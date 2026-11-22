"""Loopback presenter defaults. Andrew's app entry and validator stay intact."""

from collections import Counter
from pathlib import Path
import os
import runpy
import sys

import streamlit as st


APP = Path(__file__).resolve().parents[2] / "app"
ASSETS = Path(os.environ["PRESENTER_ASSETS_DIR"])
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import storm_page
import storm_plan
import local_provenance
import street_map

storm_plan.APPROVED_ROSTERS.update(local_provenance.approved_rosters(ASSETS))

requested = st.query_params.get("view", "planning")
original_load = getattr(storm_plan, "_loopback_base_load", storm_plan.load)
storm_plan._loopback_base_load = original_load


def local_plan(path=None):
    if path is None:
        name = "official-seed17-plan.json" if st.query_params.get("view") == "baseline" else "plan.json"
        path = ASSETS / name
    document = original_load(path)
    try:
        local_provenance.validate_locations(document, ASSETS)
    except ValueError as exc:
        raise storm_plan.Unavailable(str(exc)) from exc
    return document


storm_plan.load = local_plan

try:
    plan = storm_plan.load()
except storm_plan.Unavailable:
    plan = None

if not st.session_state.get("_local_presenter_started"):
    st.session_state["_local_presenter_started"] = True
    if requested in {"planning", "replay", "baseline"}:
        st.session_state["view"] = storm_page.STORM
    if requested in {"planning", "baseline"} and plan:
        st.session_state["storm_view"] = storm_plan.choice(plan)


def clinical_groups(ui, document):
    patients = {row["id"]: row.get("condition_category") for row in document["patients"]}
    labels = {row["category"]: row["label"] for row in document.get("condition_breakdown", [])}
    if not labels or any(category not in labels for category in patients.values()):
        return
    requested = Counter(patients.values())
    counts = {
        policy: Counter(patients[row["patient"]] for row in result["assignments"])
        for policy, result in document["policies"].items()
    }
    ui.markdown("#### Simulated condition groups")
    ui.caption("Local test scenario. Patient groups and every service or staffed place are simulated.")
    ui.table([
        {
            "Condition group": label,
            "Requests": requested[group],
            "Nearest first placed": counts["nearest_first"][group],
            "Nearest first unmet": requested[group] - counts["nearest_first"][group],
            "Exact optimum placed": counts["exact_optimum"][group],
            "Exact optimum unmet": requested[group] - counts["exact_optimum"][group],
        }
        for group, label in labels.items()
    ])


base_render = getattr(storm_plan, "_loopback_base_render", storm_plan.render)
storm_plan._loopback_base_render = base_render


def render_with_groups(ui, document):
    if not document.get("condition_breakdown"):
        base_render(ui, document)
        return
    if not storm_plan.real(document):
        base_render(ui, document)
        clinical_groups(ui, document)
        return
    content = storm_plan.markup(document)
    summary, priority_marker, rest = content.partition("<h3>By priority</h3>")
    priorities, map_marker, rest = rest.partition("<h3>Where the facilities are</h3>")
    _, area_marker, area = rest.partition("<h3>About the area</h3>")
    if not (priority_marker and map_marker and area_marker):
        base_render(ui, document)
        return
    try:
        street = street_map.page(document, ASSETS)
    except (OSError, ValueError, KeyError):
        base_render(ui, document)
        return
    ui.warning(storm_plan.NOTICE)
    ui.markdown(
        storm_plan.STYLE + '<style>.sp[data-plan="shown"],.sp.local-detail '
        '{background:#f5f8fa;padding:1.15rem;border-radius:.5rem;}</style>' + summary + "</div>",
        unsafe_allow_html=True,
    )
    street_map.render(ui, street, ASSETS)
    clinical_groups(ui, document)
    evidence = local_provenance.load(document, ASSETS)
    if evidence:
        local_provenance.render(ui, document, evidence)
    ui.markdown('<div class="sp local-detail">' + priority_marker + priorities + area_marker + area,
                unsafe_allow_html=True)


storm_plan.render = render_with_groups
runpy.run_path(str(APP / "app.py"), run_name="__main__")
