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
    "local_rate_limited", "local_inflight_limit", "shared_provider_cooldown"];
  /* The reserved or protected request budget cannot cover the search. Also local, also never a fallback. */
  var LOCAL_RESERVE = ["reserved_budget_exhausted", "reservation_month_mismatch", "protected_allowance_exhausted",
    "validation_reservation_required", "validation_allocation_exhausted", "unknown_reservation"];
  /* Live routing is switched off or not fully set up on the server. */
  var LOCAL_SETUP = ["routing_disabled", "missing_credentials", "missing_call_budget", "missing_budget_store",
    "budget_store_unavailable", "missing_approved_account", "unsupported_budget_deployment", "unverified_allocation",
    "unverified_product_entitlement", "invalid_operator_budget", "local_clock_regressed", "not_evaluated"];
  var OUTCOMES = ["ok", "no_route", "unavailable"];
  var METRICS = ["travel_minutes", "distance_km"];
  var GROUPS = ["over_limit", "not_top", "unresolved", "no_route", "not_sent"];

  function isObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
  function isNumber(value) { return typeof value === "number" && isFinite(value); }
  function isText(value) { return typeof value === "string" && value.length > 0; }
  function isBlank(value) { return value === null || value === undefined; }

  /* Why a response cannot be shown. An empty list means every part the page reads is well formed. */
  function problems(envelope) {
    if (!isObject(envelope)) return ["The file is not a finder response object."];
    if (envelope.status === "invalid_input") return ["The finder rejected the request: " + (envelope.message || "no reason given") + "."];
    var found = [];
    if (!Array.isArray(envelope.ranked)) found.push("Missing list: ranked.");
    var routing = envelope.routing;
    if (!isObject(routing)) {
      found.push("The response has no routing section, so it was not a driving-time search.");
      return found;
    }
    if (STATES.indexOf(routing.state) === -1) found.push("Unknown routing state: " + String(routing.state) + ".");
    if (!Array.isArray(routing.results)) found.push("Missing list: routing.results.");
    if (!isObject(routing.counts)) found.push("Missing routing.counts.");
    if (METRICS.indexOf(routing.ranking_metric) === -1) found.push("Unknown ranking metric: " + String(routing.ranking_metric) + ".");
    if (!isNumber(routing.travel_budget)) found.push("The travel limit is not a number.");
    if (found.length) return found;

    Object.keys(routing.counts).forEach(function (name) {
      if (!isNumber(routing.counts[name])) found.push("Count " + name + " is not a number.");
    });
    if (routing.errors !== undefined && (!Array.isArray(routing.errors) || !routing.errors.every(isText))) {
      found.push("routing.errors is not a list of reason names.");
    }
    if (routing.attribution !== undefined && routing.attribution !== null && !isObject(routing.attribution)) {
      found.push("routing.attribution is not an object.");
    }
    if (!isBlank(routing.requested_at) && !isText(routing.requested_at)) found.push("The request time is not text.");
    var rows = {};
    routing.results.forEach(function (row, i) {
      if (!isObject(row) || !isText(row.facility_id)) { found.push("Result " + (i + 1) + " has no campus id."); return; }
      var where = "Result for " + row.facility_id;
      if (rows[row.facility_id]) { found.push(where + " appears more than once."); return; }
      rows[row.facility_id] = row;
      if (OUTCOMES.indexOf(row.outcome) === -1) found.push(where + " has no recognised outcome.");
      if (METRICS.indexOf(row.metric) === -1) found.push(where + " has no recognised metric.");
      if (!isBlank(row.reason) && !isText(row.reason)) found.push(where + " has a reason that is not text.");
      if (row.exclusion_reasons !== undefined && (!Array.isArray(row.exclusion_reasons) || !row.exclusion_reasons.every(isText))) {
        found.push(where + " has exclusion reasons that are not a list of reason names.");
      }
      ["estimated_minutes", "estimated_seconds", "road_metres", "distance_km"].forEach(function (field) {
        if (!isBlank(row[field]) && !isNumber(row[field])) found.push(where + " has a " + field + " that is not a number.");
      });
      if (row.outcome === "ok" && !isNumber(row.estimated_minutes)) found.push(where + " is marked timed but has no driving time.");
      if (row.outcome !== "ok" && !isBlank(row.estimated_minutes)) found.push(where + " has a driving time without a timed outcome.");
      ["departure_time", "departure_time_source"].forEach(function (field) {
        if (!isBlank(row[field]) && !isText(row[field])) found.push(where + " has a " + field + " that is not text.");
      });
    });
    envelope.ranked.forEach(function (entry, i) {
      if (!isObject(entry) || !isText(entry.facility_id)) { found.push("Ranked entry " + (i + 1) + " has no campus id."); return; }
      var where = "Ranked campus " + entry.facility_id;
      if (!isNumber(entry.travel)) found.push(where + " has no travel figure.");
      var row = rows[entry.facility_id];
      if (!row) { found.push(where + " has no routing result."); return; }
      if (routing.ranking_metric === "travel_minutes" && row.outcome !== "ok") found.push(where + " is ranked by driving time without a timed outcome.");
      if (routing.ranking_metric === "distance_km" && !isNumber(row.distance_km)) found.push(where + " is ranked by distance without a distance.");
    });
    if (found.length > 4) found = found.slice(0, 4).concat(["And " + (found.length - 4) + " more problems."]);
    return found;
  }

  function reasonKind(reason) {
    if (LOCAL_LIMIT.indexOf(reason) !== -1) return "local_limit";
    if (LOCAL_RESERVE.indexOf(reason) !== -1) return "local_reserve";
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
      local_reserve: errors.filter(function (reason) { return reasonKind(reason) === "local_reserve"; }),
      local_setup: errors.filter(function (reason) { return reasonKind(reason) === "local_setup"; }),
      provider_errors: errors.filter(function (reason) { return reasonKind(reason) === "provider"; }),
      requested_at: routing.requested_at || null,
      approximate_origin: Boolean(routing.approximate_origin),
      coverage_empty: routing.coverage_state === "empty",
      attribution: routing.attribution || null,
    };
  }

  /*
   * Which view the person last asked for, and whether a search is in progress.
   *
   * Choosing an example, choosing a file and pressing Search each bump `intent`. A file read or a
   * search that finishes later is applied only if nothing else was asked for in between, so a slow
   * answer never replaces a newer view. A search always releases the control when it settles,
   * whatever happened. Search needs the request that produced the view, so a response opened from
   * a file, which carries no request, cannot be searched again.
   */
  function session() {
    var state = { intent: 0, inFlight: false, request: null, source: null };
    return {
      intend: function () { state.intent += 1; return state.intent; },
      isCurrent: function (token) { return token === state.intent; },
      adopt: function (source, request) { state.source = source; state.request = request || null; },
      source: function () { return state.source; },
      request: function () { return state.request; },
      searching: function () { return state.inFlight; },
      canSearch: function () { return !state.inFlight && state.request !== null; },
      begin: function () {
        if (state.inFlight || state.request === null) return null;
        state.inFlight = true;
        state.intent += 1;
        return { token: state.intent, request: state.request };
      },
      settle: function (ticket) {
        state.inFlight = false;
        return ticket.token === state.intent;
      },
    };
  }

  return { STATES: STATES, GROUPS: GROUPS, problems: problems, reasonKind: reasonKind, groupOf: groupOf,
    measure: measure, view: view, session: session };
});
