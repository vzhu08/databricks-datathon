"""Check your symptoms: the patient screen over the patient runtime (app/patient_intake).

The screen holds no clinical logic and no result of its own. Each time it is drawn it shows the
runtime's current public view for the encounter and nothing else, so an edit, a failed step, an
expiry or a reset can never leave an earlier result on the screen.

* The encounter, its handle and the service stay in the server's Streamlit session. Nothing about
  the patient goes in the URL, in browser storage, in a download or in a debug panel.
* Every runtime call happens once, in the handler of the button the patient pressed. Drawing the
  screen again never repeats a consent, an assessment or an answer.
* `compose` is the one place an approved assessment provider is injected. None is configured in
  this repository, so the runtime reports the assessment as unavailable. There is no scripted or
  fixture fallback.

The wording functions at the top are plain Python and are tested without Streamlit.
"""
import html
import logging
import os
import re
import time

if __package__:  # imported as app.patient_ui by the repository's tests
    from .patient_intake import POLICY_VERSION, PatientIntakeService
    from .patient_intake.handoff import PatientHandoff
    from .patient_intake.interview import PatientInterview
    from .patient_intake.privacy import PatientSessionError
    from .patient_intake.session import DEFAULT_TTL_SECONDS, PatientSession
else:  # imported as patient_ui from a deployed app/
    from patient_intake import POLICY_VERSION, PatientIntakeService
    from patient_intake.handoff import PatientHandoff
    from patient_intake.interview import PatientInterview
    from patient_intake.privacy import PatientSessionError
    from patient_intake.session import DEFAULT_TTL_SECONDS, PatientSession

PATIENT = "Check symptoms"
STATE_KEY = "patient"
NOTICE_VERSION = "patient-notice.v1"
TTL_SECONDS = DEFAULT_TTL_SECONDS
LANGUAGE = "en"
MAX_DESCRIPTION = 4000
MAX_ANSWER = 1500

EMERGENCY = "If this could be an emergency, call 112 now. Do not wait for this screen."
NOT_A_DOCTOR = ("This is an automated assessment from that provider. It is not a diagnosis, a "
                "prescription or a doctor's order.")
NOTICE = (
    "What you write is kept in this server's memory for this visit only. This server's copy is cleared when you "
    "press Start over, and in any case {minutes} minutes after you begin. An open page clears itself at that "
    "moment. If your device is asleep or offline then, the page clears as soon as it reconnects.",
    "Nothing you write is put in the page address, saved in your browser or offered as a download.",
    "Nothing is sent outside this server unless you agree to it on a later step, which names who receives it. "
    "Clearing this server's copy does not by itself delete what a provider has already received.",
    "This screen cannot examine you. It does not replace a doctor.",
)
SWITCHED_OFF = ("Symptom assessment is switched off on this server. No assessment provider has been approved "
                "and set up. You can write a description, but it will not be sent anywhere or assessed.")

URGENCY = {
    "emergency_ambulance": "Call an ambulance now",
    "emergency": "Go to an emergency department now",
    "consultation_24": "See a doctor within 24 hours",
    "consultation": "See a doctor (not assessed as urgent)",
    "self_care": "Self-care may be enough",
}
UNAVAILABLE = {
    "unavailable": "The assessment service could not be reached or did not answer.",
    "timeout": "The assessment service took too long to answer.",
    "rate_limited": "The assessment service is handling too many requests at the moment.",
    "budget_exhausted": "This server has no assessment requests left in its allowance.",
    "invalid_response": "The assessment service sent a reply this screen could not safely show.",
    "unauthorized": "This server is not authorised to use the assessment service.",
    "configuration_changed": "The assessment set-up changed during your visit, so earlier results were withdrawn.",
}
UNSUPPORTED = {
    "unsupported_context": "This assessment does not cover the age or language you entered.",
    "unsupported_correction": ("Your answers about what the provider understood from your words left something "
                               "unconfirmed or in conflict, and this assessment cannot yet resolve that."),
    "interview_limit": "This assessment reached its limit of follow-up questions without a result.",
    "unsupported": "The assessment provider cannot assess this description.",
}
DESTINATION = {
    "no_reviewed_destination": ("No hospital can be suggested. The team has not yet reviewed and approved a "
                                "hospital for this kind of care. Your result above still stands."),
    "navigation_unavailable": "The hospital check could not be completed. Your result above still stands.",
    "unsupported_service": "The hospital check does not cover the care named in your result.",
    "assessment_blocked": "Your result changed before the hospital check finished, so nothing is shown.",
}
ENDED = {
    "expired": ("Your visit reached its time limit and everything you wrote was cleared from this server. "
                "Start again when you are ready."),
    "reset": "Everything you wrote was cleared from this server.",
    "deleted": "Everything you wrote was cleared from this server.",
}
NO_PROVIDER = "No assessment provider is set up on this server, so your description was not sent anywhere."
OUT_OF_DATE = "That step was out of date, so it was not used. This is the current state of your visit."
BAD_ANSWER = "Answer the question shown, within any limits it gives, then send it."
UNINTERPRETED = "Your description has not been interpreted."
STOPPED = ("The assessment provider ended this assessment with the message above. It gave no result, no possible "
           "causes and no place to go. You can change your description or start over.")
