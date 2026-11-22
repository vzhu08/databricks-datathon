/*
 * Intake before Find care: pick a fictional patient, answer the questions, read the outcome.
 * Looks each state up in the generated bundle and draws it. Nothing here assesses anyone.
 * A campus is looked for only when IntakeState.finderRequest returns a request.
 */
(function () {
  "use strict";

  var I = window.IntakeState, data = window.CARE_INTAKE, care = window.CARE_ANSWERS, page = window.AskPage;
  var $ = function (id) { return document.getElementById(id); };
  var state = { scenario: null, answers: [], confirmed: false };

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
  function list(id, lines) { fill($(id), lines.map(function (line) { return el("li", { text: line }); })); }
  function mode() { return $("mode-direct").checked ? "direct" : "intake"; }

  /* Any change to the patient, an answer or the mode withdraws the confirmation and the campus answer. */
  function reset(answers) {
    state.answers = answers;
    state.confirmed = false;
    page.clear();
  }

  function drawQuestions(v) {
    fill($("answered"), v.answered.map(function (item, index) {
      return el("li", {}, [el("span", { "class": "asked", text: item.short }), el("strong", { text: item.label }),
        el("button", { type: "button", "class": "quiet", "aria-label": "Change the answer to: " + item.short, text: "Change",
          onclick: function () { reset(state.answers.slice(0, index)); draw("question"); } })]);
    }));
    $("answered").hidden = v.answered.length === 0;
    $("question").hidden = !v.next;
    $("questions-hint").textContent = v.next ? v.body
      : "The questions stop here. Change an answer to go back. The questions after it are asked again.";
    if (v.next) {
      $("question-text").textContent = "Question " + v.next.number + " of " + data.max_questions + ". " + v.next.text;
      fill($("answer-buttons"), data.answers.map(function (answer) {
        return el("button", { type: "button", "data-answer": answer, text: I.ANSWER_LABEL[answer] || answer,
          onclick: function () { reset(state.answers.concat([answer])); draw("answer"); } });
      }));
    }
    var story = v.scenario.story_answers;
    $("story-answers").hidden = story.join(",") === state.answers.join(",");
  }

  function drawOutcome(v) {
    var out = $("outcome");
    out.hidden = v.kind === "progress";
    out.setAttribute("data-kind", v.kind);
    $("outcome-for").textContent = "Fictional patient: " + v.scenario.name + ". " + v.progress + ".";
    $("outcome-headline").textContent = v.headline;
    $("outcome-body").textContent = v.body;

    $("outcome-summary").hidden = !v.summary;
    fill($("outcome-summary"), (v.summary || []).reduce(function (nodes, row) {
      return nodes.concat([el("dt", { text: row.label }), el("dd", { text: row.value.charAt(0).toUpperCase() + row.value.slice(1) })]);
    }, []));
    $("outcome-concern").hidden = v.concerns.length === 0;
    list("outcome-concern-list", v.concerns);
    $("outcome-why").hidden = v.reasons.length === 0;
    list("outcome-why-list", v.reasons);
    var limits = v.unknown.map(function (short) { return "Not sure: " + short + "."; }).concat(v.limits);
    $("outcome-limits").hidden = limits.length === 0;
    list("outcome-limits-list", limits);
    $("outcome-sources").hidden = v.sources.length === 0;
    $("outcome-sources").textContent = v.sources.length ? "References for these rules: " + v.sources.join("; ") + "." : "";

    $("outcome-confirm").hidden = !v.canConfirm;
    $("outcome-find").hidden = !v.request;
  }

  /* `moved` says what the visitor just did, so the keyboard focus and the announcement follow it. */
  function draw(moved) {
    var v = I.view(data, state.scenario, state.answers, state.confirmed);
    if (!v) {
      // No stored state for this: show the starting state of the patient and nothing else.
      state.answers = [];
      state.confirmed = false;
      page.clear();
      v = I.view(data, state.scenario, [], false);
    }
    $("story-text").textContent = v.scenario.story;
    $("story-known").textContent = v.decided;
    drawQuestions(v);
    drawOutcome(v);
    if (!moved) return;
    if (v.next && moved !== "confirm") {
      $("announcer").textContent = "";
      var first = $("answer-buttons").querySelector("button");
      if (first && moved !== "scenario") first.focus();
      return;
    }
    $("announcer").textContent = v.headline + " " + v.body;
    if (moved === "scenario") return;
    if (v.canConfirm) $("confirm").focus();
    else if (v.request) $("intake-place").focus();
    else $("outcome").focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 1000px)").matches) $("outcome").scrollIntoView({ block: "start" });
  }

  function showMode() {
    var intake = mode() === "intake";
    $("intake").hidden = !intake;
    $("intake-work").hidden = !intake;
    $("ask").hidden = intake;
    $("outcome").hidden = true;
    reset(state.answers);
    $("empty").hidden = intake;
    if (intake) draw();
  }

  function findCampus() {
    var request = I.finderRequest(data, state.scenario, state.answers, state.confirmed);
    if (!request) { reset(state.answers); draw(); return; }
    if (!page.ask(request.service, $("intake-place").value, request.urgency)) return;
    $("empty").hidden = true;
    var calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    $("slip").scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
  }

  function start() {
    var trouble = I ? I.problems(data) : ["The intake script did not load."];
    if (!page || trouble.length) {
      // The intake cannot be shown. The finder still works on its own.
      $("mode").hidden = true;
      $("intake").hidden = true;
      $("ask").hidden = false;
      return;
    }
    data.scenarios.forEach(function (scenario, index) {
      var input = el("input", { type: "radio", name: "scenario", value: scenario.id });
      input.checked = index === 0;
      $("scenario").append(el("label", {}, [input, document.createTextNode(scenario.name)]));
    });
    state.scenario = data.scenarios[0].id;
    care.places.forEach(function (place) { $("intake-place").append(el("option", { value: place.id, text: place.name })); });

    $("scenario").addEventListener("change", function (event) {
      state.scenario = event.target.value;
      reset([]);
      draw("scenario");
    });
    $("story-answers").addEventListener("click", function () {
      var scenario = data.scenarios.filter(function (s) { return s.id === state.scenario; })[0];
      reset(scenario.story_answers.slice());
      draw("answer");
    });
    $("confirm").addEventListener("click", function () {
      state.confirmed = true;
      draw("confirm");
    });
    $("intake-find").addEventListener("click", findCampus);
    $("intake-place").addEventListener("change", function () { page.clear(); $("empty").hidden = true; });
    $("mode").addEventListener("change", showMode);
    // A page restored from the browser's history can come back with a changed form: start it clean.
    window.addEventListener("pageshow", function (event) { if (event.persisted) showMode(); });
    showMode();
    window.IntakePage = { state: function () { return { scenario: state.scenario, answers: state.answers.slice(), confirmed: state.confirmed }; } };
  }

  start();
})();
