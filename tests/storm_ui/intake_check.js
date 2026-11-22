/* Checks the intake wording and the finder gate against every stored engine answer. Run with Node. */
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..", "app", "storm_ui");
const I = require(path.join(root, "intake_state.js"));
const A = require(path.join(root, "ask_state.js"));
const load = (file, name) => {
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, "data", file), "utf8"), sandbox);
  return JSON.parse(JSON.stringify(sandbox.window[name]));
};
const data = load("intake.js", "CARE_INTAKE");
const care = load("answers.js", "CARE_ANSWERS");
const clone = (value) => JSON.parse(JSON.stringify(value));
const copy = () => clone(data);

let checks = 0;
const ok = (value, message) => { checks += 1; assert.ok(value, message); };
const same = (actual, expected, message) => { checks += 1; assert.deepStrictEqual(actual, expected, message); };
const parse = (name) => {
  const [scenarioId, joined, flag] = name.split("|");
  return { scenarioId, answers: joined ? joined.split(",").map((pair) => pair.split("=")) : [], confirmed: flag === "confirmed" };
};

same(I.problems(data), [], "the committed bundle can be shown");
ok(I.problems(null).length === 1 && I.problems({}).length > 0, "a missing or empty bundle is reported");
ok(I.problems(Object.assign(copy(), { synthetic: false })).length > 0, "a bundle not marked synthetic is refused");
{
  const gap = copy();
  delete gap.catalogue.messages["intake.ready"];
  ok(I.problems(gap).length > 0, "a state with no wording for its first message is reported");
}

const cat = data.catalogue;
const kinds = {};
let ready = 0, campusAnswers = 0;
for (const name of Object.keys(data.assessments)) {
  const { scenarioId, answers, confirmed } = parse(name);
  const stored = data.assessments[name];
  same(I.key(scenarioId, answers, confirmed), name, `${name}: the page spells the key the way the build does`);
  const v = I.view(data, scenarioId, answers, confirmed);
  ok(v, `${name}: the page can show it`);
  kinds[v.kind] = (kinds[v.kind] || 0) + 1;
  same(v.state, stored.state, `${name}: the state is the stored one`);
  same(v.message, cat.messages[stored.message_ids[0]], `${name}: the message is the first message's own wording`);
  same((v.headline + " " + v.body).trim(), v.message, `${name}: the headline and the line under it are that message, uncut`);
  ok(v.headline.length > 10, `${name}: it has a headline`);
  same(v.answered.map((item) => [item.id, item.answer]), answers, `${name}: every answer so far is listed`);
  ok(v.answered.every((item) => item.label && item.short), `${name}: every answer has its question's and its own label`);
  same(v.next ? v.next.id : null, stored.next_question_ids[0] || null, `${name}: the next question is the stored one`);
  ok(stored.next_question_ids.length <= 1, `${name}: at most one question is asked at a time`);
  for (const id of stored.reason_codes) ok(cat.reasons[id], `${name}: reason ${id} has wording`);
  for (const id of stored.rule_ids) ok(cat.rules[id] && v.reasons.includes(cat.rules[id].rationale), `${name}: rule ${id} is explained`);
  for (const id of stored.reason_codes) {
    ok(cat.reasons[id] === v.message || v.reasons.includes(cat.reasons[id]), `${name}: reason ${id} is shown`);
  }
  same(v.concerns, [...new Set(stored.concerns.map((c) => cat.concerns[c.category]))], `${name}: every concern has wording`);
  const sourceIds = [...new Set([...stored.source_ids, ...stored.concerns.flatMap((c) => c.source_ids)])];
  same(v.sources.map((s) => s.id), sourceIds, `${name}: every source is listed once`);
  ok(v.sources.every((s) => s.text.length > 5), `${name}: every source has a title`);
  if (v.kind === "progress") {
    ok(v.next.answers.length >= 2 && v.next.answers.every((c) => c.id !== "conflicting"), `${name}: the choices are the catalogue's own`);
    same(v.next.answers, data.questions.find((q) => q.id === v.next.id).answers, `${name}: the choices are the question's own`);
  } else {
    same(v.unknown.length, stored.unknowns.length, `${name}: everything not known is named`);
    ok(v.limits.includes(I.NOTES.demo), `${name}: the outcome says it is a demonstration`);
  }
  // The finder gate: a request exists only for a confirmed, ready state.
  const request = I.finderRequest(data, scenarioId, answers, confirmed);
  same(Boolean(request), stored.state === "ready", `${name}: only a ready state may ask for a campus`);
  same(Boolean(v.request), stored.state === "ready", `${name}: the view agrees`);
  same(v.canConfirm, stored.state === "confirmation_required", `${name}: Confirm is offered only when a summary waits for it`);
  same(Boolean(v.summary), ["confirmation_required", "ready"].includes(stored.state), `${name}: a care summary shows only with a clinician's plan`);
  if (stored.state !== "ready") {
    same(stored.request, null, `${name}: the engine gave no request`);
    ok(!Object.prototype.hasOwnProperty.call(data.finder, name), `${name}: no campus answer is stored for it`);
  }
  if (v.kind === "emergency") ok(/112/.test(v.message) && !v.summary && !v.next && !v.canConfirm, `${name}: an emergency names 112 and asks nothing more`);
  for (const origin of data.origins) {
    const produced = I.finderResponse(data, scenarioId, answers, confirmed, origin);
    same(Boolean(produced), stored.state === "ready", `${name} from ${origin}: a campus answer exists only when ready`);
    if (!produced) continue;
    campusAnswers += 1;
    ok(A.matches(care, request.service, origin, request.urgency, produced), `${name} from ${origin}: the bridge's answer is the Find care page's answer`);
    const shown = A.view(care, request.service, origin, request.urgency);
    same(shown.status, produced.status, `${name} from ${origin}: the page shows that status`);
    same([shown.top, ...shown.backups].filter(Boolean).map((o) => o.facility_id), produced.ranked.map((r) => r.facility_id), `${name} from ${origin}: the same campuses in the same order`);
  }
  if (request) {
    ready += 1;
    same(request, { service: stored.request.service, urgency: stored.request.urgency }, `${name}: the request is the stored one`);
    same(I.finderResponse(data, scenarioId, answers, confirmed, "nowhere"), null, `${name}: an unlisted starting point has no answer`);
  }
}
same(Object.keys(kinds).sort(), ["confirm", "emergency", "progress", "ready", "stop"], "every kind of outcome occurs");
ok(ready > 0 && campusAnswers === ready * data.origins.length, "every ready state has an answer from every starting point");
ok(Object.keys(data.assessments).length <= 5000, "the bundle is within the size the page accepts");