QUESTION_WITHHELD = "The assessment provider asked a question this screen cannot show, so it was withheld."
KINDS = ("single", "multiple", "text", "evidence_review", "item_presence", "quantity", "catalog_selection")
FAILED = ("That step could not be completed, and whether it went through could not be confirmed. What you see "
          "now is the current state of your visit.")
UNCONFIRMED = ("No result could be confirmed, and any earlier result has been withdrawn. Your description may still "
               "have reached the assessment provider. If you are worried, see a doctor.")
NOT_ASSESSED = "No assessment was made. If you are worried, see a doctor."
ENGLISH_ONLY = "Write in English. This assessment does not support other languages yet."
PROVIDER_COPY = ("Starting over clears this server's copy. It does not by itself delete what the provider has "
                 "already received.")
PRESENCE = {"present": "you have this", "absent": "you do not have this", "unknown": "not clear"}
TEMPORALITY = {"current": "now", "historical": "in the past", "unknown": "timing not clear"}


PROVIDER_SETTING = "PATIENT_PROVIDER"
DATABRICKS = "databricks-experimental"
ENDPOINTS = ("databricks-gpt-oss-20b", "databricks-gpt-oss-120b")
ENDPOINT_SETTING = "PATIENT_PROVIDER_ENDPOINT"
LANE_SETTING = "PATIENT_PROVIDER_LANE"
ATTEMPT_SETTINGS = {"demo": ("PATIENT_PROVIDER_DEMO_ATTEMPTS", 6), "test": ("PATIENT_PROVIDER_TEST_ATTEMPTS", 2)}
PROVIDER_LABEL = "Databricks endpoint {endpoint} (experimental language model, not clinically validated)"
SETUP_PROBLEM = ("Symptom assessment is unavailable on this server. You can write a description, but it will not "
                 "be sent anywhere or assessed.")
_CAP = re.compile(r"[0-9]{1,2}", re.ASCII)
_log = logging.getLogger(__name__)
_reported = set()


def provider_mode(environ):
    """Decide from the server's own settings whether an assessment provider is on.

    Off unless PATIENT_PROVIDER is set. A provider that is asked for but only partly or wrongly set
    up is a problem, never a guess and never a fallback. The problems are for the operator: they
    name settings, never repeat a value, and are not shown to the patient.
    """
    chosen = (environ.get(PROVIDER_SETTING) or "").strip()
    if not chosen:
        return {"mode": "off", "problems": []}
    problems = []
    if chosen != DATABRICKS:
        problems.append(f"{PROVIDER_SETTING} does not name a provider this app can use")
    endpoint = (environ.get(ENDPOINT_SETTING) or "").strip()
    if endpoint not in ENDPOINTS:
        problems.append(f"{ENDPOINT_SETTING} is not set to a supported endpoint")
    lane = (environ.get(LANE_SETTING) or "demo").strip()
    if lane not in ATTEMPT_SETTINGS:
        problems.append(f"{LANE_SETTING} is not demo or test")
    attempts = {}
    for name, (setting, most) in ATTEMPT_SETTINGS.items():
        text = (environ.get(setting) or "0").strip()
        if not _CAP.fullmatch(text) or int(text) > most:  # ASCII digits only, so int() cannot raise
            problems.append(f"{setting} is not a whole number from 0 to {most}")
        else:
            attempts[name] = int(text)
    if not problems and attempts[lane] == 0:
        problems.append(f"{ATTEMPT_SETTINGS[lane][0]} allows no requests")
    if problems:
        return {"mode": "problem", "problems": problems}
    return {"mode": DATABRICKS, "problems": [], "endpoint": endpoint, "lane": lane,
            "demo_attempts": attempts["demo"], "test_attempts": attempts["test"]}


