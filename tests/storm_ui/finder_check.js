/* Checks that the finder page's display logic never invents, drops or mixes results. */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..", "app", "storm_ui");
const F = require(path.join(root, "finder_state.js"));
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "data", "finder_examples.js"), "utf8"), sandbox);
const bundle = sandbox.window.FINDER_EXAMPLES;

let checks = 0;
function ok(condition, message) {
  checks += 1;
  if (!condition) { console.error("FAIL " + message); process.exitCode = 1; }
}

ok(bundle && bundle.synthetic === true, "the bundle is labelled synthetic");
const expected = { timed: "ok", partial: "partial", fallback: "fallback", local_limit: "partial",
  local_limit_all: "unavailable", reserved_run: "unavailable", no_route: "no_route", unavailable: "unavailable", no_coordinates: "not_requested" };
ok(JSON.stringify(bundle.examples.map((e) => e.key).sort()) === JSON.stringify(Object.keys(expected).sort()), "the expected examples are present");

bundle.examples.forEach((example) => {
  const envelope = example.response, name = example.key;
  ok(F.problems(envelope).length === 0, name + ": the response is accepted");
  const view = F.view(envelope);
  ok(view.state === expected[name], name + ": state is " + expected[name]);
  ok(!("candidates" in example.request), name + ": the page holds no candidate records");

  // Every campus appears exactly once: ranked or in one group.
  const seen = {};
  view.ranked.forEach((entry) => { seen[entry.facility_id] = (seen[entry.facility_id] || 0) + 1; });
  F.GROUPS.forEach((group) => view.groups[group].forEach((row) => { seen[row.facility_id] = (seen[row.facility_id] || 0) + 1; }));
  envelope.routing.results.forEach((row) => ok(seen[row.facility_id] === 1, name + ": " + row.facility_id + " appears once"));
  ok(Object.keys(seen).length === envelope.routing.results.length, name + ": no campus is added");

  // The ranked order and figures are the backend's own.
  ok(JSON.stringify(view.ranked.map((e) => [e.facility_id, e.travel])) ===
     JSON.stringify(envelope.ranked.map((e) => [e.facility_id, e.travel])), name + ": ranked order and figures are unchanged");
  ok(view.ranked.length === envelope.routing.counts.returned, name + ": ranked length equals the returned count");

  // Minutes and kilometres are never mixed.
  const km = envelope.routing.ranking_metric === "distance_km";
  ok(view.unit === (km ? "km" : "minutes"), name + ": the unit follows the ranking metric");
  view.ranked.forEach((entry) => {
    if (km) ok(entry.result.estimated_minutes === null, name + ": a distance ranking shows no driving time");
    else ok(entry.result.outcome === "ok" && entry.travel === entry.result.estimated_minutes, name + ": a timed rank has its own driving time");
  });
  F.GROUPS.forEach((group) => view.groups[group].forEach((row) => {
    if (row.measure) ok(row.measure.unit === (row.result.metric === "distance_km" ? "km" : "minutes"), name + ": group figure keeps its unit");
    if (group === "unresolved" || group === "no_route" || group === "not_sent") {
      ok(row.result.estimated_minutes === null, name + ": an unresolved campus has no driving time");
    }
    if (group === "not_sent") ok(row.evaluated === false, name + ": a campus not sent was not evaluated");
    if (group === "no_route") ok(row.result.outcome === "no_route", name + ": the no-route group holds only no-route outcomes");
  }));
});

const byKey = {};
bundle.examples.forEach((example) => { byKey[example.key] = F.view(example.response); });
ok(byKey.partial.groups.unresolved.length === 1 && byKey.partial.groups.no_route.length === 1, "partial separates unavailable from unroutable");
ok(byKey.partial.provider_errors.length === 1 && byKey.partial.local_limit.length === 0, "partial reports a provider error");
ok(byKey.fallback.unit === "km" && byKey.fallback.ranked.length === 3 && byKey.fallback.groups.not_top.length === 1, "fallback ranks by kilometres");
ok(byKey.local_limit.local_limit.length === 1 && byKey.local_limit.provider_errors.length === 0, "a local limit is not a provider error");
ok(byKey.local_limit_all.local_limit.length === 1 && byKey.local_limit_all.ranked.length === 0 && byKey.local_limit_all.unit === "minutes",
  "a local limit never falls back to distance");