/* A stored answer that only says it is ready is not enough. Each forgery below must be refused. */
const story = "scheduled_dialysis", none = [];
const readyKey = I.key(story, none, true), waitKey = I.key(story, none, false);
const honest = { service: "dialysis", urgency: "routine" };
same(I.finderRequest(data, story, none, true), honest, "the honest pair passes");
same(I.finderRequest(data, story, none, false), null, "an unconfirmed summary asks for nothing");
const forge = (label, change) => {
  const forged = copy();
  change(forged.assessments, forged);
  same(I.finderRequest(forged, story, none, true), null, `forged: ${label}`);
  const v = I.view(forged, story, none, true);
  ok(!v || !v.request, `forged: ${label} (view)`);
  for (const origin of forged.origins) same(I.finderResponse(forged, story, none, true, origin), null, `forged: ${label} (campus answer from ${origin})`);
};
forge("confirmation absent", (a) => { a[readyKey].confirmation_status = "absent"; });
forge("confirmation stale", (a) => { a[readyKey].confirmation_status = "stale"; });
forge("confirmation invalid", (a) => { a[readyKey].confirmation_status = "invalid"; });
forge("no clinician plan present", (a) => { a[readyKey].clinician_confirmation = "required"; });
forge("fingerprint differs from the summary's", (a) => { a[readyKey].input_fingerprint = "0".repeat(64); });
forge("revision differs from the summary's", (a) => { a[readyKey].input_revision = 3; });
forge("state is not ready", (a) => { a[readyKey].state = "confirmation_required"; });
forge("something is still unknown", (a) => { a[readyKey].unknowns = ["warning.heavy_bleeding"]; });
forge("a question is still open", (a) => { a[readyKey].next_question_ids = ["warning.heavy_bleeding"]; });
forge("no request", (a) => { a[readyKey].request = null; });
forge("service the finder does not have", (a) => { a[readyKey].request.service = a[readyKey].care_summary.service = "cardiology_review"; });
forge("request service differs from the summary", (a) => { a[readyKey].request.service = "mri"; });
forge("request urgency differs from the summary", (a) => { a[readyKey].request.urgency = "highest"; });
forge("a capability the summary does not have", (a) => { a[readyKey].request.required_capabilities = ["contrast"]; });
forge("a preference the summary does not have", (a) => { a[readyKey].request.preferred_capabilities = ["parking"]; });
forge("no care summary", (a) => { a[readyKey].care_summary = null; });
forge("another authority", (a) => { a[readyKey].care_summary.authority = "simulated_clinician_referral"; });
forge("not marked synthetic", (a) => { a[readyKey].mode = "live"; });
forge("another story edition", (a) => { a[readyKey].scenario_version = "2"; });
forge("another story", (a) => { a[readyKey].scenario_id = "scheduled_mri"; });
forge("no summary to compare with", (a) => { delete a[waitKey]; });

