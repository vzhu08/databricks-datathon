/* Seeded browser replay of every screen's inputs (#379). Invented text only, loopback only.

   Start the app locally with no provider, warehouse or traffic settings, then run:
     node tests/input_stress/browser_check.js http://127.0.0.1:8501 1280
     node tests/input_stress/browser_check.js http://127.0.0.1:8501 390
   Needs Playwright with Chromium. Every line is PASS or FAIL, and the last line counts crashes, silent
   submits, stale results, a kept age that is not shown, and injected markup separately. The exit code is the number of failed checks. */
const { chromium } = require("playwright");
const fs = require("fs"), os = require("os"), path = require("path");

const BASE = process.argv[2] || "http://127.0.0.1:8501", WIDTH = Number(process.argv[3] || 1280), SEED = 379;
function generator(seed) { let s = seed >>> 0; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
const random = generator(SEED);
const WORDS = "invented ache ankle since Tuesday cricket invoice weather cough the my and tired rash market river".split(" ");
const sentence = count => Array.from({ length: count }, () => WORDS[Math.floor(random() * WORDS.length)]).join(" ");
const tally = { checks: 0, failed: 0, crashes: 0, silent: 0, stale: 0, unshown: 0, injected: 0 };
function check(name, ok, detail) {
  tally.checks += 1; if (!ok) tally.failed += 1;
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " :: " + String(detail).slice(0, 200) : ""));
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: WIDTH, height: 2200 } });
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const page = await context.newPage(), errors = [];
  page.on("pageerror", error => errors.push(String(error).slice(0, 150)));
  await page.goto(BASE, { waitUntil: "networkidle" });
  const wait = ms => page.waitForTimeout(ms);
  const main = () => page.locator('[data-testid="stMain"]').innerText();
  const button = name => page.getByRole("button", { name, exact: true });
  const pick = async label => { await page.locator("label", { hasText: label }).first().click(); await wait(1400); };
  const alerts = async () => (await page.locator('[data-testid="stAlert"]').allInnerTexts()).join(" | ").replace(/\s+/g, " ");
  const crashed = async () => { const n = await page.locator('[data-testid="stException"]').count(); tally.crashes += n; return n > 0; };
  const injected = async () => { const hit = await page.evaluate(() => window.__x === 1); if (hit) tally.injected += 1; return hit; };
  const paste = async (field, text) => {
    await field.click(); await page.keyboard.press("Control+A");
    await page.evaluate(value => navigator.clipboard.writeText(value), text); await page.keyboard.press("Control+V");
  };
  const fits = async name => {
    const wide = await page.evaluate(width => [...document.querySelectorAll('[data-testid="stMain"] *')].filter(element => {
      const box = element.getBoundingClientRect();
      return box.width > 0 && box.right > width + 2 && !element.closest(".cc-scroll, pre, code, iframe, svg, table");
    }).length, WIDTH);
    check(`${name}: nothing runs off a ${WIDTH}px screen`, wide === 0, wide + " elements");
  };

  /* ---- Check symptoms, with assessment off ---- */
  const area = () => page.getByRole("textbox", { name: "Describe it in your own words" });
  const age = () => page.getByRole("spinbutton", { name: "Age in years (optional)" });
  await fits("Check symptoms");
  await button("Start").click(); await wait(1300);
  check("Start without agreeing names the box to tick", /Tick the box to agree/.test(await alerts()) && !(await area().count()));
  await page.locator("label", { hasText: "I agree to what I write" }).click(); await button("Start").dblclick(); await wait(1500);
  check("a double press on Start opens one form", (await area().count()) === 1);
  const descriptions = [["blank", "", "refused"], ["spaces", "   \t  ", "refused"], ["ordinary", "Invented: a sore ankle since Tuesday, worse on stairs.", "kept"],
    ["unrelated", "What is the cricket score and where is my invoice?", "kept"], ["mixed", "Invented cough and also the weather tomorrow invoice 4471", "kept"],
    ["typos", "Inventd: soar ankel sinse tusday", "kept"], ["emoji", "🤒🤒 🦶 ouch 😵", "kept"], ["Devanagari", "आविष्कृत: मंगलवार से टखने में दर्द", "kept"],
    ["Arabic", "مخترع: ألم في الكاحل", "kept"], ["several lines", "Invented line one\nline two\n\n\tline four", "kept"],
    ["markup", '<script>window.__x=1</script><img src=x onerror="window.__x=1"> **bold**', "kept"],
    ["3,999 characters", "a".repeat(3999), "kept"], ["4,000 characters", "b".repeat(4000), "kept"], ["4,001 characters", "c".repeat(4001), "refused"],
    ["seeded 12 words", sentence(12), "kept"], ["seeded 40 words", sentence(40), "kept"], ["seeded 3 words", sentence(3), "kept"]];
  const ages = [["", "none given", true], ["0", "0 (whole years)", true], ["120", "120 (whole years)", true], ["121", null, false], ["-1", null, false],
    ["1.5", "1 (whole years)", true], ["abc", "none given", true], ["1000000000", null, false], ["35", "35 (whole years)", true]];
  let turn = 0;
  for (const [name, text, expected] of descriptions) {
    const [typedAge, keptAge, ageAllowed] = ages[turn % ages.length]; turn += 1;
    if (!(await area().count())) { await button("Change my description").click(); await wait(1200); }
    const before = await main();
    if (text.length > 3000) await paste(area(), text); else await area().fill(text);
    // focus, not a click: on a narrow screen Streamlit draws its "Press Enter to submit form" hint over a focused field
    await age().fill(""); if (typedAge) { await age().focus(); await page.keyboard.type(typedAge); }
    await button("Save and continue").click(); await wait(1700);
    const after = await main(), messages = await alerts(), editing = (await area().count()) > 0;
    if (after === before && !messages) tally.silent += 1;
    const label = `symptoms: ${name}, age "${typedAge}"`;
    if (await crashed() || await injected()) check(label, false, "crash or markup ran");
    else if (!ageAllowed) check(label + " is stopped at the age field", editing && /outside the allowed range/.test(after));
    else if (expected === "refused") check(label + " gets the description message", editing && /could not be used/.test(messages));
    else {
      const echoed = !editing && after.includes(text.trim().split("\n")[0].slice(0, 30)), kept = echoed && after.includes("Age kept with it: " + keptAge);
      if (!editing && !echoed) tally.stale += 1; else if (echoed && !kept) tally.unshown += 1;
      check(label + " is kept and shown back with its age", kept, messages.slice(0, 120));
    }
    if (editing && !ageAllowed) {  // the valid retry in the same session
      await area().fill("Invented retry after a refused age"); await age().fill("40"); await button("Save and continue").click(); await wait(1700);
      check(label + ": a valid retry is kept", (await main()).includes("Invented retry after a refused age") && !(await area().count()));
    }
  }
  if (!(await area().count())) { await button("Change my description").click(); await wait(1200); }
  await area().fill("Invented second description"); await area().press("Enter"); await wait(900);
  check("Enter in the description adds a line and the form says how to submit", (await area().count()) === 1 && /Ctrl\+Enter/.test(await main()));
  await area().press("Control+Enter"); await wait(1700);
  check("Ctrl+Enter saves the description", (await main()).includes("Invented second description") && !(await area().count()));
  await button("Change my description").click(); await wait(1200);
  await area().fill("ABANDONED invented text"); await button("Keep what I wrote before").click(); await wait(1200);
  let shown = await main();
  check("Keep what I wrote before drops the unsaved edit", shown.includes("Invented second description") && !shown.includes("ABANDONED"));
  await button("Change my description").click(); await wait(1200); await area().fill("ABANDONED invented text");
  await pick("Find care"); await pick("Check symptoms"); shown = await main();
  check("leaving the page drops abandoned text and keeps the saved description", !shown.includes("ABANDONED") && (await area().inputValue()).includes("Invented second description"));
  await button("Start over").click(); await wait(1500); shown = await main();
  check("Start over clears everything and says so", shown.includes("Before you start") && !shown.includes("Invented") && /cleared from this server/.test(await alerts()));

  /* ---- Find care: public facility evidence ---- */
  await pick("Find care"); await fits("Find care, public lookup");
  const city = page.getByRole("textbox", { name: "City" }), service = page.getByRole("textbox", { name: "Service" });
  const search = button("Search public sources");
  const NOTE = /No results are shown for the city and service above/;
  const found = async () => { const text = await main(); return ["KEM Hospital, Pune", "Jehangir Hospital"].filter(name => text.includes(name)).length; };
  const links = () => page.getByRole("link", { name: /service page/ }).count();
  await service.fill("dialysis"); await service.press("Enter"); await wait(1400);
  check("public: a first search by Enter is answered with the button to press", NOTE.test(await alerts()) && (await found()) === 0);
  await search.click(); await wait(1500);
  check("public: Pune dialysis names both operators with their pages", (await found()) === 2 && (await links()) === 2 && !NOTE.test(await alerts()));
  const edits = [[service, "maintenance haemodialysis", "Enter"], [city, "Pune ", "Tab"], [city, "Atlantis", null]];
  for (const [field, text, key] of edits) {
    await field.fill(text); if (key) await field.press(key); else { await field.blur(); await page.mouse.click(5, 5); } await wait(1400);
    const gone = (await found()) === 0 && (await links()) === 0, told = NOTE.test(await alerts());
    if (gone && !told) tally.silent += 1; if (!gone) tally.stale += 1;
    check(`public: after a hit, "${text}" then ${key || "a click away"} removes the old result and says how to search`, gone && told);
    await city.fill("Pune"); await service.fill("dialysis"); await service.blur(); await search.click(); await wait(1500);
    check("public: the valid retry names both operators again", (await found()) === 2 && (await links()) === 2);
  }
  const lookups = [["Atlantis", "dialysis", 0, /no reviewed public claim/], ["Pune", "not dialysis", 0, /no reviewed public claim/], ["Pune", "", 0, /Fill in \*?\*?Service/],
    ["", "", 0, /Fill in/], ["Pune or Mumbai?", "dialysis", 0, /no reviewed public claim/], ["Pune", "kidney dialysis?", 2, null], ["  pUnE ", " DIALYSIS ", 2, null],
    ["Pune", "x".repeat(121), 0, /Shorten/], ["Pune", sentence(6), 0, /no reviewed public claim/], ["पुणे", "डायलिसिस", 0, /no reviewed public claim/],
    ['<img src=x onerror="window.__x=1">', "dialysis", 0, /no reviewed public claim/], ["Pune", "maintenance haemodialysis", 1, null]];
  for (const [place, wanted, operators, message] of lookups) {
    if (place.length + wanted.length > 100) { await city.fill(place); await paste(service, wanted); } else { await city.fill(place); await service.fill(wanted); }
    await service.blur(); await search.click(); await wait(1500);
    const count = await found(), said = (await alerts()) + " " + (await main());
    if (count !== operators) tally.stale += count > operators ? 1 : 0;
    check(`public: "${place.slice(0, 18)}" / "${wanted.slice(0, 18)}" gives ${operators} operators` + (message ? " and a message" : ""),
      count === operators && (await links()) === operators && (!message || message.test(said)) && !(await injected()) && !(await crashed()));
  }
  await pick("Simulated scenarios"); await pick("Public facility evidence");
  check("public: the form opens clean after another mode", (await found()) === 0 && !NOTE.test(await alerts()));

  /* ---- Find care: simulated recommendation and record lookup ---- */
  await pick("Simulated scenarios"); await fits("Find care, recommendation");
  await button("Find a facility").dblclick(); await wait(2500); shown = await main();
  check("recommend: a double press gives one recommendation", (shown.match(/Send the patient to Campus/g) || []).length === 1 && !(await crashed()));
  for (const choice of ["MRI scan", "Trauma care", "Dialysis"]) {
    await pick(choice); shown = await main();
    const cleared = !/Send the patient to Campus/.test(shown);
    if (!cleared) tally.stale += 1;
    check(`recommend: choosing ${choice} removes the earlier recommendation and says to press again`, cleared && /You changed the request/.test(shown));
    await button("Find a facility").click(); await wait(2200);
    check(`recommend: ${choice} is answered`, /Send the patient to Campus|No campus is recommended|Provisional lead/.test(await main()) && !(await crashed()));
  }
  await pick("Look up the example records"); shown = await main();
  check("lookup: no recommendation or referral note is carried over from the other mode", !/Send the patient to Campus|Referral note/.test(shown));
  await fits("Find care, record lookup");
  const where = page.getByLabel("2. Where the patient is"), find = button("Search the example records");
  const LEAD = "Provisional lead: Example Regional Hospital";
  const look = async text => { if (text.length > 200) await paste(where, text); else await where.fill(text); await where.blur(); await find.click(); await wait(1600); return main(); };
  check("lookup: Jaipur, Rajasthan gives the lead and a call script", (shown = await look("Jaipur, Rajasthan")).includes(LEAD) && shown.includes("Confirmation call script"));
  const lines = ["x".repeat(4001), "a".repeat(81), "?!?!", "302001 302002", "Jaipur 302001. Or 302002", "not 302001", "Atlantis", sentence(7),
    '<img src=x onerror="window.__x=1">', "‮ruopiaJ", "999, 999", "🏥🏥"];
  for (const text of lines) {
    shown = await look("Jaipur, Rajasthan");
    shown = await look(text);
    const stale = shown.includes(LEAD) || shown.includes("Confirmation call script"), said = (await alerts()).length > 0 || /could not be located|cannot be used|No facility|Which/.test(shown);
    if (stale) tally.stale += 1; if (!said) tally.silent += 1;
    check(`lookup: "${text.slice(0, 24)}" after a lead leaves no lead and gets a message`, !stale && said && !(await injected()) && !(await crashed()));
  }
  check("lookup: a valid search works after all of it", (await look("302001")).includes(LEAD));
  await where.fill("Pune"); await where.blur(); await wait(1300); shown = await main();
  check("lookup: an edited line marks the answer as the earlier one", (await page.locator(".fc-stale").count()) > 0);

  /* ---- Storm replay ---- */
  await pick("Storm demo"); await wait(2200); await fits("Storm");
  const frame = page.frames()[1];
  const clock = () => frame.evaluate(() => [Number(document.getElementById("scrub").value), Number(document.getElementById("scrub").max)]);
  const fileError = () => frame.evaluate(() => (document.getElementById("file-error").hidden ? "" : document.getElementById("file-error").textContent));
  const scenarios = (await frame.evaluate(() => [...document.getElementById("scenario").options].map(option => option.value))).filter(Boolean);
  let combinations = 0, wrong = 0;
  for (const scenario of scenarios) for (const detour of ["0", "5", "10", "15"]) for (const view of ["map", "text"]) {
    await frame.selectOption("#scenario", scenario); await frame.check(`input[type=radio][value="${detour}"]`); await frame.check(`input[type=radio][value="${view}"]`);
    const start = await clock(); await frame.click("#skip"); const end = await clock(); combinations += 1;
    if (start[0] !== -1 || end[0] !== end[1] || await fileError()) wrong += 1;
  }
  check(`storm: ${combinations} scenario, detour and view combinations reset the clock and reach the result`, wrong === 0, wrong + " wrong");
  let actions = 0;
  for (let step = 0; step < 300; step += 1) {
    const roll = random();
    if (roll < 0.55) { const id = ["play", "next", "skip", "back", "restart"][Math.floor(random() * 5)]; if (await frame.locator("#" + id).isEnabled()) { await frame.click("#" + id); actions += 1; } }
    else if (roll < 0.7) { const [, max] = await clock(); await frame.evaluate(value => { const scrub = document.getElementById("scrub"); scrub.value = value; scrub.dispatchEvent(new Event("input", { bubbles: true })); }, String([-1, max, -50, max + 50, Math.floor(random() * max)][Math.floor(random() * 5)])); actions += 1; }
    else if (roll < 0.85) { await frame.selectOption("#scenario", scenarios[Math.floor(random() * scenarios.length)]); actions += 1; }
    else { await frame.check(`input[type=radio][value="${["0", "5", "10", "15", "map", "text"][Math.floor(random() * 6)]}"]`); actions += 1; }
  }
  const [minute, last] = await clock();
  check(`storm: ${actions} seeded presses, scrubs and changes leave the clock in range`, minute >= -1 && minute <= last && !(await fileError()));
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), "storm-files-"));
  const good = fs.readFileSync(path.join(__dirname, "..", "..", "contracts", "fixtures", "storm_replay.json"), "utf8");
  const files = { "good.json": good, "empty.json": "", "spaces.json": "  \n ", "words.txt": "Invented unrelated sentence.", "broken.json": "{ not json",
    "list.json": "[1, 2, 3]", "null.json": "null", "bare.json": "{}", "other.json": JSON.stringify({ pad: "x".repeat(2000000) }),
    "hostile.json": good.replace(/"label": "([^"]*)"/g, '"label": "$1<img src=x onerror=\\"window.__x=1\\">"') };
  for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(folder, name), text);
  const open = async name => { await frame.setInputFiles("#file", path.join(folder, name)); await wait(name === "other.json" ? 1800 : 800); return fileError(); };
  check("storm: a replay file written by the simulator opens", (await open("good.json")) === "" && (await frame.locator("#scenario").inputValue()) === "");
  for (const name of ["empty.json", "spaces.json", "words.txt", "broken.json", "list.json", "null.json", "bare.json", "other.json"]) {
    const message = await open(name);
    if (!message) tally.silent += 1;
    check(`storm: ${name} is refused in plain words and the open replay stays`, /can't be shown/.test(message) && (await clock())[1] > 0);
  }
  const hostile = await open("hostile.json");
  check("storm: markup in a file's labels is shown as text", !(await frame.evaluate(() => window.__x === 1)) && !(await injected()), hostile.slice(0, 80));
  check("storm: a good file opens straight after the refused ones", (await open("good.json")) === "");
  await frame.selectOption("#scenario", scenarios[0]); await wait(400);
  check("storm: a built-in scenario replaces the opened file", (await frame.locator("#scenario").inputValue()) === scenarios[0] && !(await fileError()));
  fs.rmSync(folder, { recursive: true, force: true });

  /* ---- Fresh sessions ---- */
  await pick("Check symptoms"); await page.locator("label", { hasText: "I agree to what I write" }).click(); await button("Start").click(); await wait(1400);
  await area().fill("Invented third description"); await button("Save and continue").click(); await wait(1600);
  await page.reload({ waitUntil: "networkidle" }); await wait(800);
  check("a refresh shows nothing from before", !(await main()).includes("Invented third"));
  const other = await (await browser.newContext()).newPage(); await other.goto(BASE, { waitUntil: "networkidle" });
  check("another session sees nothing of this one", !(await other.locator('[data-testid="stMain"]').innerText()).includes("Invented"));
  check("no page error in the whole run", errors.length === 0, errors.join(" | "));
  await crashed();
  console.log(`seed ${SEED}, width ${WIDTH}: ${tally.checks} checks, ${tally.failed} failed. crashes ${tally.crashes}, silent submits ${tally.silent}, ` +
    `stale results ${tally.stale}, kept age not shown or wrong ${tally.unshown}, markup that ran ${tally.injected}`);
  await browser.close();
  process.exit(Math.min(tally.failed, 100));
})().catch(error => { console.error("STOPPED " + String(error).slice(0, 600)); process.exit(101); });
