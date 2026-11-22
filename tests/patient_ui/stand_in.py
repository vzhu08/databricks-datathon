"""Browser-check launcher: the real app and patient runtime with a scripted stand-in provider.

    python tests/patient_ui/stand_in.py PORT [VISIT_SECONDS]

Test tooling only. Nothing here ships in app/, and every reply is invented: it says nothing about a
real provider or about clinical accuracy. Each visit gets its own stand-in, composed through the
screen's one provider seam (`patient_ui.compose`). VISIT_SECONDS (1 to 900, default 900) shortens
the session store's hard time limit so expiry can be watched.

A marker word in the description picks the scenario:

    STANDIN-URGENT       an urgent result at once
    STANDIN-STOP         a terminal provider stop
    STANDIN-SELFCARE     a completed self-care result
    STANDIN-OUTAGE       the provider raises on every call
    STANDIN-RATE         the provider answers rate_limited
    STANDIN-BAD          a malformed reply
    STANDIN-UNSUPPORTED  the provider answers unsupported
    STANDIN-LOOP         follow-up questions until a limit is reached
    (none)               evidence review, an item list, an optional amount, one choice, then a completed result

Ages under 18 are outside the stand-in interview's supported range. Answering "I'm not sure" or
"Does not match my statement" to the evidence review ends in the unsupported-correction state.
"""
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP))

import patient_ui as screen  # noqa: E402

IDENTITY = ("stand-in-provider", "invented-replies-1")
LABEL = "Stand-in provider (invented replies, test only)"
V2 = {"schema": "patient-question.v2", "options": []}
YES_NO = [{"id": "present", "label": "Yes"}, {"id": "absent", "label": "No"}, {"id": "unknown", "label": "Don't know"}]


def ask(question, continuation=None):
    return {"state": "awaiting_clarification", "question": question,
            **({"continuation": continuation} if continuation else {})}


REVIEW = ask({"id": "q-review", "kind": "evidence_review", "prompt": "unused", "options": [
    {"id": "confirm", "label": "a"}, {"id": "uncertain", "label": "b"}, {"id": "disagree", "label": "c"}],
    "evidence": {"concept_id": "stand-in-concept-1", "label": "Invented finding A", "presence": "present",
                 "temporality": "current", "source_ref": "description"}}, "stand-in-turn-1")
ITEMS = ask({**V2, "id": "q-items", "kind": "item_presence", "prompt": "Invented item question: do any of these apply?",
             "items": [{"id": "item-1", "label": "Invented item one", "required": True, "choices": YES_NO},
                       {"id": "item-2", "label": "Invented item two", "required": False, "choices": YES_NO[:2]}]})
AMOUNT = ask({**V2, "id": "q-amount", "kind": "quantity", "prompt": "Invented amount question: for how long?",
              "optional": True, "units": [
                  {"id": "unit-days", "label": "days", "min": 1, "max": 30, "integer_only": True},
                  {"id": "unit-weeks", "label": "weeks", "min": 0.5, "max": 8, "integer_only": False}]})
CHOICE = ask({"id": "q-choice", "kind": "single", "prompt": "Invented follow-up question: has it changed since it began?",
              "options": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}, {"id": "unsure", "label": "I am not sure"}]})
RESULT = {"guidance": "Invented guidance text from the stand-in provider.",
          "uncertainty": "Invented uncertainty statement from the stand-in provider."}
DONE = {"state": "completed", **RESULT, "urgency": "consultation", "possible_causes": ["Invented cause one", "Invented cause two"],
        "next_step": {"kind": "consultation", "specialty_code": None}}
SELF_CARE = {"state": "completed", **RESULT, "urgency": "self_care", "possible_causes": ["Invented cause one"], "next_step": None}
URGENT = {"state": "urgent", **RESULT, "urgency": "emergency", "possible_causes": [], "next_step": None}
STOP = {"state": "provider_stop", "guidance": "Invented stop message from the stand-in provider."}
FIXED = {"STANDIN-URGENT": URGENT, "STANDIN-STOP": STOP, "STANDIN-SELFCARE": SELF_CARE,
         "STANDIN-RATE": {"state": "provider_unavailable", "reason": "rate_limited"},
         "STANDIN-UNSUPPORTED": {"state": "unsupported", "reason": "unsupported"},
         "STANDIN-BAD": {"state": "completed", "guidance": "", "likelihood": 0.9}}


class StandIn:
    """One visit's scripted provider. `calls` counts every request it received."""

    def __init__(self):
        self.calls = 0

    def assess(self, interview, *, continuation=None):
        self.calls += 1
        description = interview["source"]["description"]
        if "STANDIN-OUTAGE" in description:
            raise TimeoutError("stand-in outage")
        reply = next((reply for marker, reply in FIXED.items() if marker in description), None)
        if reply is None and "STANDIN-LOOP" in description:
            reply = ask({**CHOICE["question"], "id": f"q-loop-{self.calls}"})
        if reply is None:
            turn = len(interview["answers"])
            reply = (REVIEW, ITEMS, AMOUNT, CHOICE, DONE)[min(turn, 4)]
        return {"provider_id": IDENTITY[0], "provider_version": IDENTITY[1], **reply}


def compose():
    service = screen.PatientIntakeService(
        interview=screen.PatientInterview(supported_age_range=(18, 120)), provider=StandIn(),
        provider_identity=IDENTITY, handoff=screen.PatientHandoff())
    return service, LABEL


if __name__ == "__main__":
    from streamlit.web import cli

    screen.compose = compose
    if len(sys.argv) > 2:
        screen.TTL_SECONDS = int(sys.argv[2])
    sys.argv = ["streamlit", "run", str(APP / "app.py"), "--server.headless", "true", "--server.address", "127.0.0.1",
                "--server.port", sys.argv[1], "--browser.gatherUsageStats", "false"]
    cli.main()
