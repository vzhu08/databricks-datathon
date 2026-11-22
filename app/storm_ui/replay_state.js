/*
 * What the storm replay page shows at a given clock minute.
 *
 * Pure functions over a replay produced by `python -m app.simulation`. Nothing here ranks,
 * allocates or estimates travel: every outcome is read from the replay's own events. Totals are
 * derived from the events announced so far, so future requests and final results stay hidden
 * during playback.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.StormState = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var SCHEMA = "storm-replay-v1";
  var BEFORE_START = -1;

  function isObject(value) { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }
  function isNumber(value) { return typeof value === "number" && isFinite(value); }
  function isText(value) { return typeof value === "string" && value.length > 0; }
  function isCount(value) { return isObject(value) && isNumber(value.used) && isNumber(value.free); }

  /* Why a file cannot be shown. An empty list means every part the page reads is present and well formed. */
  function problems(replay) {
    var found = [];
    if (!isObject(replay)) return ["The file is not a replay object."];
    if (replay.schema_version !== SCHEMA) found.push("Expected schema_version " + SCHEMA + ".");
    if (replay.synthetic !== true) found.push("The replay is not labelled synthetic.");
    ["campuses", "origins", "requests"].forEach(function (name) {
      if (!Array.isArray(replay[name])) found.push("Missing list: " + name + ".");
    });
    var policies = isObject(replay.policies) ? Object.keys(replay.policies) : [];
    if (policies.length < 2) found.push("Expected at least two policies to compare.");
    policies.forEach(function (name) {
      if (!isObject(replay.policies[name]) || !Array.isArray(replay.policies[name].events)) found.push("Policy " + name + " has no events.");
    });
    if (found.length) return found;

    var campuses = {}, pools = {}, origins = {}, requests = {};
    replay.campuses.forEach(function (campus, i) {
      if (!isObject(campus) || !isText(campus.id)) { found.push("Campus " + (i + 1) + " has no id."); return; }
      if (!isNumber(campus.latitude) || !isNumber(campus.longitude)) found.push("Campus " + campus.id + " has no position.");
      if (!Array.isArray(campus.resources)) { found.push("Campus " + campus.id + " has no resources list."); return; }
      campuses[campus.id] = true;
      campus.resources.forEach(function (pool, j) {
        var where = "Campus " + campus.id + " resource " + (j + 1);
        if (!isObject(pool) || !isText(pool.id) || !isText(pool.service)) { found.push(where + " has no id or service."); return; }
        if (pool.slots !== null && !isNumber(pool.slots)) found.push(where + " has a slot count that is not a number.");
        if (pool.tools !== undefined && !Array.isArray(pool.tools)) found.push(where + " has tools that are not a list.");
        if (["known", "unknown", "stale"].indexOf(pool.capacity_status) === -1) found.push(where + " has no recognised capacity status.");
        pools[pool.id] = true;
      });
    });
    replay.origins.forEach(function (origin, i) {
      if (!isObject(origin) || !isText(origin.id)) { found.push("Origin " + (i + 1) + " has no id."); return; }
      if (!isNumber(origin.latitude) || !isNumber(origin.longitude)) found.push("Origin " + origin.id + " has no position.");
      origins[origin.id] = true;
    });
    replay.requests.forEach(function (request, i) {
      if (!isObject(request) || !isText(request.id)) { found.push("Request " + (i + 1) + " has no id."); return; }
      var where = "Request " + request.id;
      if (!isNumber(request.arrival_minute)) found.push(where + " has no arrival minute.");
      if (!isNumber(request.max_travel_minutes)) found.push(where + " has no travel limit.");
      if (!origins[request.origin_id]) found.push(where + " names an origin that is not in the file.");
      if (!isText(request.service) || !isText(request.urgency)) found.push(where + " has no service or urgency.");
      if (request.required_tools !== undefined && !Array.isArray(request.required_tools)) found.push(where + " has tools that are not a list.");
      requests[request.id] = true;
    });
    // Events are checked only against a sound cast list, so one broken campus is reported once.
    if (found.length) return found.length > 4 ? found.slice(0, 4).concat(["And " + (found.length - 4) + " more problems."]) : found;
    policies.forEach(function (name) {
      var policy = replay.policies[name];
      policy.events.forEach(function (event, i) {
        var where = "Policy " + name + " event " + (i + 1);
        if (!isObject(event) || !requests[event.request_id]) { found.push(where + " names a request that is not in the file."); return; }
        if (!isNumber(event.minute)) found.push(where + " has no minute.");
        if (!origins[event.origin_id]) found.push(where + " names an origin that is not in the file.");
        if (!isText(event.service) || !isText(event.urgency)) found.push(where + " has no service or urgency.");
        if (event.excluded_pool_counts !== undefined && !isObject(event.excluded_pool_counts)) found.push(where + " has excluded pool counts that are not an object.");
        if (event.eligible_campuses !== undefined && !Array.isArray(event.eligible_campuses)) found.push(where + " has eligible campuses that are not a list.");
        if (event.status === "assigned") {
          if (!campuses[event.campus_id]) found.push(where + " names a campus that is not in the file.");
          if (!pools[event.resource_id]) found.push(where + " names a resource that is not in the file.");
          if (!isNumber(event.travel_minutes) || !isNumber(event.extra_travel_minutes)) found.push(where + " has no travel minutes.");
          if (event.extra_travel_minutes > 0 && (!campuses[event.nearest_campus_id] || !isNumber(event.nearest_feasible_minutes))) {
            found.push(where + " has a detour without its fastest campus.");
          }
          if (!isCount(event.resource_before) || !isCount(event.resource_after)) found.push(where + " has no slot counts before and after.");
        } else if (event.status === "unassigned") {
          if (!isText(event.reason)) found.push(where + " is not served but gives no reason.");
        } else {
          found.push(where + " has no recognised status.");
        }
      });
      if (policy.capacity_events !== undefined && !Array.isArray(policy.capacity_events)) {
        found.push("Policy " + name + " has capacity events that are not a list.");
        return;
      }
      (policy.capacity_events || []).forEach(function (change, i) {
        var where = "Policy " + name + " capacity change " + (i + 1);
        if (!isObject(change) || !pools[change.resource_id]) { found.push(where + " names a resource that is not in the file."); return; }
        if (!isNumber(change.minute) || !isNumber(change.lost_free_slots)) found.push(where + " has no minute or slot count.");
        if (!isCount(change.resource_after)) found.push(where + " has no slot counts after the change.");
      });
    });
    if (!found.length) {
      // Last guard: derive every state the page can show. Anything that still fails is reported, not drawn.
      try { rehearse(replay); } catch (error) { found.push("Part of the replay could not be read."); }
    }
    if (found.length > 4) found = found.slice(0, 4).concat(["And " + (found.length - 4) + " more problems."]);
    return found;
  }

  /* Derives every state the page can reach, so a file that cannot be drawn fails before it is opened. */
  function rehearse(replay) {
    var names = Object.keys(replay.policies);
    var last = lastMinute(replay);
    names.forEach(function (name) {
      minutes(replay).forEach(function (minute) { stateAt(replay, name, minute); });
      replay.requests.forEach(function (request) { explain(replay, name, request.id, last); });
      finalCheck(replay, name);
    });
    for (var i = 0; i < names.length; i += 1) {
      for (var j = i + 1; j < names.length; j += 1) summary(replay, names[i], names[j], names[i], names[j]);
    }
  }

  function resources(replay) {
    var index = {};
    replay.campuses.forEach(function (campus) {
      campus.resources.forEach(function (resource) {
        index[resource.id] = {
          id: resource.id, campus_id: campus.id, service: resource.service,
          tools: resource.tools || [], slots: resource.slots, status: resource.capacity_status,
        };
      });
    });
    return index;
  }

  function byId(list) {
    var index = {};
    list.forEach(function (item) { index[item.id] = item; });
    return index;
  }

  /* Minutes at which anything is announced in any policy, in order. */
  function minutes(replay) {
    var seen = {};
    replay.requests.forEach(function (request) { seen[request.arrival_minute] = true; });
    Object.keys(replay.policies).forEach(function (name) {
      var policy = replay.policies[name];
      policy.events.forEach(function (event) { seen[event.minute] = true; });
      (policy.capacity_events || []).forEach(function (change) { seen[change.minute] = true; });
    });
    return Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
  }

  function lastMinute(replay) {
    var all = minutes(replay);
    return all.length ? all[all.length - 1] : 0;
  }

  function nextMinute(replay, minute) {
    var later = minutes(replay).filter(function (m) { return m > minute; });
    return later.length ? later[0] : lastMinute(replay);
  }

  function previousMinute(replay, minute) {
    var earlier = minutes(replay).filter(function (m) { return m < minute; });
    return earlier.length ? earlier[earlier.length - 1] : BEFORE_START;
  }

  function tally(events, requests) {
    var result = {
      requested: events.length, assigned: 0, unassigned: 0, extra_travel_minutes: 0, detours: 0,
      urgent_requested: 0, urgent_on_time: 0, unassigned_reasons: {}, by_urgency: {},
    };
    events.forEach(function (event) {
      var level = result.by_urgency[event.urgency] ||
        (result.by_urgency[event.urgency] = { requested: 0, assigned: 0, unassigned: 0, extra_travel_minutes: 0 });
      var request = requests[event.request_id];
      var limit = request ? request.max_travel_minutes : null;
      level.requested += 1;
      if (event.urgency === "highest") result.urgent_requested += 1;
      if (event.status === "assigned") {
        result.assigned += 1;
        level.assigned += 1;
        result.extra_travel_minutes += event.extra_travel_minutes;
        level.extra_travel_minutes += event.extra_travel_minutes;
        if (event.extra_travel_minutes > 0) result.detours += 1;
        if (event.urgency === "highest" && (limit === null || event.travel_minutes <= limit)) {
          result.urgent_on_time += 1;
        }
      } else {
        result.unassigned += 1;
        level.unassigned += 1;
        result.unassigned_reasons[event.reason] = (result.unassigned_reasons[event.reason] || 0) + 1;
      }
    });
    return result;
  }

  /* Everything one policy panel shows at `minute`. Nothing later than `minute` is included. */
  function stateAt(replay, policyName, minute) {
    var policy = replay.policies[policyName];
    var requests = byId(replay.requests);
    var index = resources(replay);
    var events = policy.events.filter(function (event) { return event.minute <= minute; });
    var changes = (policy.capacity_events || []).filter(function (change) { return change.minute <= minute; });
    var pools = {};
    Object.keys(index).forEach(function (id) {
      var resource = index[id];
      var known = resource.status === "known" && resource.slots !== null;
      pools[id] = {
        id: id, campus_id: resource.campus_id, service: resource.service, tools: resource.tools,
        status: resource.status, reported_slots: resource.slots,
        used: known ? 0 : null, free: known ? resource.slots : null, offline: 0,
      };
    });
    // Engine order: at each minute, capacity changes apply before that minute's assignments.
    var records = changes.map(function (change) { return { minute: change.minute, order: 0, change: change }; })
      .concat(events.filter(function (event) { return event.resource_id; })
        .map(function (event) { return { minute: event.minute, order: 1, event: event }; }));
    records.sort(function (a, b) { return a.minute - b.minute || a.order - b.order; });
    records.forEach(function (record) {
      var source = record.change || record.event;
      var pool = pools[source.resource_id];
      if (!pool || !source.resource_after) return;
      pool.used = source.resource_after.used;
      pool.free = source.resource_after.free;
      if (record.change) pool.offline += record.change.lost_free_slots;
    });
    return {
      minute: minute,
      announced: replay.requests.filter(function (request) { return request.arrival_minute <= minute; }),
      events: events,
      new_events: events.filter(function (event) { return event.minute === minute; }),
      capacity_events: changes,
      new_capacity_events: changes.filter(function (change) { return change.minute === minute; }),
      pools: Object.keys(pools).map(function (id) { return pools[id]; }),
      metrics: tally(events, requests),
    };
  }

  /* The pool that a detour kept free: the matching pool at the fastest feasible campus. */
  function protectedPool(replay, event) {
    if (!event || event.status !== "assigned" || !event.extra_travel_minutes) return null;
    var wanted = (event.preserved_profiles || []).map(function (profile) { return profile.split("/").slice(1); });
    var request = byId(replay.requests)[event.request_id];
    var needs = request ? request.required_tools || [] : [];
    var index = resources(replay);
    var candidates = Object.keys(index).map(function (id) { return index[id]; }).filter(function (resource) {
      return resource.campus_id === event.nearest_campus_id && resource.service === event.service &&
        needs.every(function (tool) { return resource.tools.indexOf(tool) !== -1; });
    });
    var exact = candidates.filter(function (resource) {
      return wanted.some(function (tools) {
        return tools.every(function (tool) { return resource.tools.indexOf(tool) !== -1; });
      });
    });
    var chosen = exact[0] || candidates[0];
    return chosen ? chosen.id : null;
  }

  /* One request under one policy, as far as the clock has reached. Null until it is announced. */
  function explain(replay, policyName, requestId, minute) {
    var request = byId(replay.requests)[requestId];
    if (!request || request.arrival_minute > minute) return null;
    var events = replay.policies[policyName].events;
    var position = -1;
    events.forEach(function (event, i) { if (event.request_id === requestId) position = i; });
    var event = position === -1 ? null : events[position];
    if (!event || event.minute > minute) return { request: request, event: null, protected_pool: null, protected_use: null };
    var pool = protectedPool(replay, event);
    var use = null;
    if (pool) {
      events.slice(position + 1).forEach(function (later) {
        if (!use && later.minute <= minute && later.resource_id === pool) use = later;
      });
    }
    return { request: request, event: event, protected_pool: pool, protected_use: use };
  }

  /* Request by request, where two policies ended differently at `minute`. Totals alone cannot show this. */
  function compare(replay, policyA, policyB, minute) {
    function outcomes(policyName) {
      var index = {};
      replay.policies[policyName].events.forEach(function (event) {
        if (event.minute <= minute) index[event.request_id] = event;
      });
      return index;
    }
    var a = outcomes(policyA), b = outcomes(policyB);
    var result = { differing: [], served_only_first: [], served_only_second: [], served_differently: [] };
    replay.requests.forEach(function (request) {
      var x = a[request.id], y = b[request.id];
      if (!x && !y) return;
      if (!x || !y) { result.differing.push(request.id); return; }
      if (x.status !== y.status) {
        result.differing.push(request.id);
        (x.status === "assigned" ? result.served_only_first : result.served_only_second).push(request.id);
      } else if (x.status === "assigned" && (x.campus_id !== y.campus_id || x.resource_id !== y.resource_id ||
                 x.travel_minutes !== y.travel_minutes)) {
        result.differing.push(request.id);
        result.served_differently.push(request.id);
      }
    });
    result.identical = result.differing.length === 0;
    return result;
  }

  /*
   * The end-of-shift sentence. Totals are stated as totals. Any statement about individual requests
   * comes from comparing their outcomes one by one, never from equal counts or equal minutes.
   */
  function summary(replay, policyA, policyB, nameA, nameB, nameOf) {
    var who = function (ids) { return ids.map(nameOf || function (id) { return id; }).join(", "); };
    var last = lastMinute(replay);
    var a = stateAt(replay, policyA, last).metrics, b = stateAt(replay, policyB, last).metrics;
    var each = compare(replay, policyA, policyB, last);
    function minutesText(n) { return n + (n === 1 ? " minute" : " minutes"); }
    var text = nameA + " served " + a.assigned + " of " + a.requested + " patients. " +
      nameB + " served " + b.assigned + " of " + b.requested + ".";
    var gap = b.extra_travel_minutes - a.extra_travel_minutes;
    if (gap !== 0) text += " " + (gap > 0 ? nameB : nameA) + " added " + minutesText(Math.abs(gap)) + " of travel in total.";
    if (each.identical) {
      text += " Every patient had the same outcome under both: the same campus, the same slot pool and the same travel time.";
    } else {
      text += " " + each.differing.length + (each.differing.length === 1 ? " patient" : " patients") +
        " had a different outcome under the two policies: " + who(each.differing) + ".";
      if (each.served_only_first.length) text += " Served only under " + nameA + ": " + who(each.served_only_first) + ".";
      if (each.served_only_second.length) text += " Served only under " + nameB + ": " + who(each.served_only_second) + ".";
    }
    return text;
  }

  /* Differences between totals derived from events and the totals the replay file reports. */
  function finalCheck(replay, policyName) {
    var supplied = replay.policies[policyName].metrics || {};
    var derived = stateAt(replay, policyName, lastMinute(replay)).metrics;
    var differences = [];
    function compare(label, mine, theirs) {
      if (theirs !== undefined && JSON.stringify(mine) !== JSON.stringify(theirs)) {
        differences.push(label + ": derived " + JSON.stringify(mine) + ", file " + JSON.stringify(theirs));
      }
    }
    compare("requested", derived.requested, supplied.requested);
    compare("assigned", derived.assigned, supplied.assigned);
    compare("unassigned", derived.unassigned, supplied.unassigned);
    compare("extra_travel_minutes", derived.extra_travel_minutes, supplied.extra_travel_minutes);
    var reasons = supplied.unassigned_reasons;
    if (reasons !== undefined) {
      var keys = Object.keys(reasons).concat(Object.keys(derived.unassigned_reasons));
      keys.forEach(function (key) {
        if ((reasons[key] || 0) !== (derived.unassigned_reasons[key] || 0)) {
          compare("unassigned_reasons." + key, derived.unassigned_reasons[key] || 0, reasons[key] || 0);
        }
      });
    }
    Object.keys(supplied.by_urgency || {}).forEach(function (level) {
      var mine = derived.by_urgency[level] || { requested: 0, assigned: 0, unassigned: 0, extra_travel_minutes: 0 };
      ["requested", "assigned", "unassigned", "extra_travel_minutes"].forEach(function (field) {
        compare("by_urgency." + level + "." + field, mine[field], supplied.by_urgency[level][field]);
      });
    });
    return differences;
  }

  return {
    SCHEMA: SCHEMA, BEFORE_START: BEFORE_START,
    problems: problems, resources: resources, minutes: minutes, lastMinute: lastMinute,
    nextMinute: nextMinute, previousMinute: previousMinute, stateAt: stateAt, explain: explain,
    protectedPool: protectedPool, finalCheck: finalCheck, compare: compare, summary: summary, rehearse: rehearse,
  };
});
