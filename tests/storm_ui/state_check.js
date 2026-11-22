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

console.log(`ok ${checks} checks`);
