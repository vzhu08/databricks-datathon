"""The patient screen over the real patient runtime. Every statement and provider reply here is invented.

The provider in these tests is a scripted stand-in injected through the screen's one composition
point. It checks the screen's behaviour around the runtime. It says nothing about any real provider
or about clinical accuracy.
"""
import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from app import patient_ui as words

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None
IDENTITY = ("test-provider", "edition-1")
STATEMENT = "Invented statement: a dull ache that will not go away since Tuesday."
REVIEW = {"state": "awaiting_clarification", "continuation": "turn-1", "question": {
    "id": "q-evidence", "kind": "evidence_review", "prompt": "unused", "options": [
        {"id": "confirm", "label": "a"}, {"id": "uncertain", "label": "b"}, {"id": "disagree", "label": "c"}],
    "evidence": {"concept_id": "concept-1", "label": "Invented finding A", "presence": "present",
                 "temporality": "current", "source_ref": "description"}}}
FOLLOW_UP = {"state": "awaiting_clarification", "question": {
    "id": "q-2", "kind": "single", "prompt": "Invented follow-up [question](https://example.invalid)?",
    "options": [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]}}
SEVERAL = {"state": "awaiting_clarification", "question": {
    "id": "q-3", "kind": "multiple", "prompt": "Invented list question",
    "options": [{"id": "one", "label": "First"}, {"id": "two", "label": "Second"}, {"id": "three", "label": "Third"}]}}
DONE = {"state": "completed", "guidance": "Invented guidance text.", "urgency": "consultation",
        "uncertainty": "Invented uncertainty text.", "possible_causes": ["Invented cause one", "Invented cause two"],
        "next_step": {"kind": "consultation", "specialty_code": None}}
URGENT = {"state": "urgent", "guidance": "Invented urgent guidance.", "urgency": "emergency",
          "uncertainty": "Invented urgent uncertainty.", "possible_causes": [], "next_step": None}


V2 = {"schema": "patient-question.v2", "options": []}
ITEMS = {"state": "awaiting_clarification", "question": {
    **V2, "id": "q-items", "kind": "item_presence", "prompt": "Invented item question", "items": [
        {"id": "item-1", "label": "Invented item one", "required": True, "choices": [
            {"id": "present", "label": "Yes"}, {"id": "absent", "label": "No"}, {"id": "unknown", "label": "Don't know"}]},
        {"id": "item-2", "label": "Invented item two", "required": False, "choices": [
            {"id": "present", "label": "Yes"}, {"id": "absent", "label": "No"}]}]}}
AMOUNT = {"state": "awaiting_clarification", "question": {
    **V2, "id": "q-amount", "kind": "quantity", "prompt": "Invented amount question", "optional": True, "units": [
        {"id": "unit-days", "label": "days", "min": 1, "max": 30, "integer_only": True},
        {"id": "unit-weeks", "label": "weeks", "min": 0.5, "max": 8, "integer_only": False}]}}
CATALOG = {"state": "awaiting_clarification", "question": {
    "schema": "patient-question.v2", "id": "q-catalog", "kind": "catalog_selection", "prompt": "Invented catalog question",
    "selection": "multiple", "catalog": {"id": "invented-catalog", "edition": "edition-1"},
    "options": [{"id": "entry-1", "label": "Entry one"}, {"id": "entry-2", "label": "Entry two"}]}}
STOP = {"state": "provider_stop", "guidance": "Invented stop guidance."}


class Scripted:
    """Replies in order, counting every call. An exception in the script is raised instead of returned."""

    identity = IDENTITY

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def assess(self, interview, *, continuation=None):
        self.calls.append({"interview": interview, "continuation": continuation})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"provider_id": IDENTITY[0], "provider_version": IDENTITY[1], **reply}