def off_notice(environ):
    """What the patient is told while no provider is on. A patient cannot act on a server setting, so a
    setup problem is only said to be unavailable. The operator reads which settings from the server
    log or from `provider_mode`."""
    return SETUP_PROBLEM if provider_mode(environ)["problems"] else SWITCHED_OFF


def _databricks_factory():
    if __package__:
        from .patient_intake.providers.databricks_config import configured_databricks_provider
    else:
        from patient_intake.providers.databricks_config import configured_databricks_provider
    return configured_databricks_provider


def compose(environ=None):
    """Return (service, provider label) for one encounter.

    This is the only place an assessment provider enters the screen. With no provider setting the
    service has no provider and the runtime reports the assessment as unavailable. The one provider
    this app can switch on is the team's experimental Databricks interview, through its own server
    factory: that factory owns the workspace credentials, the per-worker request caps and the
    transport. Nothing here reads a secret, and no test story or fixture lives here.
    """
    settings = provider_mode(os.environ if environ is None else environ)
    provider = None
    if settings["problems"] and tuple(settings["problems"]) not in _reported:  # once per worker, not per redraw
        _reported.add(tuple(settings["problems"]))
        _log.warning("Patient assessment provider is off: %s", "; ".join(settings["problems"]))
    if settings["mode"] == DATABRICKS:
        try:
            provider = _databricks_factory()(
                endpoint=settings["endpoint"], enabled=True, lane=settings["lane"],
                demo_attempts=settings["demo_attempts"], test_attempts=settings["test_attempts"])
        except ValueError:  # for example the settings changed after this worker started
            provider = None
    if provider is None:
        return PatientIntakeService(interview=PatientInterview(), handoff=PatientHandoff()), None
    service = PatientIntakeService(interview=PatientInterview(), provider=provider,
                                   provider_identity=provider.identity, handoff=PatientHandoff())
    return service, PROVIDER_LABEL.format(endpoint=settings["endpoint"])


def entry(st, other):
    """The switch at the top of the app. The patient screen is the product and comes first; `other`
    names the separate Find care screen."""
    return st.radio("Screen", [PATIENT, other], horizontal=True, key="view", label_visibility="collapsed")


def plain(text):
    """Provider and patient text is shown as written, never interpreted as Markdown or HTML."""
    out = str(text)
    for mark in "\\`*_{}[]()#+-.!|<>~$:&":
        out = out.replace(mark, "\\" + mark)
    return out


def step(view, *, has_statement, editing=False):
    """Name the one thing the screen shows for a runtime view. The view decides; the screen never guesses."""
    state = view.get("state")
    if editing:
        return "describe"
    if state == "draft":
        if not has_statement:
            return "describe"
        return "send" if view.get("consent") else "consent"
    if state == "awaiting_clarification":
        question = view.get("question")
        return "question" if isinstance(question, dict) and question.get("kind") in KINDS else "withheld"
    if state in ("urgent", "completed", "provider_stop", "unsupported", "assessment_in_progress"):
        return state
    return "unavailable"


def result_lines(view):
    """The words for an urgent or completed result, in reading order. Provider text is passed through unchanged."""
    urgency = view.get("urgency")
    lines = {
        "heading": URGENCY.get(urgency, "Assessment result"),
        "guidance": view.get("guidance") or "",
        "uncertainty": view.get("uncertainty") or "",
        "causes": list(view.get("possible_causes") or []),
        "provenance": (f"Assessed by {view.get('provider_id')}, version {view.get('provider_version')}, "
                       f"under policy {view.get('policy_version')}."),
        "next_step": None,
    }
    next_step = view.get("next_step")
    if isinstance(next_step, dict) and next_step.get("kind") == "consultation":
        code = next_step.get("specialty_code")
        lines["next_step"] = ("The provider suggests seeing a doctor" + (f" (specialty code {code})" if code else "")
                              + ". This is a suggestion from the provider, not a referral.")
    return lines


