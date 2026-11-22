/*
 * What the Find care page says at each step of the intake.
 *
 * Pure functions over the bundle written by `python -m app.storm_ui.build_intake`. Nothing here
 * assesses a patient: the state, the next question, the concerns, the reasons, the care summary and
 * the care request are the intake engine's stored answers (`app.intake.assess_intake`, contract
 * `intake.v1`). These functions look one up and put it into sentences taken from the bundle's
 * catalogue, which holds the display entries of the modules that own them.
 *
 * `read` is the one place that knows the engine's field names.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.IntakeState = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var ROUTABLE = ["dialysis", "mri", "trauma_care"];
  var URGENCIES = ["routine", "time_sensitive", "highest"];
  /* Notes of the page's own, about what the demonstration is. They say nothing about a patient. */
  var NOTES = {
    demo: "This is a demonstration with fictional stories. No clinician has validated its questions or rules.",
    unknown: "An answer of “Not sure” is kept as not known. It is never counted as “No”.",
    place: "Nobody has confirmed a free place at any campus.",
  };

  /* `answers` is the visitor's answers in the order they were asked: [[question id, answer id], ...]. */
  function key(scenarioId, answers, confirmed) {
    return scenarioId + "|" + answers.map(function (pair) { return pair[0] + "=" + pair[1]; }).join(",") +
      (confirmed ? "|confirmed" : "");
  }
  function named(list, id) {
    for (var i = 0; i < list.length; i += 1) if (list[i].id === id) return list[i];
    return null;
  }
  function own(object, name) { return Object.prototype.hasOwnProperty.call(object || {}, name); }
  function list(value) { return Array.isArray(value) ? value : []; }

  /* The only function that knows the engine's field names. */
  function read(stored) {
    if (!stored || typeof stored !== "object") return null;
    return {
      state: stored.state,
      messages: list(stored.message_ids),
      next: list(stored.next_question_ids)[0] || null,
      revision: stored.input_revision,
      fingerprint: stored.input_fingerprint,
      concerns: list(stored.concerns),
      reasons: list(stored.reason_codes),
      rules: list(stored.rule_ids),
      sources: list(stored.source_ids),
      unknown: list(stored.unknowns),
      clinician: stored.clinician_confirmation,
      confirmation: stored.confirmation_status,
      summary: stored.care_summary || null,
      request: stored.request || null,
      synthetic: stored.mode === "synthetic",
      scenario: stored.scenario_id,
      version: stored.scenario_version,
      policy: stored.policy_version,
      schema: stored.schema_version,
    };
  }

  function lookup(data, scenarioId, answers, confirmed) {
    var name = key(scenarioId, answers, confirmed);
    return own(data.assessments, name) ? read(data.assessments[name]) : null;
  }

  function sameList(a, b) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    for (var i = 0; i < a.length; i += 1) if (typeof a[i] !== "string" || a[i] !== b[i]) return false;
    return true;
  }
  /* The same service, urgency and capability lists. With `authority`, the same authority as well. */
  function sameCare(a, b, authority) {
    return Boolean(a && b) && a.service === b.service && a.urgency === b.urgency &&
      sameList(a.required_capabilities, b.required_capabilities) &&
      sameList(a.preferred_capabilities, b.preferred_capabilities) &&
      (!authority || (typeof a.authority === "string" && a.authority === b.authority));
  }

  /*
   * Whether a stored state is one a visitor may be asked to confirm: synthetic, for this edition of
   * this story, waiting on a confirmation it does not have, with a clinician's plan present in the
   * story, every question answered, nothing unknown, a care summary and no care request of its own.
   */
  function mayBeConfirmed(a, scenario, answers) {
    return Boolean(a && scenario && scenario.plan) && a.synthetic &&
      a.scenario === scenario.id && a.version === scenario.version &&
      a.state === "confirmation_required" && a.confirmation === "absent" && a.clinician === "present" &&
      !a.next && !a.unknown.length && !a.request && sameCare(a.summary, scenario.plan, true) &&
      a.revision === answers.length && typeof a.fingerprint === "string" && /^[0-9a-f]{64}$/.test(a.fingerprint);
  }

  /*
   * The request the campus finder may be given, or null. The page trusts nothing but this. Two
   * stored answers must agree: the summary the visitor was shown and the ready answer the engine
   * gave after a real confirmation of it at build time. The summary has to be one that may be
   * confirmed, and the ready answer has to carry the same input fingerprint, contract and rule set
   * versions, story edition, revision and care summary as that summary, a current confirmation, and
   * a request that is exactly the summary's care. A blocked, unsupported, unfinished or mismatched
   * summary gives no request, whatever the answer stored after it says.
   */
  function finderRequest(data, scenarioId, answers, confirmed) {
    if (!confirmed) return null;
    var scenario = named(data.scenarios || [], scenarioId);
    var before = lookup(data, scenarioId, answers, false);
    var a = lookup(data, scenarioId, answers, true);
    if (!scenario || !a || !mayBeConfirmed(before, scenario, answers)) return null;
    if (!a.synthetic || a.scenario !== scenario.id || a.version !== scenario.version) return null;
    if (a.state !== "ready" || a.confirmation !== "current" || a.clinician !== "present") return null;
    if (a.fingerprint !== before.fingerprint || a.revision !== before.revision) return null;
    if (!a.policy || a.policy !== before.policy || a.policy !== data.policy_version) return null;
    if (!a.schema || a.schema !== before.schema || a.schema !== data.schema_version) return null;
    if (a.next || a.unknown.length || !a.request) return null;
    if (!sameCare(a.summary, before.summary, true) || !sameCare(a.summary, scenario.plan, true)) return null;
    if (!sameCare(a.request, a.summary, false)) return null;
    if (ROUTABLE.indexOf(a.request.service) === -1 || URGENCIES.indexOf(a.request.urgency) === -1) return null;
    return { service: a.request.service, urgency: a.request.urgency };
  }

  /*
   * The campus answer the finder bridge produced at build time for this confirmed input and this
   * starting point, or null. Only given when finderRequest gives a request.
   */
  function finderResponse(data, scenarioId, answers, confirmed, origin) {
    if (!finderRequest(data, scenarioId, answers, confirmed)) return null;
    var name = key(scenarioId, answers, true);
    if (list(data.origins).indexOf(origin) === -1 || !own(data.finder, name)) return null;
    var produced = own(data.finder[name], origin) ? data.finder[name][origin] : null;
    if (!produced || typeof produced.status !== "string" || !Array.isArray(produced.ranked)) return null;
    return produced;
  }

  function kind(a) {
    if (a.state === "emergency_escalation") return "emergency";
    if (a.state === "ready") return "ready";
    if (a.state === "confirmation_required") return "confirm";
    if (a.state === "more_information_needed" && a.next) return "progress";
    return "stop";
  }

  function unique(items) {
    return items.filter(function (item, index) { return item && items.indexOf(item) === index; });
  }
  function answerLabel(question, answerId) {
    var choice = question ? named(question.answers, answerId) : null;
    return choice ? choice.label : answerId;
  }

  /* What the story says a clinician has already decided, in one sentence. */
  function decided(data, scenario) {
    var plan = scenario.plan, cat = data.catalogue;
    if (!plan) return "In this story no clinician has asked for a service.";
    return "Already in this story. " + (cat.authorities[plan.authority] || plan.authority) + ": " +
      (cat.service_names[plan.service] || plan.service) + ", " +
      (cat.urgency_names[plan.urgency] || plan.urgency).toLowerCase() + " urgency.";
  }

  function sourceLine(cat, id) {
    var source = cat.sources[id];
    if (!source) return null;
    return { id: id, text: source.title + (source.section ? ". " + source.section : ""),
      url: /^https:\/\//.test(source.url || "") ? source.url : null };
  }

  /* Everything the page shows for one fictional story and the answers so far. Null when unknown. */
  function view(data, scenarioId, answers, confirmed) {
    var scenario = named(data.scenarios, scenarioId);
    var a = scenario ? lookup(data, scenarioId, answers, confirmed) : null;
    if (!a) return null;
    var cat = data.catalogue;
    var request = finderRequest(data, scenarioId, answers, confirmed);
    var k = kind(a);
    if (k === "ready" && !request) return null;
    // The first message is the primary one. Its first sentence is the headline, the rest sits under it.
    var message = cat.messages[a.messages[0]] || "";
    var cut = message.indexOf(". ");
    var headline = cut === -1 ? message : message.slice(0, cut + 1);
    var body = cut === -1 ? "" : message.slice(cut + 2);
    var next = a.next ? named(data.questions, a.next) : null;
    var summary = null;
    if ((k === "confirm" || k === "ready") && a.summary) {
      summary = [
        { label: "Care requested", value: cat.service_names[a.summary.service] || a.summary.service },
        { label: "Urgency", value: cat.urgency_names[a.summary.urgency] || a.summary.urgency },
        { label: "Asked for by", value: (cat.authorities[a.summary.authority] || a.summary.authority) + ", in the story" },
      ];
      if (list(a.summary.required_capabilities).length) {
        summary.push({ label: "Must have", value: a.summary.required_capabilities.join(", ") });
      }
    }
    var why = a.rules.map(function (id) { return (cat.rules[id] || {}).rationale; })
      .concat(a.reasons.map(function (id) { return cat.reasons[id]; }))
      .concat(a.messages.slice(1).map(function (id) { return cat.messages[id]; }));
    var sourceIds = a.sources.slice();
    a.concerns.forEach(function (concern) { sourceIds = sourceIds.concat(list(concern.source_ids)); });
    var notes = [];
    if (k !== "progress") {
      if (a.unknown.length && k !== "emergency") notes.push(NOTES.unknown);
      if (k === "ready") notes.push(NOTES.place);
      notes.push(NOTES.demo);
    }
    return {
      kind: k,
      state: a.state,
      fingerprint: a.fingerprint,
      scenario: scenario,
      decided: decided(data, scenario),
      known: scenario.known.map(function (fact) {
        var q = named(data.questions, fact.id);
        return { id: fact.id, short: q ? q.short : fact.id, label: answerLabel(q, fact.answer) };
      }),
      message: message,
      headline: headline,
      body: body,
      answered: answers.map(function (pair) {
        var q = named(data.questions, pair[0]);
        return { id: pair[0], short: q ? q.short : pair[0], answer: pair[1], label: answerLabel(q, pair[1]) };
      }),
      next: next ? { id: next.id, text: next.text, number: answers.length + 1, answers: next.answers } : null,
      concerns: unique(a.concerns.map(function (concern) { return cat.concerns[concern.category]; })),
      reasons: unique(why).filter(function (line) { return line !== message; }),
      unknown: k === "progress" ? [] : a.unknown.map(function (id) { return (named(data.questions, id) || {}).short || id; }),
      limits: notes,
      sources: unique(sourceIds).map(function (id) { return sourceLine(cat, id); }).filter(Boolean),
      summary: summary,
      canConfirm: k === "confirm" && mayBeConfirmed(a, scenario, answers) && Boolean(lookup(data, scenarioId, answers, true)),
      request: request,
    };
  }

  /* Why a bundle cannot be shown. An empty list means the page can draw every state in it. */
  function problems(data) {
    if (!data || typeof data !== "object") return ["The intake file did not load."];
    var found = [];
    ["questions", "scenarios", "origins"].forEach(function (name) {
      if (!Array.isArray(data[name]) || !data[name].length) found.push("Missing list: " + name + ".");
    });
    ["catalogue", "assessments", "finder"].forEach(function (name) {
      if (!data[name] || typeof data[name] !== "object") found.push("Missing section: " + name + ".");
    });
    if (data.synthetic !== true) found.push("The intake file is not marked synthetic.");
    if (found.length) return found;
    ["messages", "reasons", "concerns", "authorities", "rules", "sources", "service_names", "urgency_names"]
      .forEach(function (name) {
        if (!data.catalogue[name] || typeof data.catalogue[name] !== "object") found.push("Missing wording: " + name + ".");
      });
    if (found.length) return found;
    data.scenarios.forEach(function (scenario) {
      if (!view(data, scenario.id, [], false)) found.push("No starting state for " + scenario.id + ".");
    });
    Object.keys(data.assessments).forEach(function (name) {
      var a = read(data.assessments[name]);
      if (!a || !data.catalogue.messages[a.messages[0]]) found.push("No wording for " + name + ".");
    });
    return found.slice(0, 4);
  }

  return { key: key, read: read, lookup: lookup, finderRequest: finderRequest, finderResponse: finderResponse,
    view: view, decided: decided, problems: problems, NOTES: NOTES };
});
