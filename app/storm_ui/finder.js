/*
 * Campus finder: page behaviour.
 * Draws one finder response using finder_state.js. It never ranks, scores or estimates travel, and
 * it never contacts a routing provider. A hosting backend may supply window.FINDER_TRANSPORT, a
 * function that takes a finder request and returns a promise of the response. Only a press of the
 * Search button calls it, and never while an earlier search is still in progress.
 */
(function () {
  "use strict";

  var F = window.FinderState;
  var bundle = window.FINDER_EXAMPLES || null;
  var transport = typeof window.FINDER_TRANSPORT === "function" ? window.FINDER_TRANSPORT : null;
  var session = F.session();
  var current = { names: {}, fileName: null, envelope: null };

  var SERVICES = { dialysis: "Dialysis", mri: "MRI", trauma_care: "Trauma care" };
  var URGENCY = { highest: "highest urgency", time_sensitive: "time-sensitive urgency", routine: "routine urgency" };
  var PROVIDERS = { tomtom: "TomTom" };
  var REASONS = {
    service_ineligible: "No confirmed, current evidence that it offers this service",
    service_or_required_capability_no: "The service or a required capability is recorded as not offered",
    coordinates_unreviewed: "Its coordinates have not been reviewed",
    coordinates_disputed: "Its coordinates are disputed",
    invalid_coordinates: "Its coordinates are not valid",
    outside_geographic_shortlist: "Farther in a straight line than the campuses sent for routing",
    travel_budget_exceeded: "Over the travel limit",
    travel_unknown: "No travel figure was received",
    no_route_found: "No route by car was found",
    point_not_routable: "The point could not be matched to a road",
    provider_timeout: "The routing provider did not answer in time",
    provider_connection_error: "The routing provider could not be reached",
    provider_transient_error: "The routing provider reported a temporary error",
    provider_quota_exceeded: "The routing provider's own quota was exceeded",
    authentication_failed: "The routing provider rejected the server's credentials",
    provider_request_rejected: "The routing provider rejected the request",
    invalid_provider_response: "The routing provider's answer could not be used",
    missing_route_summary: "The routing provider's answer could not be used",
    invalid_route_measurement: "The routing provider's answer could not be used",
    provider_response_too_large: "The routing provider's answer could not be used",
    daily_call_budget_exceeded: "This app's daily request limit was reached",
    monthly_call_budget_exceeded: "This app's monthly request limit was reached",
    query_call_budget_exceeded: "This search reached its per-search request limit",
    local_rate_limited: "This app's request rate limit was reached",
    local_inflight_limit: "Too many requests were already in progress",
    shared_provider_cooldown: "Requests are paused after repeated rate-limit answers",
    validation_reservation_required: "This run needs a reserved request budget and has none",
    reserved_budget_exhausted: "The request budget reserved for this run is used up",
    reservation_month_mismatch: "The reserved request budget belongs to a different month",
    protected_allowance_exhausted: "The protected monthly allowance is used up",
    validation_allocation_exhausted: "The allowance set aside for validation runs is used up",
    unknown_reservation: "This run's reservation is not recognised",
    local_clock_regressed: "The server clock moved backwards, so requests are paused",
    routing_disabled: "Live routing is switched off on the server",
  };
  var GROUP_TITLES = {
    over_limit: "Over the travel limit",
    not_top: "Within the limit, below the campuses shown",
    unresolved: "No time available",
    no_route: "No route by car",
    not_sent: "Not sent for routing",
  };
  var COUNT_ROWS = [
    ["considered", "Campuses considered"],
    ["eligible", "With confirmed evidence for the service"],
    ["routing_eligible", "Also with reviewed coordinates"],
    ["shortlisted", "Shortlisted by straight-line distance"],
    ["evaluated", "Sent to the routing provider"],
    ["provider_calls_attempted", "Provider calls made, retries included"],
    ["timed", "Driving times received"],
    ["scored", "Within the limit used for ranking"],
    ["returned", "Shown in the ranking"],
  ];

  function $(id) { return document.getElementById(id); }
  function words(key) { return String(key).replace(/_/g, " "); }
  function sentence(text) { return text.charAt(0).toUpperCase() + text.slice(1); }
  function reasonText(reason) {
    if (REASONS[reason]) return REASONS[reason];
    if (F.reasonKind(reason) === "local_setup") return "Live routing is not fully set up on the server";
    return sentence(words(reason));
  }
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (name) {
      if (attrs[name] === null || attrs[name] === undefined || attrs[name] === false) return;
      if (name === "text") node.textContent = attrs[name];
      else node.setAttribute(name, attrs[name] === true ? "" : attrs[name]);
    });
    (children || []).forEach(function (child) { if (child !== null && child !== undefined) node.append(child); });
    return node;
  }
  function number(value, digits) { return Number(value).toFixed(digits); }
  function minutes(value) { return (value >= 10 ? number(value, 0) : number(value, 1)) + " min"; }
  function km(value) { return number(value, 1) + " km"; }
  function figure(measure) { return !measure ? "" : measure.unit === "km" ? km(measure.value) : minutes(measure.value); }
  function clock(stamp) {
    var match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(stamp || "");
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    if (!match) return null;
    return Number(match[3]) + " " + months[Number(match[2]) - 1] + " " + match[1] + ", " + match[4] + ":" + match[5] + " UTC";
  }
  function campusCell(id) {
    var name = current.names[id];
    return el("th", { scope: "row" }, name ? [name, el("span", { class: "campus-id", text: id })] : [id]);
  }
  function table(target, headings, rows) {
    target.replaceChildren(
      el("thead", {}, [el("tr", {}, headings.map(function (name) { return el("th", { scope: "col", text: name }); }))]),
      el("tbody", {}, rows));
  }

  /* The headline for the search, in words. */
  function stateWords(view) {
    var c = view.counts, limit = view.unit === "km" ? number(view.budget, 0) + " km" : number(view.budget, 0) + " minutes";
    if (view.state === "ok") {
      return ["ok", "Driving times for all " + c.shortlisted + " shortlisted campuses",
        "Campuses are ranked using estimated driving minutes, within the " + limit + " limit."];
    }
    if (view.state === "partial") {
      return ["limited", "Driving times for " + c.timed + " of " + c.shortlisted + " shortlisted campuses",
        "Only campuses with a driving time are ranked. The others are listed below with the reason. " +
        "Straight-line distance is never mixed into a ranking by driving time."];
    }
    if (view.state === "fallback") {
      return ["limited", "Ranked by straight-line distance, not driving time",
        "No driving time was received, so campuses within " + limit + " in a straight line are ranked by that distance. " +
        "A straight line is shorter than any road and says nothing about how long the drive takes."];
    }
    if (view.state === "no_route") {
      return ["none", "No route by car to any shortlisted campus",
        "The routing provider answered for every shortlisted campus and found no route. Nothing is ranked, and " +
        "straight-line distance is not used in its place."];
    }
    if (view.state === "not_requested") {
      return ["none", "No driving times were requested", view.coverage_empty
        ? "No eligible campus has reviewed coordinates, so nothing was sent to the routing provider and nothing is ranked."
        : "Nothing was shortlisted, so nothing was sent to the routing provider."];
    }
    if (view.local_limit.length) {
      return ["none", "This app's request limit was reached",
        "No driving time was requested beyond the limit, so nothing is ranked. This limit is set in this application. " +
        "It is not a provider outage, and it does not switch the ranking to straight-line distance."];
    }
    if (view.local_reserve.length) {
      return ["none", "The reserved request budget cannot cover this search",
        "No driving time was requested, so nothing is ranked. The reservation is set in this application. " +
        "It is not a provider outage, and it does not switch the ranking to straight-line distance."];
    }
    if (view.local_setup.length) {
      return ["none", "Live driving times are switched off",
        "The server is not set up to request driving times, so nothing is ranked."];
    }
    return ["none", "No driving times are available",
      "No usable driving time was received and no straight-line fallback applies, so nothing is ranked."];
  }

  function renderState(view, envelope) {
    var text = stateWords(view);
    $("state-title").parentNode.dataset.tone = text[0];
    $("state-title").textContent = text[1];
    $("state-text").textContent = text[2];
    var seen = {};
    $("state-reasons").replaceChildren.apply($("state-reasons"), view.errors.map(reasonText).filter(function (line) {
      if (seen[line]) return false;
      seen[line] = true;
      return true;
    }).map(function (line) { return el("li", { text: line + "." }); }));
    var sent = clock(view.requested_at);
    var parts = [sent ? "Requested " + sent + "." : "No request was sent to the routing provider."];
    parts.push(view.approximate_origin
      ? "The starting point is approximate: a city or PIN centre stands in for the real address."
      : "The starting point is the exact coordinates supplied.");
    if (envelope.routing.coalesced) parts.push("This answer was shared with an identical search already in progress.");
    $("request-meta").textContent = parts.join(" ");
  }

  function renderRanked(view) {
    var target = $("ranked-table");
    if (!view.ranked.length) {
      target.hidden = true;
      target.replaceChildren();
      $("ranked-note").textContent = "Nothing is ranked for this search.";
      return;
    }
    target.hidden = false;
    var distance = view.unit === "km";
    $("ranked-note").textContent = distance
      ? "Ordered by the finder using straight-line kilometres. No driving time is shown because none was received."
      : "Ordered by the finder. Driving time is one input alongside how recent and well corroborated the service evidence is.";
    var headings = distance ? ["Rank", "Campus", "Straight-line distance", "Service evidence dated", "Availability now"]
      : ["Rank", "Campus", "Estimated drive", "Road distance", "Leaving at", "Service evidence dated", "Availability now"];
    table(target, headings, view.ranked.map(function (entry) {
      var row = entry.result || {};
      var cells = [el("td", { class: "rank", text: String(entry.rank) }), campusCell(entry.facility_id),
        el("td", { class: "figure", text: distance ? km(entry.travel) : minutes(entry.travel) })];
      if (!distance) {
        cells.push(el("td", { text: row.road_metres === null || row.road_metres === undefined ? "Not reported" : km(row.road_metres / 1000) }));
        var leaving = clock(row.departure_time);
        cells.push(el("td", {}, leaving ? [leaving, el("span", { class: "campus-id", text: row.departure_time_source === "provider_summary"
          ? "as reported by the provider" : "the time the request was sent" })] : ["Not reported"]));
      }
      cells.push(el("td", { text: entry.source_date || "Not dated" }));
      cells.push(el("td", { text: !entry.availability || entry.availability === "unknown" ? "Not known" : sentence(words(entry.availability)) }));
      return el("tr", {}, cells);
    }));
  }

  function renderGroups(view) {
    var nodes = [];
    F.GROUPS.forEach(function (name) {
      var rows = view.groups[name];
      if (!rows.length) return;
      var showFigure = name === "over_limit" || name === "not_top";
      var headings = ["Campus", "Reason"];
      if (showFigure) headings.push(view.unit === "km" ? "Straight-line distance" : "Estimated drive");
      if (!showFigure || view.unit !== "km") headings.push("Straight-line distance");
      headings.push("Sent to provider");
      var body = document.createElement("table");
      table(body, headings, rows.map(function (row) {
        var why = row.reasons.length ? row.reasons : row.reason ? [row.reason] : [];
        var reason = name === "not_top" ? "Ranked lower than the campuses shown" : why.map(reasonText).join(". ");
        var cells = [campusCell(row.facility_id), el("td", { text: reason })];
        if (showFigure) cells.push(el("td", { class: "figure", text: figure(row.measure) || "None" }));
        if (!showFigure || view.unit !== "km") {
          cells.push(el("td", { text: row.straight_line_km === null ? "Not calculated" : km(row.straight_line_km) }));
        }
        cells.push(el("td", { text: row.evaluated ? "Yes" : "No" }));
        return el("tr", {}, cells);
      }));
      nodes.push(el("div", { class: "group" }, [el("h3", { text: GROUP_TITLES[name] + " (" + rows.length + ")" }),
        el("div", { class: "scroll" }, [body])]));
    });
    $("groups").replaceChildren.apply($("groups"), nodes.length ? nodes
      : [el("p", { class: "hint", text: "Every campus considered is in the ranking." })]);
  }

  function renderCounts(view) {
    $("counts-table").replaceChildren(el("tbody", {}, COUNT_ROWS.filter(function (row) {
      return view.counts[row[0]] !== undefined;
    }).map(function (row) {
      return el("tr", {}, [el("th", { scope: "row", text: row[1] }), el("td", { text: String(view.counts[row[0]]) })]);
    })));
  }

  function renderSource(view, envelope) {
    var routing = envelope.routing, a = view.attribution || {};
    function item(name, value) { return [el("dt", { text: name }), el("dd", { text: value })]; }
    var facts = [].concat(
      item("Routing provider", (PROVIDERS[routing.provider] || String(routing.provider)) + (routing.product ? ", product " + routing.product : "")),
      item("Travel mode", sentence(words(routing.mode || "not stated"))),
      item("Route preference", sentence(words(routing.routing_preference || "not stated"))));
    var nodes = [el("dl", {}, facts)];
    var source = session.source();
    if (source === "example") {
      nodes.push(el("p", { text: "This example was made by the finder code with a stand-in for the routing provider. Its times and " +
        "distances are invented and are not results from " + (a.text || "the provider") + "." }));
      if (a.required && a.text) nodes.push(el("p", { text: "A live response of this kind must credit " + a.text + "." }));
    } else if (source === "file") {
      nodes.push(el("p", { text: "This response was opened from a file. The page cannot check where the file came from, so the " +
        "provenance of its figures is unknown: they may be invented or may be provider results." }));
      if (a.required && a.text) nodes.push(el("p", { text: "The response says its estimates must credit " + a.text + "." }));
    } else if (a.required && a.text) {
      nodes.push(el("p", { text: "Driving estimates in this response are supplied by " + a.text + "." }));
    } else {
      nodes.push(el("p", { text: "This response contains no provider result, so no provider credit applies to it." }));
    }
    if (a.display_status === "operator_terms_review_required") {
      nodes.push(el("p", { text: "Public display of provider results is not cleared. The provider's display terms are still under " +
        "operator review, so keep this page to internal evaluation." }));
    } else if (a.display_status) {
      nodes.push(el("p", { text: "Display status reported in the response: " + words(a.display_status) + ". This page does not clear public display." }));
    } else {
      nodes.push(el("p", { text: "The response gives no display status, so public display of provider results is not cleared." }));
    }
    if (a.storage === "do_not_persist_provider_content") {
      nodes.push(el("p", { text: "Provider results must not be stored. This page keeps nothing after it is closed." }));
    }
    if (typeof a.terms_url === "string" && /^https:/.test(a.terms_url)) {
      nodes.push(el("p", {}, [el("a", { href: a.terms_url, rel: "noopener noreferrer", text: "Provider terms" }), " (opens the provider's website)"]));
    }
    $("source-body").replaceChildren.apply($("source-body"), nodes);
  }

  function showError(message) {
    $("file-error").textContent = message;
    $("file-error").hidden = !message;
  }

  function draw(envelope, note) {
    var view = F.view(envelope);
    $("request-note").textContent = note;
    renderState(view, envelope);
    renderRanked(view);
    renderGroups(view);
    renderCounts(view);
    renderSource(view, envelope);
    $("result").hidden = false;
  }

  /* Says, in the page header, where the response on screen came from. */
  function headerNote() {
    var source = session.source();
    $("synthetic-note").textContent = source === "example"
      ? "Example response. Every campus, the origin and every time and distance shown are invented."
      : source === "file" ? "Opened file: " + current.fileName + ". This page cannot check where it came from, so its provenance is unknown."
        : source === "search" ? "Response to the search made from this page."
          : "No response is open.";
  }

  /*
   * Shows a response after checking every part the page reads. A response that fails the check, or
   * that still cannot be drawn, leaves the previous view on screen with the reason above it.
   * `describe` words the request and `adopt` records the new source. Both run only once the response
   * has passed the check, so nothing reads a response that has not been validated.
   */
  function show(envelope, describe, adopt) {
    var found = F.problems(envelope);
    if (found.length) {
      showError("This response can't be shown. " + found.join(" ") + " Choose the output of python -m app.ranking for a request with routing." +
        (current.envelope ? " The response that was open is still shown." : ""));
      return false;
    }
    var previous = { envelope: current.envelope, note: current.note, names: current.names, fileName: current.fileName,
      source: session.source(), request: session.request() };
    var note;
    try {
      note = describe();
      adopt();
      draw(envelope, note);
    } catch (error) {
      current.names = previous.names;
      current.fileName = previous.fileName;
      session.adopt(previous.source, previous.request);
      if (previous.envelope) draw(previous.envelope, previous.note);
      headerNote();
      syncSearch();
      showError("This response can't be shown because part of it could not be drawn." +
        (previous.envelope ? " The response that was open is still shown." : ""));
      return false;
    }
    current.envelope = envelope;
    current.note = note;
    headerNote();
    syncSearch();
    showError("");
    return true;
  }

  /* Search is offered only when a backend supplied a transport, and only for a view that has a request. */
  function syncSearch() {
    if (!transport) return;
    $("search").disabled = !session.canSearch();
    $("search").textContent = session.searching() ? "Searching" : "Search driving times";
    $("search-hint").textContent = session.searching() || session.request() ? ""
      : "Search needs the request behind a response. An opened file carries none, so choose an example to search from.";
  }

  function requestWords(envelope, request) {
    var service = SERVICES[envelope.service] || sentence(words(envelope.service || "service not stated"));
    var text = service + ", " + (URGENCY[envelope.urgency] || words(envelope.urgency || "urgency not stated")) + ".";
    var routing = request && request.routing;
    if (request) text += " Travel limit " + request.travel_budget + " minutes by car.";
    if (routing && routing.shortlist_limit) text += " Up to " + routing.shortlist_limit + " nearest campuses are sent for routing.";
    if (routing) {
      text += routing.fallback_distance_km ? " If the provider cannot be reached, rank within " + routing.fallback_distance_km + " km in a straight line."
        : " No straight-line fallback was requested.";
    }
    return text;
  }

  function showExample() {
    var example = bundle.examples.filter(function (item) { return item.key === $("example").value; })[0];
    if (!example) return;
    session.intend();
    $("search-status").textContent = "";
    show(example.response, function () { return requestWords(example.response, example.request); }, function () {
      current.names = bundle.names || {};
      current.fileName = null;
      session.adopt("example", example.request);
    });
  }

  function openFile(file) {
    var token = session.intend();
    var reader = new FileReader();
    reader.onload = function () {
      if (!session.isCurrent(token)) return; // Something else was chosen while the file was being read.
      var envelope;
      try { envelope = JSON.parse(reader.result); } catch (error) {
        showError("This file can't be shown because it is not JSON. Choose the output of python -m app.ranking for a request with routing.");
        return;
      }
      var shown = show(envelope, function () { return "Showing " + file.name + ". " + requestWords(envelope, null); }, function () {
        current.names = {};
        current.fileName = file.name;
        session.adopt("file", null); // A response file carries no request, so it cannot be searched again.
      });
      if (shown) {
        $("example").value = "";
        $("search-status").textContent = "";
      }
    };
    reader.onerror = function () {
      if (session.isCurrent(token)) showError("This file could not be read. Choose it again, or choose another response file.");
    };
    reader.readAsText(file);
  }

  /*
   * The only path to a live request: one press, one call, and no second call until it settles.
   * The result is tied to the request that was submitted and is shown only if nothing else was
   * chosen while it was in progress. The control is released however the call ends.
   */
  function search() {
    if (!transport) return;
    var ticket = session.begin();
    if (!ticket) return;
    syncSearch();
    showError("");
    $("search-status").textContent = "Requesting driving times. Results appear here when the search finishes.";
    function finish(apply) {
      var currentView = session.settle(ticket);
      try {
        if (currentView) apply();
        else $("search-status").textContent = "A search finished after you chose something else, so its result is not shown.";
      } finally {
        syncSearch();
      }
    }
    Promise.resolve().then(function () { return transport(ticket.request); }).then(function (envelope) {
      finish(function () {
        var shown = show(envelope, function () { return requestWords(envelope, ticket.request); }, function () {
          current.fileName = null;
          session.adopt("search", ticket.request);
        });
        if (shown) $("example").value = "";
        $("search-status").textContent = shown ? "Showing the response to your search." : "";
      });
    }, function () {
      finish(function () {
        $("search-status").textContent = "";
        showError("The search could not be completed, and the response shown below is unchanged. Press Search driving times to try again.");
      });
    });
  }

  function start() {
    $("open-file").addEventListener("click", function () { $("file").click(); });
    $("file").addEventListener("change", function () {
      var file = $("file").files[0];
      if (file) openFile(file);
      $("file").value = "";
    });
    if (transport) {
      $("search-field").hidden = false;
      $("search").addEventListener("click", search);
      syncSearch();
    }
    headerNote();
    if (!bundle) {
      $("example").disabled = true;
      showError("The example responses did not load. Check that data/finder_examples.js sits beside this page, then reload. You can also open a response file.");
      return;
    }
    bundle.examples.forEach(function (example) {
      $("example").append(el("option", { value: example.key, text: example.title }));
    });
    $("example").append(el("option", { value: "", text: "Not an example", hidden: true }));
    $("example").addEventListener("change", showExample);
    showExample();
  }

  start();
})();
