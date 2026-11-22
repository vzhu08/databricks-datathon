/* Checks every bundled Storm control through the offline browser replay. Needs Playwright. */
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

async function checkReplays() {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE });
  try {
    const context = await browser.newContext({ offline: true });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const replay = path.resolve(__dirname, "..", "..", "app", "storm_ui", "replay.html");
    await page.goto(pathToFileURL(replay).href);

    const bundle = await page.evaluate(() => window.STORM_BUNDLE);
    const views = page.locator("input[name=view]");
    assert.deepEqual(await views.evaluateAll((items) => items.map((input) => input.value)), ["map", "text"]);

    let runs = 0;
    for (const scenario of bundle.scenarios) {
      await page.selectOption("#scenario", scenario);
      for (const cap of bundle.detour_caps) {
        await page.check(`input[name=cap][value="${cap}"]`);
        const key = `${scenario}|${cap}`;
        const expected = bundle.replays[key];
        assert.match(await page.locator("#minute-readout").innerText(), /^Before the shift/, key);
        assert.equal(await page.locator("#summary").isVisible(), false, key);
        assert.equal(await page.locator("#request-table").isVisible(), false, key);
        assert.equal(await page.locator("#file-error").isVisible(), false, key);

        await page.click("#skip");
        assert.equal(await page.locator("#summary").isVisible(), true, key);
        assert.match(await page.locator("#summary-sentence").innerText(), /\S/, key);
        assert.equal(await page.locator("#request-table tbody tr").count(), expected.requests.length, key);
        const totals = ["nearest_first", "scarcity_aware"].map((policy) =>
          `${expected.policies[policy].metrics.assigned} of ${expected.requests.length}`);
        assert.deepEqual(await page.locator("#summary-table tbody tr").first().locator("td").allInnerTexts(),
          totals, key);

        await page.check('input[name=view][value="text"]');
        assert.equal(await page.locator("svg.map").first().isVisible(), false, key);
        assert.equal(await page.locator("#summary").isVisible(), true, key);
        await page.check('input[name=view][value="map"]');
        assert.equal(await page.locator("svg.map").first().isVisible(), true, key);
        runs += 1;
      }
    }
    assert.equal(runs, 24);
    assert.deepEqual(errors, []);
    console.log(`ok ${runs} scenario/cap combinations in both map and text views`);
  } finally {
    await browser.close();
  }
}

checkReplays().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
