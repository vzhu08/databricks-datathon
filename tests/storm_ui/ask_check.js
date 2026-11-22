/* Checks the Find care page's wording against every answer in the generated bundle. Run with Node. */
"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..", "app", "storm_ui");
const A = require(path.join(root, "ask_state.js"));
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(root, "data", "answers.js"), "utf8"), sandbox);
const data = JSON.parse(JSON.stringify(sandbox.window.CARE_ANSWERS));

let checks = 0;
const ok = (value, message) => { checks += 1; assert.ok(value, message); };
const same = (actual, expected, message) => { checks += 1; assert.deepStrictEqual(actual, expected, message); };

same(A.problems(data), [], "the committed bundle can be shown");
ok(A.problems(null).length === 1 && A.problems({}).length > 0, "a missing or empty bundle is reported");
ok(data.synthetic === true, "the bundle is marked synthetic");

const statuses = {};
for (const service of data.services) for (const place of data.places) for (const urgency of data.urgencies) {
  const key = A.key(service.id, place.id, urgency.id);
  const answer = data.answers[key], v = A.view(data, service.id, place.id, urgency.id);
  const ranked = answer.response.ranked;
  statuses[v.status] = (statuses[v.status] || 0) + 1;
  same(v.status, answer.response.status, `${key}: status is the ranker's`);
  // The page never reorders, drops or adds a campus.
  same([v.top].concat(v.backups).filter(Boolean).map((o) => o.facility_id), ranked.map((r) => r.facility_id), `${key}: order is the ranker's`);
  same(v.leads.map((l) => l.facility_id), answer.response.needs_confirmation.map((l) => l.facility_id), `${key}: leads are the ranker's`);
  ok(v.request_line.includes(service.name) && v.request_line.toLowerCase().includes(urgency.name.toLowerCase()), `${key}: the slip restates the request`);
  ok(v.referral.startsWith("Referral note (demonstration, invented data)"), `${key}: the copied note says it is a demonstration`);
  if (v.status === "ok") {
    const row = ranked[0];
    same(v.top.travel, row.travel, `${key}: travel is the ranker's`);
    same(v.top.points.total, Math.round(row.score), `${key}: points are the ranker's score, rounded`);
    for (const option of [v.top].concat(v.backups)) {
      same(option.points.parts.reduce((sum, part) => sum + part.points, 0), option.points.total, `${key}/${option.facility_id}: factor points add up to the total`);
      for (const part of option.points.parts) {
        ok(Math.abs(part.points - option.row.weights[part.factor] * option.row.factors[part.factor]) <= 1, `${key}/${option.facility_id}: ${part.factor} points stay within one of the ranker's value`);
      }
      ok(option.record_text && option.record_date === option.row.source_date, `${key}/${option.facility_id}: the record text and its date are shown`);
    }
    ok(v.why[0].includes(v.top.name), `${key}: the reason names the campus`);
    same(/only campus/.test(v.why[0]), answer.eligible === 1, `${key}: "only campus" is said exactly when one qualifies`);
    const everyone = ranked.concat(answer.left_out.filter((e) => e.kind === "ranked_lower").map((e) => e.row));
    const nearer = everyone.filter((r) => r.travel < row.travel);
    if (answer.eligible > 1) {
      same(/shorter trip \(/.test(v.why.join(" ")), nearer.length > 0, `${key}: a nearer qualifying campus is named exactly when one exists`);
      same(/also the shortest trip/.test(v.why.join(" ")), nearer.length === 0, `${key}: "shortest trip" is claimed only when true`);
    }
    same(Boolean(v.caveat), row.availability === "unknown", `${key}: unknown availability always carries the caveat`);
    ok(v.referral.includes("Send to: " + v.top.name) && (!v.caveat || v.referral.includes("Before travelling")), `${key}: the note carries the answer and its caveat`);
  } else {
    same([v.top, v.backups.length, v.why.length, v.caveat], [null, 0, 0, null], `${key}: no campus is recommended without a ranked option`);
    ok(!/Send to/.test(v.referral), `${key}: the note recommends nothing`);
  }
  for (const entry of v.left_out) ok(entry.why.length > 0 && !/_/.test(entry.why), `${key}/${entry.facility_id}: a plain reason is given for leaving it out`);
}
ok(statuses.ok > 0 && statuses.needs_confirmation > 0 && statuses.no_match > 0, "the demonstration covers an answer, unconfirmed leads and no match");

// The first two examples are the same patient at two urgencies, and the answer changes.
const [first, second, third] = data.examples.map((e) => A.view(data, e.service, e.place, e.urgency));
ok(first.top.facility_id !== second.top.facility_id, "urgency changes the recommended campus in the examples");
ok(/is a shorter trip \(8 minutes\), but its record is older/.test(first.why[1]), "the trade-off is stated: nearer campus, older record");
same(third.status, "needs_confirmation", "the third example shows weak evidence as unconfirmed");
same(A.view(data, "dialysis", "nowhere", "routine"), null, "an unknown request has no answer");
same(A.day("2026-10-28"), "28 October 2026", "dates are written out");
same(A.day("soon"), "an unknown date", "a bad date is not printed as if it were one");

console.log(`ok ${checks} checks`);
