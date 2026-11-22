/* Walks the intake in a browser: successful, blocked and escalated patients, edits, keyboard and phone. Needs Playwright. */
"use strict";
const assert = require("node:assert");
const path = require("node:path");
const { chromium } = require("playwright");

const page = (name) => "file://" + path.resolve(__dirname, "..", "..", "app", "storm_ui", name);
let checks = 0;
const ok = (value, message) => { checks += 1; assert.ok(value, message); };
const same = (actual, expected, message) => { checks += 1; assert.deepStrictEqual(actual, expected, message); };

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1366, height: 860 } });
  const p = await context.newPage();
  p.on("pageerror", (error) => errors.push(error.message));
  await p.goto(page("index.html"));

  const answer = async (...answers) => { for (const a of answers) await p.click(`#answer-buttons [data-answer=${a}]`); };
  const patient = (id) => p.check(`input[name=scenario][value=${id}]`);
  const headline = () => p.textContent("#outcome-headline");
  const session = () => p.evaluate(() => window.IntakePage.state());
  const noCampus = async () => (await p.isHidden("#result")) && (await p.isHidden("#outcome-find")) && (await p.evaluate(() => window.AskPage.shown())) === null;

  // First view.
  ok(await p.isVisible("#intake") && await p.isHidden("#ask"), "the page opens on the intake");
  same(await p.locator("input[name=scenario]").count(), 7, "seven fictional patients are offered");
  ok(/made-up patient/.test(await p.textContent("#intake")) && /invented/.test(await p.textContent(".synthetic-note")), "the page says the patients are invented");
  ok(/^Question 1 of 5\./.test(await p.textContent("#question-text")), "the first question is in view");
  ok(await p.isHidden("#outcome") && await noCampus(), "nothing is concluded and no campus is offered before any answer");
  ok(/treatment plan asks for dialysis/.test(await p.textContent("#story-known")), "the story says what a clinician has already decided");
  ok(await p.isVisible('.steps a[href="replay.html"]') && await p.isVisible("label:has(#mode-direct)"), "the stress test and the direct finder stay one press away");

  // A successful journey: booked dialysis.
  await answer("no", "no", "no", "no");
  ok(await p.isHidden("#outcome") && /^Question 5 of 5\./.test(await p.textContent("#question-text")), "the questions are asked one at a time");
  await answer("yes");
  same(await headline(), "Check this summary, then confirm it.", "complete answers lead to a summary to confirm");
  same(await p.locator("#outcome-summary dd").allTextContents(), ["Dialysis", "Routine", "A clinician’s treatment plan, in the story"], "the summary states the care, the urgency and who asked for it");
  ok(await p.isVisible("#confirm") && await noCampus(), "before confirming, no campus can be looked for");
  await p.click("#confirm");
  same(await headline(), "Summary confirmed.", "confirming is acknowledged");
  ok(await p.isVisible("#intake-find") && await p.isHidden("#confirm") && await p.isHidden("#result"), "after confirming, the starting point is asked for");
  await p.click("#intake-find");
  same(await p.textContent("#headline"), "Send the patient to Campus B.", "a confirmed request reaches the existing answer");
  same(await p.textContent("#request-line"), "Dialysis from the central point. Urgency: routine.", "the answer is for the care and urgency from the summary");

  // Editing an answer withdraws the confirmation and the campus.
  await p.click("#answered li:nth-child(3) button");
  same(await session(), { scenario: "dialysis-plan", answers: ["no", "no"], confirmed: false }, "changing an answer drops it, the later ones and the confirmation");
  ok(await p.isHidden("#outcome") && await noCampus(), "the earlier campus is taken off the page");
  await answer("no", "no", "yes");
  ok(await headline() === "Check this summary, then confirm it." && await noCampus(), "the same answers again still need a fresh confirmation");

  // Changing the starting point never leaves an old campus on screen.
  await p.click("#confirm"); await p.click("#intake-find");
  await p.selectOption("#intake-place", "west");
  ok(await p.isHidden("#result") && await p.isHidden("#stale"), "changing the starting point removes the earlier campus");
  await p.click("#intake-find");
  same(await p.textContent("#headline"), "Send the patient to Campus F.", "asking again answers for the new starting point");

  // Changing mode clears both ways.
  await p.click("label:has(#mode-direct)");
  ok(await p.isVisible("#ask") && await p.isHidden("#intake") && await p.isHidden("#intake-work") && await p.isHidden("#outcome") && await p.isHidden("#result") && await p.isVisible("#empty"), "the direct finder opens empty");
  await p.click("#find");
  same([await p.inputValue("#place"), await p.textContent("#headline")], ["west", "Send the patient to Campus F."], "the direct finder still answers, for the request its own form shows");
  await p.click("label:has(#mode-intake)");
  ok(await p.isHidden("#result") && await p.isHidden("#empty") && (await session()).confirmed === false, "going back to the intake removes that answer and the earlier confirmation");
  same(await headline(), "Check this summary, then confirm it.", "and the summary waits to be confirmed again");

  // Another patient starts clean.
  await p.click("#confirm"); await p.click("#intake-find");
  await patient("stroke-signs-mri");
  same(await session(), { scenario: "stroke-signs-mri", answers: [], confirmed: false }, "choosing another patient starts from no answers");
  ok(await p.isHidden("#outcome") && await noCampus(), "and removes the earlier patient's campus");

  // Escalation: a warning sign ends the questions, even with care already booked.
  await answer("no", "yes");
  ok(/Call 112 now/.test(await headline()), "a warning sign shows the emergency message");
  same(await p.getAttribute("#outcome", "data-kind"), "emergency", "and marks it as an emergency");
  ok(await p.isHidden("#question") && await p.isHidden("#confirm") && await noCampus(), "no further question, no confirmation and no campus");
  ok(/already booked in the story does not change this/.test(await p.textContent("#outcome-why")), "the booked scan does not override the warning");
  ok(/not a diagnosis/i.test(await p.textContent("#outcome-concern")) && /placeholders/.test(await p.textContent("#outcome-limits")), "it is labelled a concern, not a diagnosis, with placeholder rules");
  await patient("dialysis-plan"); await answer("yes");
  ok(/Call 112 now/.test(await headline()) && (await session()).answers.length === 1 && await noCampus(), "the first yes is enough: later questions are not required first");

  // Blocked: not sure is not no.
  await p.click("#answered li:nth-child(1) button");
  await answer("unknown", "no", "no", "no");
  same(await headline(), "A safety question has no clear answer.", "an unsure safety answer stops the journey");
  ok(/Not sure: New chest pain or pressure\./.test(await p.textContent("#outcome-limits")) && await p.isHidden("#confirm") && await noCampus(), "the unsure answer is named and nothing can be confirmed");

  // Blocked: nobody has assessed the patient.
  for (const id of ["injury-unassessed", "kidney-symptoms"]) {
    await patient(id); await p.click("#story-answers");
    same(await headline(), "A clinician needs to assess the patient first.", `${id}: symptoms alone lead to an assessment`);
    ok(await p.isHidden("#confirm") && await p.isHidden("#outcome-summary") && await noCampus(), `${id}: no service is requested and no campus is offered`);
  }
  ok(/Kidney-related symptoms that nobody has assessed/.test(await p.textContent("#outcome-concern")), "the concern is a category");

  // Blocked: outside what the demonstration covers.
  await patient("heart-check"); await p.click("#story-answers");
  ok(await headline() === "This demonstration cannot route that kind of care." && await noCampus(), "care with no campuses is refused, not mapped to another service");
  await p.click("#answered li:nth-child(5) button"); await answer("no");
  ok(await headline() === "This demonstration does not cover this patient." && await noCampus(), "a child or pregnant patient is out of scope");

  // The assessed injury reaches trauma care at the urgency the nurse asked for.
  await patient("injury-assessed"); await p.click("#story-answers");
  same(await p.locator("#outcome-summary dd").allTextContents(), ["Trauma care", "Time-sensitive", "A nurse’s assessment, in the story"], "the assessed injury asks for trauma care");
  await p.click("#confirm");
  await p.selectOption("#intake-place", "central");
  await p.click("#intake-find");
  same(await p.textContent("#request-line"), "Trauma care from the central point. Urgency: time-sensitive.", "the finder gets the assessed urgency");
  ok(/^Send the patient to Campus /.test(await p.textContent("#headline")), "and names a campus");

  // A refresh keeps no confirmation and no campus.
  await p.reload();
  ok((await session()).confirmed === false && await p.isHidden("#outcome") && await noCampus(), "after a refresh nothing is confirmed and no campus is shown");

  // Keyboard only: answer, confirm and find without a pointer.
  await p.focus("#answer-buttons [data-answer=yes]");
  for (let i = 0; i < 4; i += 1) {
    await p.keyboard.press("Tab");
    same(await p.evaluate(() => document.activeElement.getAttribute("data-answer")), "no", `question ${i + 1}: Tab reaches No`);
    await p.keyboard.press("Enter");
    same(await p.evaluate(() => document.activeElement.getAttribute("data-answer")), "yes", `question ${i + 1}: focus moves to the next question`);
  }
  await p.keyboard.press("Enter");
  same(await p.evaluate(() => document.activeElement.id), "confirm", "after the last answer the focus is on Confirm");
  ok((await p.textContent("#announcer")).startsWith("Check this summary"), "the outcome is announced");
  await p.keyboard.press("Enter");
  same(await p.evaluate(() => document.activeElement.id), "intake-place", "after confirming the focus is on the starting point");
  await p.keyboard.press("Tab"); await p.keyboard.press("Enter");
  same(await p.textContent("#headline"), "Send the patient to Campus B.", "the keyboard reaches a campus");
  await p.focus("input[name=scenario]:checked"); await p.keyboard.press("ArrowDown");
  ok((await session()).scenario === "mri-referral" && await noCampus(), "arrow keys change the patient and clear the campus");

  // Phone width.
  const phone = await context.newPage();
  phone.on("pageerror", (error) => errors.push(error.message));
  await phone.setViewportSize({ width: 390, height: 844 });
  await phone.goto(page("index.html"));
  const fits = () => phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  ok(await fits(), "the intake fits a phone");
  await phone.click("#answer-buttons [data-answer=no]");
  ok(await phone.evaluate(() => { const r = document.querySelector("#answer-buttons button").getBoundingClientRect(); return r.height >= 44 && r.width >= 44; }), "answer buttons are large enough to tap");
  await phone.click("#story-answers");
  ok(await fits() && await phone.evaluate(() => document.getElementById("outcome").getBoundingClientRect().top < window.innerHeight), "the outcome is brought into view on a phone");
  await phone.click("#confirm"); await phone.click("#intake-find");
  ok(await fits() && await phone.isVisible("#slip"), "the campus answer fits a phone");
  await phone.check("input[name=scenario][value=stroke-signs-mri]"); await phone.click("#story-answers");
  ok(await fits() && /Call 112 now/.test(await phone.textContent("#outcome-headline")), "the emergency message fits a phone");

  same(errors, [], "no script errors");
  await browser.close();
  console.log(`ok ${checks} browser checks`);
})().catch((error) => { console.error(error); process.exit(1); });
