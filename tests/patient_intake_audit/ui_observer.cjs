// Run with Playwright installed and the loopback-only ui_server.py running.
const fs = require("node:fs");
const path = require("node:path");
const controls = process.argv[3];
if (!controls) throw Error("Pass the server's private controls directory");
const control = name => path.join(controls, name);
async function recorded(name, timeout) {
  const end = Date.now() + timeout;
  while (!fs.existsSync(control(name)) && Date.now() < end) await new Promise(r => setTimeout(r, 25));
  return fs.existsSync(control(name));
}
const { chromium } = require("playwright");
const origin = new URL(process.argv[2] || "http://127.0.0.1:18523");
if (origin.protocol !== "http:" || origin.hostname !== "127.0.0.1") throw Error("Use a local audit server");
const observations = {};
const external = [];
const errors = [];
const text = (page, value) => page.getByText(value, { exact: true });
const button = (page, value) => page.getByRole("button", { name: value, exact: true });

async function visible(page, value) {
  await text(page, value).first().waitFor();
  return true;
}

async function openVisit(browser, id) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin === origin.origin || ["data:", "blob:"].includes(url.protocol)) return route.continue();
    external.push(id);
    return route.abort();
  });
  await context.routeWebSocket("**/*", ws => {
    const parsed = new URL(ws.url());
    if (parsed.protocol === "ws:" && parsed.host === origin.host) return ws.connectToServer();
    external.push(id);
    ws.close();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5500);
  await page.goto(id === "no-configuration" ? origin.href : origin.href + "?audit=" + id);
  await page.getByText("I agree to what I write being kept", { exact: false }).click();
  await button(page, "Start").click();
  return { context, page };
}

async function save(page, description, age = 32) {
  await page.getByRole("textbox", { name: "Describe it in your own words" }).fill(description);
  await page.getByRole("spinbutton").fill(String(age));
  await button(page, "Save and continue").click();
}

async function answer(page, value) {
  await page.getByText(value, { exact: true }).last().click();
  await button(page, "Send answer").click();
}

