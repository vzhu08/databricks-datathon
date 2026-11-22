import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.intake import assess_intake, confirm_intake
from app.intake.finder_bridge import ORIGIN_IDS, find_care_for_intake
from app.storm_ui import build_ask, build_intake

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "storm_ui"


def _has_playwright():
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require.resolve('playwright')"], capture_output=True).returncode == 0


def _parse(name):
    story_id, joined, *confirmed = name.split("|")
    answers = [tuple(pair.split("=")) for pair in joined.split(",")] if joined else []
    return story_id, answers, bool(confirmed)


class IntakeBundleTests(unittest.TestCase):
    """The stored answers, checked against the real engine, stories and bridge. All inputs are invented."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = json.loads(json.dumps(build_intake.bundle()))
        cls.states = cls.bundle["assessments"]
        cls.stories = build_intake.stories()

    def test_committed_bundle_is_current_and_marked(self):
        self.assertEqual(build_intake.TARGET.read_text(encoding="utf-8"), build_intake.render())
        self.assertIs(self.bundle["synthetic"], True)
        self.assertNotIn("provisional", self.bundle)
        pairing = self.bundle["pairing"]
        self.assertEqual(build_intake.POLICY_VERSION, pairing["policy_version"])
        self.assertEqual(json.loads(build_intake.DIGEST.read_text(encoding="utf-8"))["sha256"], pairing["stories_sha256"])
        self.assertEqual(build_ask.AS_OF, pairing["finder_as_of"])
        for name in ("reviewed_editions_sha256", "finder_fixture_sha256"):
            self.assertRegex(pairing[name], r"^[0-9a-f]{64}$")
        for name, state in self.states.items():
            self.assertEqual("synthetic", state["mode"], name)

    def test_every_stored_answer_is_the_engines_own(self):
        campus_answers = 0
        for name, state in self.states.items():
            story_id, answers, confirmed = _parse(name)
            story, payload = self.stories[story_id], build_intake.payload(story_id, answers)
            self.assertEqual(build_intake.key(story_id, answers, confirmed), name)
            self.assertEqual(len(answers), payload["input_revision"], name)
            receipt = confirm_intake(payload, scenario=story) if confirmed else None
            fresh = assess_intake(payload, scenario=story, confirmation=receipt)
            self.assertEqual(json.loads(json.dumps(fresh)), state, name)
            if not confirmed:
                self.assertNotIn(name, self.bundle["finder"])
                continue
            self.assertEqual(list(ORIGIN_IDS), list(self.bundle["finder"][name]), name)
            for origin in ORIGIN_IDS:
                produced = find_care_for_intake(payload, scenario=story, confirmation=receipt, origin_id=origin)
                self.assertEqual(fresh, produced["assessment"], name)
                self.assertEqual(json.loads(json.dumps(build_ask.stable(produced["finder"]))),
                                 self.bundle["finder"][name][origin], f"{name} from {origin}")
                campus_answers += 1
        self.assertEqual(campus_answers, build_intake.measure(self.bundle)["campus_answers"])

    def test_the_walk_is_complete_and_bounded(self):
        questions = {row["id"]: row for row in self.bundle["questions"]}
        longest = 0
        for name, state in self.states.items():
            story_id, answers, confirmed = _parse(name)
            longest = max(longest, len(answers))
            if state["next_question_ids"]:
                (question,) = state["next_question_ids"]
                self.assertNotIn(question, dict(answers), name)
                for choice in questions[question]["answers"]:
                    self.assertNotEqual("conflicting", choice["id"])
                    self.assertIn(build_intake.key(story_id, answers + [(question, choice["id"])]), self.states, name)
            elif state["state"] == "confirmation_required":
                self.assertIn(build_intake.key(story_id, answers, True), self.states, name)
            elif not confirmed:
                self.assertNotIn(build_intake.key(story_id, answers, True), self.states, name)
        measured = build_intake.measure(self.bundle)
        self.assertEqual(longest, self.bundle["longest_path"])
        self.assertLessEqual(measured["states"], build_intake.MAX_STATES)
        # The stories are pinned by digest, so the measured walk is pinned with them.
        self.assertEqual((26, 8, 1, 32), (measured["states"], measured["ready"], measured["longest_path"],
                                          measured["campus_answers"]))
        self.assertEqual({story["id"] for story in self.bundle["scenarios"]}, set(self.stories))

    def test_only_a_confirmed_ready_answer_carries_a_request(self):
        for name, state in self.states.items():
            story_id, answers, confirmed = _parse(name)
            if state["state"] != "ready":
                self.assertIsNone(state["request"], name)
                self.assertNotEqual("current", state["confirmation_status"], name)
                self.assertFalse(confirmed, name)
                continue
            self.assertTrue(confirmed, name)
            before = self.states[build_intake.key(story_id, answers)]
            self.assertEqual(("confirmation_required", "absent", None),
                             (before["state"], before["confirmation_status"], before["request"]), name)
            for field in ("input_fingerprint", "input_revision", "schema_version", "policy_version", "scenario_id",
                          "scenario_version", "care_summary"):
                self.assertEqual(before[field], state[field], f"{name}: {field}")
            self.assertEqual(("current", "present", []),
                             (state["confirmation_status"], state["clinician_confirmation"], state["unknowns"]), name)
            summary = dict(state["care_summary"])
            plan = self.stories[story_id]["clinician_plan"]
            self.assertEqual({field: plan[field] for field in build_intake.PLAN_FIELDS}, summary, name)
            summary.pop("authority")
            self.assertEqual(summary, state["request"], name)

    def test_a_reported_warning_always_escalates(self):
        seen = 0
        for name, state in self.states.items():
            story_id, answers, _ = _parse(name)
            facts = {**self.stories[story_id]["known_answers"], **dict(answers)}
            if any(question.startswith("warning.") and answer == "yes" for question, answer in facts.items()):
                seen += 1
                self.assertEqual("emergency_escalation", state["state"], name)
                self.assertEqual(([], None, None), (state["next_question_ids"], state["request"], state["care_summary"]), name)
                self.assertIn("mha_erss_112", state["source_ids"], name)
            else:
                self.assertNotEqual("emergency_escalation", state["state"], name)
        self.assertGreaterEqual(seen, 2)
        # It wins over a clinician's plan in the story and over answers the story does not have.
        planned = self.states[build_intake.key("warning_with_mri_plan", [])]
        self.assertIsNotNone(self.stories["warning_with_mri_plan"]["clinician_plan"])
        self.assertEqual("emergency_escalation", planned["state"])
        self.assertTrue(planned["unknowns"])

    def test_unknown_is_never_read_as_no(self):
        seen = 0
        for name, state in self.states.items():
            story_id, answers, _ = _parse(name)
            if any(answer == "unknown" for _, answer in answers):
                seen += 1
                self.assertEqual("more_information_needed", state["state"], name)
                self.assertEqual(([], None), (state["next_question_ids"], state["request"]), name)
                self.assertTrue(state["unknowns"], name)
                self.assertNotIn(build_intake.key(story_id, answers, True), self.states)
        self.assertGreaterEqual(seen, 3)

    def test_a_story_without_a_clinicians_plan_never_reaches_a_summary(self):
        unplanned = [story_id for story_id, story in self.stories.items() if story["clinician_plan"] is None]
        self.assertIn("injury_unassessed", unplanned)
        for name, state in self.states.items():
            story_id, _, _ = _parse(name)
            if story_id in unplanned:
                self.assertNotIn(state["state"], ("confirmation_required", "ready"), name)
                self.assertIsNone(state["care_summary"], name)
        end = self.states[build_intake.key("injury_unassessed", [("warning.heavy_bleeding", "no")])]
        self.assertEqual(("clinician_assessment_needed", ["injury"]),
                         (end["state"], [concern["category"] for concern in end["concerns"]]))
        outside = self.states[build_intake.key("unsupported_concern", [])]
        self.assertEqual(("unsupported_care_need", None), (outside["state"], outside["request"]))

    def test_a_confirmation_counts_only_for_the_input_it_was_given_for(self):
        story = self.stories["scheduled_mri"]
        mild = build_intake.payload("scheduled_mri", [("context.severity", "mild")])
        moderate = build_intake.payload("scheduled_mri", [("context.severity", "moderate")])
        receipt = confirm_intake(mild, scenario=story)
        self.assertEqual("ready", assess_intake(mild, scenario=story, confirmation=receipt)["state"])
        # Another answer at the same count, another story and no receipt are all refused.
        stale = find_care_for_intake(moderate, scenario=story, confirmation=receipt, origin_id="central")
        self.assertEqual(("confirmation_required", "stale", None, None),
                         (stale["assessment"]["state"], stale["assessment"]["confirmation_status"],
                          stale["assessment"]["request"], stale["finder"]))
        other = self.stories["incomplete_history"]
        crossed = assess_intake(build_intake.payload("incomplete_history", [("context.onset", "recent")]),
                                scenario=other, confirmation=receipt)
        self.assertEqual(("confirmation_required", None), (crossed["state"], crossed["request"]))
        forged = assess_intake(mild, scenario=story, confirmation="confirmed")
        self.assertEqual(("confirmation_required", None), (forged["state"], forged["request"]))
        with self.assertRaises(ValueError):
            confirm_intake(build_intake.payload("injury_unassessed", []), scenario=self.stories["injury_unassessed"])

    def test_every_displayed_id_has_an_entry_and_no_state_claims_a_diagnosis(self):
        self.assertEqual([], build_intake._missing(self.bundle))
        catalogue = self.bundle["catalogue"]
        owned = {section: catalogue[section] for section in ("messages", "reasons", "concerns", "authorities")}
        shown = json.dumps(owned).lower()
        for word in ("probability", "% chance", "likely has", "you have", "diagnosed with", "999", "911"):
            self.assertNotIn(word, shown)
        self.assertIn("112", catalogue["messages"]["intake.warning.emergency.v1"])

    def test_the_build_stops_when_a_displayed_id_has_no_entry(self):
        short = build_intake.referral_catalogue()
        del short["authorities"]["simulated_treatment_plan"]
        with mock.patch.object(build_intake, "referral_catalogue", lambda: short):
            with self.assertRaisesRegex(build_intake.BuildError, "no authorities entry for 'simulated_treatment_plan'"):
                build_intake.bundle()
        fewer = build_intake.assessment_catalogue()
        del fewer["messages"]["intake.ready"]
        with mock.patch.object(build_intake, "assessment_catalogue", lambda: fewer):
            with self.assertRaisesRegex(build_intake.BuildError, "no messages entry for 'intake.ready'"):
                build_intake.bundle()
            self.assertEqual(1, build_intake.main(["--check"]))

    def test_the_build_stops_on_changed_stories_too_many_states_or_a_bridge_that_disagrees(self):
        with tempfile.TemporaryDirectory() as folder:
            wrong = Path(folder) / "digest.json"
            wrong.write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
            with mock.patch.object(build_intake, "DIGEST", wrong):
                with self.assertRaisesRegex(build_intake.BuildError, "does not match the digest"):
                    build_intake.bundle()
        with mock.patch.object(build_intake, "MAX_STATES", 5):
            with self.assertRaisesRegex(build_intake.BuildError, "26 states is more than the 5"):
                build_intake.bundle()

        def altered(*args, **kwargs):
            produced = find_care_for_intake(*args, **kwargs)
            produced["finder"]["ranked"] = list(reversed(produced["finder"]["ranked"]))
            produced["finder"]["status"] = "no_match"
            return produced

        with mock.patch.object(build_intake, "find_care_for_intake", altered):
            with self.assertRaisesRegex(build_intake.BuildError, "differs from the Find care page's answer"):
                build_intake.bundle()
        # A story whose text no longer matches its reviewed edition is refused by the engine, so by the build.
        changed = json.loads(json.dumps(build_intake.stories()))
        changed["scheduled_mri"]["presenting_problem"] += " Current chest pain."
        with mock.patch.object(build_intake, "stories", lambda: changed):
            with self.assertRaisesRegex(build_intake.BuildError, "intake_scenario_unreviewed"):
                build_intake.bundle()
        with mock.patch.object(build_intake, "STORY_NAMES", build_intake.STORY_NAMES[:-1]):
            with self.assertRaisesRegex(build_intake.BuildError, "list different stories"):
                build_intake.bundle()


class IntakePageTests(unittest.TestCase):
    def test_page_stays_offline_and_decides_nothing(self):
        for name in ("index.html", "ask.css", "intake.js", "intake_state.js"):
            text = (PAGE / name).read_text(encoding="utf-8")
            for marker in ("http://", "https://", "//cdn", "@import", "fetch(", "XMLHttpRequest", "WebSocket",
                           "localStorage", "sessionStorage", "indexedDB"):
                self.assertNotIn(marker, text, f"{name} must not contain {marker}")
        script = (PAGE / "intake.js").read_text(encoding="utf-8")
        # The page asks for a campus in one place, only with a request the state module returned and
        # only with the campus answer stored for that confirmed input.
        self.assertEqual(1, script.count("page.ask("))
        self.assertIn("I.finderRequest(data, state.scenario, state.answers, state.confirmed)", script)
        self.assertIn("I.finderResponse(data, state.scenario, state.answers, state.confirmed, place)", script)
        self.assertIn("page.ask(request.service, place, request.urgency, produced)", script)
        for name in ("intake.js", "intake_state.js"):
            text = (PAGE / name).read_text(encoding="utf-8")
            for word in ("danger", "112", "chest", "bleeding", "pregnan", "stroke", "breath"):
                self.assertNotIn(word, text, f"{name} must not carry rules or clinical wording: {word}")
        for word in ("dialysis", "trauma", "mri"):
            self.assertNotIn(word, script, f"intake.js must not name a service: {word}")

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
