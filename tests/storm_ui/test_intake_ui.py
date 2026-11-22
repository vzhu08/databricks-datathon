import json
import shutil
import subprocess
import unittest
from pathlib import Path

from app.storm_ui import build_ask, build_intake

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "storm_ui"
ALL_NO = ["no", "no", "no", "no"]


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require.resolve('playwright')"], capture_output=True).returncode == 0


def _scenario(scenario_id):
    return next(s for s in build_intake.SCENARIOS if s["id"] == scenario_id)


class IntakeBundleTests(unittest.TestCase):
    """The stored states, checked against the acceptance cases on issue 124. All inputs are invented."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads(json.dumps(build_intake.bundle()))
        cls.states = cls.bundle["assessments"]

    def test_committed_bundle_is_current_and_marked(self):
        self.assertEqual(build_intake.TARGET.read_text(encoding="utf-8"), build_intake.render())
        self.assertIs(self.bundle["synthetic"], True)
        self.assertIs(self.bundle["provisional"], True)
        for name, state in self.states.items():
            self.assertIs(state["synthetic"], True, name)

    def test_every_stored_state_is_the_assessment_functions_own_answer(self):
        for name, state in self.states.items():
            scenario_id, answers, *confirmed = name.split("|")
            answers = answers.split(",") if answers else []
            revision = build_intake.revision(scenario_id, answers) if confirmed else None
            fresh = json.loads(json.dumps(build_intake.assess(_scenario(scenario_id), answers, revision)))
            self.assertEqual(fresh, state, name)

    def test_the_walk_is_complete_and_bounded(self):
        longest = 0
        for name, state in self.states.items():
            scenario_id, answers, *confirmed = name.split("|")
            answers = answers.split(",") if answers else []
            longest = max(longest, len(answers))
            if state["next_question_id"]:
                self.assertEqual(build_intake.QUESTIONS[len(answers)]["id"], state["next_question_id"], name)
                for answer in build_intake.ANSWERS:
                    self.assertIn(build_intake.key(scenario_id, answers + [answer]), self.states, name)
            elif state["state"] == "awaiting_confirmation":
                self.assertIn(build_intake.key(scenario_id, answers, True), self.states, name)
        self.assertEqual(build_intake.MAX_QUESTIONS, longest)
        self.assertEqual(self.bundle["max_questions"], longest)

    def test_only_a_confirmed_ready_state_carries_a_request(self):
        ready = 0
        for name, state in self.states.items():
            if state["state"] != "ready":
                self.assertIsNone(state["request"], name)
                self.assertFalse(state["confirmation"]["present"], name)
                continue
            ready += 1
            self.assertTrue(name.endswith("|confirmed"), name)
            self.assertEqual(state["input_revision"], state["confirmation"]["bound_to"], name)
            self.assertEqual([], state["unknown_question_ids"], name)
            self.assertEqual({"service": state["clinician"]["service"], "urgency": state["clinician"]["urgency"],
                              "required_capabilities": []}, state["request"], name)
            self.assertIn(state["request"]["service"], build_intake.SUPPORTED_SERVICES, name)
        self.assertEqual(4, ready)

    def test_a_known_danger_sign_always_escalates(self):
        for name, state in self.states.items():
            answers = name.split("|")[1].split(",") if name.split("|")[1] else []
            if "yes" in answers[:4]:
                self.assertEqual("escalation", state["state"], name)
                self.assertIsNone(state["next_question_id"], name)
                self.assertIn("india-112", state["source_ids"], name)
        # It wins over a missing answer, an unknown answer and care that is already booked.
        for scenario_id in ("dialysis-plan", "stroke-signs-mri", "heart-check"):
            for answers in (["yes"], ["unknown", "yes"], ["no", "unknown", "unknown", "yes"]):
                state = self.states[build_intake.key(scenario_id, answers)]
                self.assertEqual("escalation", state["state"])
                self.assertIn("existing_request_set_aside", state["reason_ids"])

    def test_unknown_is_never_read_as_no(self):
        for name, state in self.states.items():
            if state["unknown_question_ids"]:
                self.assertIn(state["state"], ("more_information", "escalation"), name)
                self.assertIsNone(state["request"], name)
        stuck = self.states[build_intake.key("dialysis-plan", ["unknown"] * 4)]
        self.assertEqual(("more_information", "safety_unresolved", None),
                         (stuck["state"], stuck["message_id"], stuck["next_question_id"]))
        self.assertNotIn(build_intake.key("dialysis-plan", ["unknown"] * 4, True), self.states)

    def test_symptoms_alone_never_order_a_service(self):
        for scenario_id, concern in (("injury-unassessed", "injury_unassessed"),
                                     ("kidney-symptoms", "kidney_symptoms_unassessed")):
            names = [n for n in self.states if n.startswith(scenario_id + "|")]
            self.assertTrue(names)
            for name in names:
                self.assertIsNone(self.states[name]["request"], name)
                self.assertNotIn(self.states[name]["state"], ("ready", "awaiting_confirmation"), name)
            end = self.states[build_intake.key(scenario_id, ALL_NO + ["yes"])]
            self.assertEqual(("assessment_needed", [concern]), (end["state"], end["concerns"]))

    def test_unsupported_patients_and_care_stop_with_a_stated_reason(self):
        for scenario in build_intake.SCENARIOS:
            state = self.states[build_intake.key(scenario["id"], ALL_NO + ["no"])]
            self.assertEqual(("unsupported", "unsupported_population"), (state["state"], state["message_id"]))
        heart = self.states[build_intake.key("heart-check", ALL_NO + ["yes"])]
        self.assertEqual(("unsupported", "unsupported_need", None),
                         (heart["state"], heart["message_id"], heart["request"]))
        self.assertFalse(any(n.startswith("heart-check|") and n.endswith("|confirmed") for n in self.states))

    def test_the_three_supported_journeys_reach_a_request_the_finder_can_answer(self):
        finder = build_ask.bundle()["answers"]
        for scenario_id, service, urgency in (("dialysis-plan", "dialysis", "routine"), ("mri-referral", "mri", "routine"),
                                              ("injury-assessed", "trauma_care", "time_sensitive")):
            waiting = self.states[build_intake.key(scenario_id, ALL_NO + ["yes"])]
            self.assertEqual(("awaiting_confirmation", None), (waiting["state"], waiting["request"]))
            ready = self.states[build_intake.key(scenario_id, ALL_NO + ["yes"], True)]
            self.assertEqual({"service": service, "urgency": urgency, "required_capabilities": []}, ready["request"])
            for place, _name in build_ask.PLACES:
                self.assertIn(build_ask.key(service, place, urgency), finder)

    def test_a_confirmation_counts_only_for_the_answers_it_was_given_for(self):
        scenario = _scenario("dialysis-plan")
        answers = ALL_NO + ["yes"]
        right = build_intake.revision(scenario["id"], answers)
        self.assertEqual("ready", build_intake.assess(scenario, answers, right)["state"])
        for stale in (None, "", "ready", build_intake.revision(scenario["id"], ALL_NO),
                      build_intake.revision("mri-referral", answers)):
            state = build_intake.assess(scenario, answers, stale)
            self.assertEqual(("awaiting_confirmation", None), (state["state"], state["request"]), stale)
        # A confirmation cannot rescue answers that are not ready.
        for other in (["yes"], ["unknown"] * 4, ALL_NO + ["no"], ALL_NO):
            state = build_intake.assess(scenario, other, build_intake.revision(scenario["id"], other))
            self.assertIsNone(state["request"], other)
        with self.assertRaises(ValueError):
            build_intake.assess(scenario, ["maybe"])
        with self.assertRaises(ValueError):
            build_intake.assess(scenario, ["no"] * 6)

    def test_every_id_has_wording_and_no_state_claims_a_diagnosis(self):
        catalogue = self.bundle["catalogue"]
        for name, state in self.states.items():
            self.assertIn(state["message_id"], catalogue["messages"], name)
            for section, ids in (("concerns", state["concerns"]), ("reasons", state["reason_ids"]),
                                 ("limits", state["limit_ids"]), ("sources", state["source_ids"])):
                for item in ids:
                    self.assertIn(item, catalogue[section], f"{name}: {section}")
            self.assertIn("placeholder_rules", state["limit_ids"], name)
        shown = json.dumps(catalogue).lower()
        for word in ("probability", "% chance", "likely has", "you have", "diagnosed with", "999", "911"):
            self.assertNotIn(word, shown)


class IntakePageTests(unittest.TestCase):
    def test_page_stays_offline_and_decides_nothing(self):
        for name in ("index.html", "ask.css", "intake.js", "intake_state.js"):
            text = (PAGE / name).read_text(encoding="utf-8")
            for marker in ("http://", "https://", "//cdn", "@import", "fetch(", "XMLHttpRequest", "WebSocket",
                           "localStorage", "sessionStorage", "indexedDB"):
                self.assertNotIn(marker, text, f"{name} must not contain {marker}")
        script = (PAGE / "intake.js").read_text(encoding="utf-8")
        # The page asks for a campus in one place, and only with a request the state module returned.
        self.assertEqual(1, script.count("page.ask("))
        self.assertIn("I.finderRequest(data, state.scenario, state.answers, state.confirmed)", script)
        for word in ("danger", "escalation", "112", "dialysis", "trauma"):
            self.assertNotIn(word, script, f"intake.js must not carry rules or clinical wording: {word}")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the page-state checks")
    def test_wording_against_every_stored_state(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/intake_check.js")], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ checks")

    @unittest.skipUnless(_has_playwright(), "Node.js with Playwright is needed for the browser check")
    def test_intake_journeys_in_a_browser(self):
        result = subprocess.run(["node", str(ROOT / "tests/storm_ui/intake_browser_check.js")], cwd=ROOT,
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ok \d+ browser checks")


if __name__ == "__main__":
    unittest.main()
