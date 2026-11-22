"""Validate prior simulated clinician authority for a fictional scenario."""

_AUTHORITY_BY_SERVICE = {
    "dialysis": "simulated_treatment_plan",
    "mri": "simulated_clinician_referral",
    "trauma_care": "simulated_clinician_assessment",
}
_URGENCIES = frozenset({"routine", "time_sensitive", "highest"})
_PLAN_FIELDS = frozenset({
    "scenario_id", "scenario_version", "synthetic", "authority", "service",
    "urgency", "required_capabilities", "preferred_capabilities",
})

_REASONS = {
    "referral_service_unspecified": "This fictional scenario has no specified service. It needs a simulated clinician assessment before a search can start.",
    "referral_service_unsupported": "The requested service is outside this fictional finder’s scope.",
    "referral_plan_missing": "This scenario needs a matching simulated clinician plan, referral or assessment.",
    "referral_plan_invalid": "The simulated clinician plan could not be verified for this scenario.",
    "referral_plan_stale": "The simulated clinician plan belongs to a different fictional scenario or edition.",
    "referral_service_mismatch": "The simulated clinician plan does not match the scenario’s specified service.",
    "referral_authority_mismatch": "The simulated clinician plan does not provide the type of authority required for this service.",
    "referral_urgency_invalid": "The simulated clinician plan needs an explicit supported urgency.",
    "referral_capabilities_invalid": "The simulated clinician plan needs valid required and preferred capability lists.",
    "referral_plan_eligible": "A matching simulated clinician plan is present. Review the summary before searching.",
}

_AUTHORITIES = {
    "simulated_treatment_plan": "Simulated treatment plan",
    "simulated_clinician_referral": "Simulated clinician referral",
    "simulated_clinician_assessment": "Simulated clinician assessment",
}


def referral_catalogue():
    """Return fresh display mappings for referral reason and authority IDs."""
    return {"reasons": _REASONS.copy(), "authorities": _AUTHORITIES.copy()}


def _nonblank_string(value):
    return type(value) is str and bool(value.strip())


def _valid_capabilities(values):
    if type(values) is not list or any(not _nonblank_string(value) for value in values):
        return False
    # The ranker strips labels before comparing them, so duplicates at that
    # boundary are invalid even if their original whitespace differs.
    return len({value.strip() for value in values}) == len(values)


def _decision(state, reason, confirmation, candidate=None):
    return {
        "state": state,
        "reason_codes": [reason],
        "clinician_confirmation": confirmation,
        "candidate_request": candidate,
    }


def evaluate_referral_gate(*, service, clinician_plan, scenario_id, scenario_version):
    """Evaluate trusted scenario facts after the engine's safety and scope checks.

    The caller supplies the plan from the fictional scenario catalogue. An
    eligible candidate is internal to the assessment engine. The engine must
    separately bind the visitor's confirmation before exposing a finder request.
    """
    if not _nonblank_string(scenario_id) or not _nonblank_string(scenario_version):
        return _decision("invalid_input", "referral_plan_invalid", "invalid")

    if service is None and clinician_plan is None:
        return _decision("clinician_assessment_needed", "referral_service_unspecified", "required")
    if service is None:
        return _decision("invalid_input", "referral_service_mismatch", "invalid")
    if not _nonblank_string(service):
        return _decision("invalid_input", "referral_service_unsupported", "invalid")
    if service not in _AUTHORITY_BY_SERVICE:
        return _decision("unsupported_care_need", "referral_service_unsupported", "not_required")
    if clinician_plan is None:
        return _decision("clinician_assessment_needed", "referral_plan_missing", "required")

    plan = clinician_plan
    if (type(plan) is not dict or plan.keys() != _PLAN_FIELDS
            or plan["synthetic"] is not True
            or not _nonblank_string(plan["scenario_id"])
            or not _nonblank_string(plan["scenario_version"])):
        return _decision("invalid_input", "referral_plan_invalid", "invalid")
    if (plan["scenario_id"], plan["scenario_version"]) != (scenario_id, scenario_version):
        return _decision("invalid_input", "referral_plan_stale", "invalid")
    if type(plan["service"]) is not str or plan["service"] != service:
        return _decision("invalid_input", "referral_service_mismatch", "invalid")
    if type(plan["authority"]) is not str or plan["authority"] != _AUTHORITY_BY_SERVICE[service]:
        return _decision("invalid_input", "referral_authority_mismatch", "invalid")

    urgency = plan["urgency"]
    if type(urgency) is not str or urgency not in _URGENCIES:
        return _decision("invalid_input", "referral_urgency_invalid", "invalid")
    required = plan["required_capabilities"]
    preferred = plan["preferred_capabilities"]
    if not _valid_capabilities(required) or not _valid_capabilities(preferred):
        return _decision("invalid_input", "referral_capabilities_invalid", "invalid")

    return _decision("eligible", "referral_plan_eligible", "present", {
        "service": service,
        "urgency": urgency,
        "required_capabilities": required.copy(),
        "preferred_capabilities": preferred.copy(),
    })
