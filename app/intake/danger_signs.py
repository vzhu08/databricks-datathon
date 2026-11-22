"""Structured warning checks for the offline fictional intake. No text parsing or I/O."""

from collections.abc import Mapping
from copy import deepcopy


# Ordered for repeatable answers and display when several warnings are reported.
_RULES = {
    "chest_pain": ("New chest pain", "The fictional case reports new chest pain.",
                   ("nhs_chest_pain", "las_emergency")),
    "stroke_like": ("Sudden stroke-like signs",
                    "The case reports sudden face, arm or speech changes now or within "
                    "the past 24 hours, even if they have stopped.", ("nhs_stroke",)),
    "severe_breathing_difficulty": ("Severe difficulty breathing",
                                    "The case reports severe trouble breathing now.",
                                    ("nhs_breathing",)),
    "unresponsive": ("Unresponsive", "The person in the story cannot be woken now.",
                     ("las_emergency",)),
    "heavy_bleeding": ("Heavy bleeding", "The case reports heavy bleeding now.",
                       ("las_emergency",)),
}

_MESSAGES = {
    "intake.warning.emergency.v1": (
        "The fictional case has a reported warning sign. Hospital search stops here. "
        "For an actual emergency in India, call 112. Do not drive yourself. "
        "Follow the emergency operator’s instructions."
    ),
    "intake.warning.unresolved.v1": (
        "Some warning answers are missing, uncertain, inconsistent or unreadable."
    ),
    "intake.warning.none_reported.v1": (
        "The fictional case has explicit negative answers for all five listed warnings. "
        "Other care needs may still require assessment."
    ),
}

_SOURCES = {
    "nhs_chest_pain": {"title": "NHS · Chest pain",
                       "url": "https://www.nhs.uk/symptoms/chest-pain/",
                       "section": "Immediate action required"},
    "nhs_stroke": {"title": "NHS · Symptoms of a stroke",
                   "url": "https://www.nhs.uk/conditions/stroke/symptoms/",
                   "section": "Check for signs of a stroke / Immediate action required"},
    "nhs_breathing": {"title": "NHS · Shortness of breath",
                      "url": "https://www.nhs.uk/symptoms/shortness-of-breath/",
                      "section": "Immediate action required (adult section)"},
    "las_emergency": {"title": "London Ambulance Service · When to call 999",
                      "url": "https://www.londonambulance.nhs.uk/our-services/emergency-care/calling-999/",
                      "section": "Examples of when to call 999"},
    "mha_erss_112": {"title": "Ministry of Home Affairs, India · ERSS",
                     "url": "https://www.mha.gov.in/emergency-response-support-system-erss",
                     "section": "Emergency Response Support System (ERSS)"},
    "who_iitt_scope": {"title": "WHO · Interagency Integrated Triage Tool",
                       "url": "https://www.who.int/tools/triage",
                       "section": "Routine triage / Tool"},
    "rcr_mri_referral": {
        "title": "Clinical Imaging Board · MRI self-referral",
        "url": "https://www.rcr.ac.uk/our-services/management-service-delivery/"
               "clinical-imaging-board/clinical-imaging-board-statements/",
        "section": "2021 / Self-referral for MRI examination",
    },
    "niddk_dialysis_plan": {
        "title": "NIDDK · Choosing a Treatment for Kidney Failure",
        "url": "https://www.niddk.nih.gov/health-information/kidney-disease/"
               "kidney-failure/choosing-treatment",
        "section": "When do I have to start dialysis?",
    },
}


def warning_catalogue():
    """Rule ID to display row. Q owns the question and answer labels."""
    return {
        f"intake.warning.{key}.v1": {
            "question_id": f"warning.{key}", "label": label, "rationale": rationale,
            "source_ids": list(sources),
        }
        for key, (label, rationale, sources) in _RULES.items()
    }


def message_catalogue():
    """Message/reason ID to display string. The primary message is always first."""
    return _MESSAGES.copy()


def source_catalogue():
    """Source ID to display title, URL and section. Full scope is in docs/intake/sources.md."""
    return deepcopy(_SOURCES)


def evaluate_danger_signs(answers, *, known_answers=None):
    """Compare visitor answers with independent facts of the selected fictional story.

    Each layer maps full warning question IDs to exact string tokens. M/Q check
    non-warning questions. Preserve valid positives even beside malformed input.
    """
    layers = [answers]
    if known_answers is not None:
        layers.append(known_answers)
    invalid_layer = any(not isinstance(layer, Mapping) for layer in layers)
    mappings = [layer for layer in layers if isinstance(layer, Mapping)]
    triggered, sources = [], []
    missing, unknown, conflicting, invalid = [], [], [], []
    for key, (_, _, references) in _RULES.items():
        question = f"warning.{key}"
        observations = [layer[question] for layer in mappings if question in layer]
        tokens = {value for value in observations if type(value) is str}
        if not observations:
            missing.append(question)
        if invalid_layer or any(type(value) is not str for value in observations) or (
            tokens - {"yes", "no", "unknown", "conflicting"}
        ):
            invalid.append(question)
        if "unknown" in tokens:
            unknown.append(question)
        if "conflicting" in tokens or ("no" in tokens and tokens & {"yes", "unknown"}):
            conflicting.append(question)
        if "yes" in tokens:
            triggered.append(f"intake.warning.{key}.v1")
            sources.extend(references)

    # M validates the full schema. Also fail closed on an unfamiliar warning
    # in this standalone leaf, without reflecting arbitrary visitor strings.
    unknown_key = any(
        not isinstance(key, str) or (key.startswith("warning.") and key[8:] not in _RULES)
        for layer in mappings for key in layer
    )
    if triggered:
        state, message = "emergency_escalation", "intake.warning.emergency.v1"
        sources.append("mha_erss_112")
    elif missing or unknown or conflicting or invalid or unknown_key:
        state, message = "more_information_needed", "intake.warning.unresolved.v1"
    else:
        state, message = "no_reported_warning", "intake.warning.none_reported.v1"
    return {
        "state": state, "reason_codes": [message], "message_ids": [message],
        "rule_ids": triggered, "source_ids": list(dict.fromkeys(sources)),
        "missing_question_ids": missing, "unknown_question_ids": unknown,
        "conflicting_question_ids": conflicting, "invalid_question_ids": invalid,
    }
