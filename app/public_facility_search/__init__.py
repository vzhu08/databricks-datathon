"""Search a bounded collection of claims published by hospital operators."""

import json
from importlib.resources import files


def search_public_facilities(place: str, service: str) -> list[dict]:
    """Return operator-reported claims matching the requested city and service."""
    city = " ".join(place.casefold().split())
    query = " ".join(service.casefold().split())
    if query.endswith((".", "?", "!")):
        query = query[:-1].rstrip()
    if query == "kidney dialysis":
        query = "dialysis"
    claims = json.loads(files(__package__).joinpath("claims.json").read_text(encoding="utf-8"))
    results = []
    for claim in claims:
        if city != claim["city"].casefold() or query not in claim["service_queries"]:
            continue
        result = {key: value for key, value in claim.items() if key != "service_queries"}
        result.update(
            evidence_basis="Operator-reported service",
            treatment_observation_date=None,
            appointment_acceptance="Unknown",
            availability="Unknown",
            staffing="Unknown",
            entrance="Unknown",
            vf_match="No reviewed VF match asserted",
            next_action="Call the hospital to confirm the requested service, availability and arrival instructions.",
        )
        results.append(result)
    return results