/*
 * The summary the visitor confirmed is checked too, not only its fingerprint. Each pair below keeps
 * the honest ready answer and spoils the answer before it. None may ask for a campus.
 */
forge("summary before it is an emergency", (a) => { a[waitKey].state = "emergency_escalation"; });
forge("summary before it is unsupported", (a) => { a[waitKey].state = "unsupported_care_need"; });
forge("summary before it needs an assessment", (a) => { a[waitKey].state = "clinician_assessment_needed"; });
forge("summary before it is unfinished", (a) => { a[waitKey].state = "more_information_needed"; });
forge("summary before it is invalid", (a) => { a[waitKey].state = "invalid_input"; });
forge("summary before it is already ready", (a) => { a[waitKey].state = "ready"; });
forge("summary before it has an open question", (a) => { a[waitKey].next_question_ids = ["context.onset"]; });
forge("summary before it has something unknown", (a) => { a[waitKey].unknowns = ["context.onset"]; });
forge("summary before it is already confirmed", (a) => { a[waitKey].confirmation_status = "current"; });
forge("summary before it has a stale confirmation", (a) => { a[waitKey].confirmation_status = "stale"; });
forge("summary before it still needs a clinician", (a) => { a[waitKey].clinician_confirmation = "required"; });
forge("summary before it needs no clinician", (a) => { a[waitKey].clinician_confirmation = "not_required"; });
forge("summary before it carries a request", (a) => { a[waitKey].request = clone(a[readyKey].request); });
forge("summary before it is not synthetic", (a) => { a[waitKey].mode = "live"; });
forge("summary before it has no care summary", (a) => { a[waitKey].care_summary = null; });
forge("summary before it names another service", (a) => { a[waitKey].care_summary.service = "mri"; });
forge("summary before it names another urgency", (a) => { a[waitKey].care_summary.urgency = "highest"; });
forge("summary before it names another authority", (a) => { a[waitKey].care_summary.authority = "simulated_clinician_referral"; });
forge("summary before it adds a capability", (a) => { a[waitKey].care_summary.required_capabilities = ["contrast"]; });
forge("summary before it used another rule set", (a) => { a[waitKey].policy_version = "other-rules"; });
forge("summary before it used another contract", (a) => { a[waitKey].schema_version = "other-schema"; });
forge("summary before it is for another story", (a) => { a[waitKey].scenario_id = "scheduled_mri"; });
forge("summary before it is for another story edition", (a) => { a[waitKey].scenario_version = "2"; });
forge("summary before it has another fingerprint", (a) => { a[waitKey].input_fingerprint = "f".repeat(64); });
forge("summary before it has no proper fingerprint", (a) => { a[waitKey].input_fingerprint = a[readyKey].input_fingerprint = "abc"; });
forge("summary before it has a revision that is not the number of answers", (a) => { a[waitKey].input_revision = a[readyKey].input_revision = 2; });
forge("another story's whole summary in its place", (a, f) => {
  a[waitKey] = clone(f.assessments[I.key("scheduled_mri", [["context.severity", "mild"]], false)]);
});
forge("both answers agree with each other but not with the story", (a) => {
  a[waitKey].care_summary.service = a[readyKey].care_summary.service = a[readyKey].request.service = "mri";
});
forge("both answers agree on a capability the story does not have", (a) => {
  a[waitKey].care_summary.required_capabilities = ["contrast"];
  a[readyKey].care_summary.required_capabilities = ["contrast"];
  a[readyKey].request.required_capabilities = ["contrast"];
});
forge("both answers agree on a rule set the bundle does not use", (a) => {
  a[waitKey].policy_version = a[readyKey].policy_version = "other-rules";
});
forge("both answers agree on a story edition the bundle does not hold", (a) => {
  a[waitKey].scenario_version = a[readyKey].scenario_version = "2";
});
forge("story missing from the list", (a, f) => { f.scenarios = f.scenarios.filter((s) => s.id !== story); });
forge("story with no clinician plan", (a, f) => { f.scenarios.find((s) => s.id === story).plan = null; });
forge("story edition changed", (a, f) => { f.scenarios.find((s) => s.id === story).version = "2"; });

