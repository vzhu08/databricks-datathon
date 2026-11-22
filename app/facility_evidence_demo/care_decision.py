"""Pure judge workflow decision over the audience-cleared aggregate editions."""

try:
    from . import area as area_view, loader, walkthrough
except ImportError:  # Streamlit script import from the same directory
    import area as area_view
    import loader
    import walkthrough


_CHOICES = {
    "concern": ("injury", "dialysis", "mri", "other", "unsure"),
    "severity": ("mild", "moderate", "severe", "unsure"),
    "urgency": ("routine", "soon", "emergency", "unsure"),
    "danger": ("yes", "no", "unsure"),
    "injury_kind": ("head", "burn", "limb_joint", "cut_wound", "other", "unsure"),
}
_INJURY_CAPABILITY = {
    "head": ("head injury", "assessment for head injuries"),
    "burn": ("burn", "burn care"),
    "limb_joint": ("limb or joint injury", "limb or joint injury assessment and treatment"),
    "cut_wound": ("cut or wound", "wound care"),
    "other": ("other injury", "care for the specific injury"),
}
_SERVICES = {"injury": "trauma_care", "dialysis": "dialysis", "mri": "mri"}
_MISSING_FACT = {
    "trauma_care": "Which exact branch currently provides onsite trauma care, and can it receive this case?",
    "dialysis": "Which exact branch currently provides onsite dialysis, and can it take the required session?",
    "mri": "Which exact branch can currently deliver the MRI specified in the existing referral?",
}


def _loaded(result, schema):
    """Read only the server loader's result shape. Byte admission is the loader's job."""
    if not isinstance(result, dict) or result.get("status") != "ok" or type(result.get("synthetic")) is not bool:
        return None
    data = result.get("data")
    try:
        loader.check(data, schema, "edition")
    except loader.Unavailable:
        return None
    return data


def _workflow(selection):
    if selection["danger"] == "yes":
        return "emergency"
    if selection["severity"] == "severe":
        return "prompt_review"
    if selection["danger"] == "unsure" or selection["severity"] == "unsure":
        return "clarify"
    return "standard"


def _reason(selection, workflow):
    urgency = selection["urgency"]
    if workflow == "prompt_review":
        if urgency == "routine":
            return "You selected routine. Reported severe symptoms raise the review priority."
        return "Reported severe symptoms raise the review priority."
    if urgency == "soon":
        return "You asked for help soon. The local rules did not add a warning. This evidence check cannot assess whether waiting is safe."
    if urgency == "unsure":
        return "Your time urgency is unclear. This evidence check cannot establish a safe waiting time."
    return "This workflow checks facility evidence. It cannot assess whether waiting is safe."


def _service_evidence(data, service, synthetic):
    trace = data["vf_trace_case"]
    n = data["national"]
    seen = trace["same_osm_by_service"][service]
    name = walkthrough.SERVICES[service]
    return {
        "edition": data["schema"],
        "audience": data["audience"],
        "synthetic": synthetic,
        "service_label": name,
        "summary": (
            f"{walkthrough.count(seen, 'selected ' + name + ' key')} shared the same mapped object "
            "as its reference. Map agreement alone leaves current onsite service unknown."
        ),
        "trace": {
            "same_object_keys": seen,
            "grain": trace["grain"],
            "snapshots": list(trace["map_snapshots"]),
            "source_family": trace["same_origin_family"],
            "precision": trace["point_precision"],
            "source": walkthrough.source(trace["source"], "frozen source trace"),
        },
        "baseline": {
            "dataset": n["dataset"],
            "as_of": n["baseline_decisions_as_of"],
        },
        # These two payload sections are the dialysis-specific sections of
        # this frozen display edition. The public case is separate from VF.
        "issuer_pilot": walkthrough.national(data) if service == "dialysis" else None,
        "historical_case": walkthrough.public(data) if service == "dialysis" else None,
    }


