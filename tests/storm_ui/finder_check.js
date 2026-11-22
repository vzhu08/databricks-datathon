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
  local_limit_all: "unavailable", no_route: "no_route", unavailable: "unavailable", no_coordinates: "not_requested" };
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

ok(F.problems(null).length === 1, "a non-object is rejected");
ok(F.problems({ status: "ok", ranked: [] }).length === 1, "a response without routing is rejected");
ok(F.problems({ status: "invalid_input", message: "bad" })[0].indexOf("bad") !== -1, "an invalid-input reply is explained");
ok(F.problems({ ranked: [], routing: { state: "surprise", results: [], counts: {} } }).length === 1, "an unknown state is rejected");

if (!process.exitCode) console.log("ok " + checks + " checks");