ok(byKey.no_route.ranked.length === 0 && byKey.no_route.groups.no_route.length === 4, "no-route ranks nothing");
ok(byKey.no_coordinates.coverage_empty && byKey.no_coordinates.requested_at === null && byKey.no_coordinates.counts.provider_calls_attempted === 0,
  "empty coverage sends nothing");
ok(byKey.timed.groups.over_limit.length === 1 && byKey.timed.groups.over_limit[0].measure.unit === "minutes", "an over-limit campus keeps its time");

// An exhausted reserved run is this application's own limit, worded apart from a provider outage.
ok(byKey.reserved_run.local_reserve.length === 1 && byKey.reserved_run.provider_errors.length === 0 &&
   byKey.reserved_run.local_limit.length === 0, "an exhausted reserved run is a local reserve reason, not a provider error");
ok(byKey.reserved_run.ranked.length === 0 && byKey.reserved_run.unit === "minutes" && byKey.reserved_run.counts.provider_calls_attempted === 0,
  "an exhausted reserved run sends nothing and never falls back to distance");
ok(byKey.unavailable.provider_errors.length === 1 && byKey.unavailable.local_reserve.length === 0, "a provider outage is not a reserve reason");
["reserved_budget_exhausted", "reservation_month_mismatch", "protected_allowance_exhausted", "validation_reservation_required",
  "validation_allocation_exhausted", "unknown_reservation"].forEach((reason) => {
  ok(F.reasonKind(reason) === "local_reserve", reason + " is a local reserve reason");
});
["daily_call_budget_exceeded", "monthly_call_budget_exceeded", "local_rate_limited", "local_inflight_limit", "shared_provider_cooldown"]
  .forEach((reason) => ok(F.reasonKind(reason) === "local_limit", reason + " is a local limit"));
["invalid_operator_budget", "local_clock_regressed", "routing_disabled", "unverified_allocation"]
  .forEach((reason) => ok(F.reasonKind(reason) === "local_setup", reason + " is a local setup reason"));
["provider_timeout", "provider_connection_error", "provider_quota_exceeded"]
  .forEach((reason) => ok(F.reasonKind(reason) === "provider", reason + " is a provider reason"));

// Nested entries are checked before anything is drawn.
const timed = bundle.examples.find((e) => e.key === "timed").response;
const copy = () => JSON.parse(JSON.stringify(timed));
const refuses = (change, expected, message) => {
  const envelope = copy();
  change(envelope);
  const found = F.problems(envelope);
  ok(found.length > 0 && found.join(" ").includes(expected), message + ": " + found.join(" "));
};
refuses((e) => { e.routing.results[0] = null; }, "has no campus id", "a null result row");
refuses((e) => { e.routing.results[1].outcome = "fine"; }, "no recognised outcome", "an unknown outcome");
refuses((e) => { e.routing.results[1].estimated_minutes = "14"; }, "estimated_minutes that is not a number", "a text driving time");
refuses((e) => { e.routing.results[1].estimated_minutes = null; }, "marked timed but has no driving time", "a timed row without a time");
refuses((e) => { e.routing.results[4].estimated_minutes = 3; }, "driving time without a timed outcome", "a time on an untimed row");
refuses((e) => { e.routing.results[2].exclusion_reasons = "none"; }, "exclusion reasons that are not a list", "exclusion reasons that are not a list");
refuses((e) => { e.routing.results[2].facility_id = e.routing.results[1].facility_id; }, "appears more than once", "a repeated campus");
refuses((e) => { e.routing.results[0].metric = "furlongs"; }, "no recognised metric", "an unknown metric");
refuses((e) => { e.ranked[0].travel = null; }, "has no travel figure", "a ranked entry without a figure");
refuses((e) => { e.ranked[0].facility_id = "SYNTHETIC-CAMPUS-Z"; }, "has no routing result", "a ranked campus with no result");
refuses((e) => { e.ranked[0] = "B"; }, "has no campus id", "a ranked entry that is not an object");
refuses((e) => { e.routing.counts.timed = "4"; }, "Count timed is not a number", "a text count");
refuses((e) => { e.routing.errors = "provider_timeout"; }, "not a list of reason names", "errors that are not a list");
refuses((e) => { e.routing.ranking_metric = "minutes"; }, "Unknown ranking metric", "an unknown ranking metric");
refuses((e) => { delete e.routing.travel_budget; }, "travel limit is not a number", "a missing travel limit");
refuses((e) => { e.routing.attribution = "TomTom"; }, "attribution is not an object", "attribution that is not an object");
const mixed = JSON.parse(JSON.stringify(bundle.examples.find((e) => e.key === "partial").response));
mixed.ranked.push({ facility_id: "SYNTHETIC-CAMPUS-A", travel: 2.3 });
ok(F.problems(mixed).join(" ").includes("ranked by driving time without a timed outcome"), "an untimed campus cannot sit in a timed ranking");
const noisy = copy();
noisy.routing.results.forEach((row) => { row.outcome = "fine"; });
ok(F.problems(noisy).length === 5 && F.problems(noisy)[4].startsWith("And "), "a long list of problems is cut to four and a count");

