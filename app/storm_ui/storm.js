/*
 * Storm routing replay: page behaviour.
 * Reads replays produced by `python -m app.simulation` and draws what replay_state.js reports for
 * the current clock minute. It never ranks or allocates anything itself.
 */
(function () {
  "use strict";

  var S = window.StormState;
  var bundle = window.STORM_BUNDLE || null;
  var SVG = "http://www.w3.org/2000/svg";
  var MAP = { width: 600, height: 430, left: 66, right: 66, top: 44, bottom: 56 };
  var TICK_MS = 800;

  var SCENARIOS = {
    storm: ["Storm", "A routine dialysis request arrives first, then one that needs the highest urgency and a monitored dialysis slot, then a mixed wave of six."],
    no_surge: ["No surge", "Only the first routine request arrives. Use it to see what a detour costs when nothing follows."],
    overload: ["Overload", "The storm, followed by ten more highest-urgency requests for monitored dialysis. There are not enough staffed slots."],
    reversal: ["Arrivals reversed", "The highest-urgency request arrives before the routine one."],
    missing_capacity: ["Slot count unknown at A", "Campus A does not report its dialysis slots, so that pool cannot be allocated."],
    resource_loss: ["Slot goes offline", "Campus A loses an unbooked dialysis slot five minutes into the shift."],
  };
  var POLICIES = {
    nearest_first: "Nearest first",
    scarcity_aware: "Scarcity-aware",
    arrival_fifo: "Nearest first, strict arrival order",
  };
  var SERVICES = { dialysis: "Dialysis", mri: "MRI", trauma_care: "Trauma care" };
  var URGENCY = { highest: "Highest", time_sensitive: "Time-sensitive", routine: "Routine" };
  var UNSERVED = {
    no_staffed_slot_left: "no staffed slot was left at any campus within the travel limit",
    unknown_or_stale_capacity: "the only matching pools have unknown or out-of-date slot counts",
    outside_travel_window: "every matching campus is beyond the travel limit",
    required_service_or_tool_unavailable: "no campus offers the service and tools it needs",
  };
  var EXCLUDED = {
    no_staffed_slot_left: "with no staffed slot left",
    unknown_or_stale_capacity: "with an unknown or out-of-date slot count",
    outside_travel_window: "beyond the travel limit",
    required_service_or_tool_unavailable: "without the service or tools needed",
  };

  var view = { replay: null, minute: S.BEFORE_START, selected: null, policies: [], timer: null, fresh: false, custom: null };

  /* Small helpers */
  function $(id) { return document.getElementById(id); }
  function words(key) { return String(key).replace(/_/g, " "); }
  function sentence(text) { return text.charAt(0).toUpperCase() + text.slice(1); }
  function label(table, key) { return table[key] || sentence(words(key)); }
  function minutesText(n) { return n + (n === 1 ? " minute" : " minutes"); }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    fill(node, attrs, children);
    return node;
  }
  function svg(tag, attrs, children) {
    var node = document.createElementNS(SVG, tag);
    fill(node, attrs, children);
    return node;
  }
  function fill(node, attrs, children) {
    Object.keys(attrs || {}).forEach(function (name) {
      if (attrs[name] === null || attrs[name] === undefined || attrs[name] === false) return;
      if (name === "text") node.textContent = attrs[name];
      else if (name === "onclick") node.addEventListener("click", attrs[name]);
      else node.setAttribute(name, attrs[name] === true ? "" : attrs[name]);
    });
    (children || []).forEach(function (child) {
      if (child !== null && child !== undefined) node.append(child);
    });
  }
  function needs(request) {
    var tools = (request.required_tools || []).map(words);
    return label(SERVICES, request.service) + (tools.length ? ", " + tools.join(", ") : "");
  }
  function poolName(pool) {
    return label(SERVICES, pool.service) + (pool.tools.length ? ", " + pool.tools.map(words).join(", ") : "");
  }
  function placeName(id) { return sentence(words(id)); }
  function poolTitle(resourceId) {
    var pool = S.resources(view.replay)[resourceId];
    return pool ? "campus " + pool.campus_id + " " + poolName(pool).toLowerCase().replace("mri", "MRI") : "pool " + resourceId;
  }

  function glyph(urgency, x, y, r, extra) {
    var attrs = { class: "glyph urgency-" + urgency + (extra ? " " + extra : "") };
    if (urgency === "highest") {
      attrs.points = [x, y - r - 1, x + r + 1, y, x, y + r + 1, x - r - 1, y].join(" ");
      return svg("polygon", attrs);
    }
    if (urgency === "time_sensitive") {
      attrs.points = [x, y - r - 1, x + r + 1, y + r, x - r - 1, y + r].join(" ");
      return svg("polygon", attrs);
    }
    attrs.cx = x; attrs.cy = y; attrs.r = r;
    return svg("circle", attrs);
  }
  function urgencyCell(urgency) {
    var icon = svg("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" }, [glyph(urgency, 8, 8, 5)]);
    return el("span", { class: "urgency" }, [icon, label(URGENCY, urgency)]);
  }

  /* Loading */
  function showError(message) {
    $("file-error").textContent = message;
    $("file-error").hidden = !message;
  }
  function load(replay, customName) {
    var found = S.problems(replay);
    if (found.length) {
      showError("This file can't be shown. " + found.join(" ") + " Choose a replay written by python -m app.simulation.");
      return false;
    }
    showError("");
    stop();
    view.replay = replay;
    view.custom = customName || null;
    view.minute = S.BEFORE_START;
    view.selected = null;
    var names = Object.keys(replay.policies);
    view.policies = [names.indexOf("nearest_first") !== -1 ? "nearest_first" : names[0],
      names.indexOf("scarcity_aware") !== -1 ? "scarcity_aware" : names[1]];
    $("scrub").max = S.lastMinute(replay);
    $("synthetic-note").textContent = (replay.area ? replay.area.replace(", India", "") + ". " : "") +
      "Every campus, origin, request, slot count and travel time on this page is fictional.";
    buildPanels();
    render();
    return true;
  }
  function loadBundled() {
    if (!bundle) return;
    var cap = document.querySelector("input[name=cap]:checked").value;
    load(bundle.replays[$("scenario").value + "|" + cap]);
  }

  /* Clock */
  function stop() {
    if (view.timer) window.clearInterval(view.timer);
    view.timer = null;
    $("play").textContent = "Play";
  }
  function go(minute, fresh) {
    var last = S.lastMinute(view.replay);
    view.minute = Math.max(S.BEFORE_START, Math.min(last, minute));
    view.fresh = Boolean(fresh);
    if (view.selected && !S.explain(view.replay, view.policies[0], view.selected, view.minute)) view.selected = null;
    render();
    announce();
  }
  function play() {
    if (view.timer) { stop(); return; }
    if (view.minute >= S.lastMinute(view.replay)) go(S.BEFORE_START);
    $("play").textContent = "Pause";
    view.timer = window.setInterval(function () {
      go(view.minute + 1, true);
      if (view.minute >= S.lastMinute(view.replay)) stop();
    }, TICK_MS);
  }

  /* Sentences */
  function outcomeShort(event) {
    if (!event) return "";
    if (event.status !== "assigned") return "Not served";
    var text = "Campus " + event.campus_id + ", " + event.travel_minutes + " min";
    return event.extra_travel_minutes > 0 ? text + ", " + event.extra_travel_minutes + " min farther than the fastest" : text;
  }
  function profileText(replay, event) {
    var profile = (replay.protected_profiles || []).filter(function (p) { return p.service === event.service; })[0];
    if (!profile) return "the last reachable specialist slot";
    return "the last " + profile.required_tools.map(words).join(", ") + " " + label(SERVICES, profile.service).toLowerCase() +
      " slot within " + minutesText(profile.catchment_minutes);
  }
  function explainParagraphs(policyName) {
    var replay = view.replay;
    var detail = S.explain(replay, policyName, view.selected, view.minute);
    var out = [];
    if (!detail || !detail.event) return [el("p", { class: "hint", text: "Not decided yet at this minute." })];
    var event = detail.event;
    if (event.status !== "assigned") {
      out.push(el("p", { class: "lead not-served", text: "Not served." }));
      out.push(el("p", { text: sentence(label(UNSERVED, event.reason)) + "." }));
    } else if (event.extra_travel_minutes > 0) {
      out.push(el("p", { class: "lead", text: "Sent to campus " + event.campus_id + ", " + minutesText(event.travel_minutes) +
        " away, instead of campus " + event.nearest_campus_id + " at " + minutesText(event.nearest_feasible_minutes) + "." }));
      out.push(el("p", { text: "The extra " + minutesText(event.extra_travel_minutes) + " kept " + profileText(replay, event) +
        " free at campus " + event.nearest_campus_id + "." }));
      var finished = view.minute >= S.lastMinute(replay);
      out.push(el("p", { text: detail.protected_use
        ? "That slot was then used by request " + detail.protected_use.request_id + " at minute " + detail.protected_use.minute + "."
        : finished ? "That slot was never used in this replay, so the detour cost " + minutesText(event.extra_travel_minutes) + " and freed nothing that was needed."
          : "That slot has not been used yet." }));
    } else {
      out.push(el("p", { class: "lead", text: "Sent to campus " + event.campus_id + ", " + minutesText(event.travel_minutes) + " away." }));
      out.push(el("p", { text: "That was the fastest campus with a free staffed slot." }));
    }
    if (event.resource_before && event.resource_after) {
      out.push(el("p", { text: "Slots for " + poolTitle(event.resource_id) + " went from " + event.resource_before.used + " used and " +
        event.resource_before.free + " free to " + event.resource_after.used + " used and " + event.resource_after.free + " free." }));
    }
    if (event.eligible_campuses && event.eligible_campuses.length) {
      out.push(el("p", { text: "Campuses with a usable slot, fastest first: " + event.eligible_campuses.join(", ") + "." }));
    }
    var excluded = Object.keys(event.excluded_pool_counts || {}).map(function (reason) {
      return plural(event.excluded_pool_counts[reason], "pool", "pools") + " " + label(EXCLUDED, reason);
    });
    if (excluded.length) out.push(el("p", { class: "quiet", text: "Ruled out: " + excluded.join("; ") + "." }));
    return out;
  }
  function ruleText(policyName) {
    var cap = view.replay.detour_minutes;
    if (policyName === "scarcity_aware") {
      return "A routine or time-sensitive request may travel up to " + minutesText(cap) +
        " farther when that keeps the last reachable specialist slot free. Highest-urgency requests always take the fastest campus.";
    }
    if (policyName === "arrival_fifo") return "Each request goes to the fastest campus with a free staffed slot, strictly in arrival order.";
    if (policyName === "nearest_first") return "Each request goes to the fastest campus with a free staffed slot.";
    return "";
  }

  /* Map */
  function projector(replay) {
    var points = replay.campuses.concat(replay.origins);
    var lats = points.map(function (p) { return p.latitude; });
    var lons = points.map(function (p) { return p.longitude; });
    var south = Math.min.apply(null, lats), north = Math.max.apply(null, lats);
    var west = Math.min.apply(null, lons), east = Math.max.apply(null, lons);
    var squeeze = Math.cos(((south + north) / 2) * Math.PI / 180);
    var wide = Math.max((east - west) * squeeze, 1e-6), tall = Math.max(north - south, 1e-6);
    var innerW = MAP.width - MAP.left - MAP.right, innerH = MAP.height - MAP.top - MAP.bottom;
    var scale = Math.min(innerW / wide, innerH / tall);
    var padX = MAP.left + (innerW - wide * scale) / 2, padY = MAP.top + (innerH - tall * scale) / 2;
    return function (point) {
      return { x: padX + (point.longitude - west) * squeeze * scale, y: padY + (north - point.latitude) * scale };
    };
  }
  function tagWidth(text) { return text.length * 6.3 + 12; }
  /* Puts a tag near (x, y) in the candidate spot farthest from campuses, origins and earlier tags. */
  function placer(taken) {
    return function (x, y, text, quiet) {
      var half = tagWidth(text) / 2, best = [x, y - 22], bestScore = -1;
      [[0, -24], [0, 24], [-(half + 16), 0], [half + 16, 0], [-(half + 10), -22], [half + 10, -22],
        [-(half + 10), 22], [half + 10, 22], [0, -46], [0, 46], [-(half + 40), -22], [half + 40, -22],
        [-(half + 40), 22], [half + 40, 22], [-(half + 44), 0], [half + 44, 0]].forEach(function (offset) {
        var cx = x + offset[0], cy = y + offset[1];
        if (cx - half < 4 || cx + half > MAP.width - 4 || cy < 14 || cy > MAP.height - 14) return;
        var score = Infinity;
        taken.forEach(function (box) {
          var dx = Math.max(Math.abs(cx - box.x) - half - box.w, 0), dy = Math.max(Math.abs(cy - box.y) - 10 - box.h, 0);
          score = Math.min(score, Math.hypot(dx, dy));
        });
        if (score > bestScore) { bestScore = score; best = [cx, cy]; }
      });
      taken.push({ x: best[0], y: best[1], w: half, h: 10 });
      var far = Math.abs(best[0] - x) > half + 20;
      return svg("g", {}, [
        far ? svg("line", { class: "leader", x1: x, y1: y, x2: best[0] + (best[0] < x ? half : -half), y2: best[1] }) : null,
        svg("g", { class: "tag" + (quiet ? " quiet" : ""), transform: "translate(" + (best[0] - half) + " " + (best[1] - 10) + ")" }, [
          svg("rect", { width: half * 2, height: 20, rx: 2 }),
          svg("text", { x: 6, y: 14.5, text: text }),
        ]),
      ]);
    };
  }
  function drawMap(policyName, state) {
    var replay = view.replay;
    var at = projector(replay);
    var campuses = {}, origins = {};
    replay.campuses.forEach(function (c) { campuses[c.id] = at(c); });
    replay.origins.forEach(function (o) { origins[o.id] = at(o); });
    var pools = {};
    state.pools.forEach(function (pool) { (pools[pool.campus_id] = pools[pool.campus_id] || []).push(pool); });
    var freshPools = {};
    state.new_events.forEach(function (event) { if (event.resource_id) freshPools[event.resource_id] = true; });

    var root = svg("svg", { class: "map", viewBox: "0 0 " + MAP.width + " " + MAP.height, role: "img",
      "aria-label": label(POLICIES, policyName) + " map at " + readout().toLowerCase() + ". Choose Text only for the same information as tables." });
    var links = svg("g"), marks = svg("g"), tags = svg("g");
    var pairCount = {}, unservedAt = {}, taken = [], tag = placer(taken);

    var places = svg("g");
    replay.origins.forEach(function (origin) {
      var p = origins[origin.id];
      places.append(svg("g", { class: "origin" }, [
        svg("circle", { cx: p.x, cy: p.y, r: 6.5 }),
        svg("text", { x: p.x, y: p.y + 21, text: placeName(origin.id) }),
      ]));
      taken.push({ x: p.x, y: p.y + 8, w: 22, h: 17 });
    });
    replay.campuses.forEach(function (campus) {
      var p = campuses[campus.id];
      var group = svg("g", { class: "campus" }, [
        svg("rect", { x: p.x - 15, y: p.y - 15, width: 30, height: 30, rx: 2 }),
        svg("text", { class: "letter", x: p.x, y: p.y + 6, text: campus.id }),
      ]);
      var leftSide = p.x > MAP.width * 0.62;
      taken.push({ x: p.x, y: p.y, w: 17, h: 17 });
      var rows = pools[campus.id] || [];
      rows.forEach(function (pool, row) {
        var y = p.y - (rows.length - 1) * 7 + row * 14;
        var known = pool.status === "known" && pool.free !== null;
        var tokens = [];
        var i;
        if (known) {
          for (i = 0; i < pool.used; i++) tokens.push("used");
          for (i = 0; i < pool.free; i++) tokens.push("free");
          for (i = 0; i < pool.offline; i++) tokens.push("offline");
        } else {
          for (i = 0; i < Math.max(pool.reported_slots || 1, 1); i++) tokens.push("unknown");
        }
        tokens.forEach(function (kind, index) {
          var x = leftSide ? p.x - 21 - (index + 1) * 12 : p.x + 21 + index * 12;
          var fresh = view.fresh && kind === "used" && index === pool.used - 1 && freshPools[pool.id];
          group.append(svg("rect", { class: "slot " + kind + (fresh ? " fresh" : ""), x: x, y: y - 5, width: 9.5, height: 9.5 }));
          if (kind === "offline") group.append(svg("line", { class: "strike", x1: x - 1, y1: y + 6, x2: x + 10.5, y2: y - 6 }));
          if (kind === "unknown") group.append(svg("text", { class: "slot-mark", x: x + 4.75, y: y + 3.5, text: "?" }));
        });
        var edge = tokens.length * 12 + 23;
        var reach = edge + poolName(pool).length * 5.4;
        taken.push({ x: p.x + (leftSide ? -reach / 2 : reach / 2), y: y, w: reach / 2, h: 7 });
        group.append(svg("text", { class: "pool-label", x: leftSide ? p.x - edge : p.x + edge, y: y + 3.5,
          "text-anchor": leftSide ? "end" : "start", text: poolName(pool) }));
      });
      places.append(group);
    });
    // Reserve the space beside each origin where its unserved markers will sit, so tags avoid it.
    var unservedTotal = {};
    state.events.forEach(function (event) {
      if (event.status !== "assigned") unservedTotal[event.origin_id] = (unservedTotal[event.origin_id] || 0) + 1;
    });
    Object.keys(unservedTotal).forEach(function (id) {
      var across = Math.min(unservedTotal[id], 6), down = Math.ceil(unservedTotal[id] / 6);
      taken.push({ x: origins[id].x - 26 - (across - 1) * 7.5, y: origins[id].y - 1 + (down - 1) * 7.5,
        w: across * 7.5 + 3, h: down * 7.5 + 3 });
    });
    state.events.forEach(function (event) {
      var origin = origins[event.origin_id];
      var now = event.minute === state.minute, chosen = event.request_id === view.selected;
      var select = function () { view.selected = event.request_id; render(); };
      if (event.status !== "assigned") {
        var n = unservedAt[event.origin_id] = (unservedAt[event.origin_id] || 0) + 1;
        var gx = origin.x - 26 - ((n - 1) % 6) * 15, gy = origin.y - 1 + Math.floor((n - 1) / 6) * 15;
        var mark = glyph(event.urgency, gx, gy, chosen ? 6 : 5, "unserved");
        mark.addEventListener("click", select);
        mark.append(svg("title", { text: "Request " + event.request_id + ": not served" }));
        marks.append(mark, svg("line", { class: "cross", x1: gx - 3, y1: gy - 3, x2: gx + 3, y2: gy + 3 }));
        if (now || chosen) tags.append(tag(gx, gy, event.request_id + " not served"));
        return;
      }
      var campus = campuses[event.campus_id];
      var key = event.origin_id + ">" + event.campus_id;
      var k = pairCount[key] = (pairCount[key] || 0) + 1;
      var bend = (k === 1 ? 0 : Math.ceil((k - 1) / 2) * 18) * (k % 2 ? 1 : -1);
      var dx = campus.x - origin.x, dy = campus.y - origin.y, length = Math.hypot(dx, dy) || 1;
      var mx = (origin.x + campus.x) / 2 - (dy / length) * bend, my = (origin.y + campus.y) / 2 + (dx / length) * bend;
      var path = svg("path", {
        class: "link urgency-" + event.urgency + (now ? " now" : "") + (chosen ? " selected" : "") + (now && view.fresh ? " fresh" : ""),
        d: "M" + origin.x + " " + origin.y + " Q" + mx + " " + my + " " + campus.x + " " + campus.y, pathLength: 1,
      }, [svg("title", { text: "Request " + event.request_id + ": " + outcomeShort(event) })]);
      path.addEventListener("click", select);
      links.append(path);
      var cx = (origin.x + 2 * mx + campus.x) / 4, cy = (origin.y + 2 * my + campus.y) / 4;
      var dot = glyph(event.urgency, cx, cy, chosen ? 6 : 4.5);
      dot.addEventListener("click", select);
      marks.append(dot);
      if (now || chosen) {
        tags.append(tag(cx, cy, event.request_id + ", " + event.travel_minutes + " min"));
        if (event.extra_travel_minutes > 0) {
          var fast = campuses[event.nearest_campus_id];
          links.append(svg("path", { class: "fastest", d: "M" + origin.x + " " + origin.y + " L" + fast.x + " " + fast.y }));
          tags.append(tag((origin.x + fast.x) / 2, (origin.y + fast.y) / 2,
            "fastest: " + event.nearest_campus_id + ", " + event.nearest_feasible_minutes + " min", true));
        }
      }
    });

    root.append(links, places, marks, tags);
    return root;
  }

  /* Panels */
  function buildPanels() {
    var replay = view.replay;
    var names = Object.keys(replay.policies);
    var panels = $("panels");
    panels.replaceChildren();
    view.policies.forEach(function (policyName, side) {
      var heading = el("h2", { text: label(POLICIES, policyName) });
      var head = el("div", { class: "panel-head" }, [heading]);
      if (names.length > 2) {
        var choice = el("select", { "aria-label": "Policy shown in this panel" }, names.map(function (name) {
          return el("option", { value: name, text: label(POLICIES, name), selected: name === policyName });
        }));
        choice.addEventListener("change", function () { view.policies[side] = choice.value; buildPanels(); render(); });
        head.append(choice);
      }
      panels.append(el("section", { class: "panel", "aria-label": label(POLICIES, policyName) }, [
        head,
        el("p", { class: "rule-text", text: ruleText(policyName) }),
        el("div", { id: "map-" + side }),
        el("p", { class: "map-note", text: "Fictional map. A line joins a request to its campus and is not a road." }),
        el("div", { class: "tally", id: "tally-" + side }),
        el("div", { class: "event-log", id: "log-" + side }),
        el("div", { class: "slots", id: "slots-" + side }),
      ]));
    });
    $("outcome-left").textContent = label(POLICIES, view.policies[0]);
    $("outcome-right").textContent = label(POLICIES, view.policies[1]);
  }
  function tally(metrics, finished) {
    var caption = metrics.requested === 0 ? "No requests yet." : finished ? "Final totals" : "Totals so far";
    if (metrics.requested === 0) return [el("p", { text: caption })];
    function item(name, value) { return el("div", {}, [el("dt", { text: name }), el("dd", { text: value })]); }
    return [el("p", { text: caption }), el("dl", {}, [
      item("Served", metrics.assigned + " of " + metrics.requested),
      item("Highest urgency served within travel limit", metrics.urgent_on_time + " of " + metrics.urgent_requested),
      item("Not served", String(metrics.unassigned)),
      item("Extra travel", minutesText(metrics.extra_travel_minutes)),
    ])];
  }
  function slotsTable(state) {
    var changed = {};
    state.new_events.forEach(function (event) { if (event.resource_id) changed[event.resource_id] = true; });
    state.new_capacity_events.forEach(function (change) { changed[change.resource_id] = true; });
    var body = el("tbody", {}, state.pools.map(function (pool) {
      var known = pool.status === "known" && pool.free !== null;
      var note = known ? (pool.offline ? plural(pool.offline, "slot", "slots") + " went offline" : "")
        : pool.status === "stale" ? "Reported " + pool.reported_slots + ", out of date. Cannot be allocated."
          : "Count unknown. Cannot be allocated.";
      return el("tr", { class: changed[pool.id] ? "extra" : null }, [
        el("th", { scope: "row", text: "Campus " + pool.campus_id }),
        el("td", { text: poolName(pool) }),
        el("td", { text: known ? String(pool.used) : "Unknown" }),
        el("td", { text: known ? String(pool.free) : "Unknown" }),
        el("td", { class: "quiet", text: note }),
      ]);
    }));
    return el("table", {}, [
      el("caption", { text: "Staffed slots by campus" }),
      el("thead", {}, [el("tr", {}, ["Campus", "Service", "Used", "Free", "Note"].map(function (name) {
        return el("th", { scope: "col", text: name });
      }))]),
      body,
    ]);
  }
  function eventLog(state) {
    if (!state.events.length && !state.capacity_events.length) return el("p", { class: "hint", text: "Nothing has happened yet." });
    var rows = state.capacity_events.map(function (change) {
      return { minute: change.minute, order: 0, who: sentence(poolTitle(change.resource_id)),
        what: change.lost_free_slots > 0 ? plural(change.lost_free_slots, "unbooked slot", "unbooked slots") + " went offline."
          : "A slot was due to go offline, but none was unbooked, so nothing changed." };
    }).concat(state.events.map(function (event) {
      return { minute: event.minute, order: 1, who: "Request " + event.request_id,
        what: event.status === "assigned" ? outcomeShort(event) + "." : "Not served: " + label(UNSERVED, event.reason) + "." };
    }));
    rows.sort(function (a, b) { return a.minute - b.minute || a.order - b.order; });
    return el("table", {}, [
      el("caption", { text: "What happened, in order" }),
      el("thead", {}, [el("tr", {}, ["Minute", "Who", "What happened"].map(function (name) { return el("th", { scope: "col", text: name }); }))]),
      el("tbody", {}, rows.map(function (row) {
        return el("tr", {}, [el("td", { text: String(row.minute) }), el("th", { scope: "row", text: row.who }), el("td", { text: row.what })]);
      })),
    ]);
  }

  /* Request log, explanation, summary */
  function outcomeCell(event) {
    if (!event) return el("td", { class: "quiet", text: "Not decided yet" });
    if (event.status !== "assigned") return el("td", { class: "not-served", text: "Not served" });
    return el("td", { class: event.extra_travel_minutes > 0 ? "extra" : null, text: outcomeShort(event) });
  }
  function renderRequests(states) {
    var announced = states[0].announced;
    var table = $("request-table");
    var hadFocus = table.contains(document.activeElement);
    table.hidden = announced.length === 0;
    $("requests-hint").hidden = announced.length !== 0;
    var events = states.map(function (state) {
      var index = {};
      state.events.forEach(function (event) { index[event.request_id] = event; });
      return index;
    });
    table.tBodies[0].replaceChildren.apply(table.tBodies[0], announced.map(function (request) {
      var pick = function () { view.selected = request.id; render(); };
      var button = el("button", { type: "button", text: request.id, "data-request": request.id,
        "aria-label": "Explain request " + request.id, onclick: function (e) { e.stopPropagation(); pick(); } });
      return el("tr", { "aria-selected": request.id === view.selected ? "true" : "false", onclick: pick }, [
        el("th", { scope: "row" }, [button]),
        el("td", { text: "Minute " + request.arrival_minute }),
        el("td", { text: placeName(request.origin_id) }),
        el("td", { text: needs(request) }),
        el("td", {}, [urgencyCell(request.urgency)]),
        el("td", { text: request.max_travel_minutes + " min" }),
        outcomeCell(events[0][request.id]),
        outcomeCell(events[1][request.id]),
      ]);
    }));
    if (hadFocus && view.selected) {
      var again = table.querySelector('[data-request="' + view.selected + '"]');
      if (again) again.focus();
    }
  }
  function renderWhy() {
    var body = $("why-body");
    var request = view.selected && view.replay.requests.filter(function (r) { return r.id === view.selected; })[0];
    if (!request) {
      body.replaceChildren(el("p", { class: "hint", text: "Select a request in the table or on a map to see how each policy handled it." }));
      return;
    }
    var nodes = [el("p", { text: "Request " + request.id + ": " + label(URGENCY, request.urgency).toLowerCase() + " urgency, " +
      needs(request).toLowerCase().replace("mri", "MRI") + ", from " + placeName(request.origin_id) + " at minute " + request.arrival_minute +
      ". It can travel up to " + minutesText(request.max_travel_minutes) + "." })];
    view.policies.forEach(function (policyName) {
      nodes.push(el("h3", { text: label(POLICIES, policyName) }));
      explainParagraphs(policyName).forEach(function (node) { nodes.push(node); });
    });
    body.replaceChildren.apply(body, nodes);
  }
  function renderSummary(states) {
    var section = $("summary");
    var finished = view.minute >= S.lastMinute(view.replay);
    section.hidden = !finished;
    if (!finished) return;
    var a = states[0].metrics, b = states[1].metrics;
    var nameA = label(POLICIES, view.policies[0]), nameB = label(POLICIES, view.policies[1]);
    var text = nameA + " served " + a.assigned + " of " + a.requested + " requests and " + nameB.toLowerCase() + " served " + b.assigned + " of " + b.requested + ".";
    var gap = b.extra_travel_minutes - a.extra_travel_minutes;
    if (gap !== 0) {
      text += " " + (gap > 0 ? nameB : nameA) + " added " + minutesText(Math.abs(gap)) + " of travel";
      text += b.assigned === a.assigned ? " without serving anyone extra." : ".";
    } else if (b.assigned === a.assigned) {
      text += " The two policies made no difference to who was served or how far they travelled.";
    }
    $("summary-sentence").textContent = text;
    function reasons(metrics) {
      var keys = Object.keys(metrics.unassigned_reasons);
      return keys.length ? keys.map(function (key) { return metrics.unassigned_reasons[key] + ": " + label(UNSERVED, key); }).join("; ") : "None";
    }
    var rows = [
      ["Served", a.assigned + " of " + a.requested, b.assigned + " of " + b.requested],
      ["Highest urgency served within travel limit", a.urgent_on_time + " of " + a.urgent_requested, b.urgent_on_time + " of " + b.urgent_requested],
      ["Not served", String(a.unassigned), String(b.unassigned)],
      ["Why not served", reasons(a), reasons(b)],
      ["Requests sent farther than their fastest campus", String(a.detours), String(b.detours)],
      ["Extra travel", minutesText(a.extra_travel_minutes), minutesText(b.extra_travel_minutes)],
    ];
    $("summary-table").replaceChildren(
      el("thead", {}, [el("tr", {}, [el("td"), el("th", { scope: "col", text: nameA }), el("th", { scope: "col", text: nameB })])]),
      el("tbody", {}, rows.map(function (row) {
        return el("tr", {}, [el("th", { scope: "row", text: row[0] }), el("td", { text: row[1] }), el("td", { text: row[2] })]);
      })));
    var differences = S.finalCheck(view.replay, view.policies[0]).concat(S.finalCheck(view.replay, view.policies[1]));
    $("summary-check").textContent = differences.length
      ? "These totals are counted from the events and disagree with the totals stored in the replay file: " + differences.join("; ") + "."
      : "These totals are counted from the events shown above and equal the totals stored in the replay file.";
  }

  /* Clock readout */
  function readout() {
    return view.minute === S.BEFORE_START ? "Before the shift" : "Minute " + view.minute;
  }
  function renderClock() {
    var last = S.lastMinute(view.replay);
    var box = $("minute-readout");
    box.replaceChildren(readout(), el("small", { text: view.minute === S.BEFORE_START ? "Nothing has arrived" : "of " + last }));
    $("scrub").value = view.minute;
    $("scrub").setAttribute("aria-valuetext", readout());
    $("back").disabled = $("restart").disabled = view.minute === S.BEFORE_START;
    $("next").disabled = view.minute >= last;
    var span = last - S.BEFORE_START;
    $("ticks").replaceChildren.apply($("ticks"), S.minutes(view.replay).filter(function (m) { return m <= view.minute; }).map(function (m) {
      return el("span", { style: "left:" + ((m - S.BEFORE_START) / span) * 100 + "%", text: String(m) });
    }));
  }
  function announce() {
    if (view.minute === S.BEFORE_START) { $("announcer").textContent = "Before the shift. Nothing has arrived."; return; }
    var parts = view.policies.map(function (policyName) {
      var state = S.stateAt(view.replay, policyName, view.minute);
      var lines = state.new_events.map(function (event) { return "request " + event.request_id + ", " + outcomeShort(event).toLowerCase(); });
      return label(POLICIES, policyName) + ": " + (lines.length ? lines.join("; ") : "nothing new") + ".";
    });
    $("announcer").textContent = "Minute " + view.minute + ". " + parts.join(" ");
  }

  function render() {
    if (!view.replay) return;
    var finished = view.minute >= S.lastMinute(view.replay);
    var states = view.policies.map(function (policyName) { return S.stateAt(view.replay, policyName, view.minute); });
    var scenario = view.custom ? null : SCENARIOS[view.replay.scenario];
    $("scenario-note").textContent = view.custom
      ? "Showing " + view.custom + ": scenario " + words(view.replay.scenario) + ", seed " + view.replay.seed + ", detour up to " + minutesText(view.replay.detour_minutes) + "."
      : scenario ? scenario[1] : "";
    renderClock();
    states.forEach(function (state, side) {
      $("map-" + side).replaceChildren(drawMap(view.policies[side], state));
      $("tally-" + side).replaceChildren.apply($("tally-" + side), tally(state.metrics, finished));
      $("slots-" + side).replaceChildren(slotsTable(state));
      $("log-" + side).replaceChildren(eventLog(state));
    });
    renderRequests(states);
    renderWhy();
    renderSummary(states);
    view.fresh = false;
  }

  function legend() {
    function sample(children) { return svg("svg", { viewBox: "0 0 48 24", "aria-hidden": "true" }, children); }
    function line(urgency) {
      return [svg("path", { class: "link now urgency-" + urgency, d: "M3 12 L45 12" }), glyph(urgency, 24, 12, 4.5)];
    }
    var items = [
      [sample([svg("g", { class: "campus" }, [svg("rect", { x: 14, y: 2, width: 20, height: 20, rx: 2 }), svg("text", { class: "letter", x: 24, y: 17, style: "font-size:13px", text: "A" })])]), "Campus"],
      [sample([svg("g", { class: "origin" }, [svg("circle", { cx: 24, cy: 12, r: 6.5 })])]), "Where requests come from"],
      [sample(line("highest")), "Highest-urgency request"],
      [sample(line("time_sensitive")), "Time-sensitive request"],
      [sample(line("routine")), "Routine request"],
      [sample([svg("path", { class: "fastest", d: "M3 12 L45 12" })]), "Fastest campus, when it was not chosen"],
      [sample([glyph("highest", 24, 12, 5, "unserved"), svg("line", { class: "cross", x1: 21, y1: 9, x2: 27, y2: 15 })]), "Request that was not served"],
      [sample([svg("rect", { class: "slot used", x: 12, y: 7, width: 9.5, height: 9.5 }), svg("rect", { class: "slot free", x: 26, y: 7, width: 9.5, height: 9.5 })]), "Staffed slot: used, free"],
      [sample([svg("rect", { class: "slot offline", x: 19, y: 7, width: 9.5, height: 9.5 }), svg("line", { class: "strike", x1: 18, y1: 18, x2: 29.5, y2: 6 })]), "Slot that went offline"],
      [sample([svg("rect", { class: "slot unknown", x: 19, y: 7, width: 9.5, height: 9.5 }), svg("text", { class: "slot-mark", x: 23.75, y: 15.5, text: "?" })]), "Slot count unknown or out of date"],
    ];
    $("legend-list").replaceChildren.apply($("legend-list"), items.map(function (item) { return el("li", {}, [item[0], item[1]]); }));
  }

  function start() {
    legend();
    $("open-file").addEventListener("click", function () { $("file").click(); });
    $("file").addEventListener("change", function () {
      var file = $("file").files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        var replay;
        try { replay = JSON.parse(reader.result); } catch (error) {
          showError("This file can't be shown because it is not JSON. Choose a replay written by python -m app.simulation.");
          return;
        }
        if (load(replay, file.name)) $("scenario").value = "";
      };
      reader.readAsText(file);
      $("file").value = "";
    });
    $("restart").addEventListener("click", function () { stop(); go(S.BEFORE_START); });
    $("back").addEventListener("click", function () { stop(); go(S.previousMinute(view.replay, view.minute)); });
    $("next").addEventListener("click", function () { stop(); go(S.nextMinute(view.replay, view.minute), true); });
    $("play").addEventListener("click", play);
    $("scrub").addEventListener("input", function () { stop(); go(Number($("scrub").value)); });
    document.querySelectorAll("input[name=view]").forEach(function (input) {
      input.addEventListener("change", function () { document.body.dataset.view = input.value; });
    });
    document.body.dataset.view = "map";
    document.addEventListener("keydown", function (event) {
      var tagName = event.target.tagName;
      if (!view.replay || /^(INPUT|SELECT|TEXTAREA)$/.test(tagName)) return;
      if (event.key === " " && tagName !== "BUTTON") { event.preventDefault(); play(); }
      if (event.key === "ArrowRight") { stop(); go(S.nextMinute(view.replay, view.minute), true); }
      if (event.key === "ArrowLeft") { stop(); go(S.previousMinute(view.replay, view.minute)); }
    });

    if (!bundle) {
      $("scenario").disabled = true;
      ["restart", "back", "play", "next", "scrub"].forEach(function (id) { $(id).disabled = true; });
      $("requests-hint").textContent = "No replay is open.";
      showError("The built-in replays did not load. From the repository root run python -m app.storm_ui.build, then reload this page. You can also open a replay file.");
      return;
    }
    bundle.scenarios.forEach(function (name) {
      $("scenario").append(el("option", { value: name, text: label(SCENARIOS, name) instanceof Array ? SCENARIOS[name][0] : sentence(words(name)) }));
    });
    $("scenario").append(el("option", { value: "", text: "Opened file", hidden: true }));
    var parts = bundle.default.split("|");
    $("scenario").value = parts[0];
    bundle.detour_caps.forEach(function (cap) {
      $("caps").append(el("label", {}, [el("input", { type: "radio", name: "cap", value: cap, checked: String(cap) === parts[1] }), " " + cap + " min"]));
    });
    $("scenario").addEventListener("change", loadBundled);
    $("caps").addEventListener("change", function () {
      if ($("scenario").value === "") $("scenario").value = parts[0];
      loadBundled();
    });
    loadBundled();
  }

  start();
})();
