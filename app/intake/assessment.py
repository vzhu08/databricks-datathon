"""Evaluate fictional intake and bind search eligibility to released script editions."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from weakref import WeakKeyDictionary

SCHEMA_VERSION = "intake.v1"
SCENARIO_SCHEMA_VERSION = "intake.scenario.v1"
POLICY_VERSION = "intake-policy.v1.1"

_PAYLOAD = {"schema_version", "mode", "scenario_id", "input_revision", "answers"}
_SCENARIO = {
    "schema_version", "scenario_id", "scenario_version", "synthetic", "presenting_problem",
    "concern_category", "service", "known_answers", "clinician_plan",
}
_MESSAGES = {
    "invalid_input": "This fictional intake could not be read. Check the scenario and answers.",
    "more_information_needed": "More information is needed before this scenario can continue.",
    "unsupported_care_need": "This fictional case falls outside the care covered by this demonstration.",
    "clinician_assessment_needed": "The fictional patient needs a clinician's assessment before a campus search.",
    "confirmation_required": "Check the care summary against the story, then confirm it.",
    "ready": "The summary is confirmed. Choose a fictional starting point to find a campus.",
}
_REASONS = {
    "intake_invalid_input": "The input does not match the fictional intake contract.",
    "intake_scenario_unreviewed": "This edition of the fictional story and care facts needs review before a campus search.",
    "intake_question_pending": "A question still needs an answer.",
    "intake_answers_unresolved": "An answer is unknown or the reported facts disagree.",
    "intake_population_unsupported": "The demonstration covers adults who are not pregnant.",
    "intake_concern_unsupported": "The scenario asks for care outside the three modeled services.",
    "intake_concern_mismatch": "The service and the presenting concern in the fictional script disagree.",
    "intake_confirmation_required": "The visitor must confirm the current care summary.",
    "intake_confirmation_stale": "The answers, scenario or policy changed after confirmation.",
    "intake_confirmation_invalid": "The supplied confirmation could not be verified.",
    "intake_confirmed": "The visitor confirmed this care summary for the current inputs.",
}
_CONCERNS = {
    "injury": "Injury assessment", "kidney_symptom": "Kidney-related symptoms",
    "mri_referral": "MRI referral", "dialysis_plan": "Scheduled dialysis",
    "general_medical": "General medical concern", "cardiac": "Cardiac concern",
    "stroke": "Stroke-related concern", "other": "Other concern",
}
_EXPECTED_SERVICE = {"injury": "trauma_care", "mri_referral": "mri", "dialysis_plan": "dialysis"}
_RATIONALE = {"kidney_symptom": "niddk_dialysis_plan", "dialysis_plan": "niddk_dialysis_plan",
              "mri_referral": "rcr_mri_referral"}
_POLICY_SOURCE = "intake_synthetic_policy_v1"


def _distinct_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Duplicate key in reviewed scenario manifest")
    return fields


def _load_reviewed_editions(path):
    """Load release configuration once, independently of runtime scenario input."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_distinct_fields)
        if type(manifest) is not dict or set(manifest) != {"schema_version", "editions"}:
            return frozenset()
        if manifest["schema_version"] != "intake.editions.v1" or type(manifest["editions"]) is not list:
            return frozenset()
        pins = {}
        for row in manifest["editions"]:
            if type(row) is not dict or set(row) != {"scenario_id", "scenario_version", "sha256"}:
                return frozenset()
            identity = (row["scenario_id"], row["scenario_version"])
            digest = row["sha256"]
            if (not all(type(x) is str and x.strip() for x in identity) or identity in pins
                    or type(digest) is not str or len(digest) != 64
                    or any(ch not in "0123456789abcdef" for ch in digest)):
                return frozenset()
            pins[identity] = digest
        return frozenset((*identity, digest) for identity, digest in pins.items())
    except (OSError, ValueError, RecursionError):
        return frozenset()


