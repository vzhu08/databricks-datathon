"""Rank documented campus services using explicit referral urgency.

Each candidate is a reviewed snapshot for one facility_id and as_of date.
services[service] supplies its yes/no/unconfirmed decision, the latest
applicable service assertion's source_date, independently assessed upstream
families, and campus-specific capability decisions at the same assessment date.
Callers supply travel to each candidate from the same origin and transport mode.
"""

from collections.abc import Mapping
from datetime import date

from .evidence import MATCHERS
from .location import finite_number
from .search import MAX_RESULTS


WEIGHTS = {
    "routine": {"travel": 45, "recency": 25, "corroboration": 15, "preferred": 15},
    "time_sensitive": {"travel": 65, "recency": 15, "corroboration": 10, "preferred": 10},
    "highest": {"travel": 80, "recency": 10, "corroboration": 5, "preferred": 5},
}


def _labels(values, name):
    if not isinstance(values, (tuple, list, set, frozenset)):
        raise ValueError(f"{name} must be a collection of nonempty labels")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{name} must contain only nonempty labels")
    return {value.strip() for value in values}


def _iso_date(value):
    """Accept a date or a YYYY-MM-DD string, excluding timestamps."""
    if type(value) is date:
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        except ValueError:
            pass
    return None


def rank_campuses(service, urgency, candidates, *, as_of, travel_metric, travel_budget,
                  required=(), preferred=(), half_life_months=24, limit=MAX_RESULTS):
    """Return scored options and, if none qualify, unscored confirmation leads.

    Choose either travel_minutes or distance_km for the entire request. A
    candidate lacking that measurement cannot be ranked. Travel_budget uses the
    chosen unit. Pass limit=None to retain the entire eligible pool for planning.
    Scores are demo preference points out of 100. They do not predict outcomes.
    """
    if not isinstance(service, str) or service not in MATCHERS:
        raise ValueError("Choose a supported requested service")
    if not isinstance(urgency, str) or urgency not in WEIGHTS:
        raise ValueError("Choose a supported requested service and explicit urgency")
    if travel_metric not in ("travel_minutes", "distance_km"):
        raise ValueError("Choose travel_minutes or distance_km for the entire request")
    day = _iso_date(as_of)
    budget = finite_number(travel_budget)
    half_life = finite_number(half_life_months)
    if day is None or budget is None or budget <= 0 or half_life is None or half_life <= 0:
        raise ValueError("A valid assessment date, positive travel budget and half-life are required")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer or None")
    if limit is not None:
        limit = min(limit, MAX_RESULTS)

    mandatory = _labels(required, "required")
    optional = _labels(preferred, "preferred") - mandatory
    weights = dict(WEIGHTS[urgency])
    if not optional:
        weights["preferred"] = 0
    weight_total = sum(weights.values())
    weights = {name: weight * 100 / weight_total for name, weight in weights.items()}

    ranked, leads = [], []
    seen = set()
    for candidate in candidates:
        facility_id = candidate.get("facility_id")
        if not isinstance(facility_id, str) or not facility_id.strip() or facility_id in seen:
            raise ValueError("Each candidate must have a unique, nonempty facility_id")
        seen.add(facility_id)
        travel = finite_number(candidate.get(travel_metric))
        if travel is not None and travel < 0:
            travel = None
        if travel is not None and travel > budget:
            continue

        services = candidate.get("services", {})
        if not isinstance(services, Mapping):
            raise ValueError("services must map service names to assessed decisions")
        decision = services.get(service, {})
        if not isinstance(decision, Mapping):
            raise ValueError("A service decision must be a mapping")
        capabilities = decision.get("capabilities", {})
        if not isinstance(capabilities, Mapping):
            raise ValueError("capabilities must map feature names to reviewed decisions")

        current = _iso_date(candidate.get("as_of")) == day
        status = decision.get("status", "unconfirmed")
        if current and (status == "no" or any(capabilities.get(k) == "no" for k in mandatory)):
            continue
        raw_date = decision.get("source_date")
        source_day = _iso_date(raw_date)
        reasons = []
        if not current:
            reasons.append("assessment_date_mismatch")
        if status != "yes":
            reasons.append("service_unconfirmed")
        if any(capabilities.get(k) != "yes" for k in mandatory):
            reasons.append("required_capability_unconfirmed")
        if raw_date is not None and (source_day is None or source_day > day):
            reasons.append("invalid_service_evidence_date")
        if travel is None:
            reasons.append("travel_unknown")
        if reasons:
            leads.append({"facility_id": facility_id, "travel": travel, "reasons": reasons})
            continue

        families = _labels(decision.get("independent_families", ()), "independent_families")
        # Upstream families must already be reconciled by the evidence producer.
        # The first family establishes the claim; up to two more corroborate it.
        recency = 0.0
        if source_day is not None:
            age_months = (day - source_day).days / (365.2425 / 12)
            recency = 2 ** (-age_months / half_life)
        factors = {
            "travel": 1 - travel / budget,
            "recency": recency,
            "corroboration": min(2, max(0, len(families) - 1)) / 2,
            "preferred": sum(capabilities.get(k) == "yes" for k in optional) / len(optional)
            if optional else 0.0,
        }
        ranked.append({
            "facility_id": facility_id,
            "travel": travel,
            "score": sum(weights[name] * factor for name, factor in factors.items()),
            "weights": weights.copy(),
            "factors": factors,
            "source_date": source_day.isoformat() if source_day else None,
            "availability": "unknown",
        })

    ranked.sort(key=lambda row: (-row["score"], row["travel"], row["facility_id"]))
    leads.sort(key=lambda row: (row["travel"] is None, row["travel"], row["facility_id"]))
    status = "ok" if ranked else "needs_confirmation" if leads else "no_match"
    return {
        "service": service,
        "urgency": urgency,
        "as_of": day.isoformat(),
        "travel_metric": travel_metric,
        "status": status,
        "ranked": ranked[:limit],
        "needs_confirmation": [] if ranked else leads[:limit],
    }