def reason_line(view):
    """Why there is no result, in words. An unknown reason code still gets a plain sentence."""
    reason = view.get("reason")
    if view.get("state") == "unsupported":
        return UNSUPPORTED.get(reason, UNSUPPORTED["unsupported"])
    if view.get("state") == "draft":
        if reason == "invalid_input":
            return ("That description could not be used. Write what is troubling you in your own words, within "
                    f"{MAX_DESCRIPTION:,} characters, and check the age is a whole number.")
        if reason == "consent_or_input_required":
            return "A description and your agreement to send it are both needed before an assessment."
        return None
    return UNAVAILABLE.get(reason, UNAVAILABLE["unavailable"])


def quantity(text):
    """Read a typed amount without rounding or converting it. Whole numbers stay whole."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("invalid_answer")
    try:
        return int(text) if text.lstrip("+-").isdigit() else float(text)
    except ValueError:
        raise ValueError("invalid_answer") from None


def answer_for(question, read):
    """Build the runtime's answer form for one question from what the patient entered.

    `read(suffix)` returns the entered value for one field of the question. Nothing is filled in on
    the patient's behalf: an unanswered optional item is left out, and no unit is preselected.
    """
    kind = question.get("kind")
    if kind == "item_presence":
        chosen = [{"id": item["id"], "presence": read(f"-{number}")}
                  for number, item in enumerate(question["items"]) if read(f"-{number}") is not None]
        if not chosen:
            raise ValueError("invalid_answer")
        return {"items": chosen}
    if kind == "quantity":
        unit = read("-unit")
        if unit is None:
            raise ValueError("invalid_answer")
        return {"value": quantity(read("")), "unit_id": unit}
    if kind == "multiple" or (kind == "catalog_selection" and question.get("selection") == "multiple"):
        value = [option["id"] for number, option in enumerate(question["options"]) if read(f"-{number}") is True]
    else:
        value = read("")
    if value in (None, "", []):
        raise ValueError("invalid_answer")
    return value


def destination_lines(result):
    """Words for the hospital check. A reviewed hospital is listed by its approved identifier only."""
    state = (result or {}).get("state")
    if state == "reviewed_destinations":
        names = [str(row.get("facility_id")) for row in result.get("destinations", []) if isinstance(row, dict)]
        return {"text": ("Reviewed hospitals for this kind of care are listed below. Whether they can see you "
                         "today is not known: phone before you travel."), "destinations": names}
    return {"text": DESTINATION.get(state, DESTINATION["navigation_unavailable"]), "destinations": []}


# ---------------------------------------------------------------------------------------------------
# The Streamlit screen. Everything below runs on the server, inside one browser session's state.
# ---------------------------------------------------------------------------------------------------

STYLE = """
<style>
.block-container { max-width: 44rem; padding-top: 2.5rem; }
.pt-emergency { border-left: 4px solid #b3261e; padding: .5rem .9rem; margin: .25rem 0 1rem;
                background: rgba(179, 38, 30, .07); font-weight: 600; }
</style>
"""


def _box(st):
    return st.session_state.setdefault(STATE_KEY, {"visit": 0})


def _drop(st, *prefixes):
    """Remove widget values the screen no longer needs, so the encounter store is the only copy."""
    for key in [key for key in st.session_state if isinstance(key, str) and key.startswith(prefixes)]:
        del st.session_state[key]


def _forget(st, box, flash=None):
    """Drop the encounter and every widget value that belonged to it."""
    _drop(st, "pt-")
    visit = box.get("visit", 0) + 1
    box.clear()
    box.update(visit=visit)
    if flash:
        box["flash"] = flash


def _statement(handle):
    """The patient's own current description and age, read back from the encounter store."""
    try:
        interview = handle.read()[1].get("interview")
        return interview["source"]["description"], interview["context"].get("age_years")
    except (PatientSessionError, KeyError, TypeError, AttributeError):
        return None


def _act(st, action):
    """Run one runtime step for one button press, and turn every failure into a plain message."""
    box = _box(st)
    box.pop("destination", None)
    try:
        action(box)
    except PatientSessionError as error:
        if error.code == "session_revision_stale":
            box["flash"] = OUT_OF_DATE
        elif error.code == "session_encounter_unavailable" and "session" in box:
            _forget(st, box, ENDED.get(box["session"].status, ENDED["expired"]))
        else:
            box["flash"] = FAILED
    except ValueError as error:
        code = str(error)
        box["flash"] = (BAD_ANSWER if code == "invalid_answer" else OUT_OF_DATE
                        if code in ("revision_stale", "question_stale", "assessment_action_unavailable",
                                    "confirmation_unavailable", "confirmation_invalid") else FAILED)
    except Exception:  # noqa: BLE001 - a patient never sees a stack trace or an echoed value
        box["flash"] = FAILED