def evaluate(request, display=None, area=None):
    """Evaluate a new anonymous judge selection without I/O or retained state.

    The only admitted evidence arguments are results of the pinned server
    loaders. A browser request supplies only the enumerated choices.
    """
    raw = request if isinstance(request, dict) else {}
    selection = {}
    invalid = not isinstance(request, dict) or bool(raw.keys() - _CHOICES.keys())
    for key, allowed in _CHOICES.items():
        if key == "injury_kind" and selection["concern"] != "injury":
            selection[key] = "unsure"
            continue
        value = raw.get(key, "unsure")
        if not isinstance(value, str) or value not in allowed:
            invalid = True
            value = "unsure"
        selection[key] = value

    workflow = _workflow(selection)
    result = {
        "request": selection,
        "workflow_urgency": workflow,
        "service": None,
        "evidence": None,
        "area": None,
        "eligible_destinations": None,
    }
    if workflow == "emergency" or selection["urgency"] == "emergency":
        if workflow == "emergency":
            reason = "Reported immediate danger interrupts facility browsing even when the requested priority is lower."
        else:
            reason = "Your emergency selection interrupts facility browsing regardless of the separate local workflow signal."
        return dict(result, status="emergency", action="interrupt", reason=reason,
                    next_check="If this is a real emergency, contact local emergency services now.")

    if invalid:
        return dict(result, status="invalid_request", action="clarify",
                    reason="One or more selections are outside this walkthrough's choices.",
                    next_check="Choose from the available responses.")
    if selection["danger"] == "unsure":
        return dict(result, status="needs_clarification", action="clarify",
                    reason="Immediate danger is unresolved. " + _reason(selection, workflow),
                    next_check="Clarify immediate danger before using facility evidence.")
    if selection["concern"] == "unsure":
        return dict(result, status="needs_clarification", action="clarify", reason=_reason(selection, workflow),
                    next_check="Clarify the injury or existing care need before selecting service evidence.")
    if selection["concern"] == "other":
        return dict(result, status="no_supported_service", action="clarify", reason=_reason(selection, workflow),
                    next_check="Clarify the actual care need. This edition has no evidence view for this selection.")
    if selection["concern"] == "injury" and selection["injury_kind"] != "unsure":
        kind, capability = _INJURY_CAPABILITY[selection["injury_kind"]]
        return dict(
            result, status="no_supported_service", action="clarify",
            reason=f"You selected {kind}. This edition cannot verify {capability}. " + _reason(selection, workflow),
            next_check=f"Verify the exact branch and its current ability to provide {capability}.",
        )
    if selection["severity"] == "unsure":
        return dict(result, status="needs_clarification", action="clarify", reason=_reason(selection, workflow),
                    next_check="Clarify reported severity before continuing the walkthrough.")

    service = _SERVICES[selection["concern"]]
    result["service"] = service
    reason = _reason(selection, workflow)
    if service == "trauma_care":
        reason += " The injury kind is unspecified, so the evidence check covers broad trauma care only."
    data = _loaded(display, loader.SCHEMA)
    location = _loaded(area, area_view.SCHEMA)
    if location is not None:
        result["area"] = {
            **area_view.build(location),
            "edition": location["edition"],
            "as_of": location["as_of"],
            "synthetic": area["synthetic"],
        }
    if data is None or data["decision"]["point_rank"]["eligible_destinations_in_cases"] != 0:
        return dict(result, status="data_unavailable", action="verify_evidence", reason=reason,
                    next_check="Load the approved evidence edition. " + _MISSING_FACT[service])

    result["evidence"] = _service_evidence(data, service, display["synthetic"])
    result["eligible_destinations"] = data["decision"]["point_rank"]["eligible_destinations_in_cases"]
    return dict(result, status="no_reviewed_destination", action="verify_evidence", reason=reason,
                next_check=_MISSING_FACT[service])
