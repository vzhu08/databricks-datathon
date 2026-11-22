/*
 * Drives finder.html in headless Chromium through its two entry points, a response file and a
 * search, with a stand-in transport. No network and no provider. Run by test_finder_ui.py when
 * Playwright is installed.
 */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { chromium } = require("playwright");

const page = path.resolve(__dirname, "..", "..", "app", "storm_ui", "finder.html");
const sandbox = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(path.dirname(page), "data", "finder_examples.js"), "utf8"), sandbox);
const valid = JSON.parse(JSON.stringify(sandbox.window.FINDER_EXAMPLES.examples.find((e) => e.key === "partial").response));
const badRow = JSON.parse(JSON.stringify(valid));
badRow.routing.results[1].outcome = "fine";

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "finder-check-"));
  const file = (name, value) => { const target = path.join(dir, name); fs.writeFileSync(target, JSON.stringify(value)); return target; };
  const browser = await chromium.launch();
  let checks = 0;
  try {
    const p = await browser.newPage();
    const pageErrors = [];
    p.on("pageerror", (error) => pageErrors.push(error.message));
    await p.addInitScript(() => {
      window.calls = 0;
      window.answers = [];
      window.FINDER_TRANSPORT = () => { window.calls += 1; const answer = window.answers.shift();
        return answer && answer.fail ? Promise.reject(new Error("down")) : Promise.resolve(answer ? answer.value : null); };
    });
    await p.goto("file://" + page);
    const title = () => p.textContent("#state-title");
    const error = async () => (await p.isHidden("#file-error")) ? "" : p.textContent("#file-error");
    const check = (condition, message) => { assert.ok(condition, message); checks += 1; };
    const open = async (target) => { await p.setInputFiles("#file", target); await p.waitForTimeout(150); };
    const search = async (answer) => {
      await p.evaluate((a) => { window.answers.push(a); }, answer);
      await p.click("#search");
      await p.waitForFunction(() => document.getElementById("search").textContent === "Search driving times");
    };
    const before = await title();
    check((await p.evaluate(() => window.calls)) === 0, "loading the page makes no call");

    // File path: null, a non-object, a malformed row, then a valid response.
    for (const [name, value] of [["null.json", null], ["number.json", 7], ["bad-row.json", badRow]]) {
      await open(file(name, value));
      check((await error()).startsWith("This response can't be shown."), name + ": the failure is reported");
      check((await error()).includes("The response that was open is still shown."), name + ": the report says the open view is kept");
      check((await title()) === before, name + ": the prior view is preserved");
      check((await p.inputValue("#example")) === "timed" && !(await p.isDisabled("#search")), name + ": the example is still selected and searchable");
    }
    await open(file("valid.json", valid));
    check((await error()) === "" && (await title()) !== before, "a valid file is shown after the failures");
    check((await p.textContent("#synthetic-note")).includes("provenance is unknown"), "an opened file is labelled unknown provenance");
    check(await p.isDisabled("#search"), "Search is disabled for a response-only file");

    // Search path: null, a malformed row and a failure, each followed by nothing changing, then success.
    await p.selectOption("#example", "timed");
    for (const [name, answer] of [["null answer", { value: null }], ["malformed row", { value: badRow }], ["failed call", { fail: true }]]) {
      await search(answer);
      check((await error()) !== "", name + ": the failure is reported");
      check((await title()) === before, name + ": the prior view is preserved");
      check(!(await p.isDisabled("#search")), name + ": the Search control is released");
      check((await p.textContent("#synthetic-note")).startsWith("Example response."), name + ": the source label is unchanged");
    }
    await search({ value: valid });
    check((await error()) === "" && (await title()) !== before, "a valid answer is shown after the failures");
    check((await p.textContent("#synthetic-note")) === "Response to the search made from this page.", "a search answer is labelled as such");
    check((await p.textContent("#source-body")).includes("Public display of provider results is not cleared"), "public display stays gated");
    check((await p.evaluate(() => window.calls)) === 4, "four presses made four calls and nothing else called the transport");
    check(pageErrors.length === 0, "no page errors: " + pageErrors.join("; "));
    console.log("ok " + checks + " browser checks");
  } finally {
    await browser.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
})().catch((error) => { console.error(error.message); process.exit(1); });
