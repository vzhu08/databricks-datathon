"""The interactive care flow at the top of the judge page (#287). Streamlit rendering only.

All decisions come from care_decision.evaluate. The browser supplies only the enumerated choices; the evidence
editions are read by the pinned server loaders, and only when a decision needs them, so an emergency answer is
shown before any file is opened.
"""
import html

import streamlit as st

try:
    from . import area, care_decision, loader
except ImportError:  # run as a script by Streamlit
    import area
    import care_decision
    import loader

# Questions in the order they are asked. Each: key, question, help, [(value, label)].
DANGER = ("danger", "Is anyone in immediate danger right now?",
          "For example trouble breathing, heavy bleeding, unconsciousness or chest pain.",
          [("yes", "Yes"), ("no", "No"), ("unsure", "Not sure")])
URGENCY = ("urgency", "How soon do you feel help is needed?", "Your own sense of urgency. It is shown as you chose it.",
           [("routine", "Routine"), ("soon", "Soon"), ("emergency", "Emergency now"), ("unsure", "Not sure")])
CONCERN = ("concern", "What is the care need?", "",
           [("injury", "An injury"), ("dialysis", "Ongoing dialysis"), ("mri", "An MRI already ordered"),
            ("other", "Something else"), ("unsure", "Not sure")])
INJURY = ("injury_kind", "What kind of injury?", "",
          [("head", "Head"), ("burn", "Burn"), ("limb_joint", "Limb or joint"), ("cut_wound", "Cut or wound"),
           ("other", "Other"), ("unsure", "Not sure")])
SEVERITY = ("severity", "How severe does it seem?", "",
            [("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe"), ("unsure", "Not sure")])
KEYS = ("danger", "urgency", "concern", "injury_kind", "severity")

PRIORITY = {"emergency": "Emergency", "prompt_review": "Prompt review", "clarify": "Needs clarifying",
            "standard": "Standard"}
SELF = {"routine": "Routine", "soon": "Soon", "emergency": "Emergency", "unsure": "Not sure"}
SERVICE = {"trauma_care": "Trauma care", "dialysis": "Dialysis", "mri": "MRI"}


def esc(text):
    return html.escape(str(text), quote=False)


def show(markup):
    st.markdown(markup, unsafe_allow_html=True)


def ask(question):
    key, text, help_text, options = question
    labels = dict(options)
    return st.radio(text, [value for value, _ in options], index=None, key=f"care_{key}", horizontal=True,
                    format_func=labels.get, help=help_text or None)


def start_over():
    for key in KEYS:
        st.session_state.pop(f"care_{key}", None)


def collect():
    """Ask progressively. Stops asking as soon as an answer means emergency."""
    chosen = {}
    for question in (DANGER, URGENCY):
        value = ask(question)
        if value is None:
            return chosen
        chosen[question[0]] = value
        if value in ("yes", "emergency"):
            return chosen
    concern = ask(CONCERN)
    if concern is None:
        return chosen
    chosen["concern"] = concern
    if concern == "injury":
        kind = ask(INJURY)
        if kind is None:
            return chosen
        chosen["injury_kind"] = kind
    else:  # an injury kind from an earlier answer never carries over to another need
        st.session_state.pop("care_injury_kind", None)
    severity = ask(SEVERITY)
    if severity is not None:
        chosen["severity"] = severity
    return chosen


def decide(chosen):
    """Evaluate without data first; read the editions only if the decision needs them."""
    result = care_decision.evaluate(chosen)
    if result["status"] == "data_unavailable":
        result = care_decision.evaluate(chosen, loader.load(), area.load())
    return result


def complete(chosen):
    return "danger" in chosen and (chosen.get("danger") == "yes" or chosen.get("urgency") == "emergency"
                                   or "severity" in chosen)


def priorities(result):
    r = result["request"]
    cells = [("You chose", SELF[r["urgency"]], "Your own sense of urgency, unchanged."),
             ("Automatic check", PRIORITY[result["assessment_priority"]],
              "From danger, severity and missing answers only. It never reads your choice."),
             ("Combined", PRIORITY[result["workflow_urgency"]], "What the workflow does next.")]
    return ('<div class="fe-prio">' + "".join(
        f'<div class="fe-prio-cell fe-prio-{esc(value.lower().replace(" ", "-"))}"><span class="fe-prio-k">{esc(k)}</span>'
        f'<span class="fe-prio-v">{esc(value)}</span><span class="fe-prio-d">{esc(d)}</span></div>'
        for k, value, d in cells) + "</div>")


