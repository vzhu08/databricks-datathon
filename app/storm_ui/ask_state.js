/*
 * What the Find care page says for one answer.
 *
 * Pure functions over the bundle written by `python -m app.storm_ui.build_ask`. Nothing here ranks,
 * scores or decides eligibility: the order, the points, the weights and the reasons are read from
 * the ranker's response. These functions only put those numbers into sentences.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.AskState = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December"];
  var FACTORS = ["travel", "recency", "corroboration", "preferred"];
  var FACTOR_NAME = { travel: "Shorter trip", recency: "Recent record", corroboration: "Independent sources",
    preferred: "Preferred equipment" };
  var URGENCY_PHRASE = { routine: "routine urgency", time_sensitive: "time-sensitive urgency", highest: "the highest urgency" };
  var SERVICE_PHRASE = { dialysis: "dialysis", mri: "an MRI scan", trauma_care: "trauma care" };
  var REASON = {
    service_unconfirmed: "its record does not confirm the service is offered there",
    missing_service_evidence_date: "its record has no date, so nobody can tell how current it is",
    invalid_service_evidence_date: "the date on its record cannot be right",
    required_capability_unconfirmed: "its record does not confirm the equipment this request needs",
    assessment_date_mismatch: "its record was reviewed for a different date",
    travel_unknown: "the travel time to it is not known",
  };

  function key(service, place, urgency) { return service + "|" + place + "|" + urgency; }

  function day(iso) {
    if (typeof iso !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "an unknown date";
    return Number(iso.slice(8)) + " " + MONTHS[Number(iso.slice(5, 7)) - 1] + " " + iso.slice(0, 4);
  }
  function minutes(value) { return value + (value === 1 ? " minute" : " minutes"); }
  function sources(count) { return count === 1 ? "1 source" : count + " independent sources"; }
  function named(list, id) {
    for (var i = 0; i < list.length; i += 1) if (list[i].id === id) return list[i];
    return null;
  }

  /* Whole points for each factor that add up to the rounded total. */
  function points(row) {
    var total = Math.round(row.score);
    var parts = FACTORS.filter(function (name) { return row.weights[name] > 0; }).map(function (name) {
      var exact = row.weights[name] * row.factors[name];
      return { factor: name, label: FACTOR_NAME[name], exact: exact, points: Math.floor(exact),
        out_of: Math.round(row.weights[name]) };
    });
    var short = total - parts.reduce(function (sum, part) { return sum + part.points; }, 0);
    parts.slice().sort(function (a, b) { return (b.exact - b.points) - (a.exact - a.points); })
      .slice(0, Math.max(0, short)).forEach(function (part) { part.points += 1; });
    return { total: total, parts: parts };
  }

  function option(data, service, row) {
    var record = data.records[row.facility_id + "|" + service] || {};
    return {
      facility_id: row.facility_id,
      name: data.campuses[row.facility_id] ? data.campuses[row.facility_id].name : row.facility_id,
      travel: row.travel,
      record_text: record.text || null,
      record_date: row.source_date || record.source_date || null,
      sources: record.sources || 0,
      availability: row.availability || null,
      points: row.score === undefined ? null : points(row),
      row: row,
    };
  }

  function leftOut(data, service, budget, entry) {
    var record = data.records[entry.facility_id + "|" + service] || {};
    var name = data.campuses[entry.facility_id] ? data.campuses[entry.facility_id].name : entry.facility_id;
    var why;
    if (entry.kind === "too_far") why = "beyond the " + budget + "-minute limit for this urgency";
    else if (entry.kind === "ranked_lower") why = "qualifies, but scored below the three shown";
    else why = entry.reasons.map(function (reason) { return REASON[reason] || reason.replace(/_/g, " "); }).join("; ");
    return { facility_id: entry.facility_id, name: name, travel: entry.travel, kind: entry.kind, why: why,
      record_text: record.text || null };
  }

  /* Why the first campus is first, in the ranker's own numbers. */
  function why(data, answer, top, rivals) {
    var request = answer.request;
    var service = SERVICE_PHRASE[request.service] || request.service;
    var lines = [];
    if (answer.eligible === 1) {
      lines.push(top.name + " is the only campus with a confirmed record for " + service + " within " +
        request.travel_budget + " minutes of here.");
      return lines;
    }
    lines.push(top.name + " scored highest of the " + answer.eligible + " campuses with a confirmed record for " +
      service + " within " + request.travel_budget + " minutes: " + top.points.total + " points out of 100.");
    var nearer = rivals.filter(function (rival) { return rival.travel < top.travel; })
      .sort(function (a, b) { return a.travel - b.travel; })[0];
    if (!nearer) {
      lines.push("It is also the shortest trip of them.");
      return lines;
    }
    var gap = { recency: 0, corroboration: 0, preferred: 0 };
    Object.keys(gap).forEach(function (name) {
      gap[name] = top.row.weights[name] * top.row.factors[name] - nearer.row.weights[name] * nearer.row.factors[name];
    });
    var main = Object.keys(gap).sort(function (a, b) { return gap[b] - gap[a]; })[0];
    var because = main === "recency"
      ? "its record is older: " + day(nearer.record_date) + ", against " + day(top.record_date)
      : main === "corroboration"
        ? "less backs its record: " + sources(nearer.sources) + ", against " + sources(top.sources)
        : "its record confirms less of the preferred equipment";
    lines.push(nearer.name + " is a shorter trip (" + minutes(nearer.travel) + "), but " + because + ". At " +
      (URGENCY_PHRASE[request.urgency] || request.urgency) + " that outweighs the " +
      minutes(top.travel - nearer.travel) + " saved.");
    return lines;
  }

  function weightsLine(data, answer, top) {
    var urgency = named(data.urgencies, answer.request.urgency);
    var words = { travel: "a shorter trip", recency: "a recent record", corroboration: "independent sources",
      preferred: "preferred equipment" };
    var parts = top.points.parts.map(function (part, index) {
      return words[part.factor] + (index === 0 ? " is worth up to " + part.out_of + " points" : " up to " + part.out_of);
    });
    return "At " + (urgency ? urgency.name.toLowerCase() : answer.request.urgency) + " urgency, " +
      parts.join(", ").replace(/, ([^,]*)$/, " and $1") + ".";
  }

  /* Everything the page shows for one request. Null when the bundle has no such answer. */
  function view(data, service, place, urgency) {
    var answer = data.answers[key(service, place, urgency)];
    if (!answer) return null;
    var response = answer.response, request = answer.request;
    var serviceName = (named(data.services, service) || {}).name || service;
    var placeName = (named(data.places, place) || {}).name || place;
    var urgencyName = (named(data.urgencies, urgency) || {}).name || urgency;
    var options = response.ranked.map(function (row) { return option(data, service, row); });
    var lower = answer.left_out.filter(function (entry) { return entry.kind === "ranked_lower" && entry.row; })
      .map(function (entry) { return option(data, service, entry.row); });
    var top = options[0] || null;
    var out = {
      status: response.status,
      service: service, place: place, urgency: urgency,
      service_name: serviceName, place_name: placeName, urgency_name: urgencyName,
      service_phrase: SERVICE_PHRASE[service] || serviceName.toLowerCase(),
      budget: request.travel_budget,
      considered: request.candidates.length,
      eligible: answer.eligible,
      request_line: serviceName + " from the " + placeName.toLowerCase() + ". Urgency: " + urgencyName.toLowerCase() + ".",
      top: top,
      backups: options.slice(1),
      leads: response.needs_confirmation.map(function (lead) {
        return leftOut(data, service, request.travel_budget,
          { facility_id: lead.facility_id, travel: lead.travel, kind: "unconfirmed", reasons: lead.reasons });
      }),
      left_out: answer.left_out.map(function (entry) { return leftOut(data, service, request.travel_budget, entry); }),
      why: top ? why(data, answer, top, options.slice(1).concat(lower)) : [],
      weights_line: top ? weightsLine(data, answer, top) : null,
      caveat: top && top.availability === "unknown"
        ? "Nobody has confirmed a free place today. Phone " + top.name + " before the patient travels."
        : null,
      raw: answer,
    };
    out.referral = referral(out);
    return out;
  }

  /* The note a health worker copies or prints. Plain text, one fact per line. */
  function referral(v) {
    var lines = ["Referral note (demonstration, invented data)", "Care needed: " + v.service_name,
      "From: " + v.place_name, "Urgency: " + v.urgency_name];
    if (v.status === "ok") {
      lines.push("Send to: " + v.top.name + ", about " + minutes(v.top.travel) + " by road");
      if (v.top.record_text) lines.push("Record says: \"" + v.top.record_text + "\" (" + day(v.top.record_date) + ", " + sources(v.top.sources) + ")");
      if (v.backups.length) {
        lines.push("If it cannot take the patient: " + v.backups.map(function (b) {
          return b.name + " (" + minutes(b.travel) + ")";
        }).join(", then "));
      }
      if (v.caveat) lines.push("Before travelling: " + v.caveat);
    } else if (v.status === "needs_confirmation") {
      lines.push("No campus is confirmed for this within " + minutes(v.budget) + ".");
      lines.push("Phone first: " + v.leads.map(function (l) { return l.name + " (" + minutes(l.travel) + ")"; }).join(", "));
    } else {
      lines.push("No campus with a record for this is within " + minutes(v.budget) + ".");
    }
    return lines.join("\n");
  }

  /* Why a bundle cannot be shown. An empty list means the page can draw every answer in it. */
  function problems(data) {
    if (!data || typeof data !== "object") return ["The answers file did not load."];
    var found = [];
    ["services", "urgencies", "places", "examples"].forEach(function (name) {
      if (!Array.isArray(data[name]) || !data[name].length) found.push("Missing list: " + name + ".");
    });
    ["campuses", "records", "answers"].forEach(function (name) {
      if (!data[name] || typeof data[name] !== "object") found.push("Missing section: " + name + ".");
    });
    if (found.length) return found;
    data.services.forEach(function (service) {
      data.places.forEach(function (place) {
        data.urgencies.forEach(function (urgency) {
          var answer = data.answers[key(service.id, place.id, urgency.id)];
          if (!answer || !answer.response || !Array.isArray(answer.response.ranked) ||
              !Array.isArray(answer.response.needs_confirmation) || !Array.isArray(answer.left_out)) {
            found.push("No usable answer for " + key(service.id, place.id, urgency.id) + ".");
          }
        });
      });
    });
    return found.slice(0, 4);
  }

  return { key: key, day: day, minutes: minutes, sources: sources, points: points, view: view,
    referral: referral, problems: problems, FACTOR_NAME: FACTOR_NAME };
});
