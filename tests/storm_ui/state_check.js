// Checks the page's state derivation against every embedded replay. Run by test_storm_ui.py.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..");
const S = require(path.join(root, "app", "storm_ui", "replay_state.js"));
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "app", "storm_ui", "data", "scenarios.js"), "utf8"), sandbox);
const bundle = sandbox.window.STORM_BUNDLE;
const replays = bundle.replays;
let checks = 0;
const ok = (value, message) => { assert.ok(value, message); checks += 1; };
const same = (actual, expected, message) => { assert.deepEqual(actual, expected, message); checks += 1; };

same(Object.keys(replays).length, bundle.scenarios.length * bundle.detour_caps.length, "one replay per scenario and cap");
ok(replays[bundle.default], "default replay present");

for (const [key, replay] of Object.entries(replays)) {
  same(S.problems(replay), [], `${key}: valid`);
  const last = S.lastMinute(replay);
  for (const policy of Object.keys(replay.policies)) {
    same(S.finalCheck(replay, policy), [], `${key}/${policy}: derived totals equal the file's`);
    const before = S.stateAt(replay, policy, S.BEFORE_START);
    same([before.announced.length, before.events.length, before.metrics.requested], [0, 0, 0], `${key}/${policy}: nothing before the start`);
    const final = S.stateAt(replay, policy, last);
    for (const pool of final.pools) {
      same(pool.free, replay.policies[policy].final_free_slots[pool.id], `${key}/${policy}/${pool.id}: final free slots`);
      if (pool.status === "known") {
        ok(pool.free >= 0 && pool.used >= 0, `${key}/${policy}/${pool.id}: never negative`);
        same(pool.used + pool.free + pool.offline, pool.reported_slots, `${key}/${policy}/${pool.id}: slots reconcile`);
      } else {
        same([pool.used, pool.free], [null, null], `${key}/${policy}/${pool.id}: unknown or stale pools carry no counts`);
      }
    }
    // The clock never reveals a request, an assignment or a change early.
    for (const minute of S.minutes(replay)) {
      const state = S.stateAt(replay, policy, minute);
      ok(state.events.every((e) => e.minute <= minute) && state.announced.every((r) => r.arrival_minute <= minute)
        && state.capacity_events.every((c) => c.minute <= minute), `${key}/${policy}@${minute}: no future information`);
      same(state.metrics.requested, state.announced.length, `${key}/${policy}@${minute}: every announced request has an outcome`);
    }
  }
}

const storm = replays["storm|10"];
same(S.minutes(storm), [0, 5, 12, 16, 20], "storm clock");
same([S.nextMinute(storm, -1), S.nextMinute(storm, 5), S.nextMinute(storm, 20)], [0, 12, 20], "step forward");
same([S.previousMinute(storm, 12), S.previousMinute(storm, 0)], [5, -1], "step back");
same(S.stateAt(storm, "scarcity_aware", 4).announced.length, 1, "second request hidden until minute 5");
same(S.explain(storm, "scarcity_aware", "r02", 4), null, "no explanation before a request is announced");

let detour = S.explain(storm, "scarcity_aware", "r01", 0);
same([detour.event.campus_id, detour.event.nearest_campus_id, detour.event.extra_travel_minutes], ["B", "A", 4], "routine detour");
same([detour.protected_pool, detour.protected_use], ["A-dialysis", null], "protected pool not yet used at minute 0");
detour = S.explain(storm, "scarcity_aware", "r01", 5);
same(detour.protected_use.request_id, "r02", "the protected slot is used by the urgent request");
same(S.explain(storm, "nearest_first", "r01", 20).protected_pool, null, "no protected pool without a detour");
same(S.explain(storm, "nearest_first", "r02", 20).event.reason, "no_staffed_slot_left", "unserved reason kept");
const end = S.stateAt(storm, "scarcity_aware", 20).metrics;
same([end.assigned, end.unassigned, end.urgent_on_time, end.urgent_requested, end.extra_travel_minutes, end.detours], [8, 0, 2, 2, 4, 1], "storm totals, scarcity-aware");
const near = S.stateAt(storm, "nearest_first", 20).metrics;
same([near.assigned, near.unassigned, near.urgent_on_time, near.urgent_requested, near.extra_travel_minutes], [7, 1, 1, 2, 0], "storm totals, nearest first");

