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
  // The page opens on the intake. The finder this file checks is one press away.
  const direct = (tab) => tab.click("label:has(#mode-direct)");
  ok(await p.isHidden("#ask") && await p.isVisible("#intake"), "the page opens on the intake, with the finder form put away");
  await direct(p);

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

  // Exports follow the request on screen: an out-of-date answer can be neither copied nor printed.
  const spy = () => p.evaluate(() => {
    window.__copied = []; window.__prints = 0;
    Object.defineProperty(navigator, "clipboard", { configurable: true,
      value: { writeText: (text) => { window.__copied.push(text); return Promise.resolve(); } } });
    document.execCommand = () => { window.__copied.push("fallback"); return true; };
    window.print = () => { window.__prints += 1; };
  });
  const exported = () => p.evaluate(() => ({ copied: window.__copied.slice(), prints: window.__prints }));
  const press = (id) => p.evaluate((name) => { const b = document.getElementById(name); b.click(); b.dispatchEvent(new MouseEvent("click", { bubbles: true })); }, id);
  const onPaper = async () => { await p.emulateMedia({ media: "print" }); const seen = [await p.isVisible("#slip"), await p.isVisible("#stale")]; await p.emulateMedia({ media: "screen" }); return seen; };
  await spy();
  await p.click("#examples li:nth-child(1) button");
  await p.click("#copy"); await p.click("#print");
  let out = await exported();
  ok(out.copied.length === 1 && out.copied[0].includes("Send to: Campus B") && out.prints === 1, "a current answer is copied and printed");
  same(await onPaper(), [true, false], "a current answer prints its slip");

  await p.check("input[name=urgency][value=highest]");
  same([await p.isDisabled("#copy"), await p.isDisabled("#print")], [true, true], "Copy and Print are off after the request changes");
  await press("copy"); await press("print");
  out = await exported();
  same([out.copied.length, out.prints], [1, 1], "an out-of-date answer is not copied or printed, even by a forced click");
  same(await onPaper(), [false, true], "the browser's own print shows the notice, not the old slip");

  await p.check("input[name=urgency][value=routine]");
  same([await p.isDisabled("#copy"), await p.isDisabled("#print"), await p.isHidden("#stale")], [false, false, true], "switching back makes the answer current again");
  await p.click("#copy"); await p.click("#print");
  out = await exported();
  ok(out.copied.length === 2 && out.copied[1].includes("Send to: Campus B") && out.prints === 2, "after switching back the same answer is exported");
  same(await onPaper(), [true, false], "after switching back the slip prints again");

  await p.selectOption("#place", "west");
  same(await p.isDisabled("#copy"), true, "changing the starting point also turns exports off");
  await p.click("#find");
  await p.click("#copy"); await p.click("#print");
  out = await exported();
  ok(out.copied.length === 3 && out.copied[2].includes("From: West point") && out.copied[2].includes("Send to: Campus F") && out.prints === 3, "after asking again the new answer is exported");

  await p.check("input[name=urgency][value=highest]");
  await p.reload();
  await spy();
  await direct(p);
  same([await p.isHidden("#result"), await p.isVisible("#copy"), await p.isVisible("#print")], [true, false, false], "after a refresh no answer and no export control is shown");
  same((await onPaper())[0], false, "after a refresh nothing is on the slip to print");
  await press("copy"); await press("print");
  out = await exported();
  same([out.copied.length, out.prints], [0, 0], "after a refresh there is nothing to copy or print");
  await p.click("#find");
  const asked = await p.evaluate(() => ({ service: document.querySelector("input[name=service]:checked").value,
    place: document.getElementById("place").value, urgency: document.querySelector("input[name=urgency]:checked").value }));
  const now = await p.evaluate(() => { const v = window.AskPage.shown(); return { service: v.service, place: v.place, urgency: v.urgency }; });
  same(now, asked, "after a refresh the next answer is for the form as it stands");
  await p.click("#copy");
  out = await exported();
  ok(out.copied.length === 1 && out.copied[0] === await p.evaluate(() => window.AskPage.shown().referral), "and that answer is what gets copied");

  const phone = await context.newPage();
  await phone.setViewportSize({ width: 390, height: 844 });
  await phone.goto(page("index.html"));
  await direct(phone);
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
  await direct(p);
  ok(await p.isVisible("#find"), "the steps lead back to the question");

  same(errors, [], "no script errors on either page");
  await browser.close();
  console.log(`ok ${checks} browser checks`);
})().catch((error) => { console.error(error); process.exit(1); });
