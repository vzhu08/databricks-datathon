"""Select an individual verification lead from server-cleared, query-relevant projections.

Claims come from Vincent's claim mapper. The caller binds them to the submitted
service and original occurrence before calling. Names are never join keys.
"""

from collections import defaultdict
from datetime import date
from math import inf, isfinite

from .evidence import MATCHERS


_POINT = {"reported_position", "identified_campus", "verified_entrance"}
_ROUTABLE = {"identified_campus", "verified_entrance"}
_STRENGTH = {"corroborated": 2, "reported": 1}
_NEGATIVE = {"explicit_absence", "all_cases_referral"}


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _measurement(value):
    if type(value) is int and value >= 0:
        return value
    if type(value) is float and isfinite(value) and value >= 0:
        return value
    return None


def _date(value):
    try:
        return date.fromisoformat(value).toordinal()
    except (TypeError, ValueError):
        return 0


def _candidate(service, item):
    key = _text(item.get("key"))
    if not key:
        raise ValueError("A cleared candidate needs a stable display key")
    location, claim = item.get("location"), item.get("service")
    if location is not None and location.get("kind") != "location":
        raise ValueError("Expected the joined location claim")
    if claim is not None and (claim.get("kind") != "service" or claim.get("service") != service):
        raise ValueError("Claim belongs to a different service")
    loc, evidence = location or {}, claim or {}
    precision = loc.get("precision")
    source_scope = item.get("source_scope") or "unknown"
    name, area = _text(item.get("name")), _text(item.get("area"))
    availability = item.get("availability", "unknown")
    if availability not in {"unknown", "available", "full", "stale", "unavailable"}:
        raise ValueError("Unrecognized scoped availability")

    observation = item.get("travel") or {}
    minutes = _measurement(observation.get("minutes"))
    travel = {"status": "unknown", "minutes": None, "source": None}
    if precision in _ROUTABLE and source_scope != "vf_only" and loc.get("strength") != "conflicting_evidence":
        status = observation.get("status")
        if status in {"stale", "unavailable", "unknown"} or (
                status == "known" and minutes is not None and _text(observation.get("source"))):
            travel = {k: observation.get(k) for k in ("status", "source", "outcome", "reason", "requested_at")}
            travel["minutes"] = minutes if status == "known" else None
    distance = (_measurement(item.get("distance_km"))
                if precision in _POINT and loc.get("strength") != "conflicting_evidence" else None)

    sources = evidence.get("sources") or []
    support = [s for s in sources if s.get("role") == "support"]
    negative = evidence.get("decision") == "no" or any(s.get("assertion") in _NEGATIVE for s in support)
    strength = evidence.get("strength")
    affirmative = strength in _STRENGTH and any(s.get("assertion") not in _NEGATIVE for s in support)
    missing = []
    if strength == "conflicting_evidence":
        reason, priority = "conflicting_service_evidence", 4
        missing.append("Resolve the conflicting service statements for this branch.")
    elif negative:
        reason, priority = "service_reported_absent", 5
        missing.append("Check for a later branch-specific change to the reported absence or referral.")
    elif availability in {"full", "unavailable"}:
        reason, priority = "availability_" + availability, 4
        missing.append("The recorded availability is " + availability + ". Confirm a change before considering this site.")
    elif loc.get("strength") == "conflicting_evidence":
        reason, priority = "conflicting_location_evidence", 3
        missing.append("Resolve the competing branch or location before acting on the service claim.")
    elif affirmative:
        reason = "reviewed_service" if evidence.get("decision") == "yes" else "reported_service"
        priority = 0 if reason == "reviewed_service" else 1
    elif name or area or precision not in (None, "unknown") or sources or loc.get("sources"):
        reason, priority = "identity_or_area_only", 2
        missing.append("Verify whether the requested service is delivered onsite at this branch.")
    else:
        return None

    provisional = priority <= 1
    if provisional and source_scope == "vf_only":
        label = "Provisional · VF only"
        missing.append("Seek independent corroboration for the VF record.")
    else:
        label = "Provisional" if provisional else "Verification lead"
    for part in (loc, evidence):
        if part.get("missing_check"):
            missing.append(part["missing_check"])
    if provisional and evidence.get("decision") != "yes" and not evidence.get("missing_check"):
        missing.append("Confirm dated onsite service at the exact physical branch.")
    if precision not in _ROUTABLE:
        missing.append("Confirm the physical branch and destination.")
    if availability in {"stale", "unknown"}:
        missing.append("Confirm current staffed availability for the requested service.")
    if travel["minutes"] is None:
        missing.append("Road travel time to a permitted destination is unknown.")
    origins = evidence.get("independent_supporting_origins")
    # as_of is an assessment date. Only dates attached to applicable support
    # describe recency of the service observation. A record pointer adds no vote.
    cutoff = _date(evidence.get("as_of")) or date.today().toordinal()
    dates = [_date(s.get("observed_on")) for s in support]
    newest = max((d for d in dates if d <= cutoff), default=0)
    rank = (priority, -_STRENGTH.get(strength, 0), -(origins if type(origins) is int else 0), -newest)
    return rank, dict(key=key, name=name, area=area, service=claim, location=location,
                      source_scope=source_scope, availability=availability, travel=travel, distance_km=distance,
                      label=label, reason=reason, missing=list(dict.fromkeys(missing)),
                      next_action="confirmation_note" if provisional else "verify_identity")