class WordingTests(unittest.TestCase):
    def view(self, state="draft", **fields):
        return {"state": state, "revision": 3, "policy_version": words.POLICY_VERSION, "consent": False, "reason": None,
                "question": None, "guidance": None, "urgency": None, "uncertainty": None, "possible_causes": [],
                "next_step": None, "provider_id": None, "provider_version": None, **fields}

    def test_the_runtime_view_alone_decides_what_the_screen_shows(self):
        self.assertEqual(words.step(self.view(), has_statement=False), "describe")
        self.assertEqual(words.step(self.view(), has_statement=True), "consent")
        self.assertEqual(words.step(self.view(consent=True), has_statement=True), "send")
        self.assertEqual(words.step(self.view("completed"), has_statement=True, editing=False), "completed")
        self.assertEqual(words.step(self.view(), has_statement=True, editing=True), "describe")
        # While the patient is changing the description, no earlier result stays on the screen.
        self.assertEqual(words.step(self.view("completed"), has_statement=True, editing=True), "describe")
        self.assertEqual(words.step(self.view("awaiting_clarification", question={"kind": "text"}),
                                    has_statement=True), "question")
        # A question state with no question, and any state this screen does not know, show no result.
        self.assertEqual(words.step(self.view("awaiting_clarification"), has_statement=True), "withheld")
        self.assertEqual(words.step(self.view("something_new"), has_statement=True), "unavailable")

    def test_every_urgency_code_in_the_contract_has_a_heading_and_no_likelihood_is_invented(self):
        for code in ("self_care", "consultation", "consultation_24", "emergency", "emergency_ambulance"):
            self.assertIn(code, words.URGENCY)
        lines = words.result_lines(self.view(**DONE, provider_id="p", provider_version="v"))
        self.assertEqual(lines["guidance"], DONE["guidance"])
        self.assertEqual(lines["causes"], DONE["possible_causes"])
        self.assertIn("not a referral", lines["next_step"])
        self.assertIn("Assessed by p, version v", lines["provenance"])
        everything = " ".join([lines["heading"], lines["next_step"], lines["provenance"], words.NOT_A_DOCTOR])
        for claim in ("%", "likely", "probab", "confiden"):
            self.assertNotIn(claim, everything.lower())

    def test_every_failure_reason_in_the_contract_has_a_sentence(self):
        for reason in ("unavailable", "timeout", "rate_limited", "budget_exhausted", "invalid_response",
                       "unauthorized", "configuration_changed"):
            self.assertIn(reason, words.UNAVAILABLE)
        for reason in ("unsupported_context", "unsupported_correction", "interview_limit"):
            self.assertIn(reason, words.UNSUPPORTED)
        self.assertEqual(words.reason_line(self.view("provider_unavailable", reason="a_new_code")),
                         words.UNAVAILABLE["unavailable"])
        self.assertEqual(words.reason_line(self.view("unsupported", reason="a_new_code")),
                         words.UNSUPPORTED["unsupported"])
        self.assertIsNone(words.reason_line(self.view()))

    def test_an_answer_is_built_from_what_was_entered_and_nothing_is_filled_in(self):
        entered = {"-1": "present", "-unit": "unit-days", "": "3"}
        self.assertEqual(words.answer_for(ITEMS["question"], entered.get), {"items": [{"id": "item-2", "presence": "present"}]})
        self.assertEqual(words.answer_for(AMOUNT["question"], entered.get), {"value": 3, "unit_id": "unit-days"})
        self.assertIs(type(words.quantity("3")), int)
        self.assertEqual(words.quantity(" 2.5 "), 2.5)
        for nothing in ({}, {"": ""}, {"": "three"}, {"": "3"}):  # no amount, no number, or no unit chosen
            with self.assertRaises(ValueError):
                words.answer_for(AMOUNT["question"], nothing.get)
        with self.assertRaises(ValueError):
            words.answer_for(ITEMS["question"], {}.get)
        self.assertEqual(words.answer_for(CATALOG["question"], {"-0": True, "-1": False}.get), ["entry-1"])

    def test_a_question_kind_this_screen_does_not_know_is_withheld(self):
        view = self.view("awaiting_clarification", question={"kind": "a_new_kind", "prompt": "x", "options": []})
        self.assertEqual(words.step(view, has_statement=True), "withheld")
        self.assertEqual(words.step(self.view("provider_stop"), has_statement=True), "provider_stop")

    def test_a_hospital_is_listed_only_from_a_reviewed_result(self):
        self.assertEqual(words.destination_lines({"state": "no_reviewed_destination"})["destinations"], [])
        self.assertEqual(words.destination_lines(None)["destinations"], [])
        found = words.destination_lines({"state": "reviewed_destinations",
                                         "destinations": [{"facility_id": "campus-a", "availability": "unknown"}]})
        self.assertEqual(found["destinations"], ["campus-a"])
        self.assertIn("phone before you travel", found["text"])

    def test_failure_words_never_claim_that_nothing_was_sent(self):
        spoken = [words.FAILED, words.UNCONFIRMED, *words.UNAVAILABLE.values(), *words.UNSUPPORTED.values(),
                  words.QUESTION_WITHHELD, words.STOPPED, words.OUT_OF_DATE]
        for sentence in spoken:
            for claim in ("nothing new was sent", "was not sent", "no assessment was made", "not been sent"):
                self.assertNotIn(claim, sentence.lower(), sentence)
        self.assertIn("may still have reached", words.UNCONFIRMED)
        # The one "not sent" sentence belongs to the case the runtime proves: no provider on this server.
        self.assertIn("not sent anywhere", words.NO_PROVIDER)
        # Unresolved evidence is not blamed on the patient: confirming two conflicting readings also ends here.
        for blame in ("you marked", "wrong or unsure"):
            self.assertNotIn(blame, words.UNSUPPORTED["unsupported_correction"].lower())
        # Clearing is claimed for this server only.
        for sentence in words.ENDED.values():
            self.assertIn("from this server", sentence)
        self.assertIn("does not by itself delete", words.PROVIDER_COPY)

    def test_an_idle_page_is_told_to_look_again_just_after_the_time_limit(self):
        self.assertEqual(words.expiry_delay(opened=100.0, now=100.0, ttl=900), 901.0)
        self.assertEqual(words.expiry_delay(opened=100.0, now=700.0, ttl=900), 301.0)
        self.assertEqual(words.expiry_delay(opened=100.0, now=5000.0, ttl=900), 1.0)

    def test_text_from_a_patient_or_provider_cannot_become_markup(self):
        self.assertEqual(words.plain("[x](https://a.invalid) <b> ![i](u)"),
                         "\\[x\\]\\(https\\:\\/\\/a\\.invalid\\) \\<b\\> \\!\\[i\\]\\(u\\)".replace("\\/", "/"))

    ON = {"PATIENT_PROVIDER": "databricks-experimental", "PATIENT_PROVIDER_ENDPOINT": "databricks-gpt-oss-20b",
          "PATIENT_PROVIDER_DEMO_ATTEMPTS": "6"}

    def test_the_default_composition_has_no_provider_and_never_touches_the_factory(self):
        with mock.patch.object(words, "_databricks_factory", side_effect=AssertionError("factory used while off")):
            for off in ({}, {"PATIENT_PROVIDER": " "}, {"PATIENT_PROVIDER_ENDPOINT": "databricks-gpt-oss-20b",
                                                        "PATIENT_PROVIDER_DEMO_ATTEMPTS": "6"}):
                self.assertEqual(words.provider_mode(off), {"mode": "off", "problems": []})
                service, provider = words.compose(off)
                self.assertIsNone(provider)
                self.assertIsNone(service._provider)
                self.assertIsNone(service._identity)
                self.assertEqual(words.off_notice(off), words.SWITCHED_OFF)

    def test_a_half_configured_provider_is_a_named_problem_and_never_a_guess(self):
        cases = {
            "PATIENT_PROVIDER does not name": {**self.ON, "PATIENT_PROVIDER": "made-up-provider"},
            "PATIENT_PROVIDER_ENDPOINT is not set": {k: v for k, v in self.ON.items() if k != "PATIENT_PROVIDER_ENDPOINT"},
            "PATIENT_PROVIDER_ENDPOINT is not set ": {**self.ON, "PATIENT_PROVIDER_ENDPOINT": "made-up-endpoint"},
            "PATIENT_PROVIDER_LANE is not demo or test": {**self.ON, "PATIENT_PROVIDER_LANE": "made-up-lane"},
            "PATIENT_PROVIDER_DEMO_ATTEMPTS is not a whole number from 0 to 6": {**self.ON, "PATIENT_PROVIDER_DEMO_ATTEMPTS": "7"},
            "PATIENT_PROVIDER_DEMO_ATTEMPTS is not a whole number from 0 to 6 ": {**self.ON, "PATIENT_PROVIDER_DEMO_ATTEMPTS": "many"},
            "PATIENT_PROVIDER_TEST_ATTEMPTS is not a whole number from 0 to 2": {**self.ON, "PATIENT_PROVIDER_TEST_ATTEMPTS": "-1"},
            "PATIENT_PROVIDER_DEMO_ATTEMPTS allows no requests": {**self.ON, "PATIENT_PROVIDER_DEMO_ATTEMPTS": "0"},
            "PATIENT_PROVIDER_TEST_ATTEMPTS allows no requests": {**self.ON, "PATIENT_PROVIDER_LANE": "test"},
        }
        with mock.patch.object(words, "_databricks_factory", side_effect=AssertionError("factory used on a problem")):
            for expected, environ in cases.items():
                found = words.provider_mode(environ)
                self.assertEqual(found["mode"], "problem", expected)
                self.assertTrue(any(expected.strip() in problem for problem in found["problems"]), (expected, found))
                words._reported.clear()
                with self.assertLogs(words.__name__, "WARNING") as log:
                    self.assertIsNone(words.compose(environ)[1])
                with self.assertNoLogs(words.__name__, "WARNING"):  # said once per worker, not on every redraw
                    self.assertIsNone(words.compose(environ)[1])
                for said in (words.off_notice(environ), *found["problems"], *log.output):
                    for value in ("made-up-provider", "made-up-endpoint", "made-up-lane", "many"):
                        self.assertNotIn(value, said)
                self.assertTrue(any(expected.strip() in line for line in log.output))

    def test_a_cap_that_is_not_a_short_plain_number_is_a_problem_and_never_an_exception(self):
        bad = ("\u00b2", "\u0663", "\uff13", "\u2460", "1" * 5000, "9" * 3, "007", "+1", "1.0", "1e0", "0x1", "1_0",
               "1 1", "-0", "\u00bd", "\x00", "\n")
        with mock.patch.object(words, "_databricks_factory", side_effect=AssertionError("factory used on a problem")):
            for setting, most in (("PATIENT_PROVIDER_DEMO_ATTEMPTS", 6), ("PATIENT_PROVIDER_TEST_ATTEMPTS", 2)):
                for value in bad:
                    environ = {**self.ON, setting: value}
                    found = words.provider_mode(environ)
                    self.assertEqual(found, {"mode": "problem", "problems": [
                        f"{setting} is not a whole number from 0 to {most}"]}, repr(value[:8]))
                    self.assertEqual(words.off_notice(environ), words.SETUP_PROBLEM)
                    words._reported.clear()
                    with self.assertLogs(words.__name__, "WARNING") as log:
                        service, label = words.compose(environ)
                    self.assertIsNone(label)
                    self.assertIsNone(service._provider)
                    if value.strip():
                        self.assertNotIn(value, "".join(log.output))
        self.assertEqual(words.provider_mode({**self.ON, "PATIENT_PROVIDER_DEMO_ATTEMPTS": " 06 "})["demo_attempts"], 6)

    def test_what_the_patient_is_told_never_names_a_server_setting_or_this_visit_for_a_shared_allowance(self):
        for text in (words.SETUP_PROBLEM, words.SWITCHED_OFF, words.NO_PROVIDER, *words.UNAVAILABLE.values()):
            self.assertNotIn("PATIENT_", text)
            self.assertNotIn("setting", text.lower())
        self.assertIn("not be sent anywhere", words.SETUP_PROBLEM)
        self.assertIn("Find care, at the top of this page, works without it.", words.SWITCHED_OFF)
        self.assertNotIn("visit", words.UNAVAILABLE["budget_exhausted"].lower())
        self.assertNotIn("you", words.UNAVAILABLE["budget_exhausted"].lower())

    def test_the_databricks_interview_is_composed_only_through_its_server_factory(self):
        provider = Scripted()
        factory = mock.Mock(return_value=provider)
        environ = {**self.ON, "PATIENT_PROVIDER_TEST_ATTEMPTS": "2"}
        with mock.patch.object(words, "_databricks_factory", return_value=factory):
            service, label = words.compose(environ)
            factory.assert_called_once_with(endpoint="databricks-gpt-oss-20b", enabled=True, lane="demo",
                                            demo_attempts=6, test_attempts=2)
            self.assertIs(service._provider, provider)
            self.assertEqual(service._identity, IDENTITY)
            self.assertEqual(label, "Databricks endpoint databricks-gpt-oss-20b (experimental language model, "
                                    "not clinically validated)")
            # The factory may still decline (no budget left, or settings changed since the worker started).
            for declined in (mock.Mock(return_value=None), mock.Mock(side_effect=ValueError("changed"))):
                with mock.patch.object(words, "_databricks_factory", return_value=declined):
                    service, label = words.compose(environ)
                    self.assertIsNone(label)
                    self.assertIsNone(service._provider)

    def test_the_real_factory_is_the_one_named_in_the_provider_notes_and_stays_off_when_disabled(self):
        factory = words._databricks_factory()
        self.assertEqual(factory.__name__, "configured_databricks_provider")
        self.assertIsNone(factory(endpoint="databricks-gpt-oss-20b", enabled=False))
        self.assertEqual(words.ENDPOINTS, sys.modules[factory.__module__]._MODELS)