def _begin(st):
    def action(box):
        if st.session_state.get(f"pt-agree-{box['visit']}") is not True:
            box["flash"] = "Tick the box to agree before you start."
            return
        service, provider = compose()
        session = PatientSession(notice_version=NOTICE_VERSION, ttl_seconds=TTL_SECONDS)
        handle = session.open(consent=True, notice_version=NOTICE_VERSION)
        box.update(session=session, handle=handle, service=service, provider=provider, opened=time.monotonic())
    _act(st, action)


def _start_over(st):
    def action(box):
        try:
            box["session"].reset(box["handle"])
        except PatientSessionError:
            pass  # already expired: the store is empty either way
        _forget(st, box, ENDED["reset"])
    _act(st, action)


def _save(st):
    def action(box):
        key = box["visit"]
        age = st.session_state.get(f"pt-age-{key}")
        view = box["service"].edit(
            box["handle"], box["revision"], description=st.session_state.get(f"pt-description-{key}") or "",
            context={"age_years": int(age) if age is not None else None, "language": LANGUAGE})
        box["editing"] = view["state"] == "draft" and view.get("reason") == "invalid_input"
        if not box["editing"]:
            _drop(st, f"pt-description-{key}", f"pt-age-{key}")
        if box["provider"] is None and view["state"] == "draft" and not view.get("reason"):
            # Nothing can receive the description. Ask the runtime, which answers that it is unavailable.
            box["service"].assess(box["handle"], view["revision"])
    _act(st, action)


def _agree_and_send(st):
    def action(box):
        view = box["service"].consent(box["handle"], box["revision"], granted=True)
        if view.get("consent"):
            box["service"].assess(box["handle"], view["revision"])
    _act(st, action)


def _withdraw(st):
    _act(st, lambda box: box["service"].consent(box["handle"], box["revision"], granted=False))


def _send(st):
    _act(st, lambda box: box["service"].assess(box["handle"], box["revision"]))


def _answer(st, question, skip=False):
    def action(box):
        key = f"pt-answer-{box['visit']}-{question['issuance_id']}"
        value = {"skip": True} if skip else answer_for(question, lambda suffix: st.session_state.get(key + suffix))
        view = box["service"].answer(box["handle"], box["revision"], question_id=question["issuance_id"], answers=value)
        _drop(st, key)
        box["service"].assess(box["handle"], view["revision"])
    _act(st, action)


def _edit(st, editing=True):
    _box(st).update(editing=editing)
    _box(st).pop("destination", None)


def _check_hospitals(st):
    def action(box):
        service, handle, revision = box["service"], box["handle"], box["revision"]
        result = service.navigate(handle, revision, confirmation=service.confirm(handle, revision))
        box["destination"] = {"revision": revision, "result": result}
    _act(st, action)


