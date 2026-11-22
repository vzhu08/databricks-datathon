/*
 * What the campus finder page shows for one finder response.
 *
 * Pure functions over the envelope returned by `python -m app.ranking` when the request opts in to
 * routing. Nothing here ranks, scores, converts units or estimates travel: the ranked order and
 * every figure are read from the envelope, and each campus is sorted into one display group from
 * the outcome and reasons the backend supplied.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.FinderState = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var STATES = ["ok", "partial", "unavailable", "no_route", "fallback", "not_requested"];
  /* Reasons a campus was never sent to the provider. */
  var NOT_SENT = ["service_ineligible", "coordinates_unreviewed", "coordinates_disputed", "invalid_coordinates",
    "outside_geographic_shortlist"];
  /* This application's own limits. They are not a provider outage and never lead to a fallback. */
  var LOCAL_LIMIT = ["daily_call_budget_exceeded", "monthly_call_budget_exceeded", "query_call_budget_exceeded",
    "local_rate_limited", "local_inflight_limit", "shared_provider_cooldown", "validation_reservation_required"];
  /* Live routing is switched off or not fully set up on the server. */
  var LOCAL_SETUP = ["routing_disabled", "missing_credentials", "missing_call_budget", "missing_budget_store",
    "budget_store_unavailable", "missing_approved_account", "unsupported_budget_deployment", "unverified_allocation",
    "unverified_product_entitlement", "not_evaluated"];
  var GROUPS = ["over_limit", "not_top", "unresolved", "no_route", "not_sent"];

  function problems(envelope) {
    if (!envelope || typeof envelope !== "object") return ["The file is not a finder response object."];
    if (envelope.status === "invalid_input") return ["The finder rejected the request: " + (envelope.message || "no reason given") + "."];
    var found = [];
    if (!Array.isArray(envelope.ranked)) found.push("Missing list: ranked.");
    var routing = envelope.routing;
    if (!routing || typeof routing !== "object") {
      found.push("The response has no routing section, so it was not a driving-time search.");
      return found;
    }
    if (STATES.indexOf(routing.state) === -1) found.push("Unknown routing state: " + String(routing.state) + ".");
    if (!Array.isArray(routing.results)) found.push("Missing list: routing.results.");
    if (!routing.counts || typeof routing.counts !== "object") found.push("Missing routing.counts.");
    return found;
  }

  function reasonKind(reason) {
    if (LOCAL_LIMIT.indexOf(reason) !== -1) return "local_limit";
    if (LOCAL_SETUP.indexOf(reason) !== -1) return "local_setup";
    if (NOT_SENT.indexOf(reason) !== -1) return "not_sent";
    return "provider";
  }

  /* The one display group for a campus that is not in the ranked list. */
  function groupOf(row) {
    var reasons = row.exclusion_reasons || [];
    if (reasons.indexOf("travel_budget_exceeded") !== -1) return "over_limit";
    if (row.outcome === "no_route") return "no_route";
    if (NOT_SENT.indexOf(row.reason) !== -1) return "not_sent";
    if (reasons.length === 0) return "not_top";
    return "unresolved";
  }

  /* The figure the backend ranked this campus by, in the unit it supplied. Null when there is none. */
  function measure(row) {
    if (row.metric === "distance_km") return row.distance_km === null || row.distance_km === undefined ? null
      : { unit: "km", value: row.distance_km };
    if (row.outcome === "ok" && row.estimated_minutes !== null && row.estimated_minutes !== undefined) {
      return { unit: "minutes", value: row.estimated_minutes };
    }
    return null;
  }

  function view(envelope) {
    var routing = envelope.routing;
    var byId = {};
    routing.results.forEach(function (row) { byId[row.facility_id] = row; });
    var unit = routing.ranking_metric === "distance_km" ? "km" : "minutes";
    var rankedIds = {};
    var ranked = envelope.ranked.map(function (entry, index) {
      rankedIds[entry.facility_id] = true;
      return { rank: index + 1, facility_id: entry.facility_id, travel: entry.travel, unit: unit,
        source_date: entry.source_date || null, availability: entry.availability || null,
        result: byId[entry.facility_id] || null };
    });
    var groups = {};
    GROUPS.forEach(function (name) { groups[name] = []; });
    routing.results.forEach(function (row) {
      if (rankedIds[row.facility_id]) return;
      groups[groupOf(row)].push({ facility_id: row.facility_id, reason: row.reason,
        reasons: row.exclusion_reasons || [], kind: reasonKind(row.reason), evaluated: Boolean(row.evaluated),
        measure: measure(row), straight_line_km: row.distance_km === undefined ? null : row.distance_km, result: row });
    });
    var errors = routing.errors || [];
    return {
      state: routing.state,
      unit: unit,
      budget: routing.travel_budget,
      ranked: ranked,
      groups: groups,
      counts: routing.counts,
      errors: errors,
      local_limit: errors.filter(function (reason) { return reasonKind(reason) === "local_limit"; }),
      local_setup: errors.filter(function (reason) { return reasonKind(reason) === "local_setup"; }),
      provider_errors: errors.filter(function (reason) { return reasonKind(reason) === "provider"; }),
      requested_at: routing.requested_at || null,
      approximate_origin: Boolean(routing.approximate_origin),
      coverage_empty: routing.coverage_state === "empty",
      attribution: routing.attribution || null,
    };
  }

  return { STATES: STATES, GROUPS: GROUPS, problems: problems, reasonKind: reasonKind, groupOf: groupOf,
    measure: measure, view: view };
});