def _supported_assignment(allocation, candidates):
    choice = allocation.get("chosen") or {}
    key = choice.get("facility_id")
    matching = next((row for row in candidates if row["key"] == key), None)
    # Synthetic scenario campuses have their own certified destination IDs.
    # Reviewed data needs a cleared, branch-specific display projection.
    mode = allocation.get("mode")
    cleared = mode == "synthetic" and matching is None
    if matching is not None:
        loc = matching["location"] or {}
        cleared = (mode in {"synthetic", "reviewed"} and matching["source_scope"] != "vf_only"
                   and loc.get("precision") in _ROUTABLE and matching["reason"] == "reviewed_service"
                   and matching["availability"] not in {"stale", "full", "unavailable"})
    return (cleared and key in allocation.get("eligible_campus_ids", ())
            and _measurement(choice.get("travel_minutes")) is not None and _text(choice.get("travel_source"))
            and type(choice.get("free_staffed_slots")) is int and choice["free_staffed_slots"] > 0
            and _text(choice.get("capacity_source")))


def select_individual(service, candidates, *, allocation=None, emergency=False, withheld_summary=None):
    """Return a decision and exportable evidence; consumes no slots and sends no coordinates.

    Supply a current, venue-cleared allocator result for the same search only.
    For the restricted warehouse path pass B's withheld summary instead of rows.
    """
    result = dict(chosen=None, candidates=[], missing=[], allocation=None, summary=None)
    if emergency or (allocation and allocation.get("status") == "emergency"):
        return dict(result, status="emergency", reason="emergency_stop", next_action="emergency_guidance")
    if service not in MATCHERS:
        return dict(result, status="no_usable_evidence", reason="missing_requested_service",
                    missing=["Choose a supported requested service."], next_action="clarify_input")
    if withheld_summary is not None:
        if withheld_summary.get("service") != service:
            raise ValueError("Summary belongs to a different service")
        if withheld_summary.get("status") in {"no_match", "invalid_input", "unresolved_location", "ambiguous_location", "unavailable"}:
            reasons = {
                "no_match": "No query-relevant match was reported.",
                "invalid_input": "A valid search input is missing.",
                "unresolved_location": "The search location could not be identified.",
                "ambiguous_location": "Clarify which search location is intended.",
                "unavailable": "The evidence source could not be read.",
            }
            reason = withheld_summary["status"]
            return dict(result, status="no_usable_evidence", reason=reason, missing=[reasons[reason]],
                        summary=withheld_summary, next_action="clarify_input")
        return dict(result, status="withheld", reason="no_cleared_individual_projection",
                    summary=withheld_summary, next_action="request_clearance",
                    missing=["An individual identity and service claim cleared for this audience are required."])
    groups, keys = defaultdict(list), set()
    for item in candidates:
        candidate = _candidate(service, item)
        if candidate is None:
            continue
        rank, row = candidate
        if row["key"] in keys:
            raise ValueError("Duplicate occurrence or campus key in this search")
        keys.add(row["key"])
        groups[rank].append(row)
    ranked = []
    for rank in sorted(groups):
        group = groups[rank]
        # Compare one travel metric within an evidence tie. Area centroids and
        # failed routes cannot become road estimates.
        if all(c["travel"]["minutes"] is not None for c in group):
            group.sort(key=lambda c: (c["travel"]["minutes"], c["key"]))
        else:
            group.sort(key=lambda c: (c["distance_km"] if c["distance_km"] is not None else inf, c["key"]))
        ranked.extend(group)
    if allocation and allocation.get("status") == "recommended":
        if _supported_assignment(allocation, ranked):
            return dict(result, status="assigned", reason=allocation["reason"], chosen=allocation["chosen"],
                        candidates=ranked, allocation=allocation, next_action="referral_note")
        allocation = {"status": "no_recommendation", "reason": "unsupported_individual_assignment"}
    if not ranked:
        return dict(result, status="no_usable_evidence", reason="missing_individual_evidence",
                    allocation=allocation, missing=["A query-relevant service claim or identifiable facility or area is missing."],
                    next_action="clarify_input")
    chosen = ranked[0]
    status = "provisional" if chosen["next_action"] == "confirmation_note" else "verification_lead"
    return dict(result, status=status, reason=chosen["reason"], chosen=chosen, candidates=ranked,
                missing=chosen["missing"], next_action=chosen["next_action"], allocation=allocation)
