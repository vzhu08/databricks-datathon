/* Find care page: reads the form, looks the answer up in the generated bundle and draws it. */
(function () {
  "use strict";

  var A = window.AskState, data = window.CARE_ANSWERS;
  var $ = function (id) { return document.getElementById(id); };
  var shown = null;

  function el(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (name) {
      if (name === "text") node.textContent = props[name];
      else if (name === "onclick") node.addEventListener("click", props[name]);
      else node.setAttribute(name, props[name]);
    });
    (children || []).forEach(function (child) { if (child) node.append(child); });
    return node;
  }
  function fill(node, children) { node.replaceChildren.apply(node, children.filter(Boolean)); }
  function quote(text) { return text ? el("span", { "class": "quote", text: "Its record says: “" + text + "”" }) : null; }

  function choices(fieldset, name, options, picked) {
    options.forEach(function (option) {
      var input = el("input", { type: "radio", name: name, value: option.id });
      input.checked = option.id === picked;
      fieldset.append(el("label", {}, [input, document.createTextNode(option.name)]));
    });
  }
  function picked(name) {
    var input = document.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : null;
  }
  function choose(name, value) {
    var input = document.querySelector('input[name="' + name + '"][value="' + value + '"]');
    if (input) input.checked = true;
  }
  function current() { return { service: picked("service"), place: $("place").value, urgency: picked("urgency") }; }

  function drawOk(v) {
    $("headline").textContent = "Send the patient to " + v.top.name + ".";
    $("trip").textContent = "About " + A.minutes(v.top.travel) + " by road.";
    fill($("why"), v.why.map(function (line) { return el("p", { text: line }); }));
    $("record").hidden = !v.top.record_text;
    $("record-text").textContent = v.top.record_text || "";
    $("record-meta").textContent = v.top.name + "’s record, dated " + A.day(v.top.record_date) + ". Backed by " +
      A.sources(v.top.sources) + ". Invented for this demonstration.";
    $("leads").hidden = true;
    $("caveat").hidden = !v.caveat;
    $("caveat-text").textContent = v.caveat || "";
    $("copy").textContent = "Copy referral note";

    $("backups").hidden = v.backups.length === 0;
    $("backups-heading").textContent = "If " + v.top.name + " cannot take the patient";
    fill($("backup-list"), v.backups.map(function (b) {
      return el("li", {}, [el("strong", { text: b.name }),
        document.createTextNode(", " + A.minutes(b.travel) + " by road. " + b.points.total + " points. Record dated " +
          A.day(b.record_date) + ", " + A.sources(b.sources) + "."), quote(b.record_text)]);
    }));

    $("how").hidden = false;
    $("weights-line").textContent = v.weights_line;
    var rows = [v.top].concat(v.backups);
    var head = el("tr", {}, [el("th", { scope: "col", text: "Campus" }), el("th", { scope: "col", "class": "num", text: "Trip" }),
      el("th", { scope: "col", text: "Record dated" }), el("th", { scope: "col", "class": "num", text: "Sources" })]
      .concat(v.top.points.parts.map(function (part) { return el("th", { scope: "col", "class": "num", text: part.label }); }))
      .concat([el("th", { scope: "col", "class": "num", text: "Points" })]));
    var body = rows.map(function (row) {
      return el("tr", {}, [el("th", { scope: "row", text: row.name }), el("td", { "class": "num", text: row.travel + " min" }),
        el("td", { text: A.day(row.record_date) }), el("td", { "class": "num", text: String(row.sources) })]
        .concat(row.points.parts.map(function (part) {
          return el("td", { "class": "num" }, [document.createTextNode(part.points + " "), el("span", { "class": "of", text: "of " + part.out_of })]);
        }))
        .concat([el("td", { "class": "num", text: String(row.points.total) })]));
    });
    fill($("how-table"), [el("thead", {}, [head]), el("tbody", {}, body)]);
  }

  function drawNone(v) {
    var confirm = v.status === "needs_confirmation";
    $("headline").textContent = confirm
      ? "No campus is confirmed for " + v.service_phrase + " within " + A.minutes(v.budget) + "."
      : "No campus with a record for " + v.service_phrase + " is within " + A.minutes(v.budget) + ".";
    $("trip").textContent = confirm
      ? (v.leads.length === 1 ? "One campus mentions it. Phone before sending anyone." : v.leads.length + " campuses mention it. Phone before sending anyone.")
      : "The campuses whose records mention it are listed below with their travel times.";
    fill($("why"), []);
    $("record").hidden = true;
    $("caveat").hidden = true;
    $("leads").hidden = !confirm;
    fill($("leads"), v.leads.map(function (lead) {
      return el("li", {}, [el("strong", { text: lead.name }),
        document.createTextNode(", " + A.minutes(lead.travel) + " by road. Not confirmed: " + lead.why + "."), quote(lead.record_text)]);
    }));
    $("copy").textContent = "Copy this note";
    $("backups").hidden = true;
    $("how").hidden = true;
  }

  function draw(v, fresh) {
    shown = v;
    $("empty").hidden = true;
    $("result").hidden = false;
    markStale();
    $("copy-status").textContent = "";
    $("request-line").textContent = v.request_line;
    if (v.status === "ok") drawOk(v); else drawNone(v);

    var leadIds = v.status === "needs_confirmation" ? v.leads.map(function (lead) { return lead.facility_id; }) : [];
    var rest = v.left_out.filter(function (entry) { return leadIds.indexOf(entry.facility_id) === -1; });
    $("leftout").hidden = rest.length === 0;
    $("leftout-heading").textContent = v.status === "no_match" ? "Campuses whose records mention it" : "Left out, and why";
    fill($("leftout-list"), rest.map(function (entry) {
      return el("li", {}, [el("strong", { text: entry.name }),
        document.createTextNode(", " + A.minutes(entry.travel) + " by road: " + entry.why + "."),
        entry.kind === "unconfirmed" ? quote(entry.record_text) : null]);
    }));
    $("raw").textContent = JSON.stringify({ request: v.raw.request, response: v.raw.response }, null, 2);

    $("step-ask").removeAttribute("aria-current");
    $("step-answer").setAttribute("aria-current", "step");
    $("announcer").textContent = $("headline").textContent + " " + $("trip").textContent;
    if (fresh) {
      var slip = $("slip");
      slip.classList.remove("fresh");
      void slip.offsetWidth;
      slip.classList.add("fresh");
      $("answer").focus({ preventScroll: true });
      if (window.matchMedia("(max-width: 1000px)").matches) $("answer").scrollIntoView({ block: "start" });
    }
  }

  /* Takes the answer off the page, so nothing stays on screen for a request that no longer stands. */
  function clear() {
    shown = null;
    $("result").hidden = true;
    $("result").setAttribute("data-stale", "false");
    $("stale").hidden = true;
    $("load-error").hidden = true;
    $("copy-status").textContent = "";
    $("announcer").textContent = "";
    $("step-answer").removeAttribute("aria-current");
    $("step-ask").setAttribute("aria-current", "step");
  }
  /* Fills the form with one request and answers it. Used by the intake once a summary is confirmed. */
  function ask(service, place, urgency) {
    choose("service", service);
    $("place").value = place;
    choose("urgency", urgency);
    var now = current();
    if (now.service !== service || now.place !== place || now.urgency !== urgency) return false;
    find();
    return shown !== null && !stale();
  }

  function find() {
    var now = current();
    var v = A.view(data, now.service, now.place, now.urgency);
    if (!v) {
      $("load-error").hidden = false;
      $("load-error").textContent = "This demonstration has no answer for that request. Choose another starting point or kind of care.";
      return;
    }
    $("load-error").hidden = true;
    draw(v, true);
  }

  /* True when the form no longer asks what the shown answer answers. */
  function stale() {
    if (!shown) return false;
    var now = current();
    return !(now.service === shown.service && now.place === shown.place && now.urgency === shown.urgency);
  }
  /* An out-of-date answer can be read but not handed on: Copy and Print are off, and it does not print. */
  function markStale() {
    var old = stale();
    $("stale").hidden = !old;
    $("result").setAttribute("data-stale", old ? "true" : "false");
    $("copy").disabled = $("print").disabled = old;
    if (old) $("copy-status").textContent = "";
  }

  function copy() {
    if (!shown || stale()) return;
    var done = function (ok) {
      $("copy-status").textContent = ok ? "Copied. Paste it into a message or a note."
        : "Copying is blocked here. Use Print, or select the text on the slip.";
    };
    var fallback = function () {
      var area = el("textarea", { "aria-hidden": "true", style: "position:fixed;top:0;left:0;opacity:0" });
      area.value = shown.referral;
      document.body.append(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
      area.remove();
      done(ok);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(shown.referral).then(function () { done(true); }, fallback);
    } else fallback();
  }

  function start() {
    var trouble = A ? A.problems(data) : ["The page script did not load."];
    if (trouble.length) {
      $("empty").hidden = true;
      $("find").disabled = true;
      $("load-error").hidden = false;
      $("load-error").textContent = "This page could not load its answers. Open index.html from the folder that also holds the data folder. (" + trouble[0] + ")";
      return;
    }
    choices($("service"), "service", data.services, data.services[0].id);
    data.places.forEach(function (place) { $("place").append(el("option", { value: place.id, text: place.name })); });
    choices($("urgency"), "urgency", data.urgencies, data.urgencies[0].id);
    data.examples.forEach(function (example) {
      $("examples").append(el("li", {}, [el("button", { type: "button", text: example.label, onclick: function () {
        choose("service", example.service);
        $("place").value = example.place;
        choose("urgency", example.urgency);
        find();
      } })]));
    });
    $("ask").addEventListener("submit", function (event) { event.preventDefault(); find(); });
    $("ask").addEventListener("change", markStale);
    $("copy").addEventListener("click", copy);
    $("print").addEventListener("click", function () { if (shown && !stale()) window.print(); });
    // A page restored from the browser's history can come back with a changed form.
    window.addEventListener("pageshow", markStale);
    window.AskPage = { shown: function () { return shown; }, ask: ask, clear: clear };
  }

  start();
})();