def evidence_block(result):
    ev = result["evidence"]
    if not ev:
        return ""
    t = ev["trace"]
    src = t["source"]
    link = (f'<a href="{html.escape(src["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'{esc(src["label"])}</a>' + (f' ({esc(src["note"])})' if src["note"] else "")) if src["url"] \
        else esc(src["label"])
    parts = [f'<h3>What the evidence shows for {esc(ev["service_label"])}</h3>',
             f'<p>{esc(ev["summary"])}</p>',
             f'<p class="fe-quiet">{esc(t["grain"])}. Map editions: {esc(", ".join(t["snapshots"]))}, one origin '
             f'({esc(t["source_family"])}). Precision: {esc(t["precision"])}. Baseline: {esc(ev["baseline"]["dataset"])}, '
             f'as of {esc(ev["baseline"]["as_of"])}. Source: {link}.</p>']
    if ev.get("historical_case"):
        case = ev["historical_case"]
        facts = "".join(f'<li><strong>{esc(f["when"])}</strong>: {esc(f["what"])} ({esc(f["scope"])})</li>'
                        for f in case["facts"])
        parts.append(f'<h3>A dated public case: {esc(case["title"])}</h3><p>{esc(case["link_line"])}</p>'
                     f'<ul>{facts}</ul><p class="fe-quiet">Which building delivers dialysis today is not known.</p>')
    return "".join(parts)


def area_block(result):
    a = result["area"]
    if not a:
        return ""
    return (f'<h3>How precisely records are located</h3><p>{esc(a["headline"])} records can be placed only to an '
            f'area, not to a building ({esc(a["edition"])}, as of {esc(a["as_of"])}). This is national context, '
            "not a match to this request.</p>")


def render(result, chosen):
    status = result["status"]
    if status == "emergency":
        show('<section class="fe-emergency" role="alert"><h2>Get emergency help now</h2>'
             "<p><strong>Call local emergency services. In India, dial 112.</strong></p>"
             f"<p>{esc(result['reason'])}</p>"
             "<p>Facility browsing is stopped. Do not wait for this page.</p></section>")
        return
    if not complete(chosen):
        return
    service = SERVICE.get(result["service"], "")
    head = {
        "no_reviewed_destination": "No reviewed facility yet",
        "no_supported_service": "This need is outside what the evidence covers",
        "needs_clarification": "One answer needs clarifying",
        "invalid_request": "Please choose from the listed answers",
        "data_unavailable": "Data unavailable",
    }[status]
    body = [f'<section class="fe-answer fe-care-result" aria-live="polite"><p class="fe-kicker">'
            f'{"Service checked: " + esc(service) if service else "Result"}</p><h2>{esc(head)}</h2>',
            priorities(result), f'<p class="fe-lead">{esc(result["reason"])}</p>']
    if result["eligible_destinations"] == 0:
        body.append('<p class="fe-lead">0 reviewed sites can be recommended for this service in the cleared '
                    "edition. No score, travel time or available bed is shown.</p>")
    body.append(evidence_block(result))
    body.append(area_block(result))
    body.append(f'<div class="fe-next"><span>Next check</span>{esc(result["next_check"])}</div></section>')
    if (result.get("evidence") or {}).get("synthetic"):
        show('<p class="fe-synthetic" role="note"><strong>Synthetic test file.</strong> The evidence below is '
             "invented for testing.</p>")
    show("".join(body))


def flow():
    show('<section class="fe-care" aria-labelledby="fe-care-h"><p class="fe-kicker">Try it</p>'
         '<h2 id="fe-care-h">Where could this patient get care?</h2>'
         '<p class="fe-intro">Answer a few questions. Nothing you choose is stored or sent anywhere. '
         "This is a demonstration, not medical advice.</p></section>")
    chosen = collect()
    if chosen:
        render(decide(chosen), chosen)
        st.button("Start over", on_click=start_over, key="care_start_over")