// The search session: one call at a time, late answers never replace a newer view.
const exampleRequest = bundle.examples[0].request, otherRequest = bundle.examples[1].request;
{
  // Delayed success after the view changed: released, not applied.
  const s = F.session();
  s.intend(); s.adopt("example", exampleRequest);
  const ticket = s.begin();
  ok(ticket && ticket.request === exampleRequest, "a search is bound to the request that was submitted");
  ok(s.begin() === null && !s.canSearch(), "a second search cannot start while one is in progress");
  s.intend(); s.adopt("example", otherRequest);              // the person picks another example
  ok(!s.canSearch(), "the control stays held while the earlier search is still running");
  ok(s.settle(ticket) === false, "a late success is not applied to the newer view");
  ok(s.canSearch() && s.request() === otherRequest && s.source() === "example", "the control is released and the newer view is kept");
}
{
  // Delayed failure after the view changed: released, and the failure is not reported against the newer view.
  const s = F.session();
  s.intend(); s.adopt("example", exampleRequest);
  const ticket = s.begin();
  s.intend(); s.adopt("file", null);                         // the person opens a response file
  ok(s.settle(ticket) === false, "a late failure is not applied to the newer view");
  ok(!s.searching() && !s.canSearch() && s.request() === null, "a response-only file leaves no request to search with");
  ok(s.begin() === null, "Search does nothing for a response-only file");
}
{
  // A response-only import does not keep the preceding example's request.
  const s = F.session();
  s.intend(); s.adopt("example", exampleRequest);
  ok(s.canSearch(), "an example can be searched");
  s.intend(); s.adopt("file", null);
  ok(s.request() === null && !s.canSearch(), "opening a file drops the earlier example's request");
  s.intend(); s.adopt("example", otherRequest);
  ok(s.canSearch() && s.request() === otherRequest, "choosing an example restores search with that example's request");
}
{
  // An invalid row is refused, the control is released, and a retry succeeds.
  const s = F.session();
  s.intend(); s.adopt("example", exampleRequest);
  const first = s.begin();
  const bad = copy();
  bad.routing.results[1].outcome = "fine";
  ok(s.settle(first) === true && F.problems(bad).length > 0, "the answer is current but invalid, so it is not shown");
  ok(s.canSearch() && s.source() === "example", "the control is released after an invalid answer and the view is unchanged");
  const second = s.begin();
  ok(second && second.request === exampleRequest, "the retry submits the same request");
  ok(s.settle(second) === true && F.problems(copy()).length === 0, "the retry's valid answer is current and accepted");
  s.adopt("search", second.request);
  ok(s.source() === "search" && s.canSearch(), "after a shown search the page can search again");
}
{
  // A file chosen and then superseded while it was being read is ignored.
  const s = F.session();
  const slowFile = s.intend();
  const example = s.intend(); s.adopt("example", exampleRequest);
  ok(!s.isCurrent(slowFile) && s.isCurrent(example), "a stale file read is ignored");
}

ok(F.problems(null).length === 1, "a non-object is rejected");
ok(F.problems({ status: "ok", ranked: [] }).length === 1, "a response without routing is rejected");
ok(F.problems({ status: "invalid_input", message: "bad" })[0].indexOf("bad") !== -1, "an invalid-input reply is explained");
ok(F.problems({ ranked: [], routing: { state: "surprise", results: [], counts: {}, ranking_metric: "travel_minutes", travel_budget: 30 } })
  .join(" ") === "Unknown routing state: surprise.", "an unknown state is rejected");

if (!process.exitCode) console.log("ok " + checks + " checks");
