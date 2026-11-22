/* Walks the intake in a browser: successful, blocked and escalated stories, edits, keyboard, phone, no network. Needs Playwright. */
"use strict";
const assert = require("node:assert");
const path = require("node:path");
const { chromium } = require("playwright");

const page = (name) => "file://" + path.resolve(__dirname, "..", "..", "app", "storm_ui", name);
let checks = 0;
const ok = (value, message) => { checks += 1; assert.ok(value, message); };
const same = (actual, expected, message) => { checks += 1; assert.deepStrictEqual(actual, expected, message); };

const CONFIRM = "Check the care summary against the story, then confirm it.";
const READY = "The summary is confirmed. Choose a fictional starting point to find a campus.";
const MORE = "More information is needed before this scenario can continue.";

(async () => {
  const browser = await chromium.launch();
  const errors = [], requests = [];
  const context = await browser.newContext({ viewport: { width: 1366, height: 860 } });
  context.on("request", (request) => { if (!request.url().startsWith("file://")) requests.push(request.url()); });
  const p = await context.newPage();
  p.on("pageerror", (error) => errors.push(error.message));
  await p.goto(page("index.html"));

  const answer = (id) => p.click(`#answer-buttons [data-answer=${id}]`);
  const story = (id) => p.check(`input[name=scenario][value=${id}]`);
  const headline = async () => ((await p.textContent("#outcome-headline")) + " " + (await p.textContent("#outcome-body"))).trim();
  const session = () => p.evaluate(() => window.IntakePage.state());
  const noCampus = async () => (await p.isHidden("#result")) && (await p.isHidden("#outcome-find")) && (await p.evaluate(() => window.AskPage.shown())) === null;
  const summary = () => p.locator("#outcome-summary dd").allTextContents();

  // First view: a story whose care is already planned waits for a confirmation, and nothing more.
  ok(await p.isVisible("#intake") && await p.isHidden("#ask"), "the page opens on the intake");
  same(await p.locator("input[name=scenario]").count(), 7, "seven fictional stories are offered");
  ok(/made-up patient/.test(await p.textContent("#intake")) && /invented/.test(await p.textContent(".synthetic-note")), "the page says the patients are invented");
  same(await session(), { scenario: "scheduled_dialysis", answers: [], confirmed: false }, "it starts on the first story with nothing confirmed");
  ok(/fictional adult/.test(await p.textContent("#story-text")), "the story is the story edition's own text");
  same(await p.textContent("#story-known"), "Already in this story. Simulated treatment plan: Dialysis, routine urgency.", "the story says what a clinician has already planned");
  same(await p.locator("#story-facts li").count(), 9, "the facts the story already states are listed");
  ok(/New chest pain: No/.test(await p.textContent("#story-facts")), "each fact is a question's label and the story's answer");
  same(await headline(), CONFIRM, "a planned story leads to a summary to confirm");
  same(await summary(), ["Dialysis", "Routine", "Simulated treatment plan, in the story"], "the summary states the care, the urgency and who asked for it");
  ok(await p.isHidden("#questions") && await p.isVisible("#confirm") && await noCampus(), "before confirming, no campus can be looked for");
  ok(await p.isVisible('.steps a[href="replay.html"]') && await p.isVisible("label:has(#mode-direct)"), "the stress test and the direct finder stay one press away");
  ok(/NIDDK/.test(await p.textContent("#outcome-sources")) && /No clinician has validated/.test(await p.textContent("#outcome-limits")), "the rule's reference and the demonstration's limit are shown");

  // A successful journey: scheduled dialysis.
  await p.click("#confirm");
  same(await headline(), READY, "confirming is acknowledged");
  ok(await p.isVisible("#intake-find") && await p.isHidden("#confirm") && await p.isHidden("#result"), "after confirming, the starting point is asked for");
  ok(/Nobody has confirmed a free place/.test(await p.textContent("#outcome-limits")), "a ready summary says no place is confirmed");
  await p.click("#intake-find");
  same(await p.textContent("#headline"), "Send the patient to Campus B.", "a confirmed request reaches the existing answer");
  same(await p.textContent("#request-line"), "Dialysis from the central point. Urgency: routine.", "the answer is for the care and urgency from the summary");

  // Changing the starting point never leaves an old campus on screen.
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
  same(await headline(), CONFIRM, "and the summary waits to be confirmed again");

  // Another story starts clean, with the question its story leaves open.
  await p.click("#confirm"); await p.click("#intake-find");
  await story("scheduled_mri");
  same(await session(), { scenario: "scheduled_mri", answers: [], confirmed: false }, "choosing another story starts from no answers");
  ok(await p.isHidden("#outcome") && await noCampus(), "and removes the earlier story's campus");
  same(await p.textContent("#question-text"), "Question 1. How does the story describe the concern?", "the open question is the catalogue's own");
  same(await p.locator("#answer-buttons button").allTextContents(), ["Mild", "Moderate", "Severe", "Not sure"], "with the catalogue's own choices");
  await answer("mild");
  same(await summary(), ["MRI scan", "Routine", "Simulated clinician referral, in the story"], "a complete history leads to the referral's summary");
  ok(await p.isVisible("#confirm") && await noCampus(), "which still has to be confirmed");
  await p.click("#confirm"); await p.selectOption("#intake-place", "central"); await p.click("#intake-find");
  same(await p.textContent("#request-line"), "MRI scan from the central point. Urgency: routine.", "the finder gets the referral's care");

  // Editing an answer withdraws the confirmation and the campus, even when the same answer comes back.
  await p.click("#answered li:nth-child(1) button");
  same(await session(), { scenario: "scheduled_mri", answers: [], confirmed: false }, "changing an answer drops it and the confirmation");
  ok(await p.isHidden("#outcome") && await noCampus(), "the earlier campus is taken off the page");
  await answer("mild");
  ok(await headline() === CONFIRM && await p.isVisible("#confirm") && await noCampus(), "the same answer again still needs a fresh confirmation");
  await p.click("#confirm");
  await p.click("#answered li:nth-child(1) button"); await answer("moderate");
  ok(await headline() === CONFIRM && (await session()).confirmed === false && await noCampus(), "another answer is not covered by the earlier confirmation");

  // Blocked: not sure is not an answer.
  await p.click("#answered li:nth-child(1) button"); await answer("unknown");
  same(await headline(), MORE, "an unsure answer stops the journey");
  ok(/Not known: Reported severity\./.test(await p.textContent("#outcome-limits")) && await p.isHidden("#confirm") && await p.isHidden("#outcome-summary") && await noCampus(), "the unsure answer is named and nothing can be confirmed");

  // The unassessed injury: a warning sign escalates, no warning sign still needs a clinician.
  await story("injury_unassessed");
  same(await p.textContent("#story-known"), "In this story no clinician has asked for a service.", "the story has no clinician's plan");
  same(await p.textContent("#question-text"), "Question 1. Does the story report heavy bleeding now?", "the story leaves one warning question open");
  await answer("yes");
  ok(/call 112/.test(await headline()) && /Hospital search stops here/.test(await headline()), "a warning sign shows the emergency message");
  same(await p.getAttribute("#outcome", "data-kind"), "emergency", "and marks it as an emergency");
  ok(await p.isHidden("#question") && await p.isHidden("#confirm") && await noCampus(), "no further question, no confirmation and no campus");
  ok(/The case reports heavy bleeding now\./.test(await p.textContent("#outcome-why")), "the reason is the warning rule's own");
  ok(/112|ERSS/.test(await p.textContent("#outcome-sources")), "the emergency number's reference is listed");
  await p.click("#answered li:nth-child(1) button"); await answer("unknown");
  ok(/missing, uncertain, inconsistent or unreadable/.test(await headline()) && /Not known: Heavy bleeding\./.test(await p.textContent("#outcome-limits")) && await noCampus(), "an unsure warning answer is not read as no");
  await p.click("#answered li:nth-child(1) button"); await answer("no");
  same(await headline(), "The fictional patient needs a clinician's assessment before a campus search.", "symptoms alone lead to an assessment");
  ok(await p.isHidden("#confirm") && await p.isHidden("#outcome-summary") && await noCampus(), "no service is requested and no campus is offered");
  ok(/Injury assessment/.test(await p.textContent("#outcome-concern")) && /not a diagnosis/.test(await p.textContent("#outcome-concern")), "the concern is a category, not a diagnosis");

  // A warning in the story wins over care that is already referred.
  await story("warning_with_mri_plan");
  ok(/Simulated clinician referral: MRI scan/.test(await p.textContent("#story-known")), "the story has an MRI referral");
  ok(/call 112/.test(await headline()) && await p.isHidden("#questions") && await p.isHidden("#confirm") && await p.isHidden("#outcome-summary") && await noCampus(), "the reported chest pain stops the search at once");
  ok(/The fictional case reports new chest pain\./.test(await p.textContent("#outcome-why")), "and says which warning it was");

  // Blocked: outside what the demonstration covers.
  await story("unsupported_concern");
  ok(await headline() === "This fictional case falls outside the care covered by this demonstration." && await p.isHidden("#confirm") && await noCampus(), "care outside the three services is refused, not mapped to one of them");

  // The history question, then the referral.
  await story("incomplete_history");
  same(await p.locator("#answer-buttons button").allTextContents(), ["Started recently", "Ongoing", "Scheduled care", "Not sure"], "the timing question has its own choices");
  await answer("recent");
  ok(await headline() === CONFIRM && await noCampus(), "once the history is complete the referral can be confirmed");

  // The assessed injury reaches trauma care at the urgency the assessment gave.
  await story("injury_assessed");
  same(await summary(), ["Trauma care", "Time-sensitive", "Simulated clinician assessment, in the story"], "the assessed injury asks for trauma care");
  await p.click("#confirm");
  await p.selectOption("#intake-place", "central");
  await p.click("#intake-find");
  same(await p.textContent("#request-line"), "Trauma care from the central point. Urgency: time-sensitive.", "the finder gets the assessed urgency");
  same(await p.textContent("#headline"), "Send the patient to Campus F.", "and names the campus the bridge ranked first");
  await p.selectOption("#intake-place", "east"); await p.click("#intake-find");
  ok(await p.isVisible("#result") && !/^Send the patient to/.test(await p.textContent("#headline")), "from a starting point with no confirmed option, no campus is recommended");

  // A campus answer that is not the one the bridge stored is never shown.
  same(await p.evaluate(() => {
    window.CARE_INTAKE.finder["injury_assessed||confirmed"].central.ranked[0].facility_id = "E";
    document.getElementById("intake-place").value = "central";
    document.getElementById("intake-find").click();
    return [window.AskPage.shown(), document.getElementById("result").hidden];
  }), [null, true], "an altered stored campus answer shows nothing");

  // A refresh keeps no confirmation and no campus.
  await p.reload();
  ok((await session()).confirmed === false && await headline() === CONFIRM && await noCampus(), "after a refresh nothing is confirmed and no campus is shown");

  // Keyboard only: choose a story, answer, confirm and find without a pointer.
  await p.focus("input[name=scenario]:checked"); await p.keyboard.press("ArrowDown");
  same((await session()).scenario, "scheduled_mri", "arrow keys change the story");
  await p.focus("#answer-buttons [data-answer=mild]");
  await p.keyboard.press("Tab");
  same(await p.evaluate(() => document.activeElement.getAttribute("data-answer")), "moderate", "Tab moves between the choices");
  await p.keyboard.press("Enter");
  same(await p.evaluate(() => document.activeElement.id), "confirm", "after the last answer the focus is on Confirm");
  ok((await p.textContent("#announcer")).startsWith("Check the care summary"), "the outcome is announced");
  await p.keyboard.press("Enter");
  same(await p.evaluate(() => document.activeElement.id), "intake-place", "after confirming the focus is on the starting point");
  await p.keyboard.press("Tab"); await p.keyboard.press("Enter");
  ok(/^Send the patient to Campus /.test(await p.textContent("#headline")), "the keyboard reaches a campus");
  await p.focus("input[name=scenario]:checked"); await p.keyboard.press("ArrowDown");
  ok((await session()).scenario === "injury_unassessed" && await noCampus(), "arrow keys change the story and clear the campus");
  await p.focus("#answer-buttons [data-answer=yes]"); await p.keyboard.press("Enter");
  same(await p.evaluate(() => document.activeElement.id), "outcome", "an emergency takes the focus to its message");

  // Phone width.
  const phone = await context.newPage();
  phone.on("pageerror", (error) => errors.push(error.message));
  await phone.setViewportSize({ width: 390, height: 844 });
  await phone.goto(page("index.html"));
  const fits = () => phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  ok(await fits(), "the intake fits a phone");
  await phone.check("input[name=scenario][value=scheduled_mri]");
  ok(await phone.evaluate(() => [...document.querySelectorAll("#answer-buttons button")].every((b) => { const r = b.getBoundingClientRect(); return r.height >= 44 && r.width >= 44; })), "answer buttons are large enough to tap");
  await phone.click("#answer-buttons [data-answer=severe]");
  ok(await fits() && await phone.evaluate(() => document.getElementById("outcome").getBoundingClientRect().top < window.innerHeight), "the outcome is brought into view on a phone");
  await phone.click("#confirm"); await phone.click("#intake-find");
  ok(await fits() && await phone.isVisible("#slip"), "the campus answer fits a phone");
  await phone.check("input[name=scenario][value=warning_with_mri_plan]");
  ok(await fits() && /call 112/.test(await phone.textContent("#outcome-body")), "the emergency message fits a phone");

  same(requests, [], "the page asked the network for nothing");
  same(errors, [], "no script errors");
  await browser.close();
  console.log(`ok ${checks} browser checks`);
})().catch((error) => { console.error(error); process.exit(1); });