const calm = replays["no_surge|10"];
detour = S.explain(calm, "scarcity_aware", "r01", S.lastMinute(calm));
same([detour.event.extra_travel_minutes, detour.protected_pool, detour.protected_use], [4, "A-dialysis", null], "no surge: detour with no later use");

const loss = S.stateAt(replays["resource_loss|10"], "scarcity_aware", 5).pools.find((p) => p.id === "A-dialysis");
same([loss.used, loss.free, loss.offline], [0, 0, 1], "an unbooked slot goes offline");
const unknown = S.stateAt(replays["missing_capacity|10"], "nearest_first", 0).pools.find((p) => p.id === "A-dialysis");
same([unknown.status, unknown.free], ["unknown", null], "unknown capacity stays unknown");
const stale = S.stateAt(storm, "nearest_first", 20).pools.find((p) => p.id === "E-trauma");
same([stale.status, stale.reported_slots, stale.free], ["stale", 2, null], "a stale count is reported but not usable");
same(S.stateAt(replays["overload|10"], "nearest_first", 28).metrics.unassigned_reasons, { no_staffed_slot_left: 11 }, "overload reasons");

const broken = JSON.parse(JSON.stringify(storm));
broken.policies.nearest_first.metrics.assigned = 8;
ok(S.finalCheck(broken, "nearest_first").length === 1, "a file whose totals disagree with its events is reported");
same(S.problems({ schema_version: "other" }).length > 0, true, "foreign files are rejected");

// Malformed nested data is refused with a reason, never drawn.
const copy = () => JSON.parse(JSON.stringify(storm));
const refuses = (change, expected, message) => {
  const replay = copy();
  change(replay);
  const found = S.problems(replay);
  ok(found.length > 0 && found.join(" ").includes(expected), `${message}: ${found.join(" ")}`);
};
refuses((r) => { delete r.campuses[0].resources; }, "has no resources list", "a campus without its resources list");
refuses((r) => { r.campuses[1].resources = "two"; }, "has no resources list", "a campus whose resources are not a list");
refuses((r) => { r.campuses[0].resources[0] = null; }, "has no id or service", "a null resource");
refuses((r) => { r.campuses[0].resources[0].slots = "1"; }, "slot count that is not a number", "a text slot count");
refuses((r) => { delete r.campuses[2].latitude; }, "has no position", "a campus without a position");
refuses((r) => { r.origins[0] = 7; }, "has no id", "an origin that is not an object");
refuses((r) => { r.requests[0].origin_id = "nowhere"; }, "names an origin that is not in the file", "a request from an unknown origin");
refuses((r) => { delete r.requests[1].max_travel_minutes; }, "has no travel limit", "a request without a travel limit");
refuses((r) => { r.policies.nearest_first.events[0].campus_id = "Z"; }, "names a campus that is not in the file", "an event at an unknown campus");
refuses((r) => { r.policies.scarcity_aware.events[0].resource_id = "Z-none"; }, "names a resource that is not in the file", "an event in an unknown pool");
refuses((r) => { delete r.policies.nearest_first.events[0].resource_after; }, "has no slot counts before and after", "an event without slot counts");
refuses((r) => { r.policies.nearest_first.events[1] = null; }, "names a request that is not in the file", "a null event");
refuses((r) => { r.policies.nearest_first.events[0].status = "maybe"; }, "has no recognised status", "an unknown status");
refuses((r) => { r.policies.scarcity_aware.events[0].nearest_campus_id = null; }, "detour without its fastest campus", "a detour without its fastest campus");
refuses((r) => { r.policies.nearest_first.capacity_events = {}; }, "capacity events that are not a list", "capacity events that are not a list");
refuses((r) => { r.policies.nearest_first = null; }, "has no events", "a null policy");
const lossy = JSON.parse(JSON.stringify(replays["resource_loss|10"]));
lossy.policies.scarcity_aware.capacity_events[0].resource_id = "gone";
ok(S.problems(lossy).join(" ").includes("names a resource that is not in the file"), "a capacity change in an unknown pool");
const many = copy();
many.campuses.forEach((campus) => { delete campus.resources; });
same(S.problems(many).length, 5, "a long list of problems is cut to four and a count");
ok(S.problems(many)[4].startsWith("And "), "the cut is stated");
same(S.problems([]), ["The file is not a replay object."], "a list is not a replay");

