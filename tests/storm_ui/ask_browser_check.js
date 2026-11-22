/* Walks the path a judge takes: ask, read the recommendation, open the stress test. Needs Playwright. */
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

  ok(await p.isVisible("#empty") && await p.isHidden("#result"), "nothing is recommended before a question is asked");
  same(await p.getAttribute("#step-ask", "aria-current"), "step", "the first step is marked current");
  same(await p.locator("#ask input[type=radio]").count(), 6, "three kinds of care and three urgencies are offered");
  same(await p.locator("#place option").count(), 4, "four starting points are offered");

  await p.click("#find");
  same(await p.textContent("#headline"), "Send the patient to Campus B.", "the default request is answered with one campus");
  same(await p.textContent("#trip"), "About 12 minutes by road.", "the travel time is stated in a sentence");
  ok((await p.textContent("#record-text")).length > 10 && /dated 28 October 2026/.test(await p.textContent("#record-meta")), "the record text and its date are cited");
  ok(/Phone Campus B before the patient travels/.test(await p.textContent("#caveat-text")), "the availability caveat is on the slip");
  same(await p.locator("#backup-list li").count(), 2, "two backups are listed");
  same(await p.locator("#how-table tbody tr").count(), 3, "the points table has one row per shown campus");
  ok(/Campus E/.test(await p.textContent("#leftout-list")), "the unconfirmed campus is listed with its reason");
  same(await p.getAttribute("#step-answer", "aria-current"), "step", "the second step is marked current after an answer");
  same(await p.evaluate(() => document.activeElement.id), "answer", "focus moves to the recommendation");
  ok(!(await p.locator(".technical").getAttribute("open")), "technical details start closed");
  same(JSON.parse(await p.textContent("#raw")).response.ranked[0].facility_id, "B", "technical details hold the unedited response");

  await p.check("input[name=urgency][value=highest]");
  ok(await p.isVisible("#stale"), "changing the request marks the shown answer as out of date");
  await p.click("#find");
  ok(await p.isHidden("#stale"), "asking again clears the notice");
  same(await p.textContent("#headline"), "Send the patient to Campus A.", "the answer changes with urgency");

  await p.click("#examples li:nth-child(3) button");
  ok(/^No campus is confirmed for trauma care/.test(await p.textContent("#headline")), "weak evidence is not presented as a recommendation");
  same([await p.locator("#leads li").count(), await p.isHidden("#how"), await p.isHidden("#caveat")], [2, true, true], "leads are listed without scores");
  same(await p.inputValue("#place"), "central", "an example fills in the form it answers");

  await p.check("input[name=service][value=mri]");
  await p.selectOption("#place", "south");
  await p.click("#find");
  ok(/^No campus with a record for an MRI scan is within 20 minutes/.test(await p.textContent("#headline")), "no match is said plainly");
  same(await p.locator("#leftout-list li").count(), 2, "the campuses beyond the limit are still listed");

  await p.keyboard.press("Tab");
  await p.click("#copy");
  await p.waitForFunction(() => document.getElementById("copy-status").textContent.length > 0);
  ok((await p.textContent("#copy-status")).length > 0, "copying reports what happened");

  const phone = await context.newPage();
  await phone.setViewportSize({ width: 390, height: 844 });
  await phone.goto(page("index.html"));
  await phone.click("#find");
  ok(!(await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), "the page fits a phone without sideways scrolling");

  await p.goto(page("replay.html"));
  ok(/No patient has arrived yet/.test(await p.textContent("#scoreline")), "the stress test starts with nothing revealed");
  await p.click("#skip");
  ok(/^End of the shift: nearest first has placed 7 of 8 patients, urgency-aware 8 of 8\./.test(await p.textContent("#scoreline")), "skipping shows the final result in one sentence");
  ok(/Served only under Urgency-aware: Patient 2\./.test(await p.textContent("#summary-sentence")), "patients are named plainly");
  ok(!/\br0\d\b/.test(await p.textContent("main")), "no raw request id is shown");
  same(await p.getAttribute('.steps a[aria-current]', "href"), "replay.html", "the third step is marked current");
  await p.click('.steps a[href="index.html#ask"]');
  ok(await p.isVisible("#find"), "the steps lead back to the question");

  same(errors, [], "no script errors on either page");
  await browser.close();
  console.log(`ok ${checks} browser checks`);
})().catch((error) => { console.error(error); process.exit(1); });
