/* Checks the intake wording and the finder gate against every stored state. Run with Node. */
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..", "app", "storm_ui");
const I = require(path.join(root, "intake_state.js"));
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "data", "intake.js"), "utf8"), sandbox);
const data = JSON.parse(JSON.stringify(sandbox.window.CARE_INTAKE));
const copy = () => JSON.parse(JSON.stringify(data));

let checks = 0;
const ok = (value, message) => { checks += 1; assert.ok(value, message); };
const same = (actual, expected, message) => { checks += 1; assert.deepStrictEqual(actual, expected, message); };

same(I.problems(data), [], "the committed bundle can be shown");
ok(I.problems(null).length === 1 && I.problems({}).length > 0, "a missing or empty bundle is reported");
ok(I.problems(Object.assign(copy(), { synthetic: false })).length > 0, "a bundle not marked synthetic is refused");

const kinds = {};
for (const name of Object.keys(data.assessments)) {
  const [scenarioId, joined, flag] = name.split("|");
  const answers = joined ? joined.split(",") : [];
  const confirmed = flag === "confirmed";
  const stored = data.assessments[name];
  const v = I.view(data, scenarioId, answers, confirmed);
  ok(v, `${name}: the page can show it`);
  kinds[v.kind] = (kinds[v.kind] || 0) + 1;
  same(v.state, stored.state, `${name}: the state is the stored one`);
  ok(v.headline.length > 10 && v.body.length > 10, `${name}: it has a headline and a sentence under it`);
  same(v.answered.length, answers.length, `${name}: every answer so far is listed`);
  same(v.next ? v.next.id : null, stored.next_question_id, `${name}: the next question is the stored one`);
  same(v.reasons.length, stored.reason_ids.length, `${name}: every reason has wording`);
  same(v.limits.length, stored.limit_ids.length, `${name}: every limit has wording`);
  same(v.concerns.length, stored.concerns.length, `${name}: every concern has wording`);
  same(v.unknown.length, answers.filter((a) => a === "unknown").length, `${name}: every unsure answer is named`);
  // The finder gate: a request exists only for a confirmed, ready state.
  const request = I.finderRequest(data, scenarioId, answers, confirmed);
  same(Boolean(request), stored.state === "ready", `${name}: only a ready state may ask for a campus`);
  same(Boolean(v.request), stored.state === "ready", `${name}: the view agrees`);
  same(v.canConfirm, stored.state === "awaiting_confirmation", `${name}: Confirm is offered only when a summary waits for it`);
  if (v.kind === "emergency") ok(/112/.test(v.headline) && !v.summary && !v.next, `${name}: an emergency names 112 and asks nothing more`);
  if (request) same(request, { service: stored.request.service, urgency: stored.request.urgency }, `${name}: the request is the stored one`);
}
same(Object.keys(kinds).sort(), ["confirm", "emergency", "progress", "ready", "stop"], "every kind of outcome occurs");

/* A stored state that only says it is ready is not enough. Each forgery below must be refused. */
const done = ["no", "no", "no", "no", "yes"];
const readyKey = I.key("dialysis-plan", done, true), waitKey = I.key("dialysis-plan", done, false);
same(I.finderRequest(data, "dialysis-plan", done, true), { service: "dialysis", urgency: "routine" }, "the honest state passes");
same(I.finderRequest(data, "dialysis-plan", done, false), null, "an unconfirmed summary asks for nothing");
const forge = (label, change) => {
  const forged = copy();
  change(forged.assessments, forged);
  same(I.finderRequest(forged, "dialysis-plan", done, true), null, `forged: ${label}`);
  const v = I.view(forged, "dialysis-plan", done, true);
  ok(!v || !v.request, `forged: ${label} (view)`);
};
forge("confirmation missing", (a) => { a[readyKey].confirmation.present = false; });
forge("confirmation for other answers", (a) => { a[readyKey].confirmation.bound_to = "000000000000"; });
forge("revision differs from the unconfirmed state", (a) => { a[readyKey].input_revision = a[readyKey].confirmation.bound_to = "111111111111"; });
forge("state is not ready", (a) => { a[readyKey].state = "awaiting_confirmation"; });
forge("an unsure answer remains", (a) => { a[readyKey].unknown_question_ids = ["danger.breathing"]; });
forge("a question is still open", (a) => { a[readyKey].next_question_id = "danger.breathing"; });
forge("service the finder does not have", (a) => { a[readyKey].request.service = "cardiology_review"; });
forge("service differs from the clinician's", (a) => { a[readyKey].request.service = "mri"; });
forge("urgency differs from the clinician's", (a) => { a[readyKey].request.urgency = "highest"; });
forge("an invented capability", (a) => { a[readyKey].request.required_capabilities = ["contrast"]; });
forge("no clinician in the story", (a) => { a[readyKey].clinician = null; });
forge("not marked synthetic", (a) => { a[readyKey].synthetic = false; });
forge("no unconfirmed state to compare with", (a) => { delete a[waitKey]; });
{
  // A ready payload planted where an emergency belongs is still not a request, because nothing confirmed it.
  const forged = copy();
  forged.assessments[I.key("stroke-signs-mri", ["no", "yes"], false)] = JSON.parse(JSON.stringify(data.assessments[readyKey]));
  same(I.finderRequest(forged, "stroke-signs-mri", ["no", "yes"], false), null, "forged: ready payload without a confirmation");
  same(I.finderRequest(forged, "stroke-signs-mri", ["no", "yes"], true), null, "forged: confirming a state that has no confirmed form");
}
same(I.view(data, "nobody", [], false), null, "an unknown patient shows nothing");
same(I.view(data, "dialysis-plan", ["no", "maybe"], false), null, "an answer outside yes, no and not sure shows nothing");

console.log(`ok ${checks} checks`);
