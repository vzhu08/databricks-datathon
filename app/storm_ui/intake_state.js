/*
 * What the Find care page says at each step of the intake.
 *
 * Pure functions over the bundle written by `python -m app.storm_ui.build_intake`. Nothing here
 * assesses a patient: the state, the next question, the concerns, the reasons and the care request
 * are read from stored assessments. These functions look one up and put it into sentences taken
 * from the bundle's catalogue.
 *
 * PROVISIONAL field names. The team's intake contract (issue 127) is not written yet. `read` is
 * the one place that knows the stored field names; when the contract lands, change `read`.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.IntakeState = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var ANSWER_LABEL = { yes: "Yes", no: "No", unknown: "Not sure" };
  var ROUTABLE = ["dialysis", "mri", "trauma_care"];
  var URGENCIES = ["routine", "time_sensitive", "highest"];

  function key(scenarioId, answers, confirmed) {
    return scenarioId + "|" + answers.join(",") + (confirmed ? "|confirmed" : "");
  }
  function named(list, id) {
    for (var i = 0; i < list.length; i += 1) if (list[i].id === id) return list[i];
    return null;
  }

  /* The only function that knows the stored field names. */
  function read(stored) {
    if (!stored || typeof stored !== "object") return null;
    var confirmation = stored.confirmation || {};
    return {
      state: stored.state,
      message: stored.message_id,
      next: stored.next_question_id || null,
      revision: stored.input_revision,
      concerns: stored.concerns || [],
      reasons: stored.reason_ids || [],
      sources: stored.source_ids || [],
      limits: stored.limit_ids || [],
      unknown: stored.unknown_question_ids || [],
      clinician: stored.clinician || null,
      confirmationRequired: confirmation.required === true,
      confirmed: confirmation.present === true,
      confirmedFor: confirmation.bound_to || null,
      request: stored.request || null,
      synthetic: stored.synthetic === true,
    };
  }

  function lookup(data, scenarioId, answers, confirmed) {
    return read(data.assessments[key(scenarioId, answers, confirmed)]);
  }

  /*
   * The request the campus finder may be given, or null. The page trusts nothing but this: a
   * stored state that says ready is not enough unless its confirmation is for these exact answers
   * and it asks for care the finder has campuses for.
   */
  function finderRequest(data, scenarioId, answers, confirmed) {
    if (!confirmed) return null;
    var a = lookup(data, scenarioId, answers, true);
    var unconfirmed = lookup(data, scenarioId, answers, false);
    if (!a || !unconfirmed || !a.synthetic) return null;
    if (a.state !== "ready" || !a.confirmed || !a.confirmedFor) return null;
    if (a.confirmedFor !== a.revision || a.revision !== unconfirmed.revision) return null;
    if (a.next || a.unknown.length || !a.clinician || !a.request) return null;
    if (ROUTABLE.indexOf(a.request.service) === -1 || URGENCIES.indexOf(a.request.urgency) === -1) return null;
    if (a.request.service !== a.clinician.service || a.request.urgency !== a.clinician.urgency) return null;
    if (!Array.isArray(a.request.required_capabilities) || a.request.required_capabilities.length) return null;
    return { service: a.request.service, urgency: a.request.urgency };
  }

  function kind(a) {
    if (a.state === "escalation") return "emergency";
    if (a.state === "ready") return "ready";
    if (a.state === "awaiting_confirmation") return "confirm";
    if (a.state === "more_information" && a.next) return "progress";
    return "stop";
  }

  function texts(section, ids) {
    return ids.map(function (id) { return section[id]; }).filter(Boolean);
  }

  /* What the story says a clinician has already decided, in one sentence. */
  function decided(data, scenario) {
    var c = scenario.clinician, cat = data.catalogue;
    if (!c) return "In this story no clinician has seen the patient yet.";
    return "Already decided in this story: " + (cat.clinician_kinds[c.kind] || "a clinician") + " asks for " +
      (cat.service_phrases[c.service] || c.service) + ", " +
      (cat.urgency_names[c.urgency] || c.urgency).toLowerCase() + " urgency.";
  }

  /* Everything the page shows for one fictional patient and the answers so far. Null when unknown. */
  function view(data, scenarioId, answers, confirmed) {
    var scenario = named(data.scenarios, scenarioId);
    var a = scenario ? lookup(data, scenarioId, answers, confirmed) : null;
    if (!a) return null;
    var cat = data.catalogue, message = cat.messages[a.message] || {};
    var request = finderRequest(data, scenarioId, answers, confirmed);
    var k = kind(a);
    if (k === "ready" && !request) return null;
    var next = a.next ? named(data.questions, a.next) : null;
    var summary = null;
    if ((k === "confirm" || k === "ready") && a.clinician) {
      summary = [
        { label: "Care requested", value: cat.service_names[a.clinician.service] || a.clinician.service },
        { label: "Urgency", value: cat.urgency_names[a.clinician.urgency] || a.clinician.urgency },
        { label: "Asked for by", value: (cat.clinician_kinds[a.clinician.kind] || "a clinician") + ", in the story" },
      ];
    }
    return {
      kind: k,
      state: a.state,
      revision: a.revision,
      scenario: scenario,
      decided: decided(data, scenario),
      progress: answers.length + " of " + data.max_questions + " questions answered",
      headline: message.headline || "",
      body: message.body || "",
      answered: answers.map(function (answer, index) {
        var q = data.questions[index];
        return { id: q.id, short: q.short, answer: answer, label: ANSWER_LABEL[answer] || answer };
      }),
      next: next ? { id: next.id, text: next.text, number: answers.length + 1 } : null,
      concerns: texts(cat.concerns, a.concerns),
      reasons: texts(cat.reasons, a.reasons),
      unknown: a.unknown.map(function (id) { return (named(data.questions, id) || {}).short || id; }),
      limits: texts(cat.limits, a.limits),
      sources: texts(cat.sources, a.sources),
      summary: summary,
      canConfirm: k === "confirm" && a.confirmationRequired && !a.confirmed,
      request: request,
    };
  }

  /* Why a bundle cannot be shown. An empty list means the page can draw every state in it. */
  function problems(data) {
    if (!data || typeof data !== "object") return ["The intake file did not load."];
    var found = [];
    ["questions", "scenarios", "answers"].forEach(function (name) {
      if (!Array.isArray(data[name]) || !data[name].length) found.push("Missing list: " + name + ".");
    });
    ["catalogue", "assessments"].forEach(function (name) {
      if (!data[name] || typeof data[name] !== "object") found.push("Missing section: " + name + ".");
    });
    if (data.synthetic !== true) found.push("The intake file is not marked synthetic.");
    if (found.length) return found;
    data.scenarios.forEach(function (scenario) {
      if (!view(data, scenario.id, [], false)) found.push("No starting state for " + scenario.id + ".");
    });
    Object.keys(data.assessments).forEach(function (name) {
      var a = read(data.assessments[name]);
      if (!a || !data.catalogue.messages[a.message]) found.push("No wording for " + name + ".");
    });
    return found.slice(0, 4);
  }

  return { key: key, read: read, lookup: lookup, finderRequest: finderRequest, view: view, decided: decided,
    problems: problems, ANSWER_LABEL: ANSWER_LABEL };
});