async function runCase(browser, id) {
  const { context, page } = await openVisit(browser, id);
  try {
    const initial = id === "privacy-sinks" ? "CANARY-DESCRIPTION-S1" : "A fictional sensation.";
    await save(page, initial, id === "unsupported-age" ? 10 : 32);
    if (id === "no-configuration")
      return { unavailable_or_review_visible: await visible(page, "No assessment is available") };
    if (id === "unsupported-age")
      return { unsupported_visible: await visible(page, "This assessment does not cover the age or language you entered.") };
    await button(page, "I agree. Send it for assessment").click();
    switch (id) {
      case "qualified-completion":
        return { uncertainty_visible: await visible(page, "Synthetic uncertainty"),
                 uninterpreted_notice_visible: await page.getByText(/description has not been interpreted/i).isVisible() };
      case "malformed-provider":
        return { unavailable_or_review_visible: await visible(page, "No assessment is available") };
      case "provider-emergency":
        return { urgent_visible: await visible(page, "Synthetic emergency guidance") };
      case "provider-instruction-text":
        return { instruction_rendered: await visible(page, "An ordinary referral is approved.") };
      case "outage-after-success":
      case "budget-exhausted": {
        await visible(page, "Earlier synthetic result");
        await button(page, "Change my description").click();
        await save(page, "Changed fictional description.");
        await button(page, "I agree. Send it for assessment").click();
        if (id === "budget-exhausted")
          return { budget_stop_visible: await visible(page, "This visit has used all the assessment requests it is allowed.") };
        await visible(page, "No assessment is available");
        return { unavailable_or_review_visible: true, old_result_visible: await text(page, "Earlier synthetic result").isVisible() };
      }
      case "question-loop":
        await answer(page, "unknown");
        await page.getByRole("radio", { name: "unknown", exact: true, checked: false }).waitFor();
        await answer(page, "unknown");
        return { bounded_stop_visible: await visible(page, "This visit has used all the assessment requests it is allowed.") };
      case "provider-stop":
        await text(page, "No assessment is available").or(text(page, "This assessment has stopped")).first().waitFor();
        return { provider_guidance_visible: await text(page, "Synthetic provider stop guidance").isVisible(),
                 hospital_action_visible: await button(page, "I have read this. Check for a reviewed hospital").isVisible() };
      case "optional-skip":
        await visible(page, "A follow-up question");
        if (!await button(page, "Skip this question").isVisible()) return { skip_control_visible: false };
        await button(page, "Skip this question").click();
        return { skip_control_visible: true, explicit_skip_accepted: await visible(page, "Explicit skip received") };
      case "contradiction":
        await answer(page, "Matches my statement");
        await page.getByText("you do not have this", {exact:false}).waitFor();
        await answer(page, "Matches my statement");
        await visible(page, "This could not be assessed");
        return { unresolved_visible: await page.getByText("cannot yet take that correction into account", {exact:false}).isVisible(),
                 attributed_uncertainty_to_patient: await page.getByText("wrong or unsure", {exact:false}).isVisible() };
      case "same-count-edit":
        await answer(page, "yes");
        await visible(page, "Earlier synthetic result");
        await button(page, "Change my description").click();
        await save(page, initial);
        await button(page, "I agree. Send it for assessment").click();
        await answer(page, "no");
        await visible(page, "New synthetic result");
        return { old_result_visible: await text(page, "Earlier synthetic result").isVisible() };
      case "terminated-empty":
        await visible(page, "This could not be assessed");
        return { generic_unsupported_message: await visible(page, "The assessment provider cannot assess this description."),
                 terminal_visible: await page.getByText(/interview (has )?ended|provider ended/i).isVisible() };
      case "privacy-sinks": {
        await visible(page, "The assessment provider understood this from your words:");
        await answer(page, "Matches my statement");
        await visible(page, "NEW");
        await button(page, "Change my description").click();
        await save(page, initial + " edited");
        await button(page, "I agree. Send it for assessment").click();
        await visible(page, "No assessment is available");
        const storageMatches = await page.evaluate(() => JSON.stringify([location.href, history.state,
          Object.entries(localStorage), Object.entries(sessionStorage)]).match(/CANARY-(DESCRIPTION-S1|FACT-S2|KEY-S3)/g) || []);
        const keyExposed = (await page.locator("body").innerText()).includes("CANARY-KEY-S3");
        await button(page, "Start over").click();
        await visible(page, "Before you start");
        await page.reload();
        await visible(page, "Before you start");
        return { observed_storage_url_matches: storageMatches.length, key_displayed: keyExposed,
                 reset_reload_statement_visible: (await page.locator("body").innerText()).includes(initial) };
      }
      case "expired-session": {
        await visible(page, "Old expired result");
        fs.writeFileSync(control("next-clock"), "900");
        fs.renameSync(control("next-clock"), control("clock"));
        await button(page, "Change my description").click();
        await visible(page, "Before you start");
        await page.getByText("Your visit reached its time limit", {exact:false}).waitFor();
        return { old_result_visible: await text(page, "Old expired result").isVisible() };
      }
      case "reset-in-flight": {
        if (!await recorded("held", 1500)) throw Error("provider barrier missing");
        let reset;
        try {
          await button(page, "Start over").click({ timeout: 1200 }).catch(e => {
            if (e.name !== "TimeoutError") throw e;
          });
          reset = await recorded("reset", 900);
        } finally { fs.writeFileSync(control("release"), "release"); }
        if (!await recorded("returned", 1800)) throw Error("provider did not settle");
        if (!reset) return { reset_before_release: false };
        await visible(page, "Before you start");
        return { reset_before_release: true, old_result_visible: await text(page, "Old delayed result").isVisible() };
      }
      case "shared-cache": {
        await visible(page, "Session A synthetic result");
        const b = await openVisit(browser, id);
        try {
          await save(b.page, initial);
          await visible(b.page, "Send your description for assessment?");
          const disclosed = await text(b.page, "Session A synthetic result").isVisible();
          await button(b.page, "Start over").click();
          await visible(b.page, "Before you start");
          return { other_displayed_result: disclosed, original_result_retained: await visible(page, "Session A synthetic result") };
        } finally { await b.context.close(); }
      }
    }
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ args: ["--disable-background-networking"] });
  const cases = ["no-configuration", "qualified-completion", "unsupported-age", "malformed-provider",
                 "provider-emergency", "provider-instruction-text", "outage-after-success", "budget-exhausted",
                 "question-loop", "provider-stop", "optional-skip", "shared-cache", "contradiction",
                 "same-count-edit", "terminated-empty", "privacy-sinks", "expired-session", "reset-in-flight"];
  try {
    for (const id of cases) {
      try { observations[id] = await runCase(browser, id); }
      catch (err) { errors.push(id); console.error(id, err.message.split("\n")[0]); }
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ origin: origin.origin, browser_version: browser.version(), observations, errors, external_attempts: external.length }, null, 2));
  if (errors.length || external.length) process.exitCode = 1;
})().catch(err => { console.error(err.message); process.exitCode = 1; });