_REVIEWED_EDITIONS = _load_reviewed_editions(
    Path(__file__).resolve().parents[2] / "contracts" / "intake" / "reviewed_scenarios.json"
)


def _edition_is_reviewed(scenario):
    encoded = json.dumps(scenario, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return (scenario["scenario_id"], scenario["scenario_version"], digest) in _REVIEWED_EDITIONS


def assessment_catalogue():
    """Fresh display strings. The first message ID in a response is primary."""
    return {
        "messages": {"intake." + key: value for key, value in _MESSAGES.items()},
        "reasons": _REASONS.copy(), "concerns": _CONCERNS.copy(),
        "sources": {_POLICY_SOURCE: {
            "title": "Fictional intake scope and referral rules",
            "url": "contracts/intake/README.md", "version": POLICY_VERSION,
        }},
    }


class _Receipt:
    __slots__ = ("__weakref__",)

    def __reduce__(self):
        raise TypeError("Intake confirmations are local to this Python process")


# A receipt has no caller-editable binding. Only objects issued by confirm_intake
# appear here; collecting a receipt discards its entry as well.
_issued = WeakKeyDictionary()


def _blank(confirmation):
    return {
        "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION, "mode": "synthetic",
        "scenario_id": None, "scenario_version": None, "input_revision": None, "input_fingerprint": None,
        "reason_codes": ["intake_invalid_input"], "rule_ids": [], "source_ids": [],
        "message_ids": ["intake.invalid_input"], "state": "invalid_input",
        "concerns": [], "unknowns": [], "next_question_ids": [],
        "clinician_confirmation": "not_required", "care_summary": None, "request": None,
        "confirmation_status": "absent" if confirmation is None else "invalid",
    }


def _text(value):
    return type(value) is str and bool(value.strip())


def _valid_envelopes(p, s):
    return (type(p) is dict and set(p) == _PAYLOAD and p["schema_version"] == SCHEMA_VERSION
            and p["mode"] == "synthetic" and _text(p["scenario_id"])
            and type(p["input_revision"]) is int and p["input_revision"] >= 0
            and type(p["answers"]) is dict and type(s) is dict and set(s) == _SCENARIO
            and s["schema_version"] == SCENARIO_SCHEMA_VERSION and s["synthetic"] is True
            and s["scenario_id"] == p["scenario_id"] and _text(s["scenario_version"])
            and type(s["known_answers"]) is dict)


def _bind(out, p, s, receipt):
    # Only strict JSON input has a canonical binding. JSON serialization alone
    # would silently accept tuples and integer keys as valid JSON arrays/strings.
    versioned = [POLICY_VERSION, p, s]
    wire = json.dumps(versioned, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    snapshot = json.loads(wire)
    if snapshot != versioned:
        raise ValueError("Expected JSON fields")
    fingerprint = hashlib.sha256(wire.encode("ascii")).hexdigest()
    if type(receipt) is _Receipt and receipt in _issued:
        out["confirmation_status"] = "current" if _issued[receipt] == fingerprint else "stale"
    out.update(scenario_id=p["scenario_id"], scenario_version=s["scenario_version"],
               input_revision=p["input_revision"], input_fingerprint=fingerprint)
    return snapshot[1], snapshot[2]


def _state(out, state, reasons, *, messages=()):
    out["state"] = state
    out["reason_codes"] = list(reasons)
    out["message_ids"] = list(messages) if messages else ["intake." + state]
    return out


def _with_concern(out, category, reason):
    sources = [_RATIONALE.get(category, _POLICY_SOURCE)]
    out["concerns"] = [{"category": category, "reason_code": reason, "source_ids": sources}]
    out["source_ids"] = list(dict.fromkeys([*out["source_ids"], *sources]))


def _referral(out, scenario):
    from .referral_gate import evaluate_referral_gate

    category = scenario["concern_category"]
    service = scenario["service"]
    if service is not None and service != _EXPECTED_SERVICE.get(category):
        return _state(out, "invalid_input", ["intake_concern_mismatch"])

    gate = evaluate_referral_gate(service=service, clinician_plan=scenario["clinician_plan"],
                                  scenario_id=scenario["scenario_id"], scenario_version=scenario["scenario_version"])
    reasons = gate["reason_codes"]
    out["clinician_confirmation"] = gate["clinician_confirmation"]
    if gate["state"] != "eligible":
        _with_concern(out, category, reasons[0])
        return _state(out, gate["state"], reasons)

    # Preserve warning and abstention outcomes. Only a released edition may
    # advance to a summary, including when presented with an old receipt.
    if not _edition_is_reviewed(scenario):
        out["clinician_confirmation"] = "invalid"
        return _state(out, "invalid_input", ["intake_scenario_unreviewed"])

    _with_concern(out, category, reasons[0])
    request = gate["candidate_request"]
    out["care_summary"] = {**deepcopy(request), "authority": scenario["clinician_plan"]["authority"]}
    status = out["confirmation_status"]
    if status != "current":
        suffix = "required" if status == "absent" else status
        return _state(out, "confirmation_required", [*reasons, "intake_confirmation_" + suffix])
    out["request"] = deepcopy(request)
    return _state(out, "ready", [*reasons, "intake_confirmed"])


def assess_intake(payload, *, scenario, confirmation=None):
    """Assess current visitor input against a trusted catalogue script. No I/O."""
    out = _blank(confirmation)
    if not _valid_envelopes(payload, scenario):
        return out
    try:
        payload, scenario = _bind(out, payload, scenario, confirmation)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return out

    from .danger_signs import evaluate_danger_signs
    from .questions import next_question

    answers = payload["answers"]
    known = scenario["known_answers"]
    danger = evaluate_danger_signs(answers, known_answers=known)
    out["rule_ids"] = list(danger["rule_ids"])
    out["source_ids"] = list(danger["source_ids"])
    if danger["state"] == "emergency_escalation":
        out["unknowns"] = _uncertainties(danger)
        return _state(out, "emergency_escalation", danger["reason_codes"], messages=danger["message_ids"])

    if not (_text(scenario["presenting_problem"]) and _text(scenario["concern_category"])
            and scenario["concern_category"] in _CONCERNS
            and (scenario["service"] is None or scenario["service"] in ("mri", "dialysis", "trauma_care"))):
        return out

    step = next_question(answers, context_answers=known, warning_state=danger["state"])
    out["unknowns"] = _uncertainties(step)
    if step["status"] == "invalid" or danger["invalid_question_ids"]:
        return out
    if step["status"] == "unsupported":
        return _state(out, "unsupported_care_need", ["intake_population_unsupported"])
    category = scenario["concern_category"]
    if danger["state"] == "no_reported_warning" and category not in _EXPECTED_SERVICE and category != "kidney_symptom":
        _with_concern(out, category, "intake_concern_unsupported")
        return _state(out, "unsupported_care_need", ["intake_concern_unsupported"])
    if step["next_question_ids"]:
        out["next_question_ids"] = list(step["next_question_ids"])
        return _state(out, "more_information_needed", ["intake_question_pending"])
    if danger["state"] != "no_reported_warning":
        return _state(out, "more_information_needed", danger["reason_codes"], messages=danger["message_ids"])
    if step["status"] != "complete" or out["unknowns"]:
        return _state(out, "more_information_needed", ["intake_answers_unresolved"])
    return _referral(out, scenario)


def _uncertainties(result):
    return sorted({qid for field in ("missing_question_ids", "unknown_question_ids",
                                     "conflicting_question_ids", "invalid_question_ids")
                   for qid in result[field]})


def confirm_intake(payload, *, scenario):
    """Record the trusted visitor action only for an eligible current summary."""
    assessment = assess_intake(payload, scenario=scenario)
    if assessment["state"] != "confirmation_required":
        raise ValueError("The current assessment has no confirmable care summary")
    receipt = _Receipt()
    _issued[receipt] = assessment["input_fingerprint"]
    return receipt
