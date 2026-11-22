"""Connect opt-in live travel to the normal finder without changing its evidence rules."""

if "." in __package__:  # Repository package app.travel
    from ..ranking.location import coordinates, finite_number, haversine_km
    from ..ranking.search import MAX_RESULTS
    from ..ranking.urgency import rank_campuses
else:  # Databricks ships app/ as the import root
    from ranking.location import coordinates, finite_number, haversine_km
    from ranking.search import MAX_RESULTS
    from ranking.urgency import rank_campuses
from .tomtom import MODE, PREFERENCE, PROVIDER, from_environment


def find_campuses(request, *, provider=None, request_scope=None):
    """Dispatch a normalized request. Without routing, this is the offline ranker.

    The provider and its quotas are supplied only by backend code/configuration.
    The request may reduce the geographic shortlist, never increase its bound.
    """
    if not isinstance(request, dict):
        raise ValueError("Input must be one normalized request object")
    if "routing" not in request:
        return rank_campuses(**request)
    routing = request["routing"]
    allowed = {"provider", "origin", "shortlist_limit", "fallback_distance_km"}
    if not isinstance(routing, dict) or set(routing) - allowed or routing.get("provider") != PROVIDER:
        raise ValueError("routing must select tomtom and supported request options")
    origin = routing.get("origin")
    if (not isinstance(origin, dict) or set(origin) - {"latitude", "longitude", "kind", "approximate"}
            or origin.get("kind") not in ("coordinates", "city", "pin")
            or type(origin.get("approximate", False)) is not bool or coordinates(origin) is None):
        raise ValueError("routing.origin needs valid coordinates, kind and an optional approximate boolean")
    origin_point = coordinates(origin)
    approximate = origin["kind"] in ("city", "pin") or origin.get("approximate", False)
    candidates = request.get("candidates")
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError("candidates must be an array of campus objects")
    if request.get("travel_metric") != "travel_minutes":
        raise ValueError("Live routing requires travel_minutes and a minute travel_budget")
    if request.get("limit", 3) is None:
        raise ValueError("The finder limit must be a positive integer")
    options = {k: v for k, v in request.items() if k not in ("routing", "candidates")}
    rank_campuses(candidates=[], **options)  # Validate the actual budget/options before any call.
    fallback_budget = routing.get("fallback_distance_km")
    if "fallback_distance_km" in routing:
        fallback_budget = finite_number(fallback_budget)
        if fallback_budget is None or fallback_budget <= 0:
            raise ValueError("fallback_distance_km must be a separate positive kilometre budget")
    # Reuse precisely the same evidence rules. Neutral travel keeps this first
    # pass independent of distance; its scores are discarded, never returned.
    probe_options = {**options, "travel_metric": "distance_km", "travel_budget": 1, "limit": None}
    probe = rank_campuses(candidates=[{**c, "distance_km": 0} for c in candidates], **probe_options)
    eligible = {row["facility_id"] for row in probe["ranked"]}
    # When at least one candidate qualified, the ranker intentionally suppresses
    # leads. A second evidence-only pass recovers their reasons for live reporting.
    unqualified = [c for c in candidates if c["facility_id"] not in eligible]
    lead_probe = rank_campuses(candidates=[{**c, "distance_km": 0} for c in unqualified], **probe_options)
    lead_reasons = {r["facility_id"]: r["reasons"] for r in lead_probe["needs_confirmation"]}
    client = provider if provider is not None else from_environment()
    bound = routing.get("shortlist_limit", client.config.shortlist_limit)
    if type(bound) is not int or not 1 <= bound <= client.config.shortlist_limit:
        raise ValueError("shortlist_limit must be positive and within the backend bound")
    records, geographic = {}, []
    for c in candidates:
        fid = c["facility_id"]
        row = dict(facility_id=fid, provider=PROVIDER, mode=MODE, metric="travel_minutes",
                   outcome="unavailable", reason=None, requested_at=None, departure_time=None,
                   departure_time_source=None, estimated_seconds=None, estimated_minutes=None,
                   road_metres=None, distance_km=None, evaluated=False, exclusion_reasons=[])
        records[fid] = row
        if fid not in eligible:
            row["reason"] = "service_ineligible"
            row["exclusion_reasons"] = lead_reasons.get(fid, ["service_or_required_capability_no"])
            continue
        if c.get("coordinate_status") != "reviewed":
            row["reason"] = "coordinates_disputed" if c.get("coordinate_status") == "disputed" else "coordinates_unreviewed"
        elif coordinates(c) is None:
            row["reason"] = "invalid_coordinates"
        if row["reason"]:
            row["exclusion_reasons"] = [row["reason"]]
            continue
        distance = haversine_km(origin_point, coordinates(c))
        row["distance_km"] = distance
        geographic.append((distance, fid, c))
    geographic.sort(key=lambda item: (item[0], item[1]))
    selected = geographic[:bound]
    for _, fid, _ in geographic[bound:]:
        records[fid].update(reason="outside_geographic_shortlist",
                            exclusion_reasons=["outside_geographic_shortlist"])
    try:
        batch = client.routes(origin_point, [(fid, coordinates(c)) for _, fid, c in selected], request_scope=request_scope)
    finally:
        if provider is None:
            client.close()
    for _, fid, _ in selected:
        row = batch.results[fid]
        records[fid].update({key: value for key, value in row.items() if key != "fallback_allowed"})
        records[fid]["evaluated"] = fid in batch.evaluated_ids
    timed = [fid for _, fid, _ in selected if records[fid]["outcome"] == "ok"]
    use_fallback = (not timed and fallback_budget is not None and
                    any(row["fallback_allowed"] for row in batch.results.values()))
    metric = "distance_km" if use_fallback else "travel_minutes"
    budget = fallback_budget if use_fallback else finite_number(request["travel_budget"])
    scored_inputs = []
    for _, fid, c in selected:
        row = records[fid]
        if use_fallback and batch.results[fid]["fallback_allowed"]:
            value = row["distance_km"]
            row["metric"] = "distance_km"
        elif not use_fallback and row["outcome"] == "ok":
            value = row["estimated_minutes"]
        else:
            row["exclusion_reasons"] = [row["reason"] or "travel_unknown"]
            continue
        if value > budget:
            row["exclusion_reasons"] = ["travel_budget_exceeded"]
            continue
        scored_inputs.append({**c, metric: value})
    full = rank_campuses(candidates=scored_inputs,
                        **{**options, "travel_metric": metric, "travel_budget": budget, "limit": None})
    scored_count = len(full["ranked"])
    full["ranked"] = full["ranked"][:min(request.get("limit", MAX_RESULTS), MAX_RESULTS)]
    if not full["ranked"]:
        leads = [{"facility_id": fid, "travel": None,
                  "reasons": lead_reasons.get(fid, row["exclusion_reasons"])}
                 for fid, row in sorted(records.items())
                 if fid in lead_reasons or (fid in eligible and row["outcome"] == "unavailable")]
        full["needs_confirmation"] = leads[:min(request.get("limit", MAX_RESULTS), MAX_RESULTS)]
        full["status"] = "needs_confirmation" if leads else "no_match"
    outcomes = [records[fid]["outcome"] for _, fid, _ in selected]
    state = ("not_requested" if not selected else "fallback" if use_fallback else
             "ok" if all(x == "ok" for x in outcomes) else "partial" if timed else
             "no_route" if all(x == "no_route" for x in outcomes) else "unavailable")
    full["routing"] = {
        "schema_version": "1.0.0", "provider": PROVIDER, "mode": MODE,
        "product": client.config.product or None, "routing_preference": PREFERENCE, "state": state, "requested_at": batch.requested_at,
        "approximate_origin": approximate, "shortlist_limit": bound,
        "coverage_state": "available" if selected else "empty",
        "shortlist_metric": "haversine_km", "ranking_metric": metric,
        "travel_budget": budget, "usage": batch.usage, "coalesced": batch.coalesced,
        "counts": {"considered": len(candidates), "eligible": len(eligible),
                   "routing_eligible": len(geographic), "shortlisted": len(selected), "evaluated": len(batch.evaluated_ids),
                   "provider_calls_attempted": batch.calls_attempted, "timed": len(timed),
                   "omitted": len(eligible) - len(selected), "scored": scored_count,
                   "excluded": len(candidates) - scored_count, "returned": len(full["ranked"])},
        "errors": batch.errors,
        "results": [records[fid] for fid in sorted(records)],
        "attribution": {"text": "TomTom", "required": any(x in ("ok", "no_route") for x in outcomes),
                        "display_status": "operator_terms_review_required",
                        "method": "tomtom_copyright_api",
                        "scope": "synthetic_internal_evaluation",
                        "terms_url": "https://docs.tomtom.com/legal/terms-and-conditions",
                        "storage": "do_not_persist_provider_content"},
    }
    return full