/* A confirmation is for one exact input. The same story with another answer at the same count has its own. */
{
  const mild = [["context.severity", "mild"]], moderate = [["context.severity", "moderate"]];
  const a = data.assessments;
  ok(a[I.key("scheduled_mri", mild, false)].input_fingerprint !== a[I.key("scheduled_mri", moderate, false)].input_fingerprint,
    "another answer at the same count has another fingerprint");
  const forged = copy();
  forged.assessments[I.key("scheduled_mri", moderate, true)] = clone(a[I.key("scheduled_mri", mild, true)]);
  same(I.finderRequest(forged, "scheduled_mri", moderate, true), null, "forged: a confirmation of other answers");
  same(I.finderRequest(data, "scheduled_mri", moderate, true), { service: "mri", urgency: "routine" }, "the honest confirmation of those answers passes");
}

/* The campus answer is taken only from the record stored for this exact confirmed input. */
{
  const forged = copy();
  delete forged.finder[readyKey];
  same(I.finderRequest(forged, story, none, true), honest, "without a stored campus answer the request still stands");
  same(I.finderResponse(forged, story, none, true, "central"), null, "but there is no campus answer to show");
  const unlisted = copy();
  unlisted.origins = unlisted.origins.filter((o) => o !== "east");
  same(I.finderResponse(unlisted, story, none, true, "east"), null, "a starting point the bridge did not list has no answer");
  const broken = copy();
  broken.finder[readyKey].central = { status: "ok" };
  same(I.finderResponse(broken, story, none, true, "central"), null, "a campus answer with no ranking is refused");
  // The Find care page shows a bridge answer only when it is exactly the answer it holds.
  const real = I.finderResponse(data, story, none, true, "central");
  ok(A.matches(care, "dialysis", "central", "routine", real), "the honest campus answer is the page's own");
  ok(A.matches(care, "dialysis", "central", "routine", clone(real)), "a copy of it still is");
  const tamper = (label, change) => {
    const altered = clone(real);
    change(altered);
    ok(!A.matches(care, "dialysis", "central", "routine", altered), `altered campus answer: ${label}`);
  };
  ok(real.ranked.length >= 2, "the control answer ranks more than one campus");
  tamper("order swapped", (r) => { r.ranked.reverse(); });
  tamper("another campus on top", (r) => { r.ranked[0].facility_id = "E"; });
  tamper("a campus added", (r) => { r.ranked.push(clone(r.ranked[0])); });
  tamper("status changed", (r) => { r.status = "no_match"; });
  tamper("a score changed", (r) => { r.ranked[0].score += 1; });
  ok(!A.matches(care, "dialysis", "east", "routine", real), "an answer from another starting point is not this one's");
  ok(!A.matches(care, "mri", "central", "routine", real), "an answer for another service is not this one's");
  ok(!A.matches(care, "dialysis", "central", "routine", null), "no answer is not an answer");
}

// Positive controls: an untouched copy still passes, and so does every other honest pair.
same(I.finderRequest(copy(), story, none, true), honest, "an untouched copy still passes");
same(I.finderRequest(data, "injury_assessed", none, true), { service: "trauma_care", urgency: "time_sensitive" }, "a time-sensitive honest pair passes");
same(I.finderRequest(data, "incomplete_history", [["context.onset", "recent"]], true), { service: "mri", urgency: "routine" }, "an honest pair after one answer passes");
{
  // A ready answer planted where an emergency belongs is still not a request, because nothing confirmed it.
  const forged = copy();
  forged.assessments[I.key("warning_with_mri_plan", none, false)] = clone(data.assessments[readyKey]);
  same(I.finderRequest(forged, "warning_with_mri_plan", none, false), null, "forged: ready answer without a confirmation");
  same(I.finderRequest(forged, "warning_with_mri_plan", none, true), null, "forged: confirming a state that has no confirmed form");
  forged.assessments[I.key("warning_with_mri_plan", none, true)] = clone(data.assessments[readyKey]);
  same(I.finderRequest(forged, "warning_with_mri_plan", none, true), null, "forged: a ready pair planted on the emergency story");
  // Nor does a story with no clinician reach a campus by borrowing a pair.
  const borrowed = copy(), bleeding = [["warning.heavy_bleeding", "no"]];
  borrowed.assessments[I.key("injury_unassessed", bleeding, false)] = clone(data.assessments[I.key("injury_assessed", none, false)]);
  borrowed.assessments[I.key("injury_unassessed", bleeding, true)] = clone(data.assessments[I.key("injury_assessed", none, true)]);
  same(I.finderRequest(borrowed, "injury_unassessed", bleeding, true), null, "forged: an assessed story's pair planted on the unassessed one");
}
same(I.view(data, "nobody", none, false), null, "an unknown story shows nothing");
same(I.view(data, story, [["context.onset", "maybe"]], false), null, "an answer the engine was never asked about shows nothing");
same(I.view(data, "__proto__", none, false), null, "a property name is not a story");

console.log(`ok ${checks} checks`);