@unittest.skipUnless(HAS_STREAMLIT, "Streamlit is needed to run the screen")
class ScreenTests(unittest.TestCase):
    def setUp(self):
        # app.py imports its neighbours by bare name, as it does when app/ is the deployment root. Under
        # test discovery those names can belong to the test packages, so give them to app/ for one test.
        bare = ("find_care", "data_access", "ranking", "patient_ui", "patient_intake")
        saved = {name: module for name, module in sys.modules.items() if name.split(".")[0] in bare}
        for name in saved:
            del sys.modules[name]
        sys.path.insert(0, str(APP))

        def restore():
            sys.path.remove(str(APP))
            for name in [name for name in sys.modules if name.split(".")[0] in bare]:
                del sys.modules[name]
            sys.modules.update(saved)

        self.addCleanup(restore)
        import patient_ui as screen
        self.screen = screen
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DATABRICKS_", "FIND_CARE_", "PATIENT_"))}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def provider(self, *replies, **interview):
        scripted = Scripted(*replies)
        screen = self.screen

        def compose():
            return screen.PatientIntakeService(interview=screen.PatientInterview(**interview), provider=scripted,
                                               provider_identity=IDENTITY, handoff=screen.PatientHandoff()), \
                "Test provider (invented replies)"

        patcher = mock.patch.object(screen, "compose", compose)
        patcher.start()
        self.addCleanup(patcher.stop)
        return scripted

    def open(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def press(self, app, label):
        found = [button for button in app.button if button.label == label]
        self.assertEqual(len(found), 1, f"{label!r} among {[button.label for button in app.button]}")
        app = found[0].click().run()
        self.assertFalse(app.exception, app.exception)
        return app

    @staticmethod
    def shown(app):
        kinds = ("title", "subheader", "markdown", "caption", "text", "info", "warning", "error", "success")
        return "\n".join(str(element.value) for kind in kinds for element in getattr(app, kind))

    def begin(self, app, statement=STATEMENT, age=None):
        app.checkbox(key="pt-agree-0").check()
        app = self.press(app, "Start")
        app.text_area(key="pt-description-0").input(statement)
        if age is not None:
            app.number_input(key="pt-age-0").set_value(age)
        return self.press(app, "Save and continue")

    def answer(self, app, value):
        radios = [radio for radio in app.radio if str(radio.key).startswith("pt-answer-")]
        self.assertEqual(len(radios), 1)
        radios[0].set_value(value)
        return self.press(app, "Send answer")

    def test_with_no_provider_the_screen_says_so_and_invents_nothing(self):
        app = self.open()
        self.assertIn("Check your symptoms", self.shown(app))
        self.assertIn("call 112", self.shown(app))
        self.assertIn(self.screen.SWITCHED_OFF, self.shown(app))
        # Starting needs the agreement: pressing Start without it opens no encounter.
        app = self.press(app, "Start")
        self.assertIn("Tick the box", self.shown(app))
        self.assertNotIn("handle", app.session_state[self.screen.STATE_KEY])

        app = self.begin(app, age=41)
        text = self.shown(app)
        self.assertIn("No assessment is available", text)
        self.assertIn(self.screen.NO_PROVIDER, text)
        self.assertIn(self.screen.NOT_ASSESSED, text)
        self.assertNotIn(self.screen.UNCONFIRMED, text)
        self.assertIn(STATEMENT, [element.value for element in app.text])
        for invented in ("Possible causes", "How sure this is", "Where to go", "Assessed by"):
            self.assertNotIn(invented, text)
        labels = [button.label for button in app.button]
        self.assertNotIn("Try again", labels)
        self.assertNotIn("I agree. Send it for assessment", labels)
        # The runtime itself holds the unavailable state: the screen did not make it up.
        box = app.session_state[self.screen.STATE_KEY]
        view = box["service"].view(box["handle"])
        self.assertEqual((view["state"], view["reason"], view["consent"]), ("provider_unavailable", "unavailable", False))

    def test_a_fresh_statement_goes_through_review_follow_up_result_and_the_hospital_check(self):
        provider = self.provider(REVIEW, FOLLOW_UP, DONE)
        app = self.begin(self.open(), age=41)
        text = self.shown(app)
        self.assertIn("Send your description for assessment?", text)
        self.assertIn("Test provider \\(invented replies\\)", text)
        self.assertEqual(provider.calls, [])  # saving sends nothing
        # Once saved, the encounter store holds the only copy of the patient's words.
        self.assertNotIn("pt-description-0", app.session_state)
        self.assertNotIn("pt-age-0", app.session_state)

        app = self.press(app, "I agree. Send it for assessment")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["interview"]["source"]["description"], STATEMENT)
        self.assertEqual(provider.calls[0]["interview"]["context"], {"age_years": 41, "language": "en"})
        text = self.shown(app)
        self.assertIn("Invented finding A", text)
        self.assertIn("you have this, now", text)
        self.assertIn("the provider's reading, not a finding", text)

        # Drawing the screen again repeats nothing: no consent, no assessment, no answer.
        for _ in range(3):
            app = app.run()
        self.assertEqual(len(provider.calls), 1)
        box = app.session_state[self.screen.STATE_KEY]
        self.assertTrue(box["service"].view(box["handle"])["consent"])

        app = self.answer(app, "confirm")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(provider.calls[1]["continuation"], "turn-1")
        review = provider.calls[1]["interview"]["patient_evidence"][0]
        self.assertEqual((review["decision"], review["origin"]), ("confirm", "patient_review"))
        radio = [radio for radio in app.radio if str(radio.key).startswith("pt-answer-")][0]
        self.assertEqual(radio.label, "Invented follow\\-up \\[question\\]\\(https\\://example\\.invalid\\)?")

        app = self.answer(app, "yes")
        self.assertEqual(len(provider.calls), 3)
        text = self.shown(app)
        for expected in ("See a doctor (not assessed as urgent)", "Invented guidance text\\.", "Invented uncertainty text\\.",
                         "Invented cause one", "None of them is a diagnosis", "Assessed by test\\-provider, version edition\\-1",
                         "not a diagnosis, a prescription or a doctor's order", "not a referral"):
            self.assertIn(expected, text)
        self.assertNotIn("%", text)

        app = self.press(app, "I have read this. Check for a reviewed hospital")
        self.assertIn(self.screen.DESTINATION["no_reviewed_destination"], self.shown(app))
        self.assertEqual(len(provider.calls), 3)
        # Nothing about the patient is in the address, and nothing is offered as a download or raw record.
        self.assertEqual(dict(app.query_params), {})
        self.assertEqual(len(app.get("download_button")), 0)
        self.assertEqual(len(app.json), 0)
        self.assertEqual(len(app.get("expander")), 0)

    def test_a_provider_setup_problem_is_named_on_the_screen_and_nothing_is_sent(self):
        os.environ.update(PATIENT_PROVIDER="databricks-experimental", PATIENT_PROVIDER_DEMO_ATTEMPTS="6")
        with mock.patch.object(self.screen, "_databricks_factory", side_effect=AssertionError("factory used")):
            app = self.open()
            text = self.shown(app)
            self.assertIn(self.screen.SETUP_PROBLEM, text)
            self.assertNotIn("PATIENT", text)
            app = self.begin(app)
            text = self.shown(app)
            self.assertNotIn("PATIENT", text)
            self.assertIn("No assessment is available", text)
            self.assertIn(self.screen.NO_PROVIDER, text)
            self.assertNotIn("I agree. Send it for assessment", [button.label for button in app.button])

    def test_a_malformed_cap_reaches_the_unavailable_screen_without_an_exception(self):
        for value in ("\u00b2", "9" * 400):
            os.environ.update(PATIENT_PROVIDER="databricks-experimental",
                              PATIENT_PROVIDER_ENDPOINT="databricks-gpt-oss-20b", PATIENT_PROVIDER_DEMO_ATTEMPTS=value)
            with mock.patch.object(self.screen, "_databricks_factory", side_effect=AssertionError("factory used")):
                app = self.open()
                self.assertEqual(len(app.exception), 0)
                text = self.shown(app)
                self.assertIn(self.screen.SETUP_PROBLEM, text)
                self.assertNotIn("PATIENT", text)
                self.assertNotIn(value, text)
                app = self.begin(app)
                self.assertEqual(len(app.exception), 0)
                self.assertIn(self.screen.NO_PROVIDER, self.shown(app))

    def test_the_configured_databricks_interview_is_named_before_anything_is_sent(self):
        provider = Scripted(REVIEW, STOP)
        os.environ.update(PATIENT_PROVIDER="databricks-experimental", PATIENT_PROVIDER_ENDPOINT="databricks-gpt-oss-120b",
                          PATIENT_PROVIDER_DEMO_ATTEMPTS="3")
        factory = mock.Mock(return_value=provider)
        with mock.patch.object(self.screen, "_databricks_factory", return_value=factory):
            app = self.open()
            self.assertNotIn(self.screen.SWITCHED_OFF, self.shown(app))
            app = self.begin(app)
            text = self.shown(app)
            self.assertIn("Databricks endpoint databricks\\-gpt\\-oss\\-120b \\(experimental language model, not clinically validated\\)", text)
            self.assertEqual(provider.calls, [])
            app = self.press(app, "I agree. Send it for assessment")
            self.assertEqual(provider.calls[0]["interview"]["source"]["description"], STATEMENT)
            app = self.answer(app, "confirm")
            text = self.shown(app)
            self.assertIn("This assessment has stopped", text)
            self.assertIn("Invented stop guidance", text)
            self.assertNotIn("Where to go", text)
        for call in factory.call_args_list:
            self.assertEqual(call.kwargs, {"endpoint": "databricks-gpt-oss-120b", "enabled": True, "lane": "demo",
                                           "demo_attempts": 3, "test_attempts": 0})

    def test_an_urgent_result_is_shown_at_once_with_no_hospital_check(self):
        self.provider(URGENT)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        self.assertEqual([error.value for error in app.error], ["Go to an emergency department now"])
        text = self.shown(app)
        self.assertIn("Invented urgent guidance\\.", text)
        self.assertIn("No hospital is suggested for an urgent result", text)
        self.assertNotIn("I have read this. Check for a reviewed hospital", [button.label for button in app.button])

    def test_changing_the_description_clears_the_result_and_asks_for_agreement_again(self):
        provider = self.provider(DONE, DONE)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        app = self.press(app, "I have read this. Check for a reviewed hospital")
        self.assertIn("Invented guidance text", self.shown(app))

        app = self.press(app, "Change my description")
        self.assertNotIn("Invented guidance text", self.shown(app))
        self.assertEqual(app.text_area(key="pt-description-0").value, STATEMENT)  # read back from the encounter
        app.text_area(key="pt-description-0").input("Invented second statement.")
        app = self.press(app, "Save and continue")
        text = self.shown(app)
        self.assertIn("Send your description for assessment?", text)
        for stale in ("Invented guidance text", "Invented cause one", self.screen.DESTINATION["no_reviewed_destination"]):
            self.assertNotIn(stale, text)
        box = app.session_state[self.screen.STATE_KEY]
        self.assertFalse(box["service"].view(box["handle"])["consent"])
        self.assertEqual(len(provider.calls), 1)
        app = self.press(app, "I agree. Send it for assessment")
        self.assertEqual(provider.calls[1]["interview"]["source"]["description"], "Invented second statement.")

    def test_overlong_replacement_shows_validation_and_clears_the_earlier_result(self):
        provider = self.provider(DONE)
        statement = "x" * words.MAX_DESCRIPTION
        app = self.press(self.begin(self.open(), statement=statement), "I agree. Send it for assessment")
        self.assertIn("Invented guidance text", self.shown(app))
        app = self.press(app, "Change my description")
        field = app.text_area(key="pt-description-0")
        self.assertEqual(field.value, statement)
        field.input("y" * (words.MAX_DESCRIPTION + 1))
        app = self.press(app, "Save and continue")
        self.assertIn("That description could not be used", self.shown(app))
        self.assertNotIn("Invented guidance text", self.shown(app))
        self.assertEqual(app.text_area[0].value, "")
        self.assertNotIn("pt-description-0", app.session_state)
        box = app.session_state[self.screen.STATE_KEY]
        self.assertIsNone(box["handle"].read()[1]["interview"])
        self.assertEqual(len(provider.calls), 1)

        replacement = "New invented description"
        app.text_area[0].input(replacement)
        app = self.press(app, "Save and continue")
        self.assertIn("Send your description for assessment?", self.shown(app))
        self.assertIn(replacement, [element.value for element in app.text])
        self.assertEqual(len(provider.calls), 1)

    def test_a_provider_failure_withdraws_the_earlier_result(self):
        self.provider(DONE, TimeoutError("invented"), {"state": "provider_unavailable", "reason": "rate_limited"})
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        self.assertIn("Invented guidance text", self.shown(app))
        app = self.press(app, "Change my description")
        app = self.press(app, "Save and continue")
        app = self.press(app, "I agree. Send it for assessment")
        text = self.shown(app)
        self.assertIn("No assessment is available", text)
        self.assertIn(self.screen.UNAVAILABLE["unavailable"], text)
        self.assertIn(self.screen.UNCONFIRMED, text)
        self.assertNotIn("No assessment was made", text)
        self.assertNotIn("not sent", text)
        for stale in ("Invented guidance text", "Invented cause one", "Where to go"):
            self.assertNotIn(stale, text)
        app = self.press(app, "Try again")
        self.assertIn(self.screen.UNAVAILABLE["rate_limited"], self.shown(app))

    def test_an_unsure_review_and_several_choices_reach_the_runtime_as_the_patient_gave_them(self):
        provider = self.provider(SEVERAL, REVIEW, DONE)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        # Sending with nothing chosen is refused on the screen and uses no provider turn.
        app = self.press(app, "Send answer")
        self.assertIn(self.screen.BAD_ANSWER, self.shown(app))
        self.assertEqual(len(provider.calls), 1)
        boxes = sorted((box for box in app.checkbox if str(box.key).startswith("pt-answer-")), key=lambda box: box.key)
        self.assertEqual([box.label for box in boxes], ["First", "Second", "Third"])
        boxes[0].check()
        boxes[2].check()
        app = self.press(app, "Send answer")
        self.assertEqual(provider.calls[1]["interview"]["answers"][0]["answer"], ["one", "three"])
        # "I'm not sure" about the provider's reading stays unresolved, so the runtime withholds a normal result.
        app = self.answer(app, "uncertain")
        text = self.shown(app)
        self.assertIn("This could not be assessed", text)
        self.assertIn(self.screen.UNSUPPORTED["unsupported_correction"], text)
        self.assertNotIn("Invented guidance text", text)

    def fields(self, app, kind, suffix=""):
        return sorted((element for element in getattr(app, kind)
                       if str(element.key).startswith("pt-answer-") and str(element.key).endswith(suffix)),
                      key=lambda element: element.key)

    def test_extended_questions_a_skip_and_a_provider_stop(self):
        provider = self.provider(ITEMS, AMOUNT, CATALOG, AMOUNT, STOP)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        self.assertIn(self.screen.UNINTERPRETED, self.shown(app))
        answers = lambda: provider.calls[-1]["interview"]["answers"]  # noqa: E731

        # Each listed item is answered on its own. A required item left blank is refused before any provider turn.
        one, two = self.fields(app, "radio")
        self.assertEqual((one.label, two.label), ("Invented item one", "Invented item two (optional)"))
        self.assertNotIn("Skip this question", [button.label for button in app.button])
        two.set_value("present")
        app = self.press(app, "Send answer")
        self.assertIn(self.screen.BAD_ANSWER, self.shown(app))
        self.assertEqual(len(provider.calls), 1)
        one, two = self.fields(app, "radio")
        one.set_value("absent")
        two.set_value("present")
        app = self.press(app, "Send answer")
        self.assertEqual(answers()[0]["answer"], {"items": [{"id": "item-1", "presence": "absent"},
                                                            {"id": "item-2", "presence": "present"}]})

        # An amount keeps the number as typed and needs a unit the patient chose. Limits are the runtime's.
        unit = self.fields(app, "radio", "-unit")[0]
        self.assertIsNone(unit.value)
        self.fields(app, "text_input")[0].input("2.5")
        unit.set_value("unit-days")
        app = self.press(app, "Send answer")
        self.assertIn(self.screen.BAD_ANSWER, self.shown(app))
        self.assertEqual(len(provider.calls), 2)
        self.fields(app, "text_input")[0].input("3")
        self.fields(app, "radio", "-unit")[0].set_value("unit-days")
        app = self.press(app, "Send answer")
        self.assertEqual(answers()[1]["answer"], {"value": 3, "unit_id": "unit-days"})
        self.assertIs(type(answers()[1]["answer"]["value"]), int)

        for box in self.fields(app, "checkbox"):
            box.check()
        app = self.press(app, "Send answer")
        self.assertEqual(answers()[2]["answer"], ["entry-1", "entry-2"])

        # Skipping is its own button, offered only when the question is optional.
        app = self.press(app, "Skip this question")
        self.assertEqual((answers()[3]["skipped"], answers()[3]["answer"]), (True, None))

        text = self.shown(app)
        self.assertIn("This assessment has stopped", text)
        self.assertIn("Invented stop guidance\\.", text)
        self.assertIn(self.screen.STOPPED, text)
        for absent in ("Where to go", "Possible causes", "How sure this is"):
            self.assertNotIn(absent, text)
        labels = [button.label for button in app.button]
        for absent in ("Send for assessment", "Try again", "Send answer", "I have read this. Check for a reviewed hospital"):
            self.assertNotIn(absent, labels)
        # Withdrawing and agreeing again cannot restart a stopped interview.
        self.assertEqual(len(provider.calls), 5)

    def test_an_unsupported_age_offers_no_way_forward_except_a_valid_edit(self):
        provider = self.provider(DONE, supported_age_range=(18, 120))
        app = self.begin(self.open(), age=12)
        text = self.shown(app)
        self.assertIn("This could not be assessed", text)
        self.assertIn(self.screen.UNSUPPORTED["unsupported_context"], text)
        labels = [button.label for button in app.button]
        for absent in ("I agree. Send it for assessment", "Send for assessment", "Try again"):
            self.assertNotIn(absent, labels)
        self.assertEqual(provider.calls, [])
        app = self.press(app, "Change my description")
        app.text_area(key="pt-description-0").input(STATEMENT)
        app.number_input(key="pt-age-0").set_value(30)
        app = self.press(app, "Save and continue")
        self.assertIn("Send your description for assessment?", self.shown(app))

    def test_start_over_and_withdrawal_clear_what_they_say_they_clear(self):
        provider = self.provider(DONE)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        app = self.press(app, "Withdraw my agreement")
        text = self.shown(app)
        self.assertNotIn("Invented guidance text", text)
        self.assertIn("Send your description for assessment?", text)
        session = app.session_state[self.screen.STATE_KEY]["session"]

        app = self.press(app, "Start over")
        text = self.shown(app)
        self.assertIn(self.screen.ENDED["reset"], text)
        self.assertIn("Before you start", text)
        self.assertNotIn(STATEMENT, text)
        self.assertEqual(session.status, "reset")
        self.assertEqual(app.session_state[self.screen.STATE_KEY], {"visit": 1})
        for key in ("pt-description-0", "pt-age-0", "pt-agree-0"):
            self.assertNotIn(key, app.session_state)
        self.assertFalse(app.checkbox(key="pt-agree-1").value)  # agreement is asked for again
        self.assertEqual(len(provider.calls), 1)

    def test_an_expired_visit_shows_nothing_from_before(self):
        self.provider(DONE)
        with mock.patch.object(self.screen, "TTL_SECONDS", 1):
            app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
            self.assertIn("Invented guidance text", self.shown(app))
            time.sleep(1.2)
            app = app.run()
        text = self.shown(app)
        self.assertIn(self.screen.ENDED["expired"], text)
        self.assertIn("Before you start", text)
        for stale in (STATEMENT, "Invented guidance text", "Invented cause one"):
            self.assertNotIn(stale, text)
        self.assertEqual(app.session_state[self.screen.STATE_KEY], {"visit": 1})

    def test_an_out_of_date_step_is_refused_and_the_current_state_is_shown(self):
        provider = self.provider(FOLLOW_UP, DONE)
        app = self.press(self.begin(self.open()), "I agree. Send it for assessment")
        box = app.session_state[self.screen.STATE_KEY]
        # Another tab of the same visit changes the description after this page was drawn.
        box["service"].edit(box["handle"], box["revision"], description="Invented other-tab statement.",
                            context={"age_years": None, "language": "en"})
        radios = [radio for radio in app.radio if str(radio.key).startswith("pt-answer-")]
        radios[0].set_value("yes")
        app = self.press(app, "Send answer")
        text = self.shown(app)
        self.assertIn(self.screen.OUT_OF_DATE, text)
        self.assertIn("Send your description for assessment?", text)
        self.assertIn("Invented other-tab statement.", [element.value for element in app.text])
        self.assertEqual(len(provider.calls), 1)

    def test_find_care_stays_one_choice_away_and_is_not_the_first_screen(self):
        app = self.open()
        self.assertEqual(app.radio(key="view").value, self.screen.PATIENT)
        self.assertNotIn("Data: demonstration.", self.shown(app))
        app = app.radio(key="view").set_value("Find care").run()
        app = app.radio(key="lookup_source").set_value("Simulated scenarios").run()
        self.assertFalse(app.exception, app.exception)
        self.assertIn("Data: demonstration.", self.shown(app))
        self.assertNotIn("Check your symptoms", self.shown(app))


if __name__ == "__main__":
    unittest.main()