// Equal totals do not mean equal outcomes: the comparison is made request by request.
const stormCompare = S.compare(storm, "nearest_first", "scarcity_aware", 20);
same([stormCompare.differing, stormCompare.served_only_second, stormCompare.served_differently, stormCompare.identical],
  [["r01", "r02"], ["r02"], ["r01"], false], "storm: r01 and r02 differ");
same(S.compare(storm, "nearest_first", "scarcity_aware", 0).differing, ["r01"], "nothing later than the clock is compared");
ok(S.compare(replays["storm|0"], "nearest_first", "scarcity_aware", 20).identical, "detour 0: every request has the same outcome");
ok(S.summary(replays["storm|0"], "nearest_first", "scarcity_aware", "Nearest first", "Scarcity-aware")
  .includes("Every patient had the same outcome under both"), "identical outcomes are stated only after checking each request");

const swapped = copy();
{
  // Give scarcity-aware the same totals as nearest-first, but by serving a different person:
  // r01 is turned away and r02 takes the slot r01 held under nearest-first.
  const nearest = swapped.policies.nearest_first.events;
  const events = JSON.parse(JSON.stringify(nearest));
  const first = events.find((e) => e.request_id === "r01"), second = events.find((e) => e.request_id === "r02");
  const taken = { campus_id: first.campus_id, resource_id: first.resource_id, travel_minutes: first.travel_minutes,
    extra_travel_minutes: 0, nearest_campus_id: first.nearest_campus_id, nearest_feasible_minutes: first.nearest_feasible_minutes,
    resource_before: first.resource_before, resource_after: first.resource_after, eligible_campuses: first.eligible_campuses };
  Object.assign(first, { status: "unassigned", reason: second.reason, campus_id: null, resource_id: null, travel_minutes: null,
    extra_travel_minutes: null, resource_before: null, resource_after: null });
  Object.assign(second, { status: "assigned", reason: "nearest_feasible" }, taken);
  swapped.policies.scarcity_aware = { events, capacity_events: [], metrics: {}, final_free_slots: {} };
}
same(S.problems(swapped), [], "the swapped replay is well formed");
const left = S.stateAt(swapped, "nearest_first", 20).metrics, right = S.stateAt(swapped, "scarcity_aware", 20).metrics;
same([left.assigned, left.unassigned, left.extra_travel_minutes], [right.assigned, right.unassigned, right.extra_travel_minutes],
  "the swapped replay has equal totals");
const swap = S.compare(swapped, "nearest_first", "scarcity_aware", 20);
same([swap.identical, swap.differing, swap.served_only_first, swap.served_only_second], [false, ["r01", "r02"], ["r01"], ["r02"]],
  "equal totals, different people served");
const swapText = S.summary(swapped, "nearest_first", "scarcity_aware", "Nearest first", "Scarcity-aware");
ok(swapText.includes("2 patients had a different outcome under the two policies: r01, r02."), "the sentence names the requests that differ");
ok(S.summary(swapped, "nearest_first", "scarcity_aware", "Nearest first", "Urgency-aware", (id) => "Patient " + Number(id.slice(1)))
  .includes("Served only under Nearest first: Patient 1."), "the page can supply plain names for the people it lists");
ok(swapText.includes("Served only under Nearest first: r01.") && swapText.includes("Served only under Scarcity-aware: r02."),
  "the sentence says who was served under which policy");
ok(!/same outcome|no difference|anyone extra/.test(swapText), "equal totals are not described as the same result");
for (const [key, replay] of Object.entries(replays)) {
  const text = S.summary(replay, "nearest_first", "scarcity_aware", "Nearest first", "Scarcity-aware");
  const each = S.compare(replay, "nearest_first", "scarcity_aware", S.lastMinute(replay));
  same(text.includes("Every patient had the same outcome"), each.identical, `${key}: the sentence follows the request-by-request comparison`);
}

console.log(`ok ${checks} checks`);
