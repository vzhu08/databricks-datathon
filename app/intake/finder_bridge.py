"""Pass a confirmed fictional intake to the existing offline Find care scorer."""

import json

from app.ranking.urgency import rank_campuses
from app.storm_ui import build_ask

ORIGIN_IDS = tuple(place for place, _ in build_ask.PLACES)
_BUDGETS = {urgency: budget for urgency, _, budget in build_ask.URGENCIES}
_SERVICES = tuple(service for service, _ in build_ask.SERVICES)


def _rank_request(request, origin_id):
    service = request["service"]
    urgency = request["urgency"]
    if service not in _SERVICES or urgency not in _BUDGETS:
        raise ValueError("Unsupported service or urgency in confirmed intake")
    if origin_id not in ORIGIN_IDS:
        raise ValueError("Choose a fictional Find care origin")
    for field in ("required_capabilities", "preferred_capabilities"):
        labels = request[field]
        if not isinstance(labels, list) or any(not isinstance(s, str) or not s.strip() for s in labels):
            raise ValueError(f"Invalid {field} in confirmed intake")

    fixture = json.loads(build_ask.FIXTURE.read_text(encoding="utf-8"))
    if fixture["synthetic"] is not True:
        raise ValueError("Find care requires the synthetic travel fixture")
    travel = {origin["id"]: origin["travel_minutes"] for origin in fixture["origins"]}
    return rank_campuses(
        service, urgency, build_ask._candidates(service, travel[origin_id]),
        as_of=build_ask.AS_OF, travel_metric="travel_minutes", travel_budget=_BUDGETS[urgency],
        required=request["required_capabilities"], preferred=request["preferred_capabilities"],
    )


def find_care_for_intake(payload, *, scenario, confirmation=None, origin_id):
    """Reassess visitor inputs with a caller-owned trusted fictional scenario and receipt.

    Returns the fresh assessment and a nullable finder response. A broken engine
    contract or fixture raises before a result is returned to the builder.
    """
    from app.intake.assessment import POLICY_VERSION, SCHEMA_VERSION, assess_intake

    assessment = assess_intake(payload, scenario=scenario, confirmation=confirmation)
    finder = None
    if assessment["state"] == "ready":
        if (confirmation is None or assessment["confirmation_status"] != "current"
                or assessment["clinician_confirmation"] != "present"
                or assessment["mode"] != "synthetic"
                or assessment["schema_version"] != SCHEMA_VERSION
                or assessment["policy_version"] != POLICY_VERSION):
            raise ValueError("Inconsistent confirmation on ready intake")
        finder = _rank_request(assessment["request"], origin_id)
    return {"assessment": assessment, "finder": finder}