def _welcome(st, box):
    st.subheader("Before you start")
    st.markdown("\n".join("- " + line.format(minutes=TTL_SECONDS // 60) for line in NOTICE))
    if compose()[1] is None:
        st.warning(off_notice(os.environ))
    with st.form(f"pt-begin-{box['visit']}", border=False):
        st.checkbox("I agree to what I write being kept in this server's memory for this visit.",
                    key=f"pt-agree-{box['visit']}")
        st.form_submit_button("Start", type="primary", on_click=_begin, args=(st,))


def _describe(st, box, said):
    st.subheader("What is troubling you?")
    key = box["visit"]
    with st.form(f"pt-describe-{key}", border=False):
        # The earlier words come back from the encounter store, never from a copy kept by the screen.
        st.text_area("Describe it in your own words", value=said[0] if said else "", key=f"pt-description-{key}",
                     max_chars=MAX_DESCRIPTION, height=180,
                     help="For example what you feel, where, since when, and what makes it better or worse.")
        st.number_input("Age in years (optional)", min_value=0, max_value=120, step=1,
                        value=said[1] if said else None, key=f"pt-age-{key}")
        st.caption(ENGLISH_ONLY + " Saving does not send your words anywhere. Changing your description later "
                   "clears any result and asks for your agreement again.")
        st.form_submit_button("Save and continue", type="primary", on_click=_save, args=(st,))
    if said:
        st.button("Keep what I wrote before", on_click=_edit, args=(st, False))


def _said(st, said):
    if said:
        st.caption("You wrote")
        st.text(said[0])
        st.caption(UNINTERPRETED)


def _question(st, box, question):
    kind, key = question["kind"], f"pt-answer-{box['visit']}-{question['issuance_id']}"
    labels = {option["id"]: plain(option["label"]) for option in question.get("options", [])}
    st.subheader("A question about what you wrote" if kind == "evidence_review" else "A follow-up question")
    with st.form(f"pt-question-{key}", border=False):
        if kind == "evidence_review":
            evidence = question.get("evidence", {})
            st.markdown("The assessment provider understood this from your words:")
            st.markdown(f"**{plain(evidence.get('label', ''))}** ({PRESENCE.get(evidence.get('presence'), 'not clear')}, "
                        f"{TEMPORALITY.get(evidence.get('temporality'), 'timing not clear')})")
            st.caption("This is the provider's reading, not a finding. Your answer is recorded as yours.")
        if kind == "text":
            st.text_area(plain(question["prompt"]), key=key, max_chars=MAX_ANSWER)
        elif kind == "multiple" or (kind == "catalog_selection" and question.get("selection") == "multiple"):
            st.markdown(plain(question["prompt"]))
            st.caption("Choose all that apply.")
            for number, label in enumerate(labels.values()):
                st.checkbox(label, key=f"{key}-{number}")
        elif kind == "item_presence":
            st.markdown(plain(question["prompt"]))
            for number, item in enumerate(question["items"]):
                choices = {choice["id"]: plain(choice["label"]) for choice in item["choices"]}
                st.radio(plain(item["label"]) + ("" if item["required"] else " (optional)"), list(choices),
                         format_func=choices.get, index=None, horizontal=True, key=f"{key}-{number}")
        elif kind == "quantity":
            units = {unit["id"]: unit for unit in question["units"]}
            st.text_input(plain(question["prompt"]), key=key, max_chars=32, help="Type a number.")
            st.radio("Unit", list(units), index=None, key=f"{key}-unit", format_func=lambda unit: (
                f"{plain(units[unit]['label'])} ({units[unit]['min']:g} to {units[unit]['max']:g}"
                + (", whole numbers only)" if units[unit]["integer_only"] else ")")))
        else:
            st.radio(plain(question["prompt"]), list(labels), format_func=labels.get, index=None, key=key)
        st.caption("Your answer is sent to the assessment provider.")
        st.form_submit_button("Send answer", type="primary", on_click=_answer, args=(st, question))
        if question.get("optional") is True:
            st.form_submit_button("Skip this question", on_click=_answer, args=(st, question, True))


def _result(st, box, view):
    lines = result_lines(view)
    (st.error if view["state"] == "urgent" else st.info)(lines["heading"])
    st.markdown(plain(lines["guidance"]))
    if view["state"] == "urgent":
        st.markdown(f'<div class="pt-emergency">{html.escape(EMERGENCY)}</div>', unsafe_allow_html=True)
    if lines["next_step"]:
        st.markdown(plain(lines["next_step"]))
    st.subheader("How sure this is")
    st.markdown(plain(lines["uncertainty"]))
    if lines["causes"]:
        st.subheader("Possible causes")
        st.caption("Possibilities the provider listed, in no order of likelihood. None of them is a diagnosis.")
        st.markdown("\n".join("- " + plain(cause) for cause in lines["causes"]))
    st.caption(plain(lines["provenance"]) + " " + NOT_A_DOCTOR)
    if view["state"] != "completed":
        st.caption("No hospital is suggested for an urgent result. Follow the guidance above.")
        return
    st.subheader("Where to go")
    shown = box.get("destination")
    if shown and shown["revision"] == view["revision"]:
        found = destination_lines(shown["result"])
        st.markdown(found["text"])
        for name in found["destinations"]:
            st.markdown("- " + plain(name))
    else:
        st.caption("Pressing this says you have read the result above. It is not a doctor's order, and it does "
                   "not book anything.")
        st.button("I have read this. Check for a reviewed hospital", on_click=_check_hospitals, args=(st,))


def expiry_delay(opened, now, ttl):
    """Seconds until an open page must look again: just after the visit's time limit, never sooner than one second."""
    return max(1.0, ttl - (now - opened) + 1.0)


def _watch_expiry(st, box):
    """Clear an idle open page at the time limit. One timed check, not a poll: nothing is sent while waiting."""
    @st.fragment(run_every=expiry_delay(box.get("opened", time.monotonic()), time.monotonic(), TTL_SECONDS))
    def check():
        current = st.session_state.get(STATE_KEY, {})
        if "session" in current and current["session"].status != "active":
            st.rerun()  # the whole page: the next draw finds the encounter gone and shows only the notice
    check()


def render():
    """Draw the patient screen for the current server state. Called by app.py on every run."""
    import streamlit as st

    st.markdown(STYLE, unsafe_allow_html=True)
    st.title("Check your symptoms")
    st.markdown(f'<div class="pt-emergency">{html.escape(EMERGENCY)}</div>', unsafe_allow_html=True)
    box = _box(st)
    view = None
    if "handle" in box:
        try:
            view = box["service"].view(box["handle"])
        except PatientSessionError:
            _forget(st, box, ENDED.get(box["session"].status, ENDED["expired"]))
        except Exception:  # noqa: BLE001
            _forget(st, box, FAILED)
    flash = box.pop("flash", None)
    if flash:
        st.warning(flash)
    if view is None:
        _welcome(st, box)
        return

    box["revision"] = view["revision"]
    _watch_expiry(st, box)
    said = _statement(box["handle"])
    now = step(view, has_statement=said is not None, editing=box.get("editing", False))
    if box["provider"] is None:
        st.warning(off_notice(os.environ))
    if view["state"] == "draft" and reason_line(view):
        st.warning(reason_line(view))

    if now == "describe":
        _describe(st, box, said)
    else:
        _said(st, said)
    if now == "consent":
        st.subheader("Send your description for assessment?")
        st.markdown(f"To assess it, your description, your age and your answers to any follow-up questions are sent "
                    f"to **{plain(box['provider'])}**. "
                    "Nothing is sent until you agree, and you can withdraw your agreement afterwards. " + PROVIDER_COPY)
        st.button("I agree. Send it for assessment", type="primary", on_click=_agree_and_send, args=(st,))
    elif now == "send":
        st.subheader("Ready to assess")
        st.caption("You have agreed to send your description. Nothing has been assessed yet.")
        st.button("Send for assessment", type="primary", on_click=_send, args=(st,))
    elif now == "question":
        _question(st, box, view["question"])
    elif now in ("urgent", "completed"):
        _result(st, box, view)
    elif now == "provider_stop":
        st.subheader("This assessment has stopped")
        st.markdown(plain(view.get("guidance") or ""))
        st.caption(plain(f"Message from {view.get('provider_id')}, version {view.get('provider_version')}.") + " " + STOPPED)
    elif now == "withheld":
        st.subheader("A question could not be shown")
        st.markdown(QUESTION_WITHHELD + " No result is available. Change your description or start over.")
    elif now == "unsupported":
        st.subheader("This could not be assessed")
        st.markdown(reason_line(view))
        st.markdown("No assessment result was given. If you are worried, see a doctor.")
    elif now == "assessment_in_progress":
        st.subheader("An assessment did not finish")
        st.markdown("The last request was interrupted, and its result could not be confirmed. Your description may "
                    "have been sent. Change your description or start over.")
    elif now == "unavailable":
        st.subheader("No assessment is available")
        # "Not sent" is said only where the runtime proves it: this server has no provider at all.
        st.markdown(NO_PROVIDER if box["provider"] is None else reason_line(view))
        st.markdown(NOT_ASSESSED if box["provider"] is None else UNCONFIRMED)
        if box["provider"] is not None and view.get("reason") in ("unavailable", "timeout", "rate_limited"):
            st.button("Try again", on_click=_send, args=(st,))

    st.divider()
    left, middle, right = st.columns(3)
    if now != "describe":
        left.button("Change my description", on_click=_edit, args=(st,))
    if view.get("consent"):
        middle.button("Withdraw my agreement", on_click=_withdraw, args=(st,))
    right.button("Start over", on_click=_start_over, args=(st,), help="Clears everything you wrote.")
    st.caption(f"This visit clears itself {TTL_SECONDS // 60} minutes after you pressed Start. Policy {POLICY_VERSION}.")
